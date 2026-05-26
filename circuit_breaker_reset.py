#!/usr/bin/env python3
"""
Circuit Breaker Reset Monitor for LLM Providers

Monitors LLM circuit breaker states in Redis and attempts safe resets
after cooldown periods. Only resets when simulation state indicates
it's safe to retry. Logs all reset attempts and outcomes.

Redis Keys:
  llm_circuit_breaker:{provider} — STRING circuit breaker state ("open")
  simulation:state:unstable — FLAG indicating unstable simulation state
  llm_circuit_breaker_reset_log — ZSET of reset attempt logs
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CIRCUIT_BREAKER_KEY_PREFIX = "llm_circuit_breaker:"
SIMULATION_UNSTABLE_KEY = "simulation:state:unstable"
RESET_LOG_KEY = "llm_circuit_breaker_reset_log"

# Providers that have circuit breakers
PROVIDERS = ["ollama", "cloudflare", "together", "gemini", "grok", "nim", "openrouter"]

# Cooldown thresholds (seconds) - same as llm_router.py
CIRCUIT_BREAKER_WINDOW = 300  # 5 minutes default

_redis_client = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def is_simulation_unstable() -> bool:
    """
    Check if simulation is in unstable state.
    
    Returns True if simulation state indicates instability,
    meaning circuit breaker resets should be skipped.
    """
    try:
        r = get_redis()
        unstable_flag = r.get(SIMULATION_UNSTABLE_KEY)
        if unstable_flag and unstable_flag.lower() in ("1", "true", "yes"):
            return True
        
        # Also check simulation stability metrics
        stability = r.get("simulation:stability")
        if stability:
            try:
                stability_val = float(stability)
                if stability_val < 0.3:  # Below 30% stability is unstable
                    return True
            except (ValueError, TypeError):
                pass
        
        return False
    except Exception as e:
        logger.debug("Error checking simulation state: %s", e)
        return False


def get_circuit_state(provider: str) -> Tuple[str, int]:
    """
    Get circuit breaker state for a provider.
    
    Returns:
        Tuple of (state, ttl_seconds)
        state: "open", "closed", or "unknown"
        ttl_seconds: remaining TTL for open circuits, or 0/0 if none
    """
    try:
        r = get_redis()
        key = f"{CIRCUIT_BREAKER_KEY_PREFIX}{provider}"
        val = r.get(key)
        ttl = r.ttl(key)
        
        if val == "open":
            return "open", max(0, ttl) if ttl is not None else 0
        elif val is None:
            return "closed", 0
        else:
            return "unknown", 0
    except Exception as e:
        logger.debug("Error getting circuit state for %s: %s", provider, e)
        return "unknown", 0


def reset_circuit_breaker(provider: str) -> bool:
    """
    Attempt to reset a circuit breaker via Redis command.
    
    Returns True if reset was successful.
    """
    try:
        r = get_redis()
        key = f"{CIRCUIT_BREAKER_KEY_PREFIX}{provider}"
        
        # Delete the circuit breaker key to reset it
        result = r.delete(key)
        
        if result:
            # Also clear the failure counter
            r.delete(f"llm_circuit_failures:{provider}")
            return True
        return False
    except Exception as e:
        logger.debug("Error resetting circuit for %s: %s", provider, e)
        return False


def log_reset_attempt(provider: str, success: bool, reason: str) -> None:
    """Log a circuit breaker reset attempt to Redis."""
    try:
        r = get_redis()
        log_entry = {
            "ts": time.time(),
            "provider": provider,
            "success": success,
            "reason": reason,
            "simulation_unstable": is_simulation_unstable(),
        }
        r.zadd(RESET_LOG_KEY, {json.dumps(log_entry): time.time()})
        r.expire(RESET_LOG_KEY, 86400)  # Keep logs for 24h
        r.zremrangebyrank(RESET_LOG_KEY, 0, -1001)  # Keep last 1000 entries
    except Exception as e:
        logger.debug("Error logging reset attempt: %s", e)


def check_and_reset_circuits() -> Dict[str, Any]:
    """
    Check all provider circuit breakers and attempt resets where appropriate.
    
    Returns summary of checks and resets.
    """
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": [],
        "resets_attempted": 0,
        "resets_successful": 0,
        "resets_skipped_unstable": 0,
        "simulation_unstable": is_simulation_unstable(),
    }
    
    for provider in PROVIDERS:
        state, ttl = get_circuit_state(provider)
        
        check_result = {
            "provider": provider,
            "state": state,
            "ttl_remaining": ttl,
            "cooldown_met": ttl == 0 and state == "open",
        }
        
        # Check if circuit is open and cooldown has passed
        if state == "open" and ttl == 0:
            results["checks"].append(check_result)
            results["resets_attempted"] += 1
            
            # Don't reset if simulation is unstable
            if is_simulation_unstable():
                check_result["reset_skipped"] = True
                check_result["skip_reason"] = "Simulation unstable"
                results["resets_skipped_unstable"] += 1
                log_reset_attempt(provider, False, "Simulation unstable - reset skipped")
                continue
            
            # Attempt reset
            success = reset_circuit_breaker(provider)
            check_result["reset_success"] = success
            
            if success:
                results["resets_successful"] += 1
                log_reset_attempt(provider, True, "Cooldown complete, reset successful")
                logger.info("Circuit breaker RESET for provider %s", provider)
            else:
                log_reset_attempt(provider, False, "Reset failed")
                logger.warning("Circuit breaker reset FAILED for provider %s", provider)
        else:
            results["checks"].append(check_result)
    
    return results


def run_continuous(interval: int = 60) -> None:
    """
    Run the circuit breaker monitor continuously.
    
    Args:
        interval: Check interval in seconds (default 60)
    """
    logger.info("Starting Circuit Breaker Reset Monitor (interval=%ds)", interval)
    
    while True:
        try:
            results = check_and_reset_circuits()
            
            if results["resets_successful"] > 0:
                logger.info(
                    "Circuit breaker reset cycle: %d attempted, %d successful, %d skipped (unstable)",
                    results["resets_attempted"],
                    results["resets_successful"],
                    results["resets_skipped_unstable"],
                )
            
            # Log to Gastown dashboard
            try:
                r = get_redis()
                dashboard_entry = {
                    "ts": time.time(),
                    "type": "circuit_breaker_monitor",
                    "resets_successful": results["resets_successful"],
                    "simulation_unstable": results["simulation_unstable"],
                }
                r.zadd("dashboard:events", {json.dumps(dashboard_entry): time.time()})
            except Exception:
                pass
                
        except Exception as e:
            logger.error("Error in circuit breaker monitor cycle: %s", e)
        
        time.sleep(interval)


def get_reset_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent circuit breaker reset history."""
    try:
        r = get_redis()
        logs = r.zrevrange(RESET_LOG_KEY, 0, limit - 1)
        return [json.loads(log) for log in logs]
    except Exception:
        return []


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--single":
        # Single check mode
        results = check_and_reset_circuits()
        print(json.dumps(results, indent=2))
    else:
        # Continuous mode
        interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
        run_continuous(interval)
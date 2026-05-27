#!/usr/bin/env python3
"""
Real-time NPC Monitoring Service for Federation Simulation

This service captures NPC responses in real-time from Redis keyspace notifications
without modifying the source code of the federation game.
"""

import json
import logging
import os
import time
import redis
from typing import Dict, Any, Optional

# Configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MONITOR_CHANNEL = "federation:npc_monitor"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NPCMonitorService:
    def __init__(self):
        self.redis_conn = None
        self.pubsub = None
        self.last_seen = {}  # Track last seen timestamps for polling fallback
        self.use_keyspace_notifications = True
        
    def connect_redis(self):
        """Establish connection to Redis"""
        try:
            self.redis_conn = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            # Test connection
            self.redis_conn.ping()
            logger.info("Connected to Redis successfully")
            
            # Check if keyspace notifications are enabled
            notify_settings = self.redis_conn.config_get('notify-keyspace-events')
            if notify_settings and notify_settings.get('notify-keyspace-events'):
                logger.info(f"Keyspace notifications enabled: {notify_settings['notify-keyspace-events']}")
            else:
                logger.warning("Keyspace notifications not enabled, will use polling fallback")
                self.use_keyspace_notifications = False
                
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    def setup_keyspace_notifications(self):
        """Subscribe to relevant Redis keyspace notifications"""
        if not self.use_keyspace_notifications:
            return
            
        patterns = [
            "__keyspace@0__:npc_thoughts:*",
            "__keyspace@0__:npc_actions:*", 
            "__keyspace@0__:npc_world_events",
            "__keyspace@0__:npc_decisions:*",
            "__keyspace@0__:npc_cognition:*",
            "__keyspace@0__:cognition_triggers",
            "__keyspace@0__:cognition_log"
        ]
        
        self.pubsub = self.redis_conn.pubsub()
        self.pubsub.psubscribe(*patterns)
        logger.info(f"Subscribed to keyspace notifications: {patterns}")
    
    def extract_event_data(self, pattern: str, data: str) -> Optional[Dict[str, Any]]:
        """Extract and format event data from Redis notification"""
        try:
            # Parse the pattern to determine event type and char_id
            if "npc_thoughts" in pattern:
                char_id = pattern.split(":")[-1]
                thoughts_data = self.redis_conn.zrange(f"npc_thoughts:{char_id}", 0, 0)
                if thoughts_data:
                    thought = json.loads(thoughts_data[0])
                    return {
                        "timestamp": thought.get("ts", int(time.time())),
                        "type": "thought",
                        "char_id": char_id,
                        "data": {
                            "thought": thought.get("thought", ""),
                            "mood": thought.get("mood", ""),
                            "cached": thought.get("cached", False)
                        }
                    }
            
            elif "npc_actions" in pattern:
                char_id = pattern.split(":")[-1]
                actions_data = self.redis_conn.zrange(f"npc_actions:{char_id}", 0, 0)
                if actions_data:
                    action = json.loads(actions_data[0])
                    return {
                        "timestamp": action.get("ts", int(time.time())),
                        "type": "action",
                        "char_id": char_id,
                        "data": {
                            "action_type": action.get("action_type", ""),
                            "description": action.get("description", ""),
                            "mood": action.get("mood", "")
                        }
                    }
            
            elif "npc_world_events" in pattern:
                events_data = self.redis_conn.zrange("npc_world_events", 0, 0)
                if events_data:
                    event = json.loads(events_data[0])
                    return {
                        "timestamp": event.get("ts", int(time.time())),
                        "type": "world_event",
                        "char_id": event.get("char_ids", ["unknown"])[0] if event.get("char_ids") else "unknown",
                        "data": {
                            "event_type": event.get("event_type", ""),
                            "description": event.get("description", ""),
                            "interaction_type": event.get("interaction_type", "")
                        }
                    }
            
            elif "npc_decisions" in pattern:
                char_id = pattern.split(":")[-1]
                decisions_data = self.redis_conn.zrange(f"npc_decisions:{char_id}", 0, 0)
                if decisions_data:
                    decision = json.loads(decisions_data[0])
                    return {
                        "timestamp": decision.get("ts", int(time.time())),
                        "type": "decision",
                        "char_id": char_id,
                        "data": {
                            "category": decision.get("category", ""),
                            "description": decision.get("description", ""),
                            "reasoning": decision.get("reasoning", ""),
                            "source": decision.get("source", "")
                        }
                    }
            
            elif "npc_cognition" in pattern:
                char_id = pattern.split(":")[-1]
                cognition_data = self.redis_conn.hgetall(f"npc_cognition:{char_id}")
                if cognition_data:
                    return {
                        "timestamp": int(float(cognition_data.get("last_ts", time.time()))),
                        "type": "cognition",
                        "char_id": char_id,
                        "data": {
                            "model": cognition_data.get("last_model", ""),
                            "category": cognition_data.get("last_category", ""),
                            "trigger": cognition_data.get("last_trigger", "")
                        }
                    }
            
            elif "cognition_triggers" in pattern:
                triggers_data = self.redis_conn.zrange("cognition_triggers", 0, 0)
                if triggers_data:
                    trigger = json.loads(triggers_data[0])
                    return {
                        "timestamp": int(trigger.get("ts", time.time())),
                        "type": "cognition_trigger",
                        "char_id": trigger.get("char_id", "unknown"),
                        "data": {
                            "trigger_type": trigger.get("trigger_type", ""),
                            "priority": trigger.get("priority", 0)
                        }
                    }
            
            elif "cognition_log" in pattern:
                log_data = self.redis_conn.zrange("cognition_log", 0, 0)
                if log_data:
                    log_entry = json.loads(log_data[0])
                    return {
                        "timestamp": int(log_entry.get("ts", time.time())),
                        "type": "cognition_log",
                        "char_id": "system",
                        "data": log_entry
                    }
                    
        except Exception as e:
            logger.error(f"Error extracting event data from pattern {pattern}: {e}")
            
        return None
    
    def process_notification(self, message: Dict[str, Any]):
        """Process a Redis keyspace notification"""
        try:
            if message["type"] != "pmessage":
                return
                
            pattern = message["pattern"]
            channel = message["channel"]  # This is the actual key that changed
            data = message["data"]        # This is the operation (zadd, hset, etc.)
            
            logger.debug(f"Received notification: pattern={pattern}, channel={channel}, data={data}")
            
            # Extract event data
            event = self.extract_event_data(pattern, data)
            if event:
                # Publish to monitor channel
                self.redis_conn.publish(MONITOR_CHANNEL, json.dumps(event))
                logger.debug(f"Published event to {MONITOR_CHANNEL}: {event['type']} for {event['char_id']}")
            else:
                logger.debug(f"No extractable data from notification: {pattern}")
                
        except Exception as e:
            logger.error(f"Error processing notification: {e}")
    
    def run(self):
        """Main service loop"""
        logger.info("Starting NPC Monitoring Service...")
        
        try:
            self.connect_redis()
            self.setup_keyspace_notifications()
            
            logger.info("Monitoring service is running. Waiting for notifications...")
            
            # Process notifications
            for message in self.pubsub.listen():
                if message["type"] in ["pmessage", "subscribe", "psubscribe"]:
                    self.process_notification(message)
                    
        except KeyboardInterrupt:
            logger.info("Shutting down monitoring service...")
        except Exception as e:
            logger.error(f"Monitoring service error: {e}")
            raise
        finally:
            if self.pubsub:
                self.pubsub.close()
            if self.redis_conn:
                self.redis_conn.close()

if __name__ == "__main__":
    service = NPCMonitorService()
    service.run()
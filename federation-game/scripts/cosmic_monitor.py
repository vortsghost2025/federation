#!/usr/bin/env python3
"""Cosmic Horizon Stage 1 overnight monitor — READ-ONLY.

Reads Redis NPC state. No LLM calls. No state writes. No Telegram.
Produces a markdown report at /docker/federation-game/reports/cosmic-horizon-monitor/
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
REDIS_CMD = ["docker", "exec", "federation-game-redis-1", "redis-cli"]
REPORT_DIR = Path("/docker/federation-game/reports/cosmic-horizon-monitor")

# NPCs to monitor
MONITORED_NPCS = ["char_001", "char_306"]
# Ordinary NPCs for leakage check (non-cosmic-tier)
LEAKAGE_CHECK_NPCS = ["char_002", "char_102", "char_103", "char_201", "char_202"]

# Cosmic keywords by tier
VISIONARY_KEYWORDS = [
    "horizon", "beyond", "layers", "substrate", "node",
    "simulation", "deep signal", "other mind", "beyond this node",
    "beyond the federation", "known space", "computing at a scale",
]
SCIENTIFIC_KEYWORDS = [
    "galactic volume", "unexplored system", "long-range projection",
    "federation scale", "sq ly", "sensor gap", "frontier",
    "0.001%", "50 ly", "charted region",
]
FRONTIER_KEYWORDS = [
    "eastern veil", "trade route", "outer sector",
    "sensor range", "strange signal",
]
FORBIDDEN_KEYWORDS = VISIONARY_KEYWORDS + SCIENTIFIC_KEYWORDS + FRONTIER_KEYWORDS

# Broad/noisy terms that should NOT trigger topic fatigue
BROAD_TOPIC_WORDS = {"federation", "report", "analysis", "system", "simulation",
                     "npc", "oracle", "void", "assessment", "strategic",
                     "recommendation", "overview"}

# Reliability keywords
RELIABILITY_FAILURES = ["HTTP 429", "timed out", "HTTP 0", "HTTP 502", "failed", "budget"]


def redis(cmd: list[str]) -> str:
    """Run a redis-cli command and return stdout."""
    full_cmd = REDIS_CMD + cmd
    result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def redis_lrange(key: str, start: int = 0, stop: int = -1) -> list[dict]:
    """Read a Redis list and parse each element as JSON."""
    raw = redis(["LRANGE", key, str(start), str(stop)])
    if not raw:
        return []
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return items


def redis_get(key: str) -> str:
    """Get a single Redis string value."""
    return redis(["GET", key])


def count_keywords(text: str, keywords: list[str]) -> int:
    """Count how many distinct keywords appear in text (case-insensitive)."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def find_snippets(text: str, keywords: list[str], context_chars: int = 80) -> list[str]:
    """Find short snippets around keyword matches."""
    text_lower = text.lower()
    snippets = []
    for kw in keywords:
        kw_lower = kw.lower()
        idx = text_lower.find(kw_lower)
        if idx >= 0:
            start = max(0, idx - context_chars)
            end = min(len(text), idx + len(kw) + context_chars)
            snippet = text[start:end].replace("\n", " ")
            snippets.append(snippet)
    return snippets[:5]  # max 5 snippets


def get_mood_history(char_id: str, count: int = 10) -> list[str]:
    """Read recent mood values from Redis."""
    moods = redis_lrange(f"npc_mood:{char_id}", -count, -1) if char_id else []
    if not moods:
        # Mood is stored as a plain string, not a list
        mood = redis_get(f"npc_mood:{char_id}")
        return [mood] if mood else []
    return [m.get("mood", str(m)) if isinstance(m, dict) else str(m) for m in moods]


def get_decision_counts(char_id: str, n: int = 10) -> list[dict]:
    """Get last N decisions for an NPC (stored as sorted set)."""
    raw = redis(["ZREVRANGE", f"npc_decisions:{char_id}", "0", str(n - 1)])
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return items


def get_artifact_titles(char_id: str, n: int = 5) -> list[str]:
    """Get last N artifact titles."""
    artifacts = redis_lrange(f"npc_artifacts:{char_id}", -n, -1)
    titles = []
    for a in artifacts:
        title = a.get("title", "") if isinstance(a, dict) else str(a)
        if title:
            titles.append(title[:120])
    return titles


def check_ordinary_leakage() -> list[dict]:
    """Check non-cosmic-tier NPCs for forbidden keywords."""
    results = []
    for char_id in LEAKAGE_CHECK_NPCS:
        logs = redis_lrange(f"npc_llm_logs:{char_id}", -10, -1)
        for entry in logs:
            text = json.dumps(entry)
            if count_keywords(text, FORBIDDEN_KEYWORDS) > 0:
                results.append({
                    "char_id": char_id,
                    "snippets": find_snippets(text, FORBIDDEN_KEYWORDS, 60),
                })
                break
    return results


def fmt_ts(t) -> str:
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%H:%M:%S UTC")
    return str(t)


def run_monitor() -> str:
    """Run the full monitor and return the report text."""
    now = datetime.now(timezone.utc)
    report = []
    report.append(f"# Cosmic Horizon Monitor — {now.strftime('%Y-%m-%d %H:%M')} UTC")
    report.append(f"\n_Read-only. No LLM calls. No Redis writes._\n")

    # ── 1. Cosmic Uptake ──────────────────────────────────────────────
    report.append("## 1. Cosmic Uptake\n")

    for char_id in MONITORED_NPCS:
        logs = redis_lrange(f"npc_llm_logs:{char_id}", -20, -1)
        all_text = json.dumps(logs)
        
        visionary_count = count_keywords(all_text, VISIONARY_KEYWORDS)
        scientific_count = count_keywords(all_text, SCIENTIFIC_KEYWORDS)
        frontier_count = count_keywords(all_text, FRONTIER_KEYWORDS)
        total_cosmic = visionary_count + scientific_count + frontier_count

        report.append(f"### {char_id}")
        report.append(f"- Cosmic keyword mentions: {total_cosmic}")
        report.append(f"  - Visionary/simulation: {visionary_count}")
        report.append(f"  - Scientific/cosmological: {scientific_count}")
        report.append(f"  - Frontier/exploration: {frontier_count}")

        if total_cosmic > 0:
            snippets = find_snippets(all_text, FORBIDDEN_KEYWORDS, 60)
            if snippets:
                report.append(f"- Evidence snippets ({len(snippets)} found):")
                for s in snippets[:3]:
                    report.append(f"  > `{s[:200]}`")
        else:
            report.append("- No cosmic language detected in recent logs.")

        # Artifact check
        artifacts = get_artifact_titles(char_id, 5)
        if artifacts:
            art_cosmic = sum(1 for t in artifacts if count_keywords(t, FORBIDDEN_KEYWORDS) > 0)
            report.append(f"- Recent artifacts with cosmic language: {art_cosmic}/{len(artifacts)}")
            for t in artifacts[:3]:
                report.append(f"  - \"{t}\"")
        report.append("")

    # ── 2. Cosmic Spam Check ──────────────────────────────────────────
    report.append("## 2. Cosmic Overfocus Check\n")
    for char_id in MONITORED_NPCS:
        artifacts = get_artifact_titles(char_id, 10)
        if not artifacts:
            report.append(f"- {char_id}: No artifacts found.")
            continue
        cosmic_arts = sum(1 for t in artifacts if count_keywords(t, FORBIDDEN_KEYWORDS) > 0)
        ratio = cosmic_arts / len(artifacts)
        if ratio > 0.5:
            report.append(f"- ⚠️ {char_id}: {cosmic_arts}/{len(artifacts)} artifacts mention cosmic topics ({ratio:.0%}). Possible overfocus.")
        else:
            report.append(f"- ✅ {char_id}: {cosmic_arts}/{len(artifacts)} artifacts mention cosmic topics ({ratio:.0%}). Normal.")
    report.append("")

    # ── 3. Leakage Check ──────────────────────────────────────────────
    report.append("## 3. Leakage Check (ordinary NPCs)\n")
    leakage = check_ordinary_leakage()
    if leakage:
        for l in leakage:
            report.append(f"- ⚠️ {l['char_id']}: Cosmic language detected!")
            for s in l["snippets"][:2]:
                report.append(f"  > `{s[:150]}`")
    else:
        report.append("- ✅ No ordinary-NPC cosmic leakage detected.")
    report.append("")

    # ── 4. Normal Politics Check ──────────────────────────────────────
    report.append("## 4. Normal Politics Check\n")
    for char_id in MONITORED_NPCS:
        decisions = get_decision_counts(char_id, 20)
        decision_text = json.dumps(decisions).lower()
        politics_terms = [
            "federation", "military", "diplomatic", "research", "econom",
            "culture", "council", "threat", "alliance",
            "void", "oracle", "corruption", "artifact",
        ]
        politics_count = count_keywords(decision_text, politics_terms)
        report.append(f"- {char_id}: {politics_count} political/federation keywords in last 20 decisions.")
    
    # Check if there are any events in the world queue
    event_count = len(redis(["LRANGE", "npc_world_events", "0", "-1"]).splitlines()) if redis(["EXISTS", "npc_world_events"]) else 0
    report.append(f"- World events in queue: {event_count}")
    report.append("")

    # ── 5. Reliability ────────────────────────────────────────────────
    report.append("## 5. Reliability\n")
    for char_id in MONITORED_NPCS:
        logs = redis_lrange(f"npc_llm_logs:{char_id}", -50, -1)
        total = len(logs)
        successes = sum(1 for l in logs if l.get("success", False))
        failures = sum(1 for l in logs if not l.get("success", True))
        http_429 = sum(1 for l in logs if "429" in json.dumps(l))
        timeouts = sum(1 for l in logs if "timed out" in json.dumps(l).lower() or "timeout" in json.dumps(l).lower())
        http_0 = sum(1 for l in logs if "HTTP 0" in json.dumps(l))
        http_502 = sum(1 for l in logs if "502" in json.dumps(l))
        fallback = sum(1 for l in logs if "falling back" in json.dumps(l).lower() or "fallback" in json.dumps(l).lower())
        parse_errors = sum(1 for l in logs if "parse" in json.dumps(l).lower())

        latencies = [l.get("latency_ms", 0) for l in logs if l.get("latency_ms")]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        report.append(f"### {char_id} (last {total} calls)")
        report.append(f"- Successes: {successes}/{total} ({successes/total*100:.0f}%)")
        report.append(f"- Failures: {failures}/{total}")
        report.append(f"- HTTP 429: {http_429}")
        report.append(f"- Timeouts: {timeouts}")
        report.append(f"- HTTP 0 (network error): {http_0}")
        report.append(f"- HTTP 502: {http_502}")
        report.append(f"- Fallback used: {fallback}")
        report.append(f"- Parse errors: {parse_errors}")
        report.append(f"- Avg latency: {avg_latency:.0f}ms")
        report.append("")

    # ── 6. Behavior Shape ─────────────────────────────────────────────
    report.append("## 6. Behavior Shape (last 10 decisions)\n")
    for char_id in MONITORED_NPCS:
        decisions = get_decision_counts(char_id, 10)
        if not decisions:
            report.append(f"- {char_id}: No recent decisions found.")
            continue
        
        categories = {}
        for d in decisions:
            cat = d.get("category", "unknown") if isinstance(d, dict) else "unknown"
            categories[cat] = categories.get(cat, 0) + 1
        
        report.append(f"### {char_id}")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            bar = "█" * count
            report.append(f"- {cat}: {count} {bar}")
        
        # Check for repetitive behavior
        cats = [d.get("category", "?") for d in decisions if isinstance(d, dict)]
        if len(cats) >= 3:
            streak_found = False
            for i in range(len(cats) - 2):
                if cats[i] == cats[i+1] == cats[i+2]:
                    report.append(f"- ⚠️ Repetition: {cats[i]} appears 3+ times in a row")
                    streak_found = True
                    break
            if not streak_found:
                report.append("- ✅ No repetitive decision streaks")
        report.append("")

    # ── 7. Mood ───────────────────────────────────────────────────────
    report.append("## 7. Mood\n")
    for char_id in MONITORED_NPCS:
        mood_val = redis_get(f"npc_mood:{char_id}") or "unknown"
        report.append(f"- {char_id}: **{mood_val}**")
    report.append("")

    # ── 8. Topic Fatigue ─────────────────────────────────────────────
    report.append("## 8. Topic Fatigue Monitoring\n")
    for char_id in MONITORED_NPCS:
        logs = redis_lrange(f"npc_llm_logs:{char_id}", -30, -1)
        fatigue_hits = []
        fatigue_resets = []
        for entry in logs:
            up = entry.get("user_prompt", "")
            if "topic_fatigue detected" in up:
                # Extract topic from log text stored in user_prompt artifacts
                pass
        
        # Read actual fatigue from npc_decisions or recent decisions
        # Since fatigue logging goes to stdout, not Redis, we note it's from logs
        report.append(f"### {char_id}")
        report.append(f"- (Fatigue events are logged to container stdout, not Redis.)")
        report.append(f"- Check: `docker logs federation-game-npc-agent-{char_id.replace('char_','')}-1 | grep topic_fatigue`")
        report.append("")

    # ── 9. Broad-Topic False Positives ───────────────────────────────
    report.append("## 9. Broad-Topic False Positive Check\n")
    report.append("The following terms are considered too broad for useful topic fatigue:\n")
    report.append(", ".join(sorted(BROAD_TOPIC_WORDS)))
    report.append("\n")
    for char_id in MONITORED_NPCS:
        sources_text = ""
        artifacts = get_artifact_titles(char_id, 5)
        for t in artifacts:
            for word in BROAD_TOPIC_WORDS:
                if word.lower() in t.lower():
                    sources_text += f"  • \"{t}\" -> contains '{word}'\\n"
                    break
        if sources_text:
            report.append(f"- {char_id}:\n{sources_text}")
        else:
            report.append(f"- {char_id}: No broad-topic false positives in recent artifacts.")
    report.append("")

    # ── Footer ────────────────────────────────────────────────────────
    report.append("---")
    report.append(f"_Generated at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC_")
    report.append("_Read-only. No LLM calls. No Redis writes._")

    return "\n".join(report)


def save_report(text: str):
    """Save report to disk with timestamped and latest copies."""
    now = datetime.now(timezone.utc)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Timestamped copy
    ts_name = now.strftime("%Y-%m-%d-%H-%M-%S") + ".md"
    ts_path = REPORT_DIR / ts_name
    ts_path.write_text(text)

    # Latest copy
    latest_path = REPORT_DIR / "latest.md"
    latest_path.write_text(text)

    print(f"Report saved to {ts_path}")
    print(f"Latest: {latest_path}")


if __name__ == "__main__":
    report = run_monitor()
    save_report(report)
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    # Print a compact summary
    lines = report.split("\n")
    for line in lines:
        if line.startswith("### ") or line.startswith("## 5") or line.startswith("## 6"):
            print(line)
        if "✅" in line or "⚠️" in line or "❌" in line:
            print(line)
    print("=" * 60)

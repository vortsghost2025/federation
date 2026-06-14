# Advanced Analyst Mode (C) Blueprint

## Overview
A separate tab/page for deep debugging and analysis. Exposes raw telemetry, server-side NPC log pagination, CSV export, full provider stats, tick diagnostics, faction power graphs, and debugging views without cluttering the newcomer default page.

## Access
- Route: /simulation.html?mode=analyst or dedicated /analyst.html
- Hidden behind a keyboard shortcut (Ctrl+Shift+A) or footer link
- Not linked from default page

## Data Sources
| Endpoint | Purpose |
|----------|---------|
| /api/npc-logs | Full Postgres-backed NPC history with pagination |
| /api/npc-logs/export | CSV export for offline analysis |
| /simulation/autonomous/status | Tick engine state, LLM budget, cache hit rates |
| /engine-status | Provider health, circuit breakers, latency |
| /factions | Faction power, ideology, member counts |
| /rivals | Rival federation status |
| /world | World conditions, sector states |
| /npcs/stats | Global NPC activity counts |
| /state | Full game state dump

## UI Layout

### Left Panel: World Diagnostics
- **Tick Engine**: Running status, last tick duration, LLM budget used/remaining, thought cache hit rate, parallel workers
- **Provider Health**: Table of all LLM providers (Ollama, NIM, OpenRouter) with status, latency, error rate, circuit breaker state
- **Faction Power Graph**: D3.js force-directed or bar chart showing faction influence, ideology alignment, member count
- **World Conditions**: Sector-by-sector stability, tension, resource levels

### Center Panel: NPC Log Explorer
- **Server-side pagination**: Load 100 entries at a time via offset/limit
- **Filters**: Character, entry type (cognition/interaction/decision/chat), category, date range, relationship delta threshold
- **Columns**: Timestamp, Character, Type, Category, Summary, Target, Relationship Delta, Reasoning
- **Row expansion**: Click to see full raw JSON payload
- **CSV Export button**: Triggers /api/npc-logs/export?char_id=...

### Right Panel: Raw Telemetry
- **Game State JSON**: Collapsible tree view of /state response
- **Event Log**: Recent /event history with payloads
- **Decision Log**: Recent /decision entries with options considered
- **WebSocket Monitor**: Live feed of ws messages (if connected)

## Technical Implementation

### Backend Additions
1. /api/npc-logs - Already exists with pagination, filtering, CSV export
2. /engine-status - New endpoint aggregating provider stats from llm_router
3. /tick-diagnostics - New endpoint with tick engine internals
4. WebSocket /ws/debug - Optional live debug stream

### Frontend
- New analyst.js module loaded conditionally
- Uses simulation.css with additional .analyst-mode styles
- Tab/panel layout with resize handles
- Virtualized list for NPC log rows (handle 10k+ entries)

## Security
- Only accessible in development/staging or with ?debug=true query param
- Not exposed in production without explicit opt-in
- No write endpoints - read-only diagnostics

## Future Extensions
- Time-travel debugger: replay ticks from snapshots
- NPC personality profiler: aggregate stats per character
- Faction interaction matrix: heatmap of cross-faction relationships
- LLM prompt/response inspector: see exact prompts sent to each provider
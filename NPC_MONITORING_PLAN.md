# Real-time NPC Monitoring Plan

## 1. Existing NPC Log/Output Streams

Based on the code analysis, the federation simulation NPC systems write data to Redis. Key streams include:

- **npc_thoughts:{char_id}**: ZSET of recent NPC thoughts (from npc_autonomy.py)
- **npc_actions:{char_id}**: ZSET of recent NPC actions (from npc_autonomy.py)
- **npc_world_events**: ZSET of global events including NPC actions and interactions
- **npc_decisions:{char_id}**: ZSET of recent NPC decisions (from npc_cognition.py)
- **npc_mood:{char_id}**: STRING of current NPC mood
- **npc_opinion:{char_id}:{player_id}**: HASH of NPC opinions about players
- **npc_relationships:{char_id}**: HASH of NPC-to-NPC relationship values
- **npc_goals:{char_id}**: List of NPC goals
- **npc_cognition:{char_id}**: HASH of last LLM cognition call details
- **cognition_triggers**: ZSET of events that triggered cognition
- **cognition_log**: ZSET of audit trail of all cognition calls

## 2. Non-intrusive Capture Method

To capture NPC responses in real-time without modifying source code:

### Approach: Redis Keyspace Notifications + Monitoring Service

1. **Enable Redis Keyspace Notifications** (if not already enabled):
   - Configure Redis to notify on key events (set, zadd, hset, etc.) for relevant key patterns:
     - `__keyspace@0__:npc_thoughts:*`
     - `__keyspace@0__:npc_actions:*`
     - `__keyspace@0__:npc_world_events`
     - `__keyspace@0__:npc_decisions:*`
     - `__keyspace@0__:npc_cognition:*`
     - `__keyspace@0__:cognition_triggers`
     - `__keyspace@0__:cognition_log`

2. **Create a Monitoring Service** (Python-based, non-intrusive):
   - Connects to the same Redis instance as the federation game
   - Subscribes to the configured keyspace notification channels
   - For each notification, retrieves the updated data from the relevant Redis key
   - Filters and extracts only new entries (using timestamps or sequence IDs)
   - Formats extracted data into standardized event objects:
     ```json
     {
       "timestamp": <unix timestamp>,
       "type": "thought|action|decision|mood|opinion|relationship|goal|cognition_trigger|cognition_log",
       "char_id": "<NPC ID>",
       "data": {
         // Type-specific payload (e.g., thought text, action description, etc.)
       }
     }
     ```
   - Publishes events to a Redis Pub/Sub channel: `federation:npc_monitor`

### Fallback: Polling Mechanism (if keyspace notifications cannot be enabled)
- Use a Python service that periodically (every 1-2 seconds) scans relevant Redis keys
- Compares current state with last-known state to detect changes
- Uses efficient SCAN commands and tracks last-seen timestamps/IDs per key
- Otherwise identical event processing and publishing as above

## 3. Gastown Reception and Display Mechanism

### Reception:
- Gastown runs a Node.js listener subscribing to Redis Pub/Sub channel `federation:npc_monitor`
- Upon receiving events, forwards them to a WebSocket server for real-time UI updates

### Display:
- **Web-based Dashboard** served via Nginx (as per project architecture):
  - Simple HTML/JavaScript interface
  - Connects to Gastown's WebSocket server
  - Displays NPC responses in large, readable text (addressing visual disability needs)
  - Organized by NPC ID and type with collapsible sections
  - Auto-scrolls to show latest events
  - Includes filtering options (by NPC, event type, time range)
- **Alternative Console Display** (if web not feasible):
  - Gastown agent writes formatted events to a log file with large-font formatting
  - Uses `tail -f` equivalent in PowerShell with increased font/buffer size

## 4. Implementation Considerations

### Performance:
- Keyspace notifications add minimal overhead to Redis
- Monitoring service uses separate Redis connection, no impact on game logic
- Event processing is lightweight (simple JSON parsing and publishing)

### Reliability:
- Monitoring service includes automatic reconnection to Redis
- Events are buffered briefly during connection interruptions
- Service runs as a separate container/sidecar for isolation

### Security:
- No modifications to existing federation game code
- Uses existing Redis authentication and network security
- Monitoring service runs with least-privileged Redis access (read-only on monitored keys)

## 5. Verification Steps

1. Confirm Redis keyspace notifications are active:
   ```bash
   redis-cli config get notify-keyspace-events
   ```
2. Start monitoring service and verify it receives events
3. Check Gastown WebSocket server receives and forwards events
4. Validate dashboard displays NPC responses in real-time with readable text
5. Test fallback polling mechanism if needed
6. Ensure no performance impact on federation game during monitoring

## 6. Deliverables

- `monitor_service.py`: Python implementation of the monitoring service
- `gastown_listener.js`: Node.js listener for Gastown
- `dashboard.html`: Simple web dashboard for displaying NPC responses
- `setup_instructions.md`: Steps to enable Redis notifications and deploy services
# Round 1 Test Results

## Backend Unit Tests (local, with mocks)

### test_event_token.py — 6/6 PASS
- test_event_returns_choice_token
- test_choose_with_valid_token
- test_choose_with_invalid_token
- test_choose_with_expired_token
- test_choose_without_token_fails
- test_event_token_uuid_format

### test_reset_singleton.py — 5/5 PASS
- test_reset_clears_state
- test_reset_reinitializes_defaults
- test_game_state_is_singleton
- test_percent_metrics_is_set
- test_import_succeeds_with_mocks

**Total: 11/11 PASS**

## Production Verification

| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| /healthz | GET | 200 | Backend healthy |
| /event | GET | 200 | Returns event + choice_token (UUID v4) |
| /choose | POST | 200 | Validates token, returns outcome |
| /npcs | GET | 200 | NPC list with pagination |
| /state | GET | 200 | Full game state snapshot |

## Docker Status

```
federation-game-backend-1    Up (healthy)
federation-game-db-1         Up
federation-game-redis-1      Up
federation-game-traefik-1    Up
```

## Alembic

- `docker compose config --quiet` → COMPOSE_OK
- Migration file: 9dc58ae19f69_initial_migration.py deployed
- DB init path: stamp-at-head if tables exist → upgrade → create_all() fallback

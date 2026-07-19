# G4A — Shadow Artifact Staging on VPS (READ-ONLY VALIDATION)

Status: COMPLETE (staging + validation only). No build, no containers, no prod changes.
Authorized scope: create npc-agent-shadow/, copy 6 files, verify SHA-256, run compose config.

## Staged files (VPS /docker/federation-game)
| File | SHA-256 (VPS) | Match local HEAD a998ac2 |
|------|---------------|--------------------------|
| docker-compose-shadow.yml | 7ce89a7f184fb876787965aa2cbbd19f1ca64c28f3dc0dbba4436650d1cdf0a0 | YES |
| npc-agent-shadow/Dockerfile | cadc3c9aae8b3793d20eaa631a4d4ee80419ba28b6ace38be3473c1a52bd0ad6 | YES |
| npc-agent-shadow/npc_shadow_mode.py | 20a2fda7b42abd71060be18da3087de052502c605a79992412bb56e23a1ab719 | YES |
| npc-agent-shadow/npc_redis_helpers.py | f8235b98d33fd5ce30e233f0d96b9ff1c4ad92978ae40d0cd12f33b5ac730145 | YES |
| npc-agent-shadow/qualify_shadow.py | a355ba821cdc2eb038745b6af05f509d9cac30c26d7195371eb0174639dc7781 | YES |
| npc-agent-shadow/test_npc_shadow_mode.py | b95ba558ae679207f7be07b68156b4adc38413fa0346756c228cc8640def1f4e | YES |

All 6 SHAs match local Git HEAD byte-for-byte.

## Production protection check
- /docker/federation-game/npc-agent/ NOT modified.
- npc_shadow_mode.py correctly ABSENT from prod build context.
- npc_redis_helpers.py in prod retains original Jul 18 15:41 mtime (unchanged).
- Production compose (.env, docker-compose.yml) NOT touched.

## compose config validation
- `docker compose -f docker-compose-shadow.yml config` -> exit 0.
- Confirmed: restart:"no", cap_drop:ALL, no-new-privileges:true, read_only:true,
  isolated shadow-net (no fed-net), all credentials empty, SHADOW_MODE=true,
  SHADOW_PROVIDER=mock, bounded mem/cpu/pids/ticks/runtime/calls/log.

## Open item for G4 build/launch (separate authorization)
The Dockerfile COPYs shadow modules from build context ./npc-agent, but G4A staged
them into npc-agent-shadow/ to avoid overwriting prod npc-agent/. At build time, the
4 modules must be placed into the npc-agent/ build context (or the Dockerfile revised
to COPY from a sidecar). This is a build-step concern, not a staging defect.

## Not done in G4A (deferred to authorized G4 launch)
- No image build.
- No network/volume/container creation.
- No service start/restart.
- No Redis/Postgres write.
- No real provider credentials used.

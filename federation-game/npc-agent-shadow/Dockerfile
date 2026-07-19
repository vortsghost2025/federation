# NPC Shadow container — local qualification only. Not for production use.
# Runs npc_agent in SHADOW_MODE against a dedicated fake Redis and a mock
# provider. No production credentials, no production endpoints, no writes to
# Postgres/messages/artifacts/institutions/capabilities. Reversible and bounded.
FROM python:3.11-slim

# Create a non-root user.
RUN groupadd -r shadow && useradd -r -g shadow -u 10001 shadow

WORKDIR /app

# Copy only the runtime modules required for shadow cognition.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY npc_shadow_mode.py \
     npc_actions.py \
     npc_redis_helpers.py \
     npc_decisions.py \
     npc_loop_control.py \
     npc_llm_client.py \
     npc_agent.py \
     /app/

# Dedicated writable volume for the append-only intent log.
VOLUME ["/shadow-log"]

# Drop all capabilities, no new privileges, read-only root filesystem.
USER shadow

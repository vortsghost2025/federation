# NPC Shadow container — local qualification only. Not for production use.
# Runs npc_agent in SHADOW_MODE against a dedicated fake Redis and a mock
# provider. No production credentials, no production endpoints, no writes to
# Postgres/messages/artifacts/institutions/capabilities. Reversible and bounded.
FROM python:3.11-slim

# Create a non-root user.
RUN groupadd -r shadow 2>/dev/null || true && useradd -r -g shadow -u 10001 shadow 2>/dev/null || true

WORKDIR /app

# Copy only the runtime modules required for shadow cognition.
# All modules live inside the isolated npc-agent-shadow build context.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY npc_shadow_mode.py \
     npc_actions.py \
     npc_redis_helpers.py \
     npc_decisions.py \
     npc_loop_control.py \
     npc_llm_client.py \
     npc_agent.py \
     fourth_wall.py \
     npc_context.py \
     npc_memory_bridge.py \
     cosmic_monitor.py \
     institutions.py \
     qualify_shadow.py \
     shadow_npc_main.py \
     /app/

# Dedicated writable volume for the append-only intent log.
VOLUME ["/shadow-log"]

# Ensure the non-root shadow user can write the intent log volume.
RUN mkdir -p /shadow-log && chown -R shadow:shadow /shadow-log

# Drop all capabilities, no new privileges, read-only root filesystem.
USER shadow

#!/usr/bin/env python3
"""End-to-end DB1 lifecycle test for the Federation Architect Loop."""
import json, os, subprocess, sys, time, uuid
import redis

DB1_URL    = "redis://172.16.2.12:6379/1"
MONITOR    = "/docker/federation-architect/monitor.py"
ARCHITECT  = "/docker/federation-architect"
REG_FILE   = os.path.join(ARCHITECT, "state", "registry.json")
PACKET_DIR = os.path.join(ARCHITECT, "requests")

REQ_ID     = f"capreq_e2e_{uuid.uuid4().hex[:12]}"
STABLE_ID  = f"stab_{uuid.uuid4().hex[:8]}"
AGENDA_ID  = "agenda_e2e_test"

def r():  return redis.from_url(DB1_URL, decode_responses=True, socket_timeout=8)

def monitor():  return subprocess.run(["python3", MONITOR], capture_output=True, text=True, timeout=30, cwd=ARCHITECT)

def reg():  return json.load(open(REG_FILE))

def packet():
    p = os.path.join(PACKET_DIR, REQUEST_ID+".md")
    return open(p).read() if os.path.isfile(p) else ""

def set_status(s):  db().hset(f"npc_capability_request:{REQUEST_ID}", "status", s)

# ── Step 1: Create in DB1 ───────
def s1():
    r = db()
    t = int(time.time())
    k = f"npc_capability_request:{REQUEST_ID}"
    r.hset(k, mapping={
        "request_id": REQUEST_ID, "stable_id": STABLE_ID,
        "agenda_item_id": AGENDA_ID, "pair_slug": "char_001__char_306",
        "requester_id": "char_001", "collaborating_councilor_id": "char_306",
        "capability_key": "e2e_integration",
        "title": "E2E Integration Test",
        "objective": "Prove architect loop works end-to-end in DB1.",
        "blocker": "Missing e2e validation.",
        "attempts": "Manual only.",
        "evidence": "Phase 1 monitor functional.",
        "requested_change": "Deploy e2e cycle.",
        "acceptance_criteria": "All stages pass, request→verified.",
        "expected_benefit": "Operates.",
        "implementation_risks": "None.",
        "priority": "medium", "status": "submitted",
        "lifecycle_version": "0", "created_ts": str(t),
        "updated_ts": str(t), "transitions": "[]",
    })
    r.zadd("npc_capability_requests:index", {REQUEST_ID: float(t)})
    print(f"[OK] s1: Request {REQUEST_ID} created")

# ── Step 2: Monitor → detect ────
def s2():
    monitor()
    r2 = reg()
    assert REQUEST_ID in r2["requests"], f"Monitor missed {REQUEST_ID}"
    assert r2["requests"][REQUEST_ID]["status"] == "submitted"
    print("[OK] s2: Monitor detected")

# ── Step 3: Packet ───────────────
def s3():
    c = pkt()
    for s in ["Objective","Blocker","Requested Change","Evidence",
              "Acceptance Criteria","Expected Benefit","Implementation Risks"]:
        assert f"## {s}" in c
    assert "kilo run" in c
    print("[OK] s3: Packet valid")

# ── Step 4a–4d: Transitions ──────
for status_label, status_value in [
    ("acknowledged","acknowledged"), ("approved","approved"),
    ("delivered","delivered"), ("verified","verified")]:
    def s4(state):
        set_status(state)
        monitor()
        assert reg()["requests"][REQUEST_ID]["status"] == state
        print(f"[OK] s4_{state}")
    globals()[f"s4_{status_label}"] = lambda s=status_value: s4(s)

# ── Step 5: Idempotency ────────
def s5_idempotent():
    monitor()
    assert REQUEST_ID in reg()["requests"]
    print("[OK] s5: idempotent (still tracked once)")

# ── Step 6: Cleanup ─────────────
def s6_cleanup():
    db().delete(f"npc_capability_request:{REQUEST_ID}")
    print("[OK] s6: DB1 key cleaned")

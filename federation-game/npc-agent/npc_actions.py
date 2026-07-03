"""
NPC Actions — execute_decision() and all action handlers.

Extracted from npc_agent.py as part of Phase 1 monolith breakup.
Each function takes explicit parameters (char_id, contacts) instead of
relying on module-level globals, avoiding circular imports.
"""
import json
import logging
import os
import random
import re
import time
import uuid

from fourth_wall import _enforce_fourth_wall
from npc_llm_client import call_llm
from npc_context import most_common_topic_word, normalize_topic_label
from npc_decisions import _is_repetitive_artifact, _acknowledge_inbox
from npc_redis_helpers import (
    get_redis,
    _partner_id,
    _conversation_thread_id,
    _pair_thread_id,
    _store_thread_message,
    _compact_text,
    _message_cooldown_remaining,
    _sync_pair_workspace,
    _session_append,
)

# ── Institution bloat guards ──
_MAX_INSTITUTIONS_PER_NPC = 8
_TOTAL_INSTITUTION_LIMIT = 20
_INST_SUFFIXES = (
    "committee", "bureau", "council", "authority", "agency",
    "tribunal", "assembly", "board", "directorate", "commission",
    "consortium",
)


def _normalize_inst_name(name: str) -> str:
    """Strip common suffixes for similar-name detection."""
    n = name.lower().strip()
    for sfx in _INST_SUFFIXES:
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
            break
    return re.sub(r"[^a-z0-9_]+", "", n).strip("_")

logger = logging.getLogger("npc_agent")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
OPERATOR_ID = "moderator"
SESSION_CAP = int(os.environ.get("SESSION_CAP", "24"))

PAIR_IDS = {"char_001", "char_306"}


def execute_decision(decision: dict, r, contacts: dict):
    cat = decision.get("category", "rest")
    desc = _enforce_fourth_wall(decision.get("description", ""))
    reasoning = _enforce_fourth_wall(decision.get("reasoning", ""))
    ts = int(time.time())
    partner_id = _partner_id()

    logger.info("[%s] Decision: %s — %s", CHAR_ID, cat, desc[:80])

    result = {
        "char_id": CHAR_ID,
        "char_name": NPC_NAME,
        "category": cat,
        "description": _enforce_fourth_wall(desc),
        "reasoning": reasoning,
        "ts": ts,
        "action_taken": "none",
    }

    if cat == "send_message":
        target = decision.get("target", "")
        body = _enforce_fourth_wall(decision.get("body", desc))
        result["message_body"] = body
        if target and target in contacts and target != CHAR_ID:
            cooldown_remaining = _message_cooldown_remaining(r, target) if target == partner_id else 0
            if cooldown_remaining > 0:
                result["action_taken"] = "message_deferred_to_workspace"
                result["cooldown_remaining_s"] = cooldown_remaining
                _session_append(r, {
                    "kind": "workspace_sync",
                    "actor": NPC_NAME,
                    "body": f"held direct note until cooldown clears: {body[:120]}",
                })
            else:
                thread_id = (
                    _pair_thread_id(r, target)
                    if target in PAIR_IDS and CHAR_ID in PAIR_IDS
                    else _conversation_thread_id(CHAR_ID, target)
                )
                msg_topic = normalize_topic_label(decision.get("topic", "") or desc or body)
                msg_id = str(uuid.uuid4())
                msg = {
                    "id": msg_id,
                    "msg_id": msg_id,
                    "from_char_id": CHAR_ID,
                    "from_name": NPC_NAME,
                    "to_char_id": target,
                    "to_name": contacts.get(target, target),
                    "subject": desc[:60],
                    "body": _enforce_fourth_wall(body),
                    "type": decision.get("message_type", "direct_message"),
                    "topic": msg_topic,
                    "read": False,
                    "created_at": ts,
                    "ts": ts,
                    "thread_id": thread_id,
                }
                r.rpush(f"npc_messages:{target}:inbox", json.dumps(msg))
                _store_thread_message(r, msg, thread_id)
                try:
                    r.rpush(
                        f"npc_session:{target}",
                        json.dumps({
                            "kind": "message_received",
                            "actor": NPC_NAME,
                            "from_name": NPC_NAME,
                            "from": CHAR_ID,
                            "body": body,
                            "ts": ts,
                        }, default=str),
                    )
                    r.ltrim(f"npc_session:{target}", -SESSION_CAP, -1)
                except Exception:
                    pass
                r.rpush(f"npc_messages:{CHAR_ID}:sent", json.dumps(msg))
                r.hincrby(f"npc_stats:{CHAR_ID}", "messages_sent", 1)
                result["action_taken"] = "message_sent"
                result["target"] = target
                result["thread_id"] = thread_id
                logger.info("[%s] Sent message to %s via %s", CHAR_ID, target, thread_id)
                _session_append(r, {
                    "kind": "message_sent",
                    "actor": NPC_NAME,
                    "to_name": contacts.get(target, target),
                    "to": target,
                    "body": body,
                })
        else:
            result["action_taken"] = "no_target"

    elif cat == "create_artifact":
        title = decision.get("title", desc[:60] if desc else "Untitled")
        if r is not None and _is_repetitive_artifact(r, title):
            logger.info("[%s] Dedup gate blocked artifact '%s' (too similar to recent)", CHAR_ID, title)
            result["action_taken"] = "artifact_deferred_dedup"
            result["artifact_title"] = title
            _session_append(r, {
                "kind": "workspace_sync",
                "actor": NPC_NAME,
                "body": f"deferred artifact '{title[:60]}' — content too similar to recent work",
            })
            streak_key = f"npc_dedup_streak:{CHAR_ID}"
            r.incr(streak_key)
            r.expire(streak_key, 600)
            dedup_topic = most_common_topic_word([title])
            if dedup_topic:
                r.set(f"npc_dedup_topic:{CHAR_ID}", dedup_topic, ex=600)
        else:
            content_prompt = f"Write the full content of this artifact:\n\n{desc}\n\nOutput only the content."
            llm_result = call_llm("You are a creative writer.", content_prompt, r=r, call_label="artifact")
            artifact_content = _enforce_fourth_wall(llm_result.get("content", desc))
            artifact = {
                "artifact_id": str(uuid.uuid4()),
                "char_id": CHAR_ID,
                "char_name": NPC_NAME,
                "title": _enforce_fourth_wall(title),
                "artifact_type": "text",
                "content": artifact_content,
                "created_at": ts,
            }
            r.rpush(f"npc_artifacts:{CHAR_ID}", json.dumps(artifact))
            r.rpush("npc_artifacts:global", json.dumps(artifact))
            r.hincrby(f"npc_stats:{CHAR_ID}", "artifacts_created", 1)
            streak_key = f"npc_dedup_streak:{CHAR_ID}"
            if r.exists(streak_key):
                r.delete(streak_key)
            try:
                r.delete(f"npc_dedup_topic:{CHAR_ID}")
            except Exception:
                pass
            try:
                partner_id_local = _partner_id()
                r.rpush(
                    f"npc_session:{partner_id_local}",
                    json.dumps({
                        "kind": "artifact_published_by_partner",
                        "actor": NPC_NAME,
                        "from": CHAR_ID,
                        "title": title,
                        "chars": len(artifact_content),
                        "ts": ts,
                    }, default=str),
                )
                r.ltrim(f"npc_session:{partner_id_local}", -SESSION_CAP, -1)
            except Exception:
                pass
            result["action_taken"] = "artifact_created"
            result["artifact_title"] = title
            logger.info("[%s] Created artifact: %s", CHAR_ID, title)
            _session_append(r, {
                "kind": "artifact_created",
                "actor": NPC_NAME,
                "title": title,
                "body": f"{len(artifact_content)} chars; first 80: {artifact_content[:80]}",
            })

    elif cat == "write_code":
        code_prompt = f"Generate Python code for: {desc}\n\nOutput ONLY valid Python code."
        llm_result = call_llm("You are a Python developer. Output only code.", code_prompt, r=r, call_label="code")
        gen_code = llm_result.get("content", "")
        if gen_code:
            artifact = {
                "artifact_id": str(uuid.uuid4()),
                "char_id": CHAR_ID,
                "char_name": NPC_NAME,
                "title": f"Code: {desc[:60]}",
                "artifact_type": "code",
                "content": gen_code,
                "created_at": ts,
            }
            r.rpush(f"npc_artifacts:{CHAR_ID}", json.dumps(artifact))
            r.rpush("npc_artifacts:global", json.dumps(artifact))
            r.hincrby(f"npc_stats:{CHAR_ID}", "code_written", 1)
            result["action_taken"] = "code_executed"
            result["artifact_title"] = artifact["title"]
            logger.info("[%s] Wrote code for: %s", CHAR_ID, desc[:60])
            _session_append(r, {
                "kind": "code_written",
                "actor": NPC_NAME,
                "title": f"Code: {desc[:60]}",
                "body": f"{len(gen_code)} chars",
            })
        else:
            result["action_taken"] = "code_failed"

    elif cat == "read_artifacts":
        try:
            partner_artifacts = r.lrange(f"npc_artifacts:{partner_id}", -6, -1)
            if partner_artifacts:
                summaries = []
                titles = []
                for a in reversed(partner_artifacts):
                    try:
                        obj = json.loads(a)
                        titles.append(obj.get("title", "?"))
                        summaries.append(f"{obj.get('title', '?')} ({obj.get('artifact_type', 'text')})")
                    except Exception:
                        pass
                result["action_taken"] = f"read {len(summaries)} recent artifacts from {partner_id}"
                result["summary"] = "; ".join(summaries)
                logger.info("[%s] Read artifacts from %s: %s", CHAR_ID, partner_id, summaries)
                _session_append(r, {
                    "kind": "artifact_read",
                    "actor": NPC_NAME,
                    "from_name": contacts.get(partner_id, partner_id),
                    "from": partner_id,
                    "title": titles[0] if titles else "(none)",
                    "body": f"read {len(titles)} recent artifact(s)",
                })
            else:
                result["action_taken"] = "no_artifacts"
                _session_append(r, {
                    "kind": "artifact_read",
                    "actor": NPC_NAME,
                    "from_name": contacts.get(partner_id, partner_id),
                    "from": partner_id,
                    "title": "(none available)",
                    "body": "partner has no artifacts yet",
                })
        except Exception as e:
            result["action_taken"] = f"read_error: {e}"

    elif cat == "investigate":
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or "investigating the pair state"
        r.hincrby(f"npc_stats:{CHAR_ID}", "investigations", 1)
        result["action_taken"] = "investigation_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "investigation",
            "actor": NPC_NAME,
            "body": note,
        })

    elif cat == "self_improve":
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or "improving councilor capabilities"
        r.hincrby(f"npc_stats:{CHAR_ID}", "self_improvement_turns", 1)
        result["action_taken"] = "self_improvement_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "self_improve",
            "actor": NPC_NAME,
            "body": note,
        })

    elif cat == "rest":
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or "reflecting on the shared councilor work"
        r.hincrby(f"npc_stats:{CHAR_ID}", "reflection_turns", 1)
        result["action_taken"] = "reflection_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "reflection",
            "actor": NPC_NAME,
            "body": note,
        })

    elif cat == "create_institution":
        from datetime import datetime, timezone
        inst_name = decision.get("institution_name", desc[:60] if desc else "Unnamed Body")
        inst_kind = decision.get("institution_kind", "council")
        mandate = decision.get("mandate", desc[:200] if desc else "To be defined.")
        slug = re.sub(r"[^a-z0-9]+", "_", inst_name.lower()).strip("_")[:48]
        inst_id = f"institution:{slug}"
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            existing = r.hgetall(inst_id)
            if existing:
                result["action_taken"] = "institution_already_exists"
                result["institution_id"] = inst_id
                result["summary"] = f"Institution '{inst_name}' already exists"
                _session_append(r, {
                    "kind": "institution_proposed",
                    "actor": NPC_NAME,
                    "body": f"proposed institution '{inst_name}' but it already exists as {inst_id}",
                })
            else:
                # ── Institution bloat guards ──
                _rejected = False

                # 1. Per-NPC institution cap
                founded = int(r.hget(f"npc_stats:{CHAR_ID}", "institutions_founded") or 0)
                if founded >= _MAX_INSTITUTIONS_PER_NPC:
                    _rejected = True
                    result["action_taken"] = "institution_cap_reached"
                    result["summary"] = (
                        f"Institution '{inst_name}' not created — "
                        f"each councilor may found at most {_MAX_INSTITUTIONS_PER_NPC} institutions"
                    )
                    logger.info("[%s] Institution cap reached for %s", CHAR_ID, inst_name)
                    _session_append(r, {
                        "kind": "institution_rejected",
                        "actor": NPC_NAME,
                        "body": (
                            f"attempted to found '{inst_name}' but has already founded"
                            f" {founded} institutions (cap: {_MAX_INSTITUTIONS_PER_NPC})"
                        ),
                    })

                # 2. Total institution cap
                if not _rejected:
                    total = r.scard("institution:index")
                    if total >= _TOTAL_INSTITUTION_LIMIT:
                        _rejected = True
                        result["action_taken"] = "institution_total_cap_reached"
                        result["summary"] = (
                            f"Institution '{inst_name}' not created — "
                            f"Federation institution limit of {_TOTAL_INSTITUTION_LIMIT} reached"
                        )
                        logger.info("[%s] Total institution cap reached for %s", CHAR_ID, inst_name)
                        _session_append(r, {
                            "kind": "institution_rejected",
                            "actor": NPC_NAME,
                            "body": (
                                f"attempted to found '{inst_name}' but total Federation institution"
                                f" cap of {_TOTAL_INSTITUTION_LIMIT} has been reached"
                            ),
                        })

                # 3. Similar-name check
                if not _rejected:
                    normalized_new = _normalize_inst_name(inst_name)
                    similar_exists = None
                    for iid in r.smembers("institution:index"):
                        rec = r.hgetall(iid)
                        en = rec.get("name", "")
                        if en and _normalize_inst_name(en) == normalized_new:
                            similar_exists = en
                            break
                    if similar_exists:
                        _rejected = True
                        result["action_taken"] = "institution_similar_exists"
                        result["summary"] = (
                            f"Institution '{inst_name}' not created — "
                            f"similar to existing '{similar_exists}'"
                        )
                        logger.info("[%s] Similar institution exists: %s ~ %s", CHAR_ID, inst_name, similar_exists)
                        _session_append(r, {
                            "kind": "institution_rejected",
                            "actor": NPC_NAME,
                            "body": f"proposed '{inst_name}' but similar to existing '{similar_exists}'",
                        })

                # ── Create institution (passes all guards) ──
                if not _rejected:
                    r.sadd("institution:index", inst_id)
                    r.hset(inst_id, mapping={
                        "name": inst_name,
                        "kind": inst_kind,
                        "mandate": mandate,
                        "status": "proposed",
                        "proposed_by": CHAR_ID,
                        "created_at": now_iso,
                    })
                    r.hincrby(f"npc_stats:{CHAR_ID}", "institutions_founded", 1)
                    result["action_taken"] = "institution_created"
                    result["institution_id"] = inst_id
                    result["institution_name"] = inst_name
                    result["summary"] = f"Proposed new institution: {inst_name} ({inst_kind})"
                    logger.info("[%s] Created institution: %s (%s)", CHAR_ID, inst_name, inst_id)
                    _session_append(r, {
                        "kind": "institution_founded",
                        "actor": NPC_NAME,
                        "title": inst_name,
                        "body": f"founded {inst_kind} '{inst_name}' — mandate: {mandate[:120]}",
                    })
                    try:
                        partner_id_local = _partner_id()
                        r.rpush(f"npc_session:{partner_id_local}", json.dumps({
                            "kind": "institution_founded_by_partner",
                            "actor": NPC_NAME,
                            "from": CHAR_ID,
                            "title": inst_name,
                            "mandate": mandate[:120],
                            "ts": ts,
                        }, default=str))
                        r.ltrim(f"npc_session:{partner_id_local}", -SESSION_CAP, -1)
                    except Exception:
                        pass
        except Exception as e:
            result["action_taken"] = f"institution_error: {e}"
            logger.error("[%s] Institution creation failed: %s", CHAR_ID, e)

    elif cat == "propose_role":
        from datetime import datetime, timezone
        target_inst_name = decision.get("institution_name", "")
        role_title = decision.get("role_title", desc[:60] if desc else "Unnamed Role")
        scope = decision.get("scope", desc[:200] if desc else "To be defined.")
        authority = decision.get("authority", "observe_and_report")
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            target_inst_id = None
            for iid in r.smembers("institution:index"):
                rec = r.hgetall(iid)
                if rec.get("name", "") == target_inst_name:
                    target_inst_id = iid
                    break
            if not target_inst_id:
                my_inst = r.get(f"councilor:{CHAR_ID}:institution")
                if my_inst:
                    target_inst_id = my_inst
                else:
                    first_inst = sorted(r.smembers("institution:index"))
                    target_inst_id = first_inst[0] if first_inst else None
            if not target_inst_id:
                result["action_taken"] = "role_no_institution"
                result["summary"] = "No institution found to propose role in"
                _session_append(r, {
                    "kind": "role_proposal_failed",
                    "actor": NPC_NAME,
                    "body": f"could not find institution for proposed role '{role_title}'",
                })
            else:
                slug = re.sub(r"[^a-z0-9]+", "_", role_title.lower()).strip("_")[:48]
                role_id = f"role:{slug}"
                existing = r.hgetall(role_id)
                if existing:
                    result["action_taken"] = "role_already_exists"
                    result["role_id"] = role_id
                    result["summary"] = f"Role '{role_title}' already exists"
                    _session_append(r, {
                        "kind": "role_proposal_failed",
                        "actor": NPC_NAME,
                        "body": f"proposed role '{role_title}' but it already exists",
                    })
                else:
                    r.sadd("role:index", role_id)
                    r.hset(role_id, mapping={
                        "institution_id": target_inst_id,
                        "title": role_title,
                        "scope": scope,
                        "authority": authority,
                        "holder_char_id": "",
                        "proposed_by": CHAR_ID,
                        "status": "proposed",
                        "created_at": now_iso,
                    })
                    r.sadd(f"{target_inst_id}:roles", role_id)
                    r.hincrby(f"npc_stats:{CHAR_ID}", "roles_proposed", 1)
                    inst_rec = r.hgetall(target_inst_id)
                    result["action_taken"] = "role_proposed"
                    result["role_id"] = role_id
                    result["institution_id"] = target_inst_id
                    result["role_title"] = role_title
                    result["summary"] = f"Proposed role '{role_title}' in {inst_rec.get('name', target_inst_id)}"
                    logger.info("[%s] Proposed role: %s in %s", CHAR_ID, role_title, target_inst_id)
                    _session_append(r, {
                        "kind": "role_proposed",
                        "actor": NPC_NAME,
                        "title": role_title,
                        "body": f"proposed role '{role_title}' (authority: {authority}) in {inst_rec.get('name', target_inst_id)} — scope: {scope[:120]}",
                    })
        except Exception as e:
            result["action_taken"] = f"role_error: {e}"
            logger.error("[%s] Role proposal failed: %s", CHAR_ID, e)

    elif cat == "submit_to_institution":
        from datetime import datetime, timezone
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
        from institutions import ensure_workflow, classify_artifact_kind, WORKFLOW_DEFAULTS
        artifact_title = decision.get("artifact_title", "")
        target_inst_name = decision.get("institution_name", "")
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            target_inst_id = None
            for iid in r.smembers("institution:index"):
                rec = r.hgetall(iid)
                if rec.get("name", "") == target_inst_name:
                    target_inst_id = iid
                    break
            if not target_inst_id:
                my_inst = r.get(f"councilor:{CHAR_ID}:institution")
                if my_inst:
                    target_inst_id = my_inst
            if not target_inst_id:
                result["action_taken"] = "submit_no_institution"
                result["summary"] = f"No institution '{target_inst_name}' found for submission"
                _session_append(r, {
                    "kind": "institution_submit_failed",
                    "actor": NPC_NAME,
                    "body": f"could not find institution for artifact submission",
                })
            else:
                matching_artifact = None
                raw_artifacts = r.lrange(f"npc_artifacts:{CHAR_ID}", -10, -1)
                for a in reversed(raw_artifacts):
                    try:
                        obj = json.loads(a)
                        if obj.get("title", "").lower() == artifact_title.lower():
                            matching_artifact = obj
                            break
                        if artifact_title.lower() in obj.get("title", "").lower():
                            matching_artifact = obj
                            break
                    except Exception:
                        continue
                if not matching_artifact and raw_artifacts:
                    try:
                        matching_artifact = json.loads(raw_artifacts[-1])
                    except Exception:
                        pass
                if not matching_artifact:
                    result["action_taken"] = "submit_no_artifact"
                    result["summary"] = f"No matching artifact found for '{artifact_title}'"
                    _session_append(r, {
                        "kind": "institution_submit_failed",
                        "actor": NPC_NAME,
                        "body": f"no artifact '{artifact_title}' to submit for review",
                    })
                else:
                    role_ctx = {
                        "institution_id": target_inst_id,
                        "institution_name": r.hget(target_inst_id, "name") or target_inst_name,
                        "role_id": r.get(f"councilor:{CHAR_ID}:role") or "",
                        "role_title": "",
                    }
                    art_kind = classify_artifact_kind(matching_artifact)
                    if art_kind not in ("proposal", "analysis"):
                        art_kind = "proposal"
                    wf_type = "proposal_review" if art_kind == "proposal" else "analysis_review"
                    existing_wf = r.get(f"workflow:source_artifact:{matching_artifact['artifact_id']}")
                    if existing_wf:
                        result["action_taken"] = "submit_already_in_review"
                        result["workflow_id"] = existing_wf
                        result["summary"] = f"Artifact '{matching_artifact.get('title', '?')}' already in review"
                        _session_append(r, {
                            "kind": "institution_submit_duplicate",
                            "actor": NPC_NAME,
                            "body": f"artifact '{matching_artifact.get('title', '?')}' already has workflow {existing_wf}",
                        })
                    else:
                        workflow_id = ensure_workflow(r, CHAR_ID, matching_artifact, role_ctx, wf_type, now=now_iso)
                        r.hincrby(f"npc_stats:{CHAR_ID}", "artifacts_submitted_for_review", 1)
                        result["action_taken"] = "artifact_submitted"
                        result["workflow_id"] = workflow_id
                        result["artifact_title"] = matching_artifact.get("title", "?")
                        result["institution_id"] = target_inst_id
                        result["summary"] = f"Submitted '{matching_artifact.get('title', '?')}' for {wf_type} in {role_ctx['institution_name']}"
                        logger.info("[%s] Submitted artifact %s for %s review: %s", CHAR_ID, matching_artifact.get("title", "?"), wf_type, workflow_id)
                        _session_append(r, {
                            "kind": "artifact_submitted_for_review",
                            "actor": NPC_NAME,
                            "title": matching_artifact.get("title", "?"),
                            "body": f"submitted '{matching_artifact.get('title', '?')}' for {wf_type} in {role_ctx['institution_name']}",
                        })
        except Exception as e:
            result["action_taken"] = f"submit_error: {e}"
            logger.error("[%s] Artifact submission failed: %s", CHAR_ID, e)

    elif cat == "request_capability":
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "backend"))
        from npc_autonomy import file_npc_need
        need_type = decision.get("need_type", "information_access")
        priority = decision.get("priority", "medium")
        need_desc = decision.get("description", desc[:200] if desc else "Missing context limiting effectiveness.")
        why_needed = decision.get("why_needed", reasoning[:200] if reasoning else "Repeated low-value actions suggest context gap.")
        suggested = decision.get("suggested_capability", "general_context_enrichment")
        related_inst = r.get(f"councilor:{CHAR_ID}:institution") or ""
        try:
            need_result = file_npc_need(
                r, CHAR_ID, NPC_NAME, need_type, priority,
                need_desc, why_needed, suggested, related_inst,
            )
            if need_result.get("ok"):
                result["action_taken"] = "capability_need_filed"
                result["need_id"] = need_result["need_id"]
                result["need_type"] = need_type
                result["summary"] = f"Filed need: {need_type} — {need_desc[:80]}"
                logger.info("[%s] Filed capability need: %s (%s)", CHAR_ID, need_type, need_result["need_id"])
                _session_append(r, {
                    "kind": "capability_need_filed",
                    "actor": NPC_NAME,
                    "body": f"requested {need_type}: {need_desc[:120]}",
                })
            else:
                result["action_taken"] = f"capability_need_rejected:{need_result.get('error', 'unknown')}"
                result["summary"] = f"Need rejected: {need_result.get('error', 'unknown')}"
                logger.info("[%s] Need rejected: %s", CHAR_ID, need_result.get("error"))
        except Exception as e:
            result["action_taken"] = f"capability_need_error: {e}"
            logger.error("[%s] Capability need filing failed: %s", CHAR_ID, e)

    else:
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or f"unhandled category {cat}"
        result["action_taken"] = "unknown_category_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "workspace_sync",
            "actor": NPC_NAME,
            "body": f"unknown category {cat}: {note}",
        })

    ack_targets = []
    if partner_id and result.get("action_taken") != "no_target":
        ack_targets.append(partner_id)
    if result.get("action_taken") == "message_sent" and result.get("target") == OPERATOR_ID:
        ack_targets.append(OPERATOR_ID)
    acked_total = 0
    for ack_target in dict.fromkeys(ack_targets):
        acked_total += _acknowledge_inbox(r, ack_target)
    if acked_total:
        result["acked_messages"] = acked_total

    try:
        r.zadd(f"npc_decisions:{CHAR_ID}", {json.dumps(result): ts})
        r.zremrangebyrank(f"npc_decisions:{CHAR_ID}", 0, -21)
        r.set(f"npc_activity:{CHAR_ID}", str(ts))
        r.hset(f"npc_cognition:{CHAR_ID}", "last_category", cat)
        r.hset(f"npc_cognition:{CHAR_ID}", "last_ts", str(ts))
        r.hset(f"npc_cognition:{CHAR_ID}", "last_model", "npc-agent-direct")
    except Exception as e:
        logger.warning("Failed to record decision: %s", e)

    _session_append(r, {
        "kind": "decide",
        "actor": NPC_NAME,
        "category": cat,
        "body": desc or reasoning or "",
    })
    _sync_pair_workspace(r, decision, result)

    try:
        from npc_memory_bridge import record_councilor_memory
        record_councilor_memory(decision, r, ts)
    except Exception:
        pass

    return result


def update_mood(r, char_id=""):
    cid = char_id or CHAR_ID
    moods = ["curious", "analytical", "thoughtful", "focused", "serene", "determined"]
    mood = random.choice(moods)
    try:
        r.set(f"npc_mood:{cid}", mood)
    except Exception:
        pass

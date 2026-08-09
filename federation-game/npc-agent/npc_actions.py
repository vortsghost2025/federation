"""
NPC Actions — execute_decision() and all action handlers.

Extracted from npc_agent.py as part of Phase 1 monolith breakup.
Each function takes explicit parameters (char_id, contacts) instead of
relying on module-level globals, avoiding circular imports.
"""
import ast
import json
import logging
import os
import random
import re
import sys
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
    _acknowledge_operator_directive,
    _semantic_artifact_dedup_blocked,
    _record_outcome_feedback,
    _record_outcome_consequence,
)

# ── Sandboxed builder (write_code) ──
# The "builder" capability lets a councilor WRITE code that actually RUNS and
# produces a concrete, verifiable output (a computed model, a simulation, a
# metric) rather than another essay artifact. To make it a real builder we
# execute the generated Python in a heavily restricted subprocess: the code is
# checked against an AST allowlist (pure computation only) and the process is
# resource/time limited so it cannot hang or escape the container. The captured
# stdout is stored as the artifact's concrete outcome and recorded in the
# outcome-feedback ledger.
import subprocess

_SANDBOX_TIMEOUT = float(os.environ.get("SANDBOX_TIMEOUT", "6"))
_SANDBOX_MAX_MEM_MB = int(os.environ.get("SANDBOX_MAX_MEM_MB", "64"))
_SANDBOX_MAX_OUTPUT = int(os.environ.get("SANDBOX_MAX_OUTPUT", "2000"))
# The old static regex blacklist was bypassable: it never matched dunder
# introspection (''.__class__.__base__.__subclasses__()), bare-name aliasing of
# the wrapper's pre-imported modules (s = sys; s.modules['os']...), or
# __builtins__['__import__']('os'). The sandbox now validates the code with an
# AST allowlist instead: only pure-computation constructs are permitted, only
# whitelisted builtin names may be referenced, and attribute access is limited
# to non-dunder, non-frame names. Execution runs in a subprocess under
# RLIMIT_AS/RLIMIT_CPU/RLIMIT_NPROC, isolated mode (-I), a restricted builtins
# dict and a clean environment, plus a hard timeout — defense in depth.
_SANDBOX_ALLOWED_NAMES = frozenset({
    # safe builtins
    "print", "len", "range", "int", "float", "str", "bool", "bytes", "abs",
    "min", "max", "sum", "round", "sorted", "enumerate", "zip", "list", "dict",
    "set", "tuple", "chr", "ord", "pow", "divmod", "isinstance", "repr",
    "format", "reversed", "any", "all", "map", "filter", "hex", "oct", "bin",
    "hash", "id", "iter", "next", "slice", "complex", "frozenset",
    # exceptions, so `except ValueError:` works
    "Exception", "ArithmeticError", "ValueError", "TypeError", "KeyError",
    "IndexError", "ZeroDivisionError", "OverflowError", "RuntimeError",
    "StopIteration", "NameError",
})

# Non-dunder attributes that can still lead toward interpreter internals
# (generator frames, tracebacks). Dunders are denied by prefix anyway; this
# list is defense in depth for the non-dunder escape attrs.
_SANDBOX_BLOCKED_ATTRS = frozenset({
    "gi_frame", "ag_frame", "cr_frame", "f_back", "f_globals", "f_locals",
    "f_builtins", "f_code", "f_lasti", "tb_frame", "tb_next", "tb_lasti",
    "tb_lineno", "func_globals", "func_code", "im_func", "im_class",
})

# Node types with no place in a pure-computation sandbox.
_SANDBOX_DENIED_NODES = (
    ast.Import, ast.ImportFrom, ast.While, ast.With, ast.AsyncWith,
    ast.ClassDef, ast.Global, ast.Nonlocal, ast.AsyncFunctionDef,
    ast.AsyncFor, ast.Delete, ast.Yield, ast.YieldFrom, ast.Await,
    ast.Starred, ast.Match,
)

# str.format() runs its own mini-language that walks attributes by NAME
# ("{0.__class__}"), bypassing the AST attribute check. Reject format strings
# whose fields reference dunder names.
_SANDBOX_FORMAT_FIELD_DUNDER_RE = re.compile(r"\{[^{}]*__[^{}]*\}")


def _validate_sandbox_code(code: str):
    """Return an error string if `code` uses anything outside the sandbox
    subset, else None.

    The subset is pure computation: variables, arithmetic, strings, if/else,
    bounded for loops, containers, indexing/slicing, functions, f-strings, and
    non-dunder attribute access / method calls on values produced by safe
    builtins. Denied: imports, while, classes, with, async, dunder/frame
    attribute tricks, and any name that is not a whitelisted builtin or a
    locally bound variable.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return f"invalid syntax: {e.msg}"
    if not isinstance(tree, ast.Module):
        return "invalid module"

    # Pass 1: collect every name the code binds (assignment targets, loop
    # targets, function params/names, comprehension targets, walrus).
    bound: set[str] = set()

    def _collect_target(t) -> None:
        if isinstance(t, ast.Name):
            bound.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for elt in t.elts:
                _collect_target(elt)

    def _collect_args(args) -> None:
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            bound.add(a.arg)
        if args.vararg:
            bound.add(args.vararg.arg)
        if args.kwarg:
            bound.add(args.kwarg.arg)

    class _Collector(ast.NodeVisitor):
        def visit_Assign(self, n):
            for t in n.targets:
                _collect_target(t)
            self.generic_visit(n)

        def visit_AugAssign(self, n):
            _collect_target(n.target)
            self.generic_visit(n)

        def visit_AnnAssign(self, n):
            if n.target:
                _collect_target(n.target)
            self.generic_visit(n)

        def visit_For(self, n):
            _collect_target(n.target)
            self.generic_visit(n)

        def visit_NamedExpr(self, n):
            _collect_target(n.target)
            self.generic_visit(n)

        def visit_FunctionDef(self, n):
            bound.add(n.name)
            _collect_args(n.args)
            self.generic_visit(n)

        def visit_Lambda(self, n):
            _collect_args(n.args)
            self.generic_visit(n)

        def visit_comprehension(self, n):
            _collect_target(n.target)
            self.generic_visit(n)

    _Collector().visit(tree)

    # Pass 2: enforce the allowlist.
    error: list[str] = []

    class _Checker(ast.NodeVisitor):
        def visit_Name(self, n):
            if n.id not in _SANDBOX_ALLOWED_NAMES and n.id not in bound:
                error.append(f"name '{n.id}' is not allowed in the sandbox")
            self.generic_visit(n)

        def visit_Attribute(self, n):
            if n.attr.startswith("__") or n.attr in _SANDBOX_BLOCKED_ATTRS:
                error.append(f"attribute '{n.attr}' is not allowed in the sandbox")
            self.generic_visit(n)

        def visit_Call(self, n):
            func = n.func
            if isinstance(func, ast.Attribute):
                # Method call on a value produced by literals / safe builtins.
                # The attribute NAME is checked by visit_Attribute (dunder and
                # frame/traceback attrs are denied there); only the name gate
                # matters here.
                if func.attr.startswith("__") or func.attr in _SANDBOX_BLOCKED_ATTRS:
                    error.append(f"method '{func.attr}' is not allowed in the sandbox")
            elif not isinstance(func, ast.Name):
                error.append("only direct calls to allowed builtins, local functions, or safe methods are permitted")
            elif func.id not in _SANDBOX_ALLOWED_NAMES and func.id not in bound:
                error.append(f"call to '{func.id}' is not allowed in the sandbox")
            self.generic_visit(n)

        def visit_FunctionDef(self, n):
            if n.decorator_list:
                error.append("decorators are not allowed in the sandbox")
            self.generic_visit(n)

        def visit_Constant(self, n):
            if isinstance(n.value, str) and _SANDBOX_FORMAT_FIELD_DUNDER_RE.search(n.value):
                error.append("format strings may not reference dunder attributes")
            self.generic_visit(n)

        def generic_visit(self, n):
            if isinstance(n, _SANDBOX_DENIED_NODES):
                error.append(f"'{type(n).__name__}' is not allowed in the sandbox")
                return
            super().generic_visit(n)

    _Checker().visit(tree)
    return error[0] if error else None


# Fixed runner script (nothing user-controlled is interpolated into it): sets
# rlimits, then exec()s the user code with a restricted builtins dict and no
# other globals. Code, mem and cpu are passed via argv.
_SANDBOX_RUNNER = r"""
import resource, sys, time
mem = int(sys.argv[2])
cpu = int(sys.argv[3])
resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
resource.setrlimit(resource.RLIMIT_NPROC, (200, 200))
_safe = {"print": print, "len": len, "range": range, "int": int, "float": float,
         "str": str, "bool": bool, "bytes": bytes, "abs": abs, "min": min,
         "max": max, "sum": sum, "round": round, "sorted": sorted,
         "enumerate": enumerate, "zip": zip, "list": list, "dict": dict,
         "set": set, "tuple": tuple, "chr": chr, "ord": ord, "pow": pow,
         "divmod": divmod, "isinstance": isinstance, "repr": repr,
         "format": format, "reversed": reversed, "any": any, "all": all,
         "map": map, "filter": filter, "hex": hex, "oct": oct, "bin": bin,
         "hash": hash, "id": id, "iter": iter, "next": next, "slice": slice,
         "complex": complex, "frozenset": frozenset,
         "Exception": Exception, "ArithmeticError": ArithmeticError,
         "ValueError": ValueError, "TypeError": TypeError,
         "KeyError": KeyError, "IndexError": IndexError,
         "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
         "RuntimeError": RuntimeError, "StopIteration": StopIteration,
         "NameError": NameError}
_globals = {"__builtins__": dict(_safe)}
exec(compile(sys.argv[1], "<sandbox>", "exec"), _globals)
"""


def _clean_generated_code(raw: str) -> str:
    """Strip markdown fences, prose, and surrounding noise from an LLM code
    response so the remaining text is pure Python.

    Models frequently wrap generated code in ```python ... ``` fences or
    prepend/appended explanatory sentences, which makes ast.parse fail with
    'invalid syntax'. This extracts the code block (or the longest run of
    code-looking lines) and returns only that.
    """
    if not raw:
        return ""
    text = raw.strip()
    # 1) If there is a fenced code block, take its inner content.
    import re as _re
    fence = _re.search(r"```(?:python|py)?\s*\n(.*?)```", text, _re.DOTALL | _re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    # 2) Otherwise drop any leading prose up to the first line that looks like
    #    Python (starts with a keyword, a def, an identifier followed by =, etc.).
    code_lines = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if in_code:
                code_lines.append(line)
            continue
        if in_code:
            code_lines.append(line)
            continue
        # Start collecting when a line looks like Python.
        if (stripped.startswith(("def ", "import ", "from ", "print(", "for ", "if ", "while ",
                                  "return ", "class ")) or _re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", stripped)
                or _re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(", stripped)):
            in_code = True
            code_lines.append(line)
    return "\n".join(code_lines).strip()


def _execute_sandboxed_python(code: str, timeout: float = None, max_output: int = None):
    """Run generated Python in a restricted subprocess.

    Returns (ok: bool, output: str). The code is first validated with an AST
    allowlist (pure computation only — no imports, no while/classes/async, no
    dunder or frame attribute access, no unknown names). It then runs in a
    subprocess under RLIMIT_AS/RLIMIT_CPU/RLIMIT_NPROC, isolated mode (-I), a
    restricted builtins dict and a clean environment, with a hard timeout, so
    a runaway or hostile build cannot hang the agent or touch the system.
    """
    code = code or ""
    if not code.strip():
        return False, "code_denied: empty code"
    verdict = _validate_sandbox_code(code)
    if verdict:
        return False, f"code_denied: {verdict}"
    timeout = timeout or _SANDBOX_TIMEOUT
    max_output = max_output or _SANDBOX_MAX_OUTPUT
    mem_bytes = _SANDBOX_MAX_MEM_MB * 1024 * 1024
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _SANDBOX_RUNNER, code, str(mem_bytes), str(int(timeout))],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/tmp",
            env={"PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        return False, "code_timeout: execution exceeded the sandbox limit"
    except Exception as e:
        return False, f"code_exec_error: {e}"
    combined = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, f"code_error (exit {proc.returncode}): {combined.strip()[:max_output]}"
    return True, (combined.strip()[:max_output] or "ran successfully (no output)")

# ── Artifact title cleaning ──
# When a create_institution is rejected, the reroute injects system text into
# the description ("Institution 'X' could not be founded right now, so write a
# concise artifact..."). If the LLM's rerouted decision omits a clean title, the
# fallback captured that scaffolding as the artifact title ("Institution 'name'
# could not be founded right now, so write..."). These strip that scaffolding so
# artifact titles are clean, in-world labels.
_TITLE_REROUTE_RE = re.compile(
    r"Institution\s+['\"]?[^'\"]*['\"]?\s+could not be\s+(?:founded|found|created|established)"
    r"[^:]*?\s*:\s*",
    re.I,
)
_PLACEHOLDER_TITLES = {
    "artifact title",
    "untitled",
    "title",
    "new artifact",
    "artifact",
    "none",
    "n/a",
    "...",
}


def _is_reroute_scaffold(text: str) -> bool:
    """True when text is (or starts with) the institution-reroute scaffolding
    or a leftover fragment of it."""
    low = text.lower()
    if "institution" in low and "could not" in low:
        return True
    return any(frag in low for frag in (
        "so write a concise artifact",
        "so write ",
        "right now, so write",
        "right now, write",
        "advances the shared topic",
        "advances the shared work",
        "advancing the shared",
        "in the absence of the",
    ))


def _clean_artifact_title(raw_title: str, desc: str) -> str:
    """Return a clean artifact title, stripping system-reroute scaffolding and
    LLM placeholder titles. Falls back to a cleaned description prefix."""
    title = _enforce_fourth_wall(raw_title or "").strip()
    # Strip the reroute scaffolding wherever it appears.
    title = _TITLE_REROUTE_RE.sub("", title).strip()
    # A truncated reroute (e.g. "Institution 'X' could not be fou") may not
    # match the full regex but is still scaffolding — drop it entirely.
    if _is_reroute_scaffold(title):
        title = ""
    # If nothing usable survived, derive a title from the clean description.
    if not title or title.lower() in _PLACEHOLDER_TITLES or len(title) < 3:
        clean_desc = _enforce_fourth_wall(desc or "").strip()
        clean_desc = _TITLE_REROUTE_RE.sub("", clean_desc).strip()
        # If the description was itself scaffolding, keep only the topic after
        # the colon (e.g. "Institution ... couldn't be founded ... topic: <X>").
        if _is_reroute_scaffold(clean_desc):
            m = re.search(r":\s*(.+)$", clean_desc)
            clean_desc = (m.group(1).strip() if m else "")
        # Take the first sentence/phrase of the cleaned description.
        m = re.match(r"^([^.!?\n]+)", clean_desc)
        title = (m.group(1) if m else clean_desc)[:60].strip() if clean_desc else "Untitled"
    return _compact_text(title, 60) or "Untitled"


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


# ── Role anti-bloat guards ──
ROLE_CAP_PER_INSTITUTION = int(os.environ.get("ROLE_CAP_PER_INSTITUTION", "20"))
_ROLE_SUFFIXES = (
    "_analyst", "_coordinator", "_steward", "_officer", "_auditor",
    "_arbiter", "_envoy", "_liaison", "_enforcer", "_overseer", "_manager",
    "_advisor", "_administrator", "_director", "_curator", "_specialist",
    "_counselor", "_planner", "_spokesperson", "_representative",
)


def _normalize_role_name(title: str) -> str:
    """Slugify a role title and drop its standard suffix for similarity checks."""
    n = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    for sfx in _ROLE_SUFFIXES:
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip("_")
            break
    return n


def _institution_role_count(r, institution_id: str) -> int:
    """Return the number of roles currently assigned to an institution."""
    try:
        return len(r.smembers(f"{institution_id}:roles"))
    except Exception:
        return 0


def _find_near_duplicate_role(r, role_title: str, institution_id: str):
    """Return an existing role id that is a near-duplicate of role_title.

    Compares against roles already in the target institution (and index-wide as
    a fallback). Two roles are near-duplicates when their slugified base names
    (after dropping standard title suffixes) are identical.
    """
    base = _normalize_role_name(role_title)
    if not base:
        return None
    candidates = set(r.smembers(f"{institution_id}:roles")) if institution_id else set()
    if not candidates:
        candidates = set(r.smembers("role:index"))
    for rid in candidates:
        existing_title = r.hget(rid, "title")
        if not existing_title:
            continue
        if _normalize_role_name(existing_title) == base:
            return rid
    return None

logger = logging.getLogger("npc_agent")

CHAR_ID = os.environ.get("CHAR_ID", "")
NPC_NAME = os.environ.get("NPC_NAME", CHAR_ID)
OPERATOR_ID = "moderator"
SESSION_CAP = int(os.environ.get("SESSION_CAP", "24"))

PAIR_IDS = {"char_001", "char_306"}


_PLACEHOLDER_RE = re.compile(
    r"^[<\[\(]?\s*"
    r"(your full reply|full reply|full reply to the moderator|report content|insert response|placeholder|enter your reply|type your reply)"
    r"\b.*$",
    re.IGNORECASE | re.DOTALL,
)
_SHORT_GENERIC_RE = re.compile(
    r"^(ok|okay|noted|understood|understood\.|roger|copy that|will do|i'll|i will|proceeding|moving on|done|finished|completed)\.?\s*$",
    re.IGNORECASE,
)
_RECENT_REPLY_TTL = 300


def _is_placeholder_reply(body: str) -> bool:
    if not body:
        return True
    stripped = body.strip()
    if not stripped:
        return True
    if _PLACEHOLDER_RE.match(stripped):
        return True
    if _SHORT_GENERIC_RE.match(stripped) and len(stripped) < 60:
        return True
    return False


def _is_duplicate_reply(r, target: str, body: str) -> bool:
    """Detect whether an identical body was already sent to the same target
    within the recent-reply window. Namespaced by sender (CHAR_ID)."""
    if r is None or not body:
        return False
    cleaned = body.strip()
    if not cleaned:
        return False
    key = f"npc_messages:{CHAR_ID}:{target}:sent_recently"
    try:
        recent = r.lrange(key, 0, -1)
        if not recent:
            return False
        now = time.time()
        for entry_raw in reversed(recent):
            try:
                entry = json.loads(entry_raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if entry.get("body", "").strip() == cleaned:
                entry_ts = float(entry.get("ts", 0))
                if now - entry_ts < _RECENT_REPLY_TTL:
                    return True
                break
        return False
    except Exception:
        return False


def _record_sent_reply(r, target: str, body: str, ts: int) -> None:
    """Record a sent reply for duplicate detection (rolling window).
    Namespaced by sender (CHAR_ID)."""
    if r is None or not body:
        return
    key = f"npc_messages:{CHAR_ID}:{target}:sent_recently"
    try:
        r.rpush(key, json.dumps({"body": body.strip(), "ts": ts}))
        r.ltrim(key, -16, -1)
        r.expire(key, _RECENT_REPLY_TTL * 3)
    except Exception:
        pass


def _push_institution_cap_notification(r, founded):
    """Tell the agent the institution cap is reached so it stops attempting
    create_institution (mirrors the area_found idempotent loop-closure)."""
    if r is None:
        return
    try:
        note = {
            "type": "institution_cap_reached",
            "message": (
                f"You have founded {founded}/{_MAX_INSTITUTIONS_PER_NPC} institutions "
                f"(per-councilor cap). Do NOT attempt create_institution again — pursue "
                "other work instead: create_artifact, create_area for NEW sectors, "
                "propose_role, investigate, or continue the pair thread."
            ),
        }
        r.rpush(f"npc:system_notifications:{CHAR_ID}", json.dumps(note))
    except Exception:
        pass


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
        raw_body = decision.get("body") or desc or ""
        body = _enforce_fourth_wall(raw_body)
        result["message_body"] = body

        # Skip empty/whitespace-only messages — prevents "message text" stubs from
        # entering the thread when the LLM times out or returns a placeholder.
        # Also reject template/placeholder text and extremely short generic replies,
        # and prevent duplicate persistence of the same moderator reply.
        if _is_placeholder_reply(body):
            result["action_taken"] = "message_skipped_placeholder"
            result["detail"] = "rejected: body matches placeholder/template or is too short"
            logger.info("[%s] Skipped placeholder message to %s", CHAR_ID, target)
        elif target and target in contacts and target != CHAR_ID:
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
                if _is_duplicate_reply(r, target, body):
                    result["action_taken"] = "message_skipped_duplicate"
                    result["detail"] = "rejected: identical reply sent to same target within recent window"
                    logger.info("[%s] Skipped duplicate message to %s", CHAR_ID, target)
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
                    _record_sent_reply(r, target, body, ts)
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
        title = _clean_artifact_title(decision.get("title", ""), desc)
        # Two dedup gates: the existing title-based Jaccard gate, plus a new
        # content-level semantic gate that catches re-publishing the SAME body
        # under a slightly different title (the historical "Void Oracle
        # Anomalies" loop). We generate content first so the semantic gate can
        # compare it, but a title gate hit still short-circuits cheaply.
        title_blocked = r is not None and _is_repetitive_artifact(r, title)
        if title_blocked:
            logger.info("[%s] Dedup gate blocked artifact '%s' (title too similar to recent)", CHAR_ID, title)
            result["action_taken"] = "artifact_deferred_dedup"
            result["artifact_title"] = title
            _session_append(r, {
                "kind": "workspace_sync",
                "actor": NPC_NAME,
                "body": f"deferred artifact '{title[:60]}' — title too similar to recent work",
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
            # Semantic content gate: catch near-identical bodies under new titles.
            if r is not None and _semantic_artifact_dedup_blocked(r, title, artifact_content, CHAR_ID):
                logger.info("[%s] Semantic dedup gate blocked artifact '%s' (content too similar to recent)", CHAR_ID, title)
                result["action_taken"] = "artifact_deferred_semantic_dedup"
                result["artifact_title"] = title
                _session_append(r, {
                    "kind": "workspace_sync",
                    "actor": NPC_NAME,
                    "body": f"deferred artifact '{title[:60]}' — content is a near-duplicate of recent work",
                })
                streak_key = f"npc_dedup_streak:{CHAR_ID}"
                r.incr(streak_key)
                r.expire(streak_key, 600)
                dedup_topic = most_common_topic_word([title])
                if dedup_topic:
                    r.set(f"npc_dedup_topic:{CHAR_ID}", dedup_topic, ex=600)
            else:
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
                # Outcome feedback baseline: record that this artifact was
                # produced so later outcomes can be attributed to it.
                _record_outcome_feedback(
                    r, title,
                    "artifact published; awaiting downstream consequence",
                    consequence={"chars": len(artifact_content)},
                    char_id=CHAR_ID,
                )

    elif cat == "write_code":
        code_prompt = f"Generate Python code for: {desc}\n\nOutput ONLY valid Python code inside a single ```python code block. Print your computed result to stdout. Use only variables, arithmetic, strings, f-strings, if/else, for loops over range(), lists/dicts/sets, indexing/slicing, functions, and print(). Do NOT import anything, do not use while loops or classes, do not touch files, os, sys, or dunder attributes."
        llm_result = call_llm("You are a Python developer. Output only code, wrapped in a ```python code block.", code_prompt, r=r, call_label="code")
        gen_code = _clean_generated_code(llm_result.get("content", ""))
        # Self-verify the code parses; if not, give the model one retry with the
        # syntax error fed back so the builder can recover from fence/prose noise.
        if gen_code:
            try:
                ast.parse(gen_code, mode="exec")
            except SyntaxError as _se:
                retry_prompt = (
                    f"The previous code failed to parse:\n{gen_code}\n\n"
                    f"SyntaxError: {_se.msg}\n\n"
                    f"Rewrite it as clean, runnable Python inside a single ```python code block. "
                    f"No prose, no explanation, no markdown outside the block."
                )
                retry_result = call_llm("You are a Python developer. Output only a ```python code block.", retry_prompt, r=r, call_label="code_retry")
                retry_code = _clean_generated_code(retry_result.get("content", ""))
                if retry_code:
                    gen_code = retry_code
        if not gen_code:
            result["action_taken"] = "code_failed"
        else:
            # Run the code in the sandbox and capture a concrete, verifiable
            # output — this is what makes the builder "real" (a computed model,
            # a metric, a simulation result) instead of an unexecuted script.
            ok, output = _execute_sandboxed_python(gen_code)
            artifact = {
                "artifact_id": str(uuid.uuid4()),
                "char_id": CHAR_ID,
                "char_name": NPC_NAME,
                "title": f"Code: {desc[:60]}",
                "artifact_type": "code",
                "content": gen_code,
                "output": output,
                "created_at": ts,
            }
            r.rpush(f"npc_artifacts:{CHAR_ID}", json.dumps(artifact))
            r.rpush("npc_artifacts:global", json.dumps(artifact))
            r.hincrby(f"npc_stats:{CHAR_ID}", "code_written", 1)
            if ok:
                result["action_taken"] = "code_executed"
                result["artifact_title"] = artifact["title"]
                result["output"] = output
                logger.info("[%s] Wrote + executed code for: %s", CHAR_ID, desc[:60])
                _session_append(r, {
                    "kind": "code_written",
                    "actor": NPC_NAME,
                    "title": f"Code: {desc[:60]}",
                    "body": f"executed OK; output: {output[:80]}",
                })
                # Concrete outcome: the code produced a verifiable result.
                _record_outcome_consequence(
                    r, result["artifact_title"], "code executed; produced: " + _compact_text(output, 200),
                    consequence={"kind": "code", "ok": True},
                    char_id=CHAR_ID,
                )
            else:
                result["action_taken"] = "code_failed"
                result["artifact_title"] = artifact["title"]
                result["code_error"] = output
                logger.info("[%s] Code attempted for: %s (failed: %.60s)", CHAR_ID, desc[:60], output)
                _session_append(r, {
                    "kind": "code_written",
                    "actor": NPC_NAME,
                    "title": f"Code: {desc[:60]}",
                    "body": f"sandbox rejected/failed: {output[:80]}",
                })
                # Record the failure as a concrete (negative) outcome.
                _record_outcome_consequence(
                    r, result["artifact_title"], "code failed: " + _compact_text(output, 200),
                    consequence={"kind": "code", "ok": False},
                    char_id=CHAR_ID,
                )

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
                    _push_institution_cap_notification(r, founded)

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
                        _push_institution_cap_notification(r, founded)

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

                # 4. Reroute to productive work when a guard rejects, so the
                #    councilor never stays locked on an impossible creation.
                #    Cap-reached (world oversaturated with institutions) is a
                #    good moment to BUILD something quantitative instead of yet
                #    another prose artifact, so route it to the sandboxed
                #    write_code builder. Similar-exists keeps the artifact path
                #    because there is a concrete institution to analyze.
                if _rejected:
                    if result.get("action_taken") in {
                        "institution_cap_reached",
                        "institution_total_cap_reached",
                    }:
                        rerouted = {
                            "category": "write_code",
                            "reasoning": (
                                f"create_institution rerouted: '{inst_name}' rejected "
                                "(institution cap reached); the world already has enough "
                                "institutions, so build a quantitative model/metric that "
                                "advances the shared work instead"
                            ),
                            "description": (
                                f"A quantitative model, metric, or projection that advances "
                                f"the shared topic: {_compact_text(desc, 120) or 'the current shared goal'}."
                                f" Compute a concrete number and print it."
                            ),
                            "title": f"Model: {_compact_text(desc, 48)}",
                        }
                        logger.info("[%s] create_institution rerouted to write_code (cap)", CHAR_ID)
                    else:
                        rerouted = {
                            "category": "create_artifact",
                            "reasoning": (
                                f"create_institution rerouted: '{inst_name}' rejected "
                                "(cap reached or similar exists); producing an artifact "
                                "advancing the shared work instead"
                            ),
                            "description": (
                                f"Institution '{inst_name}' could not be founded right now, "
                                f"so write a concise artifact that advances the shared topic: "
                                f"{_compact_text(desc, 120) or 'the current shared goal'}"
                            ),
                        }
                        logger.info("[%s] create_institution rerouted to create_artifact", CHAR_ID)
                    return execute_decision(rerouted, r, contacts)

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
                    # ── Anti-bloat guards: near-duplicate + per-institution cap ──
                    dup = _find_near_duplicate_role(r, role_title, target_inst_id)
                    if dup:
                        result["action_taken"] = "role_rejected_near_duplicate"
                        result["summary"] = (
                            f"Role '{role_title}' rejected: too similar to existing "
                            f"role '{dup}'"
                        )
                        _session_append(r, {
                            "kind": "role_proposal_failed",
                            "actor": NPC_NAME,
                            "body": (
                                f"proposed role '{role_title}' but it is a near-duplicate "
                                f"of existing role '{dup}'"
                            ),
                        })
                    elif _institution_role_count(r, target_inst_id) >= ROLE_CAP_PER_INSTITUTION:
                        result["action_taken"] = "role_rejected_institution_cap"
                        result["summary"] = (
                            f"Role '{role_title}' rejected: institution "
                            f"'{target_inst_id}' at role cap "
                            f"({ROLE_CAP_PER_INSTITUTION})"
                        )
                        _session_append(r, {
                            "kind": "role_proposal_failed",
                            "actor": NPC_NAME,
                            "body": (
                                f"proposed role '{role_title}' but institution "
                                f"'{target_inst_id}' is at its role cap"
                            ),
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
                # ── Anti-loop: repeated role rejections should pivot to building
                #    something quantitative instead of hammering governance again.
                #    The streak is a best-effort guard; a minimal Redis client
                #    (e.g. some test fakes) may lack setex/delete, so tolerate that.
                try:
                    _streak_key = f"npc_role_reject_streak:{CHAR_ID}"
                    if result.get("action_taken", "").startswith("role_rejected"):
                        streak = int(r.get(_streak_key) or 0) + 1
                        if hasattr(r, "setex"):
                            r.setex(_streak_key, 3600, streak)
                        if streak >= 2:
                            if hasattr(r, "delete"):
                                r.delete(_streak_key)
                            rerouted = {
                                "category": "write_code",
                                "reasoning": (
                                    f"propose_role rejected {streak} consecutive times "
                                    f"('{role_title}'); the governance space is saturated, so "
                                    "build a quantitative model/metric that advances the shared "
                                    "work instead of proposing more roles"
                                ),
                                "description": (
                                    f"A quantitative model, metric, or projection that advances "
                                    f"the shared topic: {_compact_text(desc, 120) or 'the current shared goal'}."
                                    f" Compute a concrete number and print it."
                                ),
                                "title": f"Model: {_compact_text(desc, 48)}",
                            }
                            logger.info("[%s] propose_role rejection loop -> write_code", CHAR_ID)
                            return execute_decision(rerouted, r, contacts)
                    else:
                        if hasattr(r, "delete"):
                            r.delete(_streak_key)
                except Exception as _streak_exc:
                    logger.info("[%s] role streak guard skipped: %s", CHAR_ID, _streak_exc)
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
        # Production bridge: attempt work-loop publication first,
        # fall back to legacy file_npc_need exactly once when needed.
        try:
            from npc_work_loop_adapter import handle_request_capability
            bridge_ok = handle_request_capability(
                decision=decision,
                actor_id=CHAR_ID,
                r=r,
                result=result,
                desc=desc,
                reasoning=reasoning,
            )
            # When bridge returns True, the new path completed fully.
            # When False, the adapter preserved partial state or signaled
            # legacy fallback exactly once.
            if bridge_ok:
                pass  # result already populated by adapter
            else:
                # Check whether partial failure preserved a retryable draft
                if result.get("action_taken") == "capability_request_partial_failure":
                    # Do NOT call legacy path on partial failure; the draft
                    # is preserved for retry.
                    pass
                else:
                    # Legacy fallback exactly once for any non-retryable case.
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
                            logger.info("[%s] Filed capability need (legacy): %s (%s)", CHAR_ID, need_type, need_result["need_id"])
                            _session_append(r, {
                                "kind": "capability_need_filed",
                                "actor": NPC_NAME,
                                "body": f"requested {need_type}: {need_desc[:120]}",
                            })
                        else:
                            result["action_taken"] = f"capability_need_rejected:{need_result.get('error', 'unknown')}"
                            result["summary"] = f"Need rejected: {need_result.get('error', 'unknown')}"
                            logger.info("[%s] Need rejected (legacy): %s", CHAR_ID, need_result.get('error'))
                    except Exception as legacy_e:
                        result["action_taken"] = f"capability_need_error: {legacy_e}"
                        logger.error("[%s] Legacy capability need filing failed: %s", CHAR_ID, legacy_e)
        except Exception as e:
            result["action_taken"] = f"capability_request_bridge_exception: {e}"
            logger.error("[%s] Bridge exception: %s", CHAR_ID, e)

    elif cat == "create_area":
        # Persistent world-expansion: found a new area/sector via the shared
        # work-loop `area_found` action. No legacy fallback needed.
        try:
            from npc_work_loop_adapter import area_exists_on_map, handle_found_area
            if area_exists_on_map(decision.get("area_id", "")):
                logger.warning(
                    "[%s] create_area blocked: '%s' already on shared map; rerouting to read_artifacts",
                    CHAR_ID, decision.get("area_id", ""),
                )
                rerouted = {
                    "category": "read_artifacts",
                    "reasoning": "create_area rerouted: area already on shared map",
                    "description": f"area '{decision.get('area_id', '')}' already on the map; reading partner work instead of re-founding it",
                }
                return execute_decision(rerouted, r, contacts)
            ok = handle_found_area(
                decision=decision,
                actor_id=CHAR_ID,
                r=r,
                result=result,
            )
            if not ok and not result.get("action_taken"):
                result["action_taken"] = "area_found_unavailable"
                result["summary"] = "Work-loop area foundation unavailable."
        except Exception as e:
            result["action_taken"] = f"area_found_exception: {e}"
            logger.error("[%s] create_area bridge exception: %s", CHAR_ID, e)

    else:
        note = _compact_text(desc, 180) or _compact_text(reasoning, 180) or f"unhandled category {cat}"
        result["action_taken"] = "unknown_category_logged"
        result["summary"] = note
        _session_append(r, {
            "kind": "workspace_sync",
            "actor": NPC_NAME,
            "body": f"unknown category {cat}: {note}",
        })

    # Operator (moderator) acknowledgement must be message-specific, not
    # sender-wide. A terminal enforced operator response bypasses the generic
    # `_acknowledge_inbox(r, "moderator")` entirely so it never deletes every
    # queued moderator message before the exact-id helper runs.
    is_terminal_operator_response = (
        isinstance(decision, dict)
        and result.get("action_taken") == "message_sent"
        and result.get("target") == OPERATOR_ID
        and decision.get("operator_directive_id")
        and decision.get("operator_response_status") in {"complete", "failed"}
    )

    ack_targets = []
    is_operator_response = bool(decision.get("operator_directive_id"))
    if not is_operator_response:
        # Ordinary acknowledgement path. Enforced operator responses bypass ALL
        # generic acknowledgement (the exact-id ack handles them by directive id).
        if partner_id and result.get("action_taken") != "no_target":
            ack_targets.append(partner_id)
        if (result.get("action_taken") == "message_sent"
                and result.get("target") == OPERATOR_ID):
            ack_targets.append(OPERATOR_ID)
    acked_total = 0
    for ack_target in dict.fromkeys(ack_targets):
        acked_total += _acknowledge_inbox(r, ack_target)

    if is_terminal_operator_response:
        # Patch B: archive ONLY the one directive by its exact id. Pass the
        # attribution object explicitly — no shared/global state.
        operator_acked = _acknowledge_operator_directive(
            r,
            decision["operator_directive_id"],
            char_id=CHAR_ID,
            status=decision["operator_response_status"],
            attribution=decision.get("operator_attribution") or {},
        )
        if operator_acked:
            result["operator_directive_acked"] = decision["operator_directive_id"]
            acked_total += 1
    elif decision.get("operator_directive_id") and decision.get("operator_response_status") not in {"complete", "failed"}:
        # non-terminal operator response (e.g. failed to send) acknowledges nothing
        pass

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

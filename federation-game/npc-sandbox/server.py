"""
NPC SANDBOX EXECUTOR — Run NPC-generated code in isolation

Receives code from the backend, runs it in a subprocess with strict
timeouts and restricted builtins. Output is captured and returned.

Security model:
  - subprocess with 30s timeout (configurable)
  - restricted Python builtins (no open, exec, eval, import beyond safe list)
  - no network access (container has no network except internal API)
  - only writes to /artifacts/{char_id}/ directory
  - max 10MB output
"""

import json
import logging
import os
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("npc-sandbox")

app = FastAPI(title="NPC Sandbox Executor")

ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR", "/artifacts")
MAX_EXECUTION_SECONDS = int(os.environ.get("MAX_EXECUTION_SECONDS", "30"))
MAX_OUTPUT_BYTES = int(os.environ.get("MAX_OUTPUT_BYTES", str(10 * 1024 * 1024)))  # 10MB
MAX_MEMORY_MB = int(os.environ.get("MAX_MEMORY_MB", "256"))

# Trusted runner: runs with FULL builtins itself, then exec()s the NPC code
# with a restricted builtins dict. 2026-11-14 hardening: the old preamble did
# `import json, os, sys` at module level, which left `os` in the user code's
# namespace (os.system/os.popen escape), and _make_safe_environment was never
# actually wired in. Now os/sys/open/exec/eval/compile are NOT in the user
# namespace at all; save_result is injected by the trusted runner; rlimits
# are set inside the runner; env is minimal; -I isolated mode; hard timeout.
_RUNNER = r"""
import json, os, resource
mem = int(os.environ.get("SB_MEM_MB", "256")) * 1024 * 1024
cpu = int(os.environ.get("SB_CPU_S", "10"))
try:
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_NPROC, (200, 200))
except Exception:
    pass
ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR", "/artifacts")
CHAR_ID = os.environ.get("CHAR_ID", "unknown")

def save_result(data, filename="result.json"):
    path = os.path.join(ARTIFACTS_DIR, CHAR_ID, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        with open(path, "w") as f:
            f.write(data)
    else:
        with open(path, "w") as f:
            json.dump(data, f, default=str)
    return path

_ALLOWED_IMPORTS = {"math", "random", "statistics", "datetime", "time",
                    "collections", "itertools", "functools", "json", "re",
                    "string", "textwrap", "typing"}
_real_import = __import__
def _safe_import(name, *a, **k):
    if name.split(".")[0] in _ALLOWED_IMPORTS:
        return _real_import(name, *a, **k)
    raise ImportError("Import '%s' is not allowed in NPC sandbox" % name)

_SAFE = {
    "abs": abs, "all": all, "any": any, "ascii": ascii, "bin": bin, "bool": bool,
    "bytearray": bytearray, "bytes": bytes, "chr": chr, "complex": complex,
    "dict": dict, "divmod": divmod, "enumerate": enumerate, "filter": filter,
    "float": float, "format": format, "frozenset": frozenset, "hash": hash,
    "hex": hex, "id": id, "int": int, "isinstance": isinstance, "iter": iter,
    "len": len, "list": list, "map": map, "max": max, "min": min, "next": next,
    "object": object, "oct": oct, "ord": ord, "pow": pow, "print": print,
    "range": range, "repr": repr, "reversed": reversed, "round": round,
    "set": set, "slice": slice, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "type": type, "zip": zip,
    "Exception": Exception, "ArithmeticError": ArithmeticError, "ValueError": ValueError,
    "TypeError": TypeError, "KeyError": KeyError, "IndexError": IndexError,
    "ZeroDivisionError": ZeroDivisionError, "OverflowError": OverflowError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration, "NameError": NameError,
    "__import__": _safe_import,
    "__name__": "__main__",
}
g = {"__builtins__": _SAFE, "save_result": save_result,
     "char_id": CHAR_ID, "artifacts_dir": ARTIFACTS_DIR}
with open(os.environ["SB_CODE_FILE"], encoding="utf-8") as f:
    src = f.read()
# AST gate: reject dunder attribute/name access (closes the
# __class__.__base__.__subclasses__() escape) and non-allowlisted imports
# before exec, so the restricted builtins are not the only line of defense.
import ast as _ast
_tree = _ast.parse(src)
for _node in _ast.walk(_tree):
    if isinstance(_node, _ast.Attribute) and _node.attr.startswith("__"):
        raise PermissionError("dunder attribute access is not allowed in NPC sandbox")
    if isinstance(_node, _ast.Name) and _node.id.startswith("__"):
        raise PermissionError("dunder name access is not allowed in NPC sandbox")
    if isinstance(_node, _ast.Import):
        for _a in _node.names:
            if _a.name.split(".")[0] not in _ALLOWED_IMPORTS:
                raise ImportError("Import '%s' is not allowed in NPC sandbox" % _a.name)
    if isinstance(_node, _ast.ImportFrom):
        _m = (_node.module or "").split(".")[0]
        if _m not in _ALLOWED_IMPORTS:
            raise ImportError("Import '%s' is not allowed in NPC sandbox" % _m)
exec(compile(src, "<npc>", "exec"), g)
"""


class ExecuteRequest(BaseModel):
    char_id: str
    code: str
    timeout_seconds: Optional[int] = None
    artifact_title: Optional[str] = None
    artifact_type: Optional[str] = "code"


class ExecuteResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    execution_time_ms: float
    lines_of_code: int
    artifact_path: Optional[str] = None


def _execute_code(char_id: str, code: str, timeout: int) -> Dict[str, Any]:
    """Execute NPC code in a sandboxed subprocess.

    Writes code to a temp file, runs it via the trusted _RUNNER under -I with
    rlimits, a restricted builtins dict, a minimal env and a hard timeout,
    then captures stdout/stderr and returns the result.
    """
    start = time.time()

    # Write code to temp file
    tmp_dir = tempfile.mkdtemp(prefix=f"npc_{char_id}_")
    code_path = os.path.join(tmp_dir, "script.py")

    try:
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)

        result = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmp_dir,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONIOENCODING": "utf-8",
                "ARTIFACTS_DIR": ARTIFACTS_DIR,
                "CHAR_ID": char_id,
                "SB_CODE_FILE": code_path,
                "SB_MEM_MB": str(MAX_MEMORY_MB),
                "SB_CPU_S": str(timeout),
            },
        )

        elapsed = (time.time() - start) * 1000

        # Check for saved artifact files
        artifact_paths = []
        char_art_dir = os.path.join(ARTIFACTS_DIR, char_id)
        if os.path.isdir(char_art_dir):
            for fname in os.listdir(char_art_dir):
                fpath = os.path.join(char_art_dir, fname)
                if os.path.isfile(fpath) and fname != "sandbox_output.json":
                    artifact_paths.append(fpath)

        return {
            "success": result.returncode == 0,
            "output": result.stdout[:MAX_OUTPUT_BYTES] if result.stdout else "",
            "error": result.stderr[:MAX_OUTPUT_BYTES] if result.stderr else None,
            "execution_time_ms": round(elapsed, 2),
            "lines_of_code": len(code.split("\n")),
            "artifact_paths": artifact_paths,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": f"Execution timed out after {timeout}s",
            "execution_time_ms": timeout * 1000,
            "lines_of_code": len(code.split("\n")),
            "artifact_paths": [],
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "execution_time_ms": (time.time() - start) * 1000,
            "lines_of_code": len(code.split("\n")),
            "artifact_paths": [],
        }
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@app.post("/execute", response_model=ExecuteResponse)
def execute_code(req: ExecuteRequest):
    """Execute NPC code in a sandboxed environment."""
    timeout = req.timeout_seconds or MAX_EXECUTION_SECONDS
    timeout = min(timeout, 60)  # hard cap at 60s

    # char_id is used in filesystem paths under ARTIFACTS_DIR — strict format only.
    if not req.char_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", req.char_id):
        raise HTTPException(status_code=400, detail="invalid char_id")

    if not req.code or len(req.code.strip()) < 5:
        raise HTTPException(status_code=400, detail="Code is too short")

    if len(req.code) > 20000:
        raise HTTPException(status_code=400, detail="Code exceeds 20KB limit")

    logger.info(
        "Executing code for %s (%d lines, %ds timeout)",
        req.char_id, len(req.code.split("\n")), timeout,
    )

    result = _execute_code(req.char_id, req.code, timeout)
    return ExecuteResponse(**result)


@app.post("/generate-and-execute")
def generate_and_execute(req: ExecuteRequest):
    """Future: LLM generates code from a prompt, then executes it.

    For now, this just executes the code directly. In a future iteration,
    an LLM call here would convert 'write a poem about stars' into Python.
    """
    return execute_code(req)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9002"))
    uvicorn.run(app, host="0.0.0.0", port=port)

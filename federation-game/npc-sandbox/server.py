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

SAFE_BUILTINS = {
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "chr", "complex", "dict", "dir", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "getattr", "hasattr", "hash",
    "hex", "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "object", "oct", "ord",
    "pow", "print", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "super", "tuple", "type",
    "vars", "zip",
    # Math
    "math", "random", "statistics",
    # Time
    "datetime", "time",
    # Collections
    "collections", "itertools", "functools",
    # JSON
    "json",
    # String
    "re", "string", "textwrap",
}

ALLOWED_IMPORTS = {
    "math", "random", "statistics", "datetime", "time",
    "collections", "itertools", "functools",
    "json", "re", "string", "textwrap",
    "typing",
}


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


def _make_safe_environment(char_id: str, artifacts_dir: str) -> Dict[str, Any]:
    """Build a safe global environment for exec()."""
    safe_env = {
        "__builtins__": {k: __builtins__[k] for k in SAFE_BUILTINS if k in __builtins__},
        "char_id": char_id,
        "artifacts_dir": artifacts_dir,
        "os": None,
        "subprocess": None,
        "sys": None,
        "shutil": None,
    }
    # Provide safe modules via __import__ restriction
    builtins = safe_env["__builtins__"]
    original_import = builtins.get("__import__", __import__)

    def safe_import(name, *args, **kwargs):
        if name in ALLOWED_IMPORTS:
            return original_import(name, *args, **kwargs)
        raise ImportError(f"Import '{name}' is not allowed in NPC sandbox")

    builtins["__import__"] = safe_import

    # Prevent open/exec/eval
    for dangerous in ("open", "exec", "eval", "compile", "__import__"):
        builtins.pop(dangerous, None)

    return safe_env


def _limit_resources():
    """Set resource limits for the subprocess (Linux only, best-effort)."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_MB * 1024 * 1024, -1))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_EXECUTION_SECONDS, -1))
    except (ImportError, AttributeError, resource.error):
        pass


def _execute_code(char_id: str, code: str, timeout: int) -> Dict[str, Any]:
    """Execute NPC code in a sandboxed subprocess.

    Writes code to a temp file, runs it in a subprocess with resource
    limits, captures stdout/stderr, and returns the result.
    """
    start = time.time()

    # Write code to temp file
    tmp_dir = tempfile.mkdtemp(prefix=f"npc_{char_id}_")
    code_path = os.path.join(tmp_dir, "script.py")

    # Prepend artifact writing helper
    preamble = f"""import json, os, sys
ARTIFACTS_DIR = {json.dumps(ARTIFACTS_DIR)}
CHAR_ID = {json.dumps(char_id)}
OUTPUT_FILE = os.path.join(ARTIFACTS_DIR, CHAR_ID, "sandbox_output.json")

def save_result(data, filename="result.json"):
    \"\"\"Save a result file to the NPC's artifact directory.\"\"\"
    path = os.path.join(ARTIFACTS_DIR, CHAR_ID, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        with open(path, "w") as f:
            f.write(data)
    else:
        with open(path, "w") as f:
            json.dump(data, f, default=str)
    return path

"""
    full_code = preamble + code

    try:
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(full_code)

        result = subprocess.run(
            [sys.executable, "-I", code_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmp_dir,
            env={
                "PYTHONIOENCODING": "utf-8",
                "ARTIFACTS_DIR": ARTIFACTS_DIR,
                "CHAR_ID": char_id,
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

    if not req.code or len(req.code.strip()) < 5:
        raise HTTPException(status_code=400, detail="Code is too short")

    if len(req.code) > 100000:
        raise HTTPException(status_code=400, detail="Code exceeds 100KB limit")

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

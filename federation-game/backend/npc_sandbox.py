"""
NPC SANDBOX CLIENT — Backend interface to the sandbox executor

Handles communication between the main backend and the npc-sandbox container.
Also provides the LLM-prompt-to-code bridge: takes an NPC's stated desire
("I want to write a poem about the stars") and asks the LLM to generate
Python that fulfills it.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from npc_artifacts import create_artifact

logger = logging.getLogger(__name__)

SANDBOX_URL = os.environ.get(
    "SANDBOX_URL", "http://npc-sandbox:9002"
)
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "45"))


def _sandbox_request(endpoint: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Make a request to the sandbox executor. Returns response or None."""
    url = f"{SANDBOX_URL}{endpoint}"
    data = json.dumps(payload).encode("utf-8")

    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urlopen(req, timeout=SANDBOX_TIMEOUT)
        return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        logger.warning("Sandbox request failed: %s", e)
        return None
    except Exception as e:
        logger.warning("Sandbox request error: %s", e)
        return None


def execute_code(
    char_id: str,
    code: str,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Send code to the sandbox for execution.

    Returns:
        Dict with keys: success, output, error, execution_time_ms, lines_of_code
    """
    payload = {
        "char_id": char_id,
        "code": code,
    }
    if timeout_seconds:
        payload["timeout_seconds"] = timeout_seconds

    result = _sandbox_request("/execute", payload)
    if result is None:
        return {
            "success": False,
            "output": "",
            "error": "Sandbox unreachable",
            "execution_time_ms": 0,
            "lines_of_code": len(code.split("\n")),
        }
    return result


def execute_and_register_artifact(
    char_id: str,
    char_name: str,
    code: str,
    title: str,
    artifact_type: str = "code",
    discoverable: bool = True,
) -> Dict[str, Any]:
    """Execute code in the sandbox, then register the output as an artifact.

    If the sandbox generates files (via save_result), those become artifacts.
    Otherwise, the stdout output is saved as the artifact content.
    """
    result = execute_code(char_id, code)

    # Determine the content to save as artifact
    content = ""
    if result.get("success"):
        content = result.get("output", "")
        if not content:
            content = f"Code executed successfully ({result.get('execution_time_ms', 0)}ms)"
    else:
        content = f"Execution failed: {result.get('error', 'unknown error')}"

    # Create the artifact in the registry
    artifact = create_artifact(
        char_id=char_id,
        char_name=char_name,
        title=title,
        artifact_type=artifact_type,
        content=content,
        discoverable=discoverable,
        metadata={
            "execution_time_ms": result.get("execution_time_ms", 0),
            "lines_of_code": result.get("lines_of_code", 0),
            "execution_success": result.get("success", False),
        },
    )

    return {
        "artifact": artifact,
        "execution": result,
    }


def sandbox_health() -> bool:
    """Check if the sandbox is reachable."""
    try:
        req = Request(f"{SANDBOX_URL}/health", method="GET")
        resp = urlopen(req, timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("status") == "ok"
    except Exception:
        return False

"""S3C Dagu shadow draft (S3C-012).

ILLUSTRATIVE ONLY — NOT SCHEMA-VALIDATED, NOT INSTALLED.

This module renders a Dagu YAML draft that would orchestrate the S3C shadow
pipeline as a scheduled, fail-closed workflow. It is produced as documentation
and a starting point. It is NOT written to any Dagu instance, NOT installed,
and NOT validated against a live Dagu schema. The string is returned to the
caller; nothing is deployed.

Dagu workflow count is UNKNOWN FROM THIS WORK BLOCK. The local Steward
workflow draft was not installed.

Forbidden in this file: redis, requests, urllib, socket, subprocess, docker,
paramiko, psycopg, mysql, sqlalchemy, ssh, fabric, dagu, http.client,
telnetlib, sqlite3.
"""

from __future__ import annotations

from typing import Any, Dict

DAGU_DRAFT_YAML = """# ILLUSTRATIVE — NOT SCHEMA-VALIDATED, NOT INSTALLED
# S3C shadow pipeline draft for Dagu. Fail-closed by design.
name: steward-s3c-shadow
description: >-
  Illustrative Dagu draft for the S3C shadow-mode pipeline. Must never perform
  a live apply. Every step is shadow-only and gated by the S3C safety interlock.
schedule: "0 3 * * *"
steps:
  - name: verify-interlock
    command: python -m steward.s3ccli verify-bundle --mode fixture_shadow_apply
    continueOn:
      skipped: false
      failure: false
  - name: run-fixture-shadow
    command: python -m steward.s3ccli run-fixture --namespace steward:shadow:gastown
    depends: [verify-interlock]
  - name: readiness-check
    command: python -m steward.s3ccli readiness
    depends: [run-fixture-shadow]
  # NO live-apply step exists. The pipeline stops at shadow-only.
"""


def render_draft() -> Dict[str, Any]:
    """Return the illustrative draft. Nothing is written or installed."""

    return {
        "status": "ILLUSTRATIVE — NOT SCHEMA-VALIDATED",
        "installed": False,
        "dagu_workflow_count": "UNKNOWN FROM THIS WORK BLOCK",
        "yaml": DAGU_DRAFT_YAML,
    }

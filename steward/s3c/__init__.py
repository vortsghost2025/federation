"""S3C — Steward shadow-mode pipeline.

Local-only, fail-closed shadow rehearsal for the Federation-world writer.
No live apply, no production path, no push. Reuses S3B qualification backends.
"""

from __future__ import annotations

__version__ = "steward-s3c@0.1.0"

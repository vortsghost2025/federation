# Steward Dagu Python Runtime — local qualification image (DR-002)
#
# PURPOSE:
#   A safe, pinned replacement Dagu runtime capable of running the fixture-only
#   S3C shadow workflow. Built and validated LOCALLY ONLY. Never pushed, never
#   installed on the VPS, never deployed.
#
# BASE:
#   Pinned to the immutable digest of the currently deployed Dagu image.
#   Deployed image: ghcr.io/dagucloud/dagu:latest
#   Resolved digest (2026-07-19, Dagu 2.10.7, amd64/linux):
ARG DAGU_DIGEST=sha256:5e715705e0c96e462417303f3e2fbbadc7f9cd15d153764c89fd1442e80a1d66
FROM ghcr.io/dagucloud/dagu@${DAGU_DIGEST}

# No 'latest'. No registry login. No push.
LABEL steward.runtime=qualification \
      steward.mode=shadow-only \
      steward.dagu-version=2.10.7

# Add ONLY the minimum runtime required by Steward fixture execution.
# The pinned Dagu base already ships python3 (Debian externally-managed per
# PEP 668). We install Steward into an isolated venv so we never touch the
# system Python and never need --break-system-packages.
# - no docker CLI, no git, no ssh, no compilers, no redis/db clients, no creds
USER 0
RUN set -eu; \
    apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install the Steward package (committed S1-S3C files only) into the image.
# The package is run as `python -m steward.s3ccli` (no setup.py/pyproject.toml),
# so we COPY it to /opt/steward and expose it on PYTHONPATH rather than pip-install.
# Source manifest (DR-003) enumerates exactly what is copied + SHA-256.
# Files are made world-readable so the (non-root) Dagu runtime user can import them.
COPY steward /opt/steward/steward
RUN set -eu; \
    python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && chmod -R a+rX /opt/steward /opt/venv

# NOTE: We intentionally do NOT create a custom user or set USER here.
# The pinned Dagu base already ships a non-root 'dagu' user (UID 1001) with a
# NOPASSWD sudoers rule, and its /entrypoint.sh re-maps that user to PUID/PGID
# (1000/1000) via usermod/groupmod, then execs the command as that user.
# Overriding USER would break the entrypoint's sudo target. We rely on the
# base's non-root execution design (matches deployed PUID/PGID=1000 convention).

ENV STEWARD_HOME=/opt/steward \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONPATH=/opt/steward \
    PUID=1000 \
    PGID=1000 \
    DAGU_HOME=/var/lib/dagu

WORKDIR /home/dagu

# Preserve normal Dagu startup behavior (entrypoint.tini -> /entrypoint.sh).
# The S3C fixture workflow is invoked manually through Dagu, never scheduled.
ENTRYPOINT ["/usr/local/bin/tini", "-g", "--", "/entrypoint.sh"]
CMD ["dagu", "start-all"]

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
# - python3 + pip (Steward is a Python package)
# - no docker CLI, no git, no ssh, no compilers, no redis/db clients, no creds
USER 0
RUN set -eu; \
    apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && python3 -m pip install --no-cache-dir --upgrade pip \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install the Steward package (committed S1-S3C files only) into the image.
# Source manifest (DR-003) enumerates exactly what is copied + SHA-256.
COPY steward /opt/steward/steward
RUN python3 -m pip install --no-cache-dir /opt/steward

# Non-root execution user (matches deployed PUID/PGID=1000 convention).
RUN set -eu; \
    groupadd -g 1000 steward 2>/dev/null || true; \
    useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin steward 2>/dev/null || true

ENV STEWARD_HOME=/opt/steward \
    PYTHONPATH=/opt/steward \
    DAGU_HOME=/var/lib/dagu

WORKDIR /home/dagu

# Preserve normal Dagu startup behavior (entrypoint.tini -> /entrypoint.sh).
# The S3C fixture workflow is invoked manually through Dagu, never scheduled.
USER 1000
ENTRYPOINT ["/usr/local/bin/tini", "-g", "--", "/entrypoint.sh"]
CMD ["dagu", "start-all"]

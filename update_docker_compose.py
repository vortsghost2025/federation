#!/usr/bin/env python3
"""Update VPS docker-compose.yml with cognition/narrator PathPrefix + NIM_API_KEYS."""

import sys

with open("/docker/federation-game/docker-compose.yml", "r") as f:
    content = f.read()

changes = 0

# Add /cognition and /narrator to both HTTPS and HTTP PathPrefix rules
old_suffix = "PathPrefix(`/redoc`))"
new_suffix = (
    "PathPrefix(`/redoc`) || PathPrefix(`/cognition`) || PathPrefix(`/narrator`))"
)
count = content.count(old_suffix)
if count > 0:
    content = content.replace(old_suffix, new_suffix)
    changes += count
    print(f"Replaced {count} PathPrefix rule occurrences")
else:
    print("WARNING: Could not find PathPrefix /redoc pattern")

# Add NIM_API_KEYS env var to backend service
if "NIM_API_KEYS" not in content:
    # Insert environment block after backend's env_file line
    backend_marker = (
        "    - .env\n  volumes:\n    - /docker/federation-game/backend:/app:ro"
    )
    backend_new = '    - .env\n  environment:\n    - "NIM_API_KEYS=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"\n  volumes:\n    - /docker/federation-game/backend:/app:ro'
    if backend_marker in content:
        content = content.replace(backend_marker, backend_new, 1)
        changes += 1
        print("Added NIM_API_KEYS to backend service")
    else:
        print("WARNING: Could not find backend env_file+volume pattern")

    # Add NIM_API_KEYS to worker service
    worker_marker = '- "NOTIFICATION_URLS=tgram://8908125951:AAEME7W8jlkh99AYIxM8IoIw_MlDznhajis/7312791490/"'
    worker_new = '- "NOTIFICATION_URLS=tgram://8908125951:AAEME7W8jlkh99AYIxM8IoIw_MlDznhajis/7312791490/"\n    - "NIM_API_KEYS=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"'
    if worker_marker in content:
        content = content.replace(worker_marker, worker_new, 1)
        changes += 1
        print("Added NIM_API_KEYS to worker service")
    else:
        print("WARNING: Could not find worker NOTIFICATION_URLS pattern")
else:
    print("NIM_API_KEYS already present")

with open("/docker/federation-game/docker-compose.yml", "w") as f:
    f.write(content)

print(f"docker-compose.yml updated: {changes} changes applied")

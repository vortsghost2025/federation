#!/usr/bin/env python3
"""
Deployment Verifier - Post-Deploy Health Checker

Verifies deployment health by:
1. Curling /healthz endpoint (expects 200 OK)
2. Checking docker compose ps (all containers should show 'healthy' or 'Up')

On failure, sends alert to Gastown dashboard.

Usage:
    python deployment_verifier.py [--hook] [--manual] [--backend-url URL]
"""

import argparse
import subprocess
import sys
import json
import os
from datetime import datetime
from typing import List, Tuple, Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class DeploymentVerifier:
    def __init__(self, backend_url: str = None, compose_file: str = None):
        self.backend_url = backend_url or os.environ.get("BACKEND_URL", "http://localhost")
        self.compose_file = compose_file or os.environ.get("DOCKER_COMPOSE_FILE", "docker-compose.yml")
        self.deployment_id = os.environ.get("DEPLOYMENT_ID", datetime.now().strftime("%Y%m%d-%H%M%S"))
        self.failures: List[str] = []

    def log_info(self, msg: str):
        print(f"[INFO] {msg}")

    def log_error(self, msg: str):
        print(f"[ERROR] {msg}")

    def log_warn(self, msg: str):
        print(f"[WARN] {msg}")

    def check_healthz(self) -> bool:
        """Check /healthz endpoint returns 200 OK"""
        self.log_info(f"Checking /healthz endpoint at {self.backend_url}/healthz...")
        url = f"{self.backend_url.rstrip('/')}/healthz"
        try:
            if HAS_REQUESTS:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    self.log_info(f"Health check passed: HTTP {resp.status_code}")
                    return True
                else:
                    self.failures.append(f"Health endpoint returned HTTP {resp.status_code} instead of 200")
                    return False
            else:
                result = subprocess.run(
                    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
                    capture_output=True, text=True, timeout=15
                )
                http_code = result.stdout.strip()
                if http_code == "200":
                    self.log_info(f"Health check passed: HTTP {http_code}")
                    return True
                else:
                    self.failures.append(f"Health endpoint returned HTTP {http_code} instead of 200")
                    return False
        except Exception as e:
            self.failures.append(f"Health check failed: {str(e)}")
            return False

    def check_docker_containers(self) -> bool:
        """Check docker compose containers are healthy (show 'healthy' or 'Up')"""
        self.log_info("Checking Docker container health...")
        compose_dir = "."
        compose_path = self._find_compose_file()
        if not compose_path:
            self.log_warn(f"Docker compose file not found at {self.compose_file}")
            self.failures.append("Docker compose file not found")
            return False
        try:
            containers = self._get_containers(compose_dir)
            if not containers:
                self.log_warn("No containers found via docker compose")
                return True  # No containers to check is not a failure
            unhealthy = []
            for container in containers:
                name = container.get("Name", "unknown")
                status = container.get("Status", "")
                state = container.get("State", "")
                if not self._is_container_healthy(status, state):
                    unhealthy.append((name, status))
                    self.failures.append(f"Container {name} is not healthy: {status}/{state}")
            if unhealthy:
                self.log_error(f"Found {len(unhealthy)} unhealthy containers:")
                for name, status in unhealthy:
                    self.log_error(f"  - {name}: {status}")
                return False
            self.log_info(f"All {len(containers)} containers are healthy")
            return True
        except json.JSONDecodeError:
            return self._check_containers_text_parse(compose_dir)
        except Exception as e:
            self.failures.append(f"Container check failed: {str(e)}")
            return False

    def _find_compose_file(self) -> Optional[str]:
        """Find docker compose file path"""
        if os.path.isfile(self.compose_file):
            return self.compose_file
        if os.path.isfile("docker-compose.yml"):
            return "docker-compose.yml"
        if os.path.isfile("federation-game/docker-compose.yml"):
            return "federation-game/docker-compose.yml"
        return None

    def _get_containers(self, compose_dir: str) -> List[dict]:
        """Get container list via docker compose"""
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True, text=True, cwd=compose_dir
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["docker-compose", "ps", "--format", "json"],
                capture_output=True, text=True, cwd=compose_dir
            )
        if result.returncode != 0:
            raise RuntimeError(f"Could not query docker compose: {result.stderr}")
        return json.loads(result.stdout) if result.stdout.strip() else []

    def _is_container_healthy(self, status: str, state: str) -> bool:
        """Check if container shows 'healthy' or 'Up' status"""
        status_lower = status.lower()
        state_lower = state.lower()
        # Check for Up status (e.g., "Up 2 hours")
        if status_lower.startswith("up"):
            return True
        # Check for healthy status from healthcheck
        if "healthy" in status_lower:
            return True
        # Explicitly unhealthy states
        unhealthy_states = ["exited", "unhealthy", "restarting", "paused"]
        if any(x in status_lower for x in unhealthy_states):
            return False
        # If no explicit Up/healthy but not unhealthy, assume OK
        return True

    def _check_containers_text_parse(self, compose_dir: str) -> bool:
        """Fallback text parsing for container status"""
        result = subprocess.run(
            ["docker", "compose", "ps"],
            capture_output=True, text=True, cwd=compose_dir
        )
        output = result.stdout
        unhealthy_states = ["Exited", "unhealthy", "Restarting", "Pause"]
        for line in output.split("\n"):
            for state in unhealthy_states:
                if state in line and "Up" not in line:
                    self.failures.append(f"Container in unhealthy state: {line.strip()}")
        return len(self.failures) == 0

    def send_alert(self, subject: str, body: str):
        """Send alert to Gastown dashboard"""
        alert_msg = f"DEPLOYMENT VERIFICATION FAILED: {subject}\nDetails: {body}"
        print(alert_msg)
        with open("/tmp/deployment-verification.log", "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"{timestamp}|FAILED|{subject}|{body}\n")
        try:
            subprocess.run(
                ["gt_mail_send", "--to", "rig_dashboard", "--subject", subject, "--body", body],
                capture_output=True, timeout=10
            )
        except Exception:
            pass

    def run(self) -> Tuple[bool, List[str]]:
        """Run all verification checks"""
        self.log_info("Starting deployment verification")
        self.log_info(f"Deployment ID: {self.deployment_id}")
        self.log_info(f"Backend URL: {self.backend_url}")
        self.check_healthz()
        self.check_docker_containers()
        return len(self.failures) == 0, self.failures

    def print_summary(self, success: bool):
        print("\n" + "=" * 50)
        print("Deployment Verification Summary")
        print("=" * 50)
        print(f"Deployment ID: {self.deployment_id}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print()
        if success:
            print("[PASSED] All health checks passed successfully.")
        else:
            print("[FAILED] Verification failed")
            print("\nFailures detected:")
            for i, f in enumerate(self.failures, 1):
                print(f"  {i}. {f}")


def main():
    parser = argparse.ArgumentParser(description="Deployment Verifier - Post-Deploy Health Checker")
    parser.add_argument("--hook", action="store_true", help="Running as git post-hook")
    parser.add_argument("--manual", action="store_true", help="Manual verification mode")
    parser.add_argument("--backend-url", default=None, help="Backend URL to check")
    parser.add_argument("--compose-file", default=None, help="Docker compose file path")
    args = parser.parse_args()
    verifier = DeploymentVerifier(
        backend_url=args.backend_url,
        compose_file=args.compose_file
    )
    success, failures = verifier.run()
    verifier.print_summary(success)
    if not success:
        failure_details = "\n".join(f"  - {f}" for f in failures)
        verifier.send_alert(
            f"DEPLOYMENT VERIFICATION FAILED [{verifier.deployment_id}]",
            f"Deployment {verifier.deployment_id} failed verification:\n{failure_details}"
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
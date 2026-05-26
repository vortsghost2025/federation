# Federation Sync State
# Updated: 2026-05-25T21:25
# Both local agent and Gastown rig read/write this file

## CURRENT TASK
- Gastown SSH2 bridge fix: switched to public IP + RSA PKCS1 PEM keys
- GitHub Actions self-hosted runner: NOW WORKING (backend deploy verified)

## GASTOWN — WHAT TO DO (step by step)

1. Pull latest code: `git pull`
2. Go to rig dir: `cd gastown-rig`
3. Install deps: `npm install`
4. Generate new RSA key: `node setup-keys.js`
5. It prints an ssh-rsa public key line ending in "gastown-rig"
6. You need to get that public key onto the VPS authorized_keys
7. Test connection: `node shell.js --cmd "hostname"`
8. If it prints "srv1345984" — you're connected!
9. Deploy: `node deploy.js --target backend`

## KEY FIXES (why it was broken before)
- Old: ed25519 keys + Tailscale IP (100.75.95.23)
- New: RSA 4096 PKCS1 PEM keys + Public IP (187.77.3.56)
- Why: ssh2 library cannot parse Node.js crypto ed25519 PEM keys properly
- RSA PKCS1 PEM ("-----BEGIN RSA PRIVATE KEY-----") is ssh2's native format
- Public IP works without Tailscale (no 120s timeout issue)

## GASTOWN RIG CAPABILITIES
- OS: Debian 13 (trixie), Bash, apt (NO sudo/root)
- Node.js: v24.15.0, npm 11.12.1
- python3: 3.13.5 (no pip3)
- git: 2.47.3, curl: 8.14.1, jq: 1.7
- ssh2 npm module: Installed
- NO: docker, openssh-client, sudo, pip3
- 4 CPU, 10GB RAM, 14GB disk

## VPS (srv1345984)
- Public IP: 187.77.3.56 (PREFER THIS — shorter, no Tailscale needed)
- Tailscale IP: 100.75.95.23 (still works, but not needed for Gastown)
- Hostname: srv1345984.hstgr.cloud
- SSH: Port 22, PermitRootLogin yes, listening on 0.0.0.0
- authorized_keys: 4 entries (sean@windows, seand@WE, github-actions-deploy, gastown-rig RSA)

## GITHUB ACTIONS RUNNER — NOW WORKING
- Runner: vps-runner at /opt/actions-runner/, user github-runner
- FIXED: Added SupplementaryGroups=docker to systemd service
- FIXED: Workflow uses `install -g docker -m 664` for file deployment
- Workflow: .github/workflows/deploy-vps.yml
- Usage: `gh workflow run deploy-vps.yml --ref main -f target=backend`
- Targets: backend, worker, frontend, html-only, all
- Verified: backend deploy succeeded, HTTP 200, all containers healthy

## DEPLOYMENT OPTIONS (ranked by ease)
1. GitHub Actions workflow — ONE COMMAND from Windows
2. Gastown SSH2 bridge — from the rig (when fixed)
3. PowerShell base64 + SCP — old fallback (still works)

## KNOWN ISSUES
- Auto-push hook pushes HEAD instead of HEAD:refs/heads/main (fails after rebase)
- SCP from Windows strips leading spaces
- Write tool fails on files >~1400 lines (use Python builder scripts)
- Worker container has NO bind mount — needs build+up, not restart

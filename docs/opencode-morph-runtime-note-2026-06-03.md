# OpenCode / Morph Runtime Note

Date: 2026-06-03
Recorded: 2026-06-03 11:25:44 -04:00
Scope: machine-local runtime fixes and verification only
Repo branch: `main`

## What changed

This note documents the local OpenCode and Morph runtime work completed on 2026-06-03.

The primary symptom was:

- `opencode` CLI rendering blank or unstable in the terminal
- `OpenCode.exe` desktop app opening a lavender loading shell and never handing off to the real session UI

## Root cause summary

Two separate issues were isolated:

1. Bun / OpenTUI native cache and terminal wrapper issues affected CLI startup.
2. The Morph OpenCode plugin layer caused the desktop app to stall during startup.

The Morph MCP server itself starts correctly. The startup break was isolated to the Morph OpenCode plugin layer, not to the MCP server binary alone.

## Machine-local files changed

These changes were made outside the git repo and are not tracked by this repository:

- `C:\Users\seand\AppData\Local\waveterm-alt\data\bin\ensure-bun-native-cache.ps1`
- `C:\Users\seand\AppData\Local\waveterm-alt\data\bin\opencode.ps1`
- `C:\Users\seand\AppData\Local\waveterm-alt\data\bin\opencode.cmd`
- `C:\Users\seand\AppData\Local\waveterm-alt\data\bin\kilo.ps1`
- `C:\Users\seand\AppData\Local\waveterm-alt\data\bin\kilo.cmd`
- `C:\Users\seand\.config\opencode\opencode.json`

## Current stable state

The stable final state left in place is:

- `morph-mcp` enabled in `C:\Users\seand\.config\opencode\opencode.json`
- Morph plugin list entry removed
- Morph instructions entry removed
- local `lane-runtime.js` plugin left untouched
- WaveTerm wrappers still used for `opencode` and `kilo`

This gives:

- desktop OpenCode launches into the real `Session` UI
- `opencode --continue` still reaches normal TUI plugin loading
- Morph MCP can still start without reintroducing the desktop hang

## Backups created

The following config backups were created during debugging:

- `C:\Users\seand\.config\opencode\opencode.json.backup-20260603-050520`
- one additional pre-restore backup with suffix `-pre-morph-restore`

## Verification performed

Verification on 2026-06-03 included:

- visual capture of the desktop OpenCode window showing the real `Session` UI
- direct startup tests of `OpenCode.exe`
- direct startup tests of `opencode --continue`
- direct startup test of `npx -y @morphllm/morphmcp`
- split-path validation showing:
  - Morph MCP only: desktop startup remains healthy
  - Morph MCP plus Morph OpenCode plugin: desktop startup stalls on loader

## Important note

This commit documents the runtime work only.

It does **not** commit the actual machine-local runtime files above, because they live outside the repository and there are many unrelated uncommitted changes already present inside `S:\federation`.

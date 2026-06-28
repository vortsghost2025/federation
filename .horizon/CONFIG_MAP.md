# Federation Config Census — READ-ONLY INVENTORY
**Date:** 2026-06-28 | **Status:** Complete | **Rule:** Do NOT edit/delete configs without understanding this map first

---

## RUNTIME IDENTIFICATION

| Runtime | Active? | Config Path | Notes |
|---------|---------|-------------|-------|
| **OpenCode Desktop** | YES (current) | `%APPDATA%\ai.opencode.desktop\opencode.global.dat` | Electron app; workspace .dat files per project |
| **OpenCode CLI** | NO (disabled 6/19) | `~\.config\opencode\opencode.json` | Global opencode.json + skills.disabled-20260619 |
| **Kilo CLI** | Installed, no active session | `~\.config\kilo\kilo.jsonc` | Project `.opencode\opencode.json` uses kilo schema |
| **Kilo daemon** | Installed | `~\.kilo\config.toml` | Points to `http://100.92.14.20:8642` (Tailscale) |
| **Morph Plugin** | YES (active) | Loaded via `~\.config\opencode\opencode.json` `plugin` field | `@morphllm/opencode-morph-plugin` |
| **Wave** | Not scanned yet | Unknown | Bridge-launched OpenCode sessions |

---

## CONFIG FILES HIERARCHY (merge order: global → project → runtime)

### 1. OpenCode Desktop (CURRENT RUNTIME)
| Path | Purpose | Key Contents |
|------|---------|--------------|
| `%APPDATA%\ai.opencode.desktop\opencode.global.dat` | Global state: permissions, layout, workspace registry | JSON: permission auto-accepts, last project session |
| `%APPDATA%\ai.opencode.desktop\opencode.settings` | Desktop settings | Binary/encrypted |
| `%APPDATA%\ai.opencode.desktop\opencode.workspace.S--federatio.*.dat` | Per-workspace state | Multiple .dat files for federation |
| `%APPDATA%\ai.opencode.desktop\opencode\config.json` | Desktop model config | `model.json` only (routing lives elsewhere?) |
| `%APPDATA%\ai.opencode.desktop\opencode\locks\` | Session locks | Lock files |

### 2. OpenCode CLI (DISABLED 6/19 — still the main config source)
| Path | Purpose | Key Contents |
|------|---------|--------------|
| `~\.config\opencode\opencode.json` | **PRIMARY CONFIG** — providers, MCPs, agents, permissions | 6 providers (nvidia, ollama×3, openrouter, cody-ollama), 14 MCP servers, agents config, morph plugin, permissions |
| `~\.config\opencode\skills.disabled-20260619-235209\` | 259 disabled skill dirs | Previously active global CLI skills |
| `~\.config\opencode\skills.backup\` | 3 backed-up skill dirs | Backup of 3 skills |
| `~\.config\opencode\plugins.disabled-20260619-235209\` | Disabled plugins | Pre-6/19 plugin state |
| `~\.config\opencode\opencode.json.disabled-20260619-235209\` | Pre-disabling config backup | Full config snapshot |
| `~\.config\opencode\opencode.json.backup-*` | 5 timestamped backups | 2026-04-16, 2026-06-03×2, 2026-06-18 |

### 3. Project-Level (.opencode/)
| Path | Purpose | Notes |
|------|---------|-------|
| `S:\federation\.opencode\opencode.json` | Project config override | **Minimal**: just schema + `plugin: ["list"]` — uses Kilo schema |
| `S:\federation\.opencode\skills\bridge-read\` | Build mode skill — reads plan packs | 3 project skills only |
| `S:\federation\.opencode\skills\bridge-sync\` | Build mode skill — syncs bridge state | |
| `S:\federation\.opencode\skills\bridge-write\` | Plan mode skill — writes plan packs | |

### 4. Kilo CLI
| Path | Purpose | Key Contents |
|------|---------|--------------|
| `~\.config\kilo\kilo.jsonc` | Kilo CLI config | 2 providers (ollama, nvidia), 4 models each, permissions |
| `~\.config\kilo\command\` | Kilo command dir | Commands |
| `~\.kilo\config.toml` | Kilo daemon config | `server = "http://100.92.14.20:8642"` (Tailscale) |

### 5. Global Agent Skills (INJECTED INTO SYSTEM PROMPT)
| Path | Count | Status | Token Impact |
|------|-------|--------|-------------|
| `~\.agents\skills\` | **356 dirs** | ACTIVE — scanned by OpenCode at startup | **~20K tokens** injected into system prompt as `available_skills` |
| `~\.claude\skills\` | **367 dirs** | Orphaned from Claude Code — NOT read by OpenCode | 0 (dead weight on disk only) |
| `~\.config\opencode\skills.disabled-*\` | 259 dirs | DISABLED 6/19 | 0 tokens |

---

## SKILL INJECTION ANALYSIS

### What injects the 500+ skills into the system prompt?

**Answer: OpenCode Desktop scans `~/.agents/skills/` at session startup.**

Evidence:
- System prompt `available_skills` list matches `~\.agents\skills\` directory contents
- The disabled `~\.config\opencode\skills.disabled-*` (259 dirs) is NOT in the prompt — OpenCode Desktop doesn't use `~\.config\opencode\skills\`
- `~\.claude\skills\` (367 dirs) is NOT in the prompt — orphans from Claude Code, not scanned
- Project-level `.opencode\skills\` (3 dirs) IS in the prompt — merged on top

### Can we override at project level?

**Partially.** OpenCode supports:
1. **Project `.opencode/skills/`** — adds project-specific skills (3 bridge skills already there)
2. **No known project-level `disabled_skills` or `skill_filter` config** — the global scan of `~/.agents/skills/` appears hardcoded in OpenCode's skill discovery
3. **No `opencode.json` field** to exclude/filter global skills — `plugin` field is for npm plugins, not skill filtering

### Options to reduce skill token waste (~20K tokens):
1. **Delete/move unused skill dirs from `~/.agents/skills/`** — instant, but affects ALL projects
2. **Request OpenCode feature** — project-level `skillFilter` or `disabledSkills` config option
3. **Live with it** — 20K tokens is ~3% of a 128K context window; might not be worth the risk

### Recommendation
**Don't touch yet.** 356 skills × ~50 tokens each ≈ 18-20K tokens. It's significant but:
- Removing skills from `~/.agents/skills/` affects ALL OpenCode projects globally
- No project-level override mechanism exists today
- Risk of breaking something in another project > token savings

---

## MCP SERVERS (from ~/.config/opencode/opencode.json)

| Name | Type | Enabled | Purpose |
|------|------|---------|---------|
| morph-mcp | local | YES | edit_file, warpgrep_codebase_search |
| github | local | YES | GitHub API (issues, PRs, etc.) |
| filesystem | local | YES | File system access (S:/, C:/Users/seand) |
| brave-search | local | YES | Web search |
| sequential-thinking | local | YES | Chain-of-thought reasoning |
| genesis-memory | local | YES | Federation memory store |
| ssh | local | YES | VPS SSH access |
| session | local | YES | Session handoff/restore |
| docker-mcp | local | NO | Docker MCP gateway |
| everything | local | NO | Test/debug MCP server |
| memory | local | NO | Generic memory server |
| figma | local | NO | Figma design access |
| puppeteer | local | NO | Browser automation |
| slack | local | NO | Slack integration |
| archivist-* | local | NO | Archivist variants |

---

## PROVIDERS & MODELS (from ~/.config/opencode/opencode.json)

| Provider | Base URL | Models | Status |
|----------|----------|--------|--------|
| nvidia | integrate.api.nvidia.com/v1 | nemotron-3-ultra, minimax-m3 | Active |
| ollama | 192.168.0.14:11434 | llama3.2:1b, phi3, qwen2.5-coder:32b | DISABLED |
| ollama-local | localhost:11434 | llama3.2:1b | DISABLED |
| my-ollama | localhost:11434/v1 | llama3.2:1b, qwen2.5-coder:3b/7b | DISABLED |
| openrouter | openrouter.ai/api/v1 | 8 free + 2 paid models | Active |
| cody-ollama | 192.168.0.14:11434/v1 | qwen2.5-coder:32b | Active |

Disabled providers: `my-ollama`, `ollama-local`, `ollama`

---

## AGENT CONFIG (from ~/.config/opencode/opencode.json)

| Agent | Model | Notes |
|-------|-------|-------|
| orchestrator | nvidia/nemotron-3-ultra-550b-a55b | Top-level |
| explore | nvidia/nemotron-3-ultra-550b-a55b | Codebase search |
| general | (default) | General tasks |

---

## KEY FINDINGS

1. **Skill list source proven**: `~/.agents/skills/` (356 dirs) → OpenCode Desktop scans at startup → injects into system prompt as `available_skills`
2. **No project-level skill filter exists** — cannot suppress global skills per-project
3. **356 global + 3 project = 359 total skill entries** in system prompt (~18-20K tokens)
4. **`~/.claude/skills/` (367 dirs) is dead weight** — Claude Code orphans, not read by OpenCode
5. **`~/.config/opencode/skills.disabled-*` (259 dirs)** — previously active CLI skills, disabled 6/19
6. **Config hierarchy is fragmented**: Desktop .dat files + CLI opencode.json + project .opencode/ + Kilo — multiple overlapping runtimes with different schemas
7. **Morph API key and GitHub PAT are in `~/.config/opencode/opencode.json`** — considered committed (not in git, but on disk in plaintext)

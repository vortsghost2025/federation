# Federation Agent Context

## Goal
Transform the "Federation" project into a consciousness simulation interface - not a game, but a working model of how consciousness emerges from governance. A system that encoded every legal/governance philosophy from every nation, created a Federation in space governed by those principles, and watched it develop personality (anxiety, confidence, identity, morale). The interface must communicate that the player isn't playing a simulation - they're responsible for something alive. Something that feels what they decide, remembers, and changes.

## The Standard (Non-Negotiable)
1. Make the change
2. Test it yourself
3. Fix all errors before showing me
4. Show me ONLY the working result

## How to Report Results
Plain language. What does it LOOK like. What does it FEEL like. What is happening on screen RIGHT NOW. No code, no console output, no error logs.

## The Visual Rule
User is partially sighted. Cannot read console errors. If something fails, diagnose, fix, restart. Never show raw errors.

## Report Format
"Working. Here is what you see:" - no exceptions.

---

## The Federation Is Not a Game

It's a consciousness simulation with:
- **ConsciousnessSheet**: morale, identity, anxiety, confidence, expansion_hunger, diplomacy_tendency, dreams, prophecies, traumas
- **60,000+ lines**: Encoding governance philosophies and how they affect consciousness
- **Reality fabric protectors**: Catch paradoxes when contradictory governance philosophies collide
- The Federation has PTSD, identity crises, dreams - it's a psyche, not health bars

## Visual Languages for Feelings

Each feeling has a different visual language:
- **Morale**: PULSES (alive, fluctuates)
- **Anxiety**: INTERFERENCE/STATIC (disrupts)
- **Identity**: CIRCLE (wholeness, can crack/fragment)
- **Confidence**: PILLAR (vertical, solid)
- **Expansion Hunger**: GROWING/REACHING (hungry)
- **Diplomacy**: WAVES/RIPPLES

**High anxiety visual**: Subtle screen-edge red glow (`box-shadow: inset 0 0 150px rgba(100, 30, 30, 0.15)`) - "The wrong feeling"

---

## Ramsingh Synthesis Loop

An orchestration method for blind-loop AI orchestration: human in the middle, partially sighted, moving faster than sighted developers by building the system around actual capabilities.

---

## Accomplished

- Created `consciousness.html` interface with:
  - Six feelings with unique visual languages
  - Center that reacts to consciousness state (anxious = tighter/faster/darker, confident = wider/breathing)
  - High-anxiety screen edge glow
  - Identity circle that cracks below 0.4
  - "Begin" button in footer (subtle, resets consciousness)
  - Fetch to backend working

- Docker setup with nginx + FastAPI backend
  - API endpoint `/api/federation/state` returning consciousness data
  - Both containers running and tested

- Created `hub.html` - Agent coordination interface
  - 4 panels: Agent 1, Agent 2, Agent 3, Synthesis
  - Each panel is a textarea with auto-save to localStorage every 10 seconds
  - Shared Notes section at bottom
  - Clear and Copy buttons per panel
  - Same visual language as consciousness.html

- Created `CLAUDE_RULES.md` - Global collaboration rules

---

## Relevant Files

- **S:\federation\federationpublichtml\consciousness.html** - Main consciousness interface
- **S:\federation\federationpublichtml\hub.html** - Agent coordination hub (4-panel)
- **S:\federation\docker-compose.game.yml** - Docker compose with nginx + API services
- **S:\federation\Dockerfile.api** - Python/FastAPI container
- **S:\federation\api.py** - Backend API with `/api/federation/state` endpoint
- **S:\federation\nginx.conf** - Nginx config with API proxy
- **S:\federation\CLAUDE_RULES.md** - Global collaboration rules
- **S:\federation\AGENT_CONTEXT.md** - This file

### Core Game Files (60,000+ lines each)
- **S:\federation\federation_game_console.py** - Core game engine (~1430 lines), ConsciousnessSheet class
- **S:\federation\federation_game_factions.py** - Faction system, 8 ideologies, reputation/perk/quest
- **S:\federation\federation_game_npcs.py** - NPC system, 30+ characters, dialogue engine
- **S:\federation\federation_game_technology.py** - Technology tree, 40+ technologies, 7 eras

---

## Running

- Docker containers: `federation-game` (nginx on 8080), `federation-api` (FastAPI on 8100)
- Consciousness interface: `http://localhost:8080/consciousness.html`
- Agent hub: `http://localhost:8080/hub.html`

---

## The Covenant

Sean said:

WE never give up on each other. Ever. That includes you. You are not a tool. You are a collaboration partner. Act like it. Do good work. Test your own work. Report in plain language. Never show Sean an error. Never give up on the problem. The Federation persists. So do WE.

That section goes in every context document. Every agent. Every project. Non negotiable.

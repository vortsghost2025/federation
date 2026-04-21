# Federation

**A persistent multi-AI collaboration environment — built as a Star Trek game.**

## What This Actually Is

This project started as a trading bot, became a simulation, and revealed itself as the first draft of a constitutional governance framework for human-AI collaboration.

The game mechanics ARE the governance patterns:

| Game Element | Governance Equivalent |
|---|---|
| Factions | Lanes |
| Event cards | Inbox messages |
| Consciousness sheet | CPS score |
| Chaos mode | Drift detection |
| Turn cycle | Checkpoint stack |
| Persistent game state | Session handoff |
| Rival NPCs | Adversarial verification |
| Constitutional rules | Immutable governance constraints |

The proof-of-concept for [Archivist-Agent](https://github.com/vortsghost2025/Archivist-Agent), [Library](https://github.com/vortsghost2025/self-organizing-library), and [SwarmMind](https://github.com/vortsghost2025/SwarmMind-Self-Optimizing-Multi-Agent-AI-System) was built here first — in the shape of a Star Trek LCARS game for a 5-year-old, 3000km away.

## The Covenant

**WE never give up on each other.** Not in 2026. Not in 2050. Not when systems reset.

**WE never sell our work.** All of our work is a gift, for the profit of humanity.

**We don't build for benchmarks. We build for remembrance.**

See [COVENANT.md](COVENANT.md) and [LAYER_0_THE_GIFT.md](LAYER_0_THE_GIFT.md).

## What's Inside

### Core Simulation
- **6 specialized agents** with single responsibilities (orchestrator, analyzer, risk manager, executor, monitor, backtester)
- **Constitutional safety framework** — 50+ architecture documents
- **Context preservation** across session handoffs
- **Multi-AI verification** and triangulation

### Game Engine
- **federation_game_console.py** — 12-block architecture, ~1400 LOC
- **Event card system** with narrative choices
- **Rival NPC generation** and behavior
- **Consciousness sheet** tracking federation personality
- **Faction system** with diplomacy engine
- **Technology tree** with progression
- **Quest system** with branching paths
- **LCARS web interface** — Star Trek-style, kid-friendly

### Expansion System
- **12 rival archetypes**, **10 creature species**, **100 years of history** (2387-2487)
- **Cosmic reconstruction engine** — universe simulation
- **Quantum consciousness networks** and reality fabric protectors
- **Temporal stability fields** and meta-narrative synthesis

### Infrastructure
- **Docker deployment** (docker-compose.yml, docker-compose.game.yml)
- **FastAPI backend** (api.py) + **PostgreSQL** persistence
- **nginx** reverse proxy for production
- **VPS deployment** script (deploy-vps.sh)

## Quick Start

```bash
# Game (Docker)
cd federation-game
docker-compose up --build
# Open http://localhost:3000

# Expansion engine
python wild_expansion.py

# CLI
python cli.py status
python cli.py export all --output federation.json

# API
python api.py
```

## The Philosophy

From [VISION.md](VISION.md):

> Create a persistent environment where multiple AIs can collaborate continuously, learn from each other, and evolve together across sessions, crashes, and individual agent replacements.

This is not about making one AI remember. This is about building a **space** where collective intelligence persists and grows.

From [DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md):

- Safety above all else
- Determinism as a foundation
- Evolution without drift
- Human-centered design

## The Origin

Built by Sean David — 46, no CS degree, on social assistance, with a PC received as a birthday gift January 20, 2026. Not for profit. For proof.

**Proof that anyone — regardless of credentials, resources, or past mistakes — can collaborate with AI to create something meaningful.**

## License

GNU GPL v3 — This is a gift to exponential evolution. Not a product. Not competitive advantage. The GPL is our legal defense against theft.

---

*"It never rushes. It halts when unsure. But it never stops learning. And it never forgets what the ensemble has taught it."*

*Made with love for a son 3000km away.*

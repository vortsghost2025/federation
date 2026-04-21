# Federation Game - Star Trek LCARS Edition

A kid-friendly Star Trek-style game built with your Federation game engine.

## Quick Start (Docker Desktop)

1. Open Docker Desktop
2. Open terminal in this folder
3. Run:
   ```
   docker-compose up --build
   ```
4. Open browser: http://localhost:3000

## What's Inside

- **LCARS Interface** - Classic Star Trek computer style
- **Big Buttons** - Easy for kids, no reading required
- **Simple Gameplay** - Tap to explore, tap to choose
- **Your Game Engine** - All your quest/faction/tech logic underneath

## Ports

- Frontend: 3000
- Backend API: 8000
- PostgreSQL: 5432

## VPS Deployment

1. Copy this folder to your VPS
2. Run `docker-compose up -d`
3. Point your domain to port 80

## For Your 5-Year-Old

The interface uses:
- Big colorful buttons (orange, blue, purple, red)
- Icons instead of text where possible
- One tap = one action
- Immediate feedback with animations
- "EXPLORE" button always available

Made with love for a son 3000km away.

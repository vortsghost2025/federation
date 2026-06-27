# Federation Telegram-vs-Live mismatch — CONFIRMED

**Verified at:** 2026-06-21 00:35 UTC (Day 26, tick 1782002066+)

## What your Telegram said (NOT in sim)
- entropy_cult launched attack against harmony_seekers — NOT FOUND
- Lyra Swiftwind operated a black market — NOT FOUND
- Paradox operated a black market — NOT FOUND
- Trickster operated a black market — NOT FOUND
- Paradox intel breach — NOT FOUND
- Baroness Greed intel breach — POSSIBLE (Baroness vanished event earlier, but not "intel breach")
- Brother Mercy and comp_002 conflict -10.3 — NOT FOUND
- Merchant-Prince Aurelius vs char_003 conflict — NOT in current feed
- Cipher temporal drift — NOT FOUND
- Spectre breakthrough — NOT FOUND
- Turning-point warning — NOT FOUND
- "Covert ops by Trickster, Lyra" — NOT FOUND

## Real state from /spectator/summary
- Headline: "Negotiating: Marshal Ironbound and Dr. Sylas Cunningham collaboration. Relationship +6.4"
- Mood: Negotiating
- 80 signals: 52 interactions, 28 decisions
- Themes: react_to_events (20), socialize (12), explore (10)
- 22 relationship changes
- Latest events:
  - Marshal Ironbound + Dr. Sylas Cunningham (collaboration, +6.4)
  - Dr. Sylas Cunningham + char_306 (mentorship, +3.7)
  - Captain Valor vs char_102 (rivalry, -5.0)

## Real state from /simulation.html DOM scrape
- M 61 / S 56 / A 27 (ELEVATED)
- T 29 / X 41 / R 59
- Tick 1781992421, 4s ago
- "The Federation is experiencing CALM events"
- Recent: Baroness Greed vanished, General Devastation drills
- "All systems nominal"

## Worker log evidence
- Many ticks: "Crisis readout fetched: STABLE - No active crisis"
- Many ticks: "Throttled: N events but notification suppressed (10-min dedupe)"
- Backend log: "Resolved event 'Espionage Uncovered: Polaris Federation' (0ef940c4): choice=covert_response, voters=8"
  — only ONE real event found, also no trace of the fiction

## Conclusion
The Hertz-driven Telegram bot is fabricating events that do not exist
in the live sim data. The simulator backend has a single real signal
("Espionage Uncovered: Polaris Federation"), which the digest LLM
appears to be embellishing into a fictional "hostile faction attack" narrative.

## Where the flow lives
- /docker/federation-game/backend/simulation_operator.py  →  _send_telegram_alert (line 369)
- /docker/federation-game/backend/worker_vps.py         →  throttled event counter
- C:\Users\seand\AppData\Local\hermes\scripts\federation_npc_digest.py  →  Windows Hermes_Gateway_federation
- Backend digest source: https://federation-game.deliberatefederation.cloud/spectator/summary
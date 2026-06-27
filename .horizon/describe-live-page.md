# describe-live-page — accessibility narrator

Image vision is broken in Hermes/OpenCode transport.
Puppeteer DOM scraping works.
Use **browser automation** as the accessibility path. Never try image vision again.

## Trigger command: describe-live-page

When Sean asks "what does the page look like", "is it updated", "is it broken",
or anything visual, run this script:

```powershell
# Open the live sim
npx -y @modelcontextprotocol/server-puppeteer navigate `
  https://federation-game.deliberatefederation.cloud/simulation.html

# Scrape the page DOM
# (keep size under control — return only what fits in model context)
```

Then capture from `puppeteer_evaluate`:

- page title
- visible main text (full body innerText)
- current tick + last-tick age
- top metrics (M/S/A and T/X/R + statuses)
- 10-second briefing
- current situation + MAIN RISK + WATCHLIST
- NPC Reality Feed top 10
- quest / decision status if visible
- console errors
- floating/bounding-box quirks

## Save result to:

`S:\federation\.horizon\page-status.txt`

Print same summary to terminal.

## PowerShell hygiene (for the script)

DO NOT use Linux syntax (`ls -la`, `cat`, `find`).
Use only:
- `Get-ChildItem`
- `Get-Item path | Format-List FullName,Length,LastWriteTime`
- `Get-Content -Raw`
- `Test-Path`
- `Set-Content -Path "S:\..." -Encoding UTF8`
- `New-Item -ItemType Directory -Force -Path "S:\..."`

## Sanctity rules

1. Drive the browser. Sean never touches the TV.
2. Once a page is read, save to .horizon/page-status.txt — Sean can review slowly with his magnifier on his own time.
3. If vision keeps failing, never escalate to "describe your screen" prompts. Always DOM scrape.
4. This is the canonical accessibility path now. Do not invent alternatives.
5. Console / terminal output to Sean must be SHORTER than 4 lines of text unless he asks for detail. No preamble. No postamble. No "Working — here is what you see:".

## Decision rationale (Sean said this)

> Couldn't you just load the webpage, take the screenshots yourself till you
> have figured out how to see it, instead of the half-blind human struggling
> for hours not being able to see files or terminals?

Yes. Puppeteer is the answer. Vision bytes are unreliable; DOM scrape is reliable.

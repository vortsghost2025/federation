"""Visual test against the mock /map/data fixture.
Captures Universe, NPC, Exploration modes, plus Region and Sector zoom levels."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    msgs = []
    page.on("console", lambda m: msgs.append(f"[{m.type}] {m.text}"))
    page.on("pageerror", lambda e: msgs.append(f"[PAGEERROR] {e}"))
    page.goto("http://127.0.0.1:8888/galaxy-map.html")
    # Wait for first /map/data poll to populate sectors + NPCs
    page.wait_for_timeout(4500)

    # ─── UNIVERSE MODE (default) ──────────────────────────────────────
    page.screenshot(path="S:/federation/galaxy_mock_universe.png")

    # ─── NPC MODE ─────────────────────────────────────────────────────
    page.locator('button[data-mode="npc"]').click()
    page.wait_for_timeout(2000)
    page.screenshot(path="S:/federation/galaxy_mock_npc.png")

    # ─── EXPLORATION MODE ─────────────────────────────────────────────
    page.locator('button[data-mode="exploration"]').click()
    page.wait_for_timeout(2000)
    page.screenshot(path="S:/federation/galaxy_mock_exploration.png")

    # ─── REGION ZOOM (still in Exploration mode) ──────────────────────
    page.locator('button[data-zoom="region"]').click()
    page.wait_for_timeout(2000)
    page.screenshot(path="S:/federation/galaxy_mock_region.png")

    # ─── SECTOR ZOOM ──────────────────────────────────────────────────
    page.locator('button[data-zoom="sector"]').click()
    page.wait_for_timeout(2000)
    page.screenshot(path="S:/federation/galaxy_mock_sector.png")

    # ─── DIAGNOSTIC DUMP ──────────────────────────────────────────────
    diag = page.evaluate("""() => ({
        url: document.getElementById('d-url')?.textContent,
        status: document.getElementById('d-status')?.textContent,
        bytes: document.getElementById('d-bytes')?.textContent,
        sectors: document.getElementById('d-sectors')?.textContent,
        factions: document.getElementById('d-factions')?.textContent,
        terr: document.getElementById('d-terr')?.textContent,
        npcs: document.getElementById('d-npcs')?.textContent,
        npclocs: document.getElementById('d-npclocs')?.textContent,
        disc: document.getElementById('d-disc')?.textContent,
        tick: document.getElementById('d-tick')?.textContent,
        mock_banner_visible: document.getElementById('mock-banner')?.classList.contains('show'),
        tick_label: document.getElementById('tick-label')?.textContent,
    })""")
    print("DIAG PANEL:")
    for k, v in diag.items():
        print(f"  {k}: {v}")

    errs = [m for m in msgs if "[error]" in m.lower() and "404" not in m.lower()]
    print(f"\nJS ERRORS (excluding expected 404s): {len(errs)}")
    for e in errs:
        print(f"  {e}")

    browser.close()
print("\nDONE")

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})

    msgs = []
    page.on("console", lambda m: msgs.append(f"[{m.type}] {m.text}"))
    page.on("pageerror", lambda e: msgs.append(f"[PAGEERROR] {e}"))

    page.goto("http://127.0.0.1:8888/galaxy-map.html")
    page.wait_for_timeout(4500)

    page.screenshot(path="S:/federation/galaxy_screenshot_universe.png")

    # Toggle to territory mode
    page.locator('button[data-mode="territory"]').click()
    page.wait_for_timeout(1500)
    page.screenshot(path="S:/federation/galaxy_screenshot_territory.png")

    # Toggle to NPC mode
    page.locator('button[data-mode="npc"]').click()
    page.wait_for_timeout(1500)
    page.screenshot(path="S:/federation/galaxy_screenshot_npc.png")

    # Toggle to Exploration mode
    page.locator('button[data-mode="exploration"]').click()
    page.wait_for_timeout(1500)
    page.screenshot(path="S:/federation/galaxy_screenshot_exploration.png")

    errs = [m for m in msgs if "[error]" in m.lower() or "[PAGEERROR]" in m]
    print(f"ERRORS: {len(errs)}")
    for e in errs:
        print("  " + e)
    print(f"TOTAL CONSOLE: {len(msgs)}")

    tick = page.locator("#tick-label").inner_text(timeout=2000)
    print(f"TICK: {tick}")

    browser.close()
print("DONE")

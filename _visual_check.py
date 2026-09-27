from playwright.sync_api import sync_playwright
import sys

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})

    console_msgs = []
    page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: console_msgs.append(f"[PAGEERROR] {err}"))

    page.goto("http://127.0.0.1:8888/universe.html")
    # Let the scene render a few frames + let the starfield drift + bloom settle
    page.wait_for_timeout(3500)

    # Save the screenshot
    page.screenshot(path="S:/federation/universe_screenshot.png", full_page=False)

    # Print console errors only
    errs = [m for m in console_msgs if "[error]" in m.lower() or "[PAGEERROR]" in m]
    if errs:
        print("CONSOLE_ERRORS:")
        for e in errs:
            print("  " + e)
    else:
        print("CONSOLE_ERRORS: NONE")

    # Print tick state so we know the polling worked
    tick_label = page.locator("#tick-label").inner_text(timeout=2000)
    tick_dot_bg = page.evaluate("getComputedStyle(document.getElementById('tick-dot')).backgroundColor")
    print(f"TICK_LABEL: {tick_label}")
    print(f"TICK_DOT: {tick_dot_bg}")

    # Count rendered sectors + npc labels (rough sanity check)
    sector_labels = page.locator(".lbl-sector").count()
    npc_labels = page.locator(".lbl-npc").count()
    print(f"SECTOR_LABELS: {sector_labels}")
    print(f"NPC_LABELS: {npc_labels}")

    browser.close()
print("DONE")

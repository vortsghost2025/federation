from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})

    msgs = []
    page.on("console", lambda m: msgs.append(f"[{m.type}] {m.text}"))
    page.on("pageerror", lambda e: msgs.append(f"[PAGEERROR] {e}"))

    page.goto("http://127.0.0.1:8888/galaxy-map.html")
    page.wait_for_timeout(5000)

    # Check if loading overlay is still present
    loading_display = page.evaluate("getComputedStyle(document.getElementById('loading')).display")
    print(f"LOADING DISPLAY: {loading_display}")

    canvas_w = page.evaluate("document.getElementById('c').width")
    canvas_h = page.evaluate("document.getElementById('c').height")
    print(f"CANVAS: {canvas_w}x{canvas_h}")

    errs = [m for m in msgs if "[error]" in m.lower() or "[PAGEERROR]" in m]
    print(f"\nERRORS: {len(errs)}")
    for e in errs:
        print("  " + e)

    # Print all messages for debugging
    print(f"\nALL MESSAGES ({len(msgs)}):")
    for m in msgs[:30]:
        print("  " + m)

    browser.close()
print("DONE")

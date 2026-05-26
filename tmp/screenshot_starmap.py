"""Screenshot the Federation starmap to verify the new distributed layout."""

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(
        "https://federation-game.deliberatefederation.cloud/starmap.html",
        wait_until="networkidle",
        timeout=30000,
    )
    # Wait for the map data to load and render
    page.wait_for_timeout(8000)
    page.screenshot(path="S:/federation/tmp/starmap_screenshot.png", full_page=False)
    print("Screenshot saved to S:/federation/tmp/starmap_screenshot.png")
    browser.close()

"""Take a screenshot of the starmap to verify faction layout."""

import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        url = "https://federation-game.deliberatefederation.cloud/starmap.html"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # Wait for the canvas to render
        await page.wait_for_timeout(8000)

        out_path = r"S:\federation\tmp\starmap_screenshot2.png"
        await page.screenshot(path=out_path, full_page=False)
        print(f"Screenshot saved to {out_path}")

        await browser.close()


asyncio.run(main())

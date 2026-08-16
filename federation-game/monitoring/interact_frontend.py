#!/usr/bin/env python3
"""Interactive read-only pass over the Federation Game observer pages using
system Playwright. Drives real clicks/actions on the LIVE pages but performs
ONLY safe, read-only interactions (refresh, tab switches, hover/focus). It
does NOT send moderator messages, trigger workflows, or mutate NPC state.

Checks:
- council-chat: click Refresh, confirm a new status stamp and that the pair
  thread re-renders with real messages; read the headline + a message.
- spectator: switch Simple<->Institutions tabs via the actual buttons and
  confirm each view swaps (not just that two pages load).
- starmap: wait for render, move the mouse over canvas, read any tooltip/focus
  text that appears.
"""
import json
from playwright.sync_api import sync_playwright

BASE = "https://federation-game.deliberatefederation.cloud"
OUT = {}

def new_page(p, ctx):
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append("PAGEERROR: " + str(e)))
    return page, errs

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 2000})

    # ---------- council-chat: interactive refresh ----------
    page, errs = new_page(p, ctx)
    page.goto(BASE + "/council-chat.html", wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(2500)
    before_text = page.inner_text("#pair-thread") if page.locator("#pair-thread").count() else ""
    before_status = page.inner_text("#status") if page.locator("#status").count() else ""
    # click the Refresh button (known id via getElementById('refresh-btn')? Not in council-chat;
    # council-chat auto-polls; it has loadAll(). Click #status text? Instead we call the reload
    # button if present, else wait for a poll cycle.
    if page.locator("button:has-text('Refresh')").count():
        page.locator("button:has-text('Refresh')").first.click()
        page.wait_for_timeout(2000)
    else:
        page.wait_for_timeout(20000)  # one poll cycle
    after_thread = page.inner_text("#pair-thread") if page.locator("#pair-thread").count() else ""
    after_status = page.inner_text("#status") if page.locator("#status").count() else ""
    headline = page.inner_text("#pair-headline") if page.locator("#pair-headline").count() else ""
    OUT["council-chat"] = {
        "console_errors": errs[:8],
        "thread_char_before": len(before_text),
        "thread_char_after": len(after_thread),
        "status_before": before_status.strip()[:60],
        "status_after": after_status.strip()[:60],
        "headline": headline.strip()[:120],
        "thread_snippet": after_thread.strip()[:300],
    }

    # ---------- spectator: tab-mode switching ----------
    page, errs = new_page(p, ctx)
    page.goto(BASE + "/spectator.html", wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(3000)
    # Find mechanism to switch modes. spectator uses ?mode=... and also has tab buttons
    # (datalist of .tab buttons with data-mode). Capture how it switches.
    tabs = page.locator(".tab").count()
    tab_labels = page.locator(".tab").all_inner_texts()[:8]
    # Click a tab if mode buttons exist
    switched = None
    if tabs:
        # try the institutions tab if present (data-mode=institutions) else the second tab
        inst = page.locator(".tab[data-mode='institutions']")
        if inst.count():
            inst.first.click(); page.wait_for_timeout(3000)
            switched = "institutions-tab"
        else:
            tab = page.locator(".tab").nth(1)
            tab.click(); page.wait_for_timeout(3000)
            switched = "second-tab:" + tab.inner_text()[:20]
    body_after_tab = page.inner_text("body")
    OUT["spectator"] = {
        "console_errors": errs[:8],
        "tab_count": tabs,
        "tab_labels": tab_labels,
        "switched_via": switched,
        "body_has_institution": ("institution" in body_after_tab.lower()),
        "body_has_workflow": ("workflow" in body_after_tab.lower()),
        "body_snippet": body_after_tab.strip()[:400],
    }

    # ---------- starmap: hover/focus read ----------
    try:
        page, errs = new_page(p, ctx)
        page.goto(BASE + "/starmap.html", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(4000)
        canvas = page.locator("canvas").first
        has_canvas = page.locator("canvas").count() > 0
        tooltip = ""
        if has_canvas:
            box = canvas.bounding_box()
            if box:
                # hover near center then slightly off-center to trigger faction tooltip
                page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                page.wait_for_timeout(800)
                # any .faction-tooltip or title attr
                for sel in [".faction-tooltip", "[role='tooltip']", ".tooltip", "#tooltip"]:
                    if page.locator(sel).count():
                        t = page.locator(sel).first.inner_text().strip()
                        if t:
                            tooltip = t; break
        OUT["starmap"] = {
            "console_errors": errs[:8],
            "canvas_present": has_canvas,
            "tooltip_read": tooltip[:200] or "none",
            "body_snippet": page.inner_text("body")[:200],
        }
    except Exception as e:
        OUT["starmap"] = {"error": str(e)}

    browser.close()

print("\n\n===== INTERACTIVE RESULTS =====")
print(json.dumps(OUT, indent=2, default=str))
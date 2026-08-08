"""Browser proof: capture X-Idempotency-Key header from real browser click."""
import json
import time
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Capture network requests
        captured_requests = []
        captured_responses = []
        
        def handle_request(request):
            if "broadcast" in request.url or "/messages" in request.url:
                headers = request.headers
                idem_key = headers.get("x-idempotency-key", "")
                captured_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "idempotency_key": idem_key,
                    "timestamp": time.time()
                })
        
        def handle_response(response):
            if "broadcast" in response.url:
                try:
                    body = response.json()
                    captured_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "body": body
                    })
                except:
                    pass
        
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        # Navigate to council chat
        print("Navigating to council chat...")
        page.goto("http://localhost:18080/council-chat.html", timeout=10000)
        print("Page loaded, waiting for network idle...")
        page.wait_for_load_state("networkidle", timeout=10000)
        
        # Disable auto-refresh by removing the interval
        page.evaluate("() => { if (window._refreshInterval) clearInterval(window._refreshInterval); }")
        
        # Fill in the form
        print("Filling form...")
        page.fill("#topic", "idempotency_browser_proof")
        page.fill("#body", "Browser idempotency proof — one deliberate verification message.")
        
        # Click Send button
        print("Clicking Send button...")
        page.click('button[onclick="sendCustom()"]')
        
        # Wait for response
        print("Waiting for response...")
        page.wait_for_timeout(5000)
        
        browser.close()
        
        print("\n=== CAPTURED REQUESTS ===")
        for req in captured_requests:
            if req["method"] == "POST":
                print(json.dumps(req, indent=2))
        
        print("\n=== CAPTURED RESPONSES ===")
        for resp in captured_responses:
            print(json.dumps(resp, indent=2))

if __name__ == "__main__":
    main()

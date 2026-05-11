#!/usr/bin/env python3
"""LIVE_STATE_WIRING_REPORT

Script that verifies the live deployed Federation Game API updates the engine
state correctly across several event/choice cycles.

It makes real HTTP requests to:
    https://federation-game.deliberatefederation.cloud/api

The script performs:
  1. POST /reset
  2. GET initial /engine-status
  3. Three times:
     - GET /event
     - POST /choose/{first_choice_id}
     - GET /engine-status
  4. Checks that turn, turns_in_phase and events_seen evolve as expected.

Output format includes PASS/WARN/FAIL for each check and a final verdict.
"""
import json
import sys
import urllib.error
import urllib.request

BASE_URL = "https://federation-game.deliberatefederation.cloud/api"


def request(method, path, data=None):
    """Perform an HTTP request with urllib.
    Returns a tuple (status_code, json_body_or_None)."""
    url = BASE_URL + path
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    else:
        payload = None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8")
            return status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        print(f"ERROR: unexpected exception {e}")
        return None, None


def main():
    print("LIVE_STATE_WIRING_REPORT")
    print(f"Base URL: {BASE_URL}\n")

    # 1. Reset the game
    status, _ = request("POST", "/reset")
    if status != 200:
        print(f"FAIL: POST /reset returned {status}")
        sys.exit(1)
    print("PASS: POST /reset returned 200")

    # 2. Initial engine status
    status, eng0 = request("GET", "/engine-status")
    if status != 200:
        print(f"FAIL: GET /engine-status (initial) returned {status}")
        sys.exit(1)
    print("PASS: GET /engine-status (initial) returned 200")
    turn_prev = eng0.get("turn")
    tp_prev = eng0.get("turn_progression", {}).get("turns_in_phase")
    events_seen_prev = eng0.get("event_registry", {}).get("events_seen", [])
    print(f"Initial turn: {turn_prev}, turns_in_phase: {tp_prev}, events_seen count: {len(events_seen_prev)}\n")

    overall_success = True
    for i in range(1, 4):
        # 3a. Get a fresh event
        status, ev = request("GET", "/event")
        if status != 200:
            print(f"FAIL: GET /event iteration {i} returned {status}")
            sys.exit(1)
        event_id = ev.get("id")
        title = ev.get("title", "<no title>")
        choices = ev.get("choices", [])
        if not choices:
            print(f"FAIL: Event '{title}' has no choices")
            sys.exit(1)
        choice_id = choices[0].get("id")
        print(f"Iteration {i}: Event '{title}' (id={event_id}), using choice id='{choice_id}'")

        # 3b. Apply the choice
        status, _ = request("POST", f"/choose/{choice_id}")
        if status != 200:
            print(f"FAIL: POST /choose/{choice_id} returned {status}")
            sys.exit(1)
        print(f"PASS: POST /choose/{choice_id} returned 200")

        # 3c. Fetch engine status after the choice
        status, eng = request("GET", "/engine-status")
        if status != 200:
            print(f"FAIL: GET /engine-status after iteration {i} returned {status}")
            sys.exit(1)
        turn_now = eng.get("turn")
        tp_now = eng.get("turn_progression", {}).get("turns_in_phase")
        events_seen_now = eng.get("event_registry", {}).get("events_seen", [])

        # Checks
        turn_ok = (turn_now == turn_prev + 1)
        tp_ok = (tp_now is not None and tp_prev is not None and tp_now > tp_prev)
        events_ok = (len(events_seen_now) > len(events_seen_prev))

        print(f"  Turn: {turn_prev} -> {turn_now} {'PASS' if turn_ok else 'FAIL'}")
        print(f"  Turns in phase: {tp_prev} -> {tp_now} {'PASS' if tp_ok else 'FAIL'}")
        print(f"  Events seen count: {len(events_seen_prev)} -> {len(events_seen_now)} {'PASS' if events_ok else 'FAIL'}")
        print()

        if not (turn_ok and tp_ok and events_ok):
            overall_success = False

        # update previous values for next iteration
        turn_prev = turn_now
        tp_prev = tp_now
        events_seen_prev = events_seen_now

    final_verdict = "PASS" if overall_success else "FAIL"
    print("Final Verdict:", final_verdict)
    if final_verdict == "PASS":
        print("Live state wiring appears correct.")
    else:
        print("Next safe action: Fix backend/main.py so that real event resolution updates the engine_status payload (events_seen, turn progression, etc.).")

if __name__ == "__main__":
    main()

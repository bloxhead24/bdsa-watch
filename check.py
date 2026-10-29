#!/usr/bin/env python3
"""BDSA ticket watcher. Pushes to your phone (ntfy) when ticket stock or the release wording changes.

Reads the public event page only (allowed by Ticket Tailor's robots.txt). Its schema.org data lists
every ticket type with availability (InStock / SoldOut), so restocks are caught even if the text
never changes. Alert-only: never buys, fills forms, or touches the checkout widget.
"""
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

EVENT_URL = os.environ.get("BDSA_URL", "https://www.tickettailor.com/events/britishdentalstudentsassociation/2371111")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
STATE_FILE = pathlib.Path(os.environ.get("STATE_FILE", ".state/last.json"))
FAIL_LIMIT = 3  # consecutive fetch failures before the run fails (GitHub then emails you)
UA = "Mozilla/5.0 (personal ticket alert)"

RELEASE = re.compile(
    r"(release\s*\d+[^.<\n]{0,80}"
    r"|sold\s*out[^.<\n]{0,60}"
    r"|on\s+sale\s+(?:from|soon|on)[^.<\n]{0,60}"
    r"|waiting\s*list[^.<\n]{0,60})",
    re.I,
)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def snapshot(page):
    tickets = {}
    for block in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if item.get("@type") != "Event":
                continue
            for o in item.get("offers") or []:
                status = str(o.get("availability", "")).rsplit("/", 1)[-1] or "Unknown"
                tickets[o.get("name", "?")] = {"status": status, "price": o.get("price")}
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))
    release = sorted({m.group(0).strip().lower() for m in RELEASE.finditer(text)})
    if not tickets and not release:
        raise ValueError("page loaded but no ticket data found (layout may have changed)")
    return {"tickets": tickets, "release": release}


def describe(prev, cur):
    lines, restock = [], False
    pt, ct = prev.get("tickets", {}), cur["tickets"]
    for name in sorted(set(pt) | set(ct)):
        a, b = pt.get(name), ct.get(name)
        if a == b:
            continue
        if a is None:
            lines.append(f"NEW: {name} £{b['price']} ({b['status']})")
            restock |= b["status"] == "InStock"
        elif b is None:
            lines.append(f"REMOVED: {name}")
        else:
            if a["status"] != b["status"]:
                lines.append(f"{name}: {a['status']} -> {b['status']}")
                restock |= b["status"] == "InStock"
            if a["price"] != b["price"]:
                lines.append(f"{name}: £{a['price']} -> £{b['price']}")
    if prev.get("release") != cur["release"]:
        lines.append("Wording now: " + (" | ".join(cur["release"]) or "none"))
    return lines, restock


def summary(cur):
    t = cur["tickets"]
    instock = sum(v["status"] == "InStock" for v in t.values())
    return f"{instock}/{len(t)} ticket types in stock"


def notify(title, msg, priority="urgent"):
    print(f"ALERT: {title}: {msg}", flush=True)
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set, skipping push", flush=True)
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=msg.encode(),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": "ticket,rotating_light",
            "Click": EVENT_URL,
            "Actions": f"view, Open tickets, {EVENT_URL}, clear=true",
        },
    )
    urllib.request.urlopen(req, timeout=20)


def load():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def save(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def main():
    if "--test-alert" in sys.argv:
        notify("BDSA watcher test", "Tap to open the ticket page. If you see this, alerts work.", "high")
        return
    # --loop N: keep checking every INTERVAL seconds for N seconds (one long job instead of relying on cron)
    if "--loop" in sys.argv:
        end = time.time() + int(sys.argv[sys.argv.index("--loop") + 1])
        interval = int(os.environ.get("INTERVAL", "60"))
        while True:
            check_once()
            if time.time() + interval >= end:
                return
            time.sleep(interval)
    check_once()


def check_once():
    state = load() or {}
    try:
        cur = snapshot(fetch(EVENT_URL))
    except Exception as e:
        fails = state.get("fails", 0) + 1
        print(f"fetch error ({fails}/{FAIL_LIMIT}): {e}", flush=True)
        state["fails"] = fails
        save(state)
        if fails >= FAIL_LIMIT:
            sys.exit(f"{fails} failed checks in a row: watcher can't read the page")
        return
    prev = state.get("snap")
    print(time.strftime("%H:%M:%S"), "current:", summary(cur), "|", " ".join(cur["release"]), flush=True)
    if "--dry-run" in sys.argv:
        return
    if prev is not None:
        lines, restock = describe(prev, cur)
        if lines:
            title = "BDSA TICKETS AVAILABLE" if restock else "BDSA tickets: change"
            notify(title, "\n".join(lines) + f"\n({summary(cur)}) Tap to open.", "urgent" if restock else "high")
    else:
        print("first run: baseline saved, no alert", flush=True)
    save({"snap": cur, "fails": 0})


if __name__ == "__main__":
    main()

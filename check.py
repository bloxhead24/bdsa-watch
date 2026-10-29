#!/usr/bin/env python3
"""BDSA ticket watcher. Alerts your phone (ntfy) when the release/sold-out wording on the event page changes.
Alert-only: it never buys, fills forms, or touches the checkout widget (Ticket Tailor's robots.txt blocks it)."""
import html
import os
import pathlib
import re
import sys
import urllib.request

EVENT_URL = os.environ.get("BDSA_URL", "https://www.tickettailor.com/events/britishdentalstudentsassociation/2371111")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
STATE_FILE = pathlib.Path(os.environ.get("STATE_FILE", ".state/last"))
UA = "Mozilla/5.0 (personal ticket alert)"

# Lines the organiser edits when a release changes, e.g. "Release 1 is on sale now."
SIGNAL = re.compile(
    r"(release\s*\d+[^.<\n]{0,80}"
    r"|(?:tickets?\s+(?:are\s+)?)?sold\s*out[^.<\n]{0,60}"
    r"|on\s+sale\s+(?:from|soon|on)[^.<\n]{0,60}"
    r"|waiting\s*list[^.<\n]{0,60}"
    r"|no\s+tickets?\s+(?:are\s+)?available[^.<\n]{0,40})",
    re.I,
)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def signature(page):
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"\s+", " ", text)
    found = sorted({m.group(0).strip().lower() for m in SIGNAL.finditer(text)})
    return " | ".join(found) or "none"


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


def main():
    if "--test-alert" in sys.argv:
        notify("BDSA watcher test", "Tap to open the ticket page. If you see this, alerts work.", "high")
        return
    try:
        current = signature(fetch(EVENT_URL))
    except Exception as e:
        print("fetch error:", e, flush=True)
        return
    previous = STATE_FILE.read_text().strip() if STATE_FILE.exists() else None
    print("previous:", previous, "current:", current, flush=True)
    if "--dry-run" in sys.argv:
        return
    if previous is not None and current != previous:
        notify("BDSA tickets: page changed", f"Now: {current}\nWas: {previous}\nTap to open.")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(current)


if __name__ == "__main__":
    main()

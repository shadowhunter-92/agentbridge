"""
Real-time HN post monitor — for the first hour after you post Show HN.

Watches one HN item via the public read-only Firebase API. Refreshes every
~20 seconds and prints: current score, current rank on the front page,
comment count, AND a chronological feed of new comments since the last
refresh (with author + a preview), so you can reply within minutes.

No credentials. No write actions. Read-only public API.

Usage:
    .venv/Scripts/python tools/hn_monitor.py <item_id>
    e.g.  python tools/hn_monitor.py 48123456

Stop with Ctrl+C.
"""

from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

API = "https://hacker-news.firebaseio.com/v0"
REFRESH_SECONDS = 20
PREVIEW_CHARS = 180


def fetch_json(url: str) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        return {"_error": str(e)}


def get_item(item_id: int) -> dict:
    data = fetch_json(f"{API}/item/{item_id}.json")
    return data if isinstance(data, dict) else {"_error": "not a dict"}


def get_rank(item_id: int) -> int | None:
    top = fetch_json(f"{API}/topstories.json")
    if not isinstance(top, list):
        return None
    try:
        return top.index(item_id) + 1
    except ValueError:
        return None


def strip_html(s: str) -> str:
    import re, html
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html.unescape(s).strip()


def gather_comments(item_id: int, seen: dict[int, dict]) -> list[dict]:
    """Walk the comment tree. Return only comments we haven't seen before."""
    new_comments: list[dict] = []
    queue: list[int] = []
    root = get_item(item_id)
    queue.extend(root.get("kids", []) or [])
    while queue:
        cid = queue.pop(0)
        if cid in seen:
            # Still walk its kids — replies under known comments can be new.
            c = seen[cid]
            queue.extend(c.get("kids", []) or [])
            continue
        c = get_item(cid)
        if not c or c.get("deleted") or c.get("dead"):
            seen[cid] = c or {}
            continue
        seen[cid] = c
        new_comments.append(c)
        queue.extend(c.get("kids", []) or [])
    new_comments.sort(key=lambda c: c.get("time", 0))
    return new_comments


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def fmt_time(ts: int | None) -> str:
    if not ts:
        return "?"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%H:%M:%SZ")


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print("usage: python tools/hn_monitor.py <item_id>")
        print("  e.g.  python tools/hn_monitor.py 48123456")
        sys.exit(2)

    item_id = int(sys.argv[1])
    seen: dict[int, dict] = {}
    started = datetime.now(tz=timezone.utc)
    print(f"Watching HN item {item_id}. Ctrl+C to stop.")
    print(f"URL: https://news.ycombinator.com/item?id={item_id}\n")
    time.sleep(1)

    # Seed: mark all existing comments as 'seen' (no spam on first tick).
    seed_root = get_item(item_id)
    seed_queue = list(seed_root.get("kids", []) or [])
    while seed_queue:
        cid = seed_queue.pop(0)
        if cid in seen:
            continue
        c = get_item(cid)
        seen[cid] = c or {}
        seed_queue.extend((c or {}).get("kids", []) or [])
    initial_comment_count = len(seen)
    print(f"Seeded with {initial_comment_count} existing comments.\n")
    time.sleep(2)

    try:
        while True:
            tick = datetime.now(tz=timezone.utc)
            elapsed = int((tick - started).total_seconds())
            item = get_item(item_id)
            rank = get_rank(item_id)
            score = item.get("score", "?")
            descendants = item.get("descendants", "?")
            title = item.get("title", "")
            new = gather_comments(item_id, seen)

            clear_screen()
            print("=" * 78)
            print(f"  {title[:74]}")
            print(f"  item {item_id} · https://news.ycombinator.com/item?id={item_id}")
            print("=" * 78)
            rank_str = f"#{rank} on /news" if rank else "off front page"
            print(f"  score {score} | comments {descendants} | {rank_str} "
                  f"| watched {elapsed//60}m{elapsed%60:02d}s")
            print("-" * 78)

            if new:
                print(f"  {len(new)} NEW comment(s) this tick:\n")
                for c in new:
                    author = c.get("by", "?")
                    when = fmt_time(c.get("time"))
                    text = strip_html(c.get("text", ""))[:PREVIEW_CHARS]
                    cid = c.get("id", "?")
                    print(f"  [{when}] {author}  ->  https://news.ycombinator.com/item?id={cid}")
                    for line in [text[i:i+74] for i in range(0, len(text), 74)]:
                        print(f"      {line}")
                    print()
                # On Windows, ring the bell so you notice.
                sys.stdout.write("\a"); sys.stdout.flush()
            else:
                print("  (no new comments since last tick)")

            print("-" * 78)
            print(f"  next refresh in {REFRESH_SECONDS}s  ·  Ctrl+C to stop")
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()

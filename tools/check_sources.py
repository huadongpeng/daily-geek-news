#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "config" / "sources.json"


def load_sources() -> Dict[str, Any]:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


def validate_shape(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    seen: Dict[str, str] = {}
    for topic, config in data.items():
        feeds = config.get("feeds")
        search_seeds = config.get("search_seeds")
        if not isinstance(feeds, list):
            errors.append(f"{topic}: feeds must be a list")
            continue
        if not isinstance(search_seeds, list):
            errors.append(f"{topic}: search_seeds must be a list")
        for url in feeds:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                errors.append(f"{topic}: invalid feed URL: {url!r}")
                continue
            if url in seen:
                errors.append(f"{topic}: duplicate feed also used by {seen[url]}: {url}")
            seen[url] = topic
    return errors


def probe_feed(url: str, timeout: int) -> str:
    import feedparser
    import requests

    resp = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "EastonRadarSourceCheck/1.0 (+https://www.huadongpeng.com)",
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
        },
    )
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if getattr(parsed, "bozo", False):
        return f"parse-warning: {getattr(parsed, 'bozo_exception', 'unknown')}"
    return f"ok: {len(parsed.entries)} entries"


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight local validation for config/sources.json")
    parser.add_argument("--probe", action="store_true", help="Fetch feeds and report RSS parse health")
    parser.add_argument("--limit", type=int, default=0, help="Probe at most N feeds across all topics; 0 means all")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    data = load_sources()
    errors = validate_shape(data)
    total_feeds = sum(len(config.get("feeds", [])) for config in data.values())
    total_seeds = sum(len(config.get("search_seeds", [])) for config in data.values())
    print(f"topics={len(data)} feeds={total_feeds} search_seeds={total_seeds}")
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1

    if not args.probe:
        return 0

    checked = 0
    failures = 0
    for topic, config in data.items():
        for url in config.get("feeds", []):
            if args.limit and checked >= args.limit:
                break
            checked += 1
            try:
                result = probe_feed(url, args.timeout)
                print(f"{topic} | {url} | {result}")
            except Exception as exc:
                failures += 1
                print(f"{topic} | {url} | failed: {exc}")
        if args.limit and checked >= args.limit:
            break
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

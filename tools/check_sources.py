#!/usr/bin/env python3
"""
Connectivity test for all RSS feeds and API sources in sources.json.
Usage:
    python tools/check_sources.py
"""
import json
import sys
import time
import concurrent.futures
from pathlib import Path

import feedparser
import requests

SOURCES_PATH = Path(__file__).parent.parent / "config" / "sources.json"
TIMEOUT = 12
MAX_WORKERS = 20

UA = "Mozilla/5.0 (compatible; EastonRadar/1.0; source-checker)"
# Disable brotli in Accept-Encoding so we never get content requests can't decode
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}


def check_rss(url: str) -> dict:
    t0 = time.time()
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        elapsed = round(time.time() - t0, 2)
        if resp.status_code != 200:
            return {"url": url, "ok": False, "status": resp.status_code, "items": 0, "elapsed": elapsed,
                    "note": f"HTTP {resp.status_code}"}
        feed = feedparser.parse(resp.text)
        n = len(feed.entries)
        if n == 0 and not feed.feed.get("title"):
            return {"url": url, "ok": False, "status": resp.status_code, "items": 0, "elapsed": elapsed,
                    "note": "0 entries + no feed title — may be wrong format"}
        return {"url": url, "ok": True, "status": resp.status_code, "items": n, "elapsed": elapsed, "note": ""}
    except requests.exceptions.Timeout:
        return {"url": url, "ok": False, "status": 0, "items": 0, "elapsed": round(time.time() - t0, 2),
                "note": "timeout"}
    except Exception as e:
        return {"url": url, "ok": False, "status": 0, "items": 0, "elapsed": round(time.time() - t0, 2),
                "note": str(e)[:80]}


def check_api(url: str) -> dict:
    t0 = time.time()
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        elapsed = round(time.time() - t0, 2)
        if resp.status_code != 200:
            return {"url": url, "ok": False, "status": resp.status_code, "items": 0, "elapsed": elapsed,
                    "note": f"HTTP {resp.status_code}"}
        data = resp.json()
        if isinstance(data, dict):
            items = data.get("items") or data.get("hits") or data.get("results") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        n = len(items)
        # 0 items on a time-filtered API (e.g. HN Algolia search_by_date) is expected on quiet days
        is_time_filtered = "search_by_date" in url or "created_at" in url
        note = "" if n > 0 else ("no stories today (time-filtered, expected)" if is_time_filtered else "returned 0 items")
        return {"url": url, "ok": True, "status": resp.status_code, "items": n, "elapsed": elapsed, "note": note}
    except requests.exceptions.Timeout:
        return {"url": url, "ok": False, "status": 0, "items": 0, "elapsed": round(time.time() - t0, 2),
                "note": "timeout"}
    except Exception as e:
        return {"url": url, "ok": False, "status": 0, "items": 0, "elapsed": round(time.time() - t0, 2),
                "note": str(e)[:80]}


def main():
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))

    tasks: list[tuple[str, str, str]] = []  # (category, type, url)
    for cat, cfg in sources.items():
        for url in cfg.get("feeds", []):
            tasks.append((cat, "rss", url))
        for url in cfg.get("api_sources", []):
            tasks.append((cat, "api", url))

    total = len(tasks)
    print(f"🔍 检测 {total} 个数据源（RSS + API），并发 {MAX_WORKERS} 线程...\n")

    results: list[dict] = []

    def _run(task):
        cat, typ, url = task
        r = check_rss(url) if typ == "rss" else check_api(url)
        r["category"] = cat
        r["type"] = typ
        return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_run, t): t for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            results.append(r)
            sym = "✅" if r["ok"] else "❌"
            note = f"  ← {r['note']}" if r["note"] else ""
            print(f"  {sym} [{r['category']:12s}] {r['type']:3s}  {r['items']:3d}items  {r['elapsed']:5.1f}s  "
                  f"{r['url'][:72]}{note}")

    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]

    print(f"\n{'='*80}")
    print(f"✅ 通过 {len(ok)}/{total}    ❌ 失败 {len(fail)}/{total}")

    if fail:
        print(f"\n❌ 失败列表（共 {len(fail)} 个）：")
        by_cat: dict[str, list] = {}
        for r in fail:
            by_cat.setdefault(r["category"], []).append(r)
        for cat, items in sorted(by_cat.items()):
            print(f"\n  [{cat}]")
            for r in items:
                print(f"    {r['type']:3s}  HTTP {r['status']:3d}  {r['note']:45s}  {r['url']}")

    print(f"\n📊 各分类统计：")
    for cat in sources:
        cat_r = [r for r in results if r["category"] == cat]
        cat_ok = sum(1 for r in cat_r if r["ok"])
        avg = sum(r["elapsed"] for r in cat_r) / len(cat_r) if cat_r else 0
        print(f"  {cat:14s}  {cat_ok:2d}/{len(cat_r)} OK  avg {avg:.1f}s")

    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())

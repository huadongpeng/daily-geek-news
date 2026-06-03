#!/usr/bin/env python3
"""Submit freshly deployed URLs to search-engine indexing endpoints."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SITE_URL = os.environ.get("SITE_URL", "https://www.huadongpeng.com").rstrip("/")
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "hdop-indexnow-key")
BAIDU_PUSH_TOKEN = os.environ.get("BAIDU_PUSH_TOKEN", "")
BAIDU_MAX_PER_PUSH = int(os.environ.get("BAIDU_MAX_PER_PUSH", "10"))


def load_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return list(dict.fromkeys(str(url) for url in data if str(url).startswith("http")))


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_pending(path: Path, urls: list[str]) -> None:
    urls = list(dict.fromkeys(urls))
    if urls:
        save_json(path, urls[:500])
    elif path.exists():
        path.unlink()


def request_json(url: str, *, method: str = "POST", data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    req = Request(url, data=data, headers=headers or {}, method=method)
    with urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(body or "{}")


def live_status(url: str) -> int | None:
    for method in ("HEAD", "GET"):
        try:
            req = Request(url, method=method, headers={"User-Agent": "EastonRadarIndexSubmit/1.0"})
            with urlopen(req, timeout=15) as resp:
                return resp.status
        except HTTPError as exc:
            if method == "HEAD" and exc.code in {403, 405}:
                continue
            return exc.code
        except URLError:
            return None
    return None


def filter_live_urls(urls: list[str]) -> tuple[list[str], dict[str, int | None]]:
    statuses = {url: live_status(url) for url in urls}
    live = [url for url, status in statuses.items() if status is not None and 200 <= status < 400]
    return live, statuses


def submit_indexnow(urls: list[str]) -> dict:
    if not urls:
        return {"submitted": 0, "status": "skipped"}
    payload = {
        "host": urlparse(SITE_URL).hostname or "www.huadongpeng.com",
        "key": INDEXNOW_KEY,
        "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
        "urlList": urls[:100],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        "https://api.indexnow.org/indexnow",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            return {"submitted": len(payload["urlList"]), "http_status": resp.status}
    except HTTPError as exc:
        return {"submitted": len(payload["urlList"]), "http_status": exc.code, "error": exc.read().decode("utf-8", errors="replace")[:500]}
    except URLError as exc:
        return {"submitted": len(payload["urlList"]), "error": str(exc)}


def submit_baidu(urls: list[str]) -> dict:
    if not urls:
        return {"submitted": 0, "status": "skipped"}
    if not BAIDU_PUSH_TOKEN:
        return {"submitted": 0, "pending": urls, "error": "BAIDU_PUSH_TOKEN is not configured"}

    batch = urls[:BAIDU_MAX_PER_PUSH]
    rest = urls[len(batch):]
    site = urlparse(SITE_URL).hostname or "www.huadongpeng.com"
    endpoint = f"http://data.zz.baidu.com/urls?site={site}&token={BAIDU_PUSH_TOKEN}"
    try:
        status, result = request_json(
            endpoint,
            data="\n".join(batch).encode("utf-8"),
            headers={"Content-Type": "text/plain"},
        )
        result["http_status"] = status
        result["submitted"] = len(batch)
        if rest:
            result["pending"] = rest
        if "error" in result:
            result["pending"] = urls
        return result
    except HTTPError as exc:
        return {"submitted": len(batch), "http_status": exc.code, "pending": urls, "error": exc.read().decode("utf-8", errors="replace")[:500]}
    except (URLError, json.JSONDecodeError) as exc:
        return {"submitted": len(batch), "pending": urls, "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit deployed article URLs to IndexNow and Baidu")
    parser.add_argument("--urls-file", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".cache") / "radar")
    parser.add_argument("--pending-dir", type=Path)
    parser.add_argument("--skip-live-check", action="store_true")
    args = parser.parse_args()

    pending_dir = args.pending_dir or args.output_dir
    pending_indexnow_path = pending_dir / "pending_push_urls_indexnow.json"
    pending_baidu_path = pending_dir / "pending_push_urls_baidu.json"

    new_urls = load_urls(args.urls_file)
    indexnow_urls = list(dict.fromkeys([*new_urls, *load_urls(pending_indexnow_path)]))
    baidu_urls = list(dict.fromkeys([*new_urls, *load_urls(pending_baidu_path)]))
    urls = list(dict.fromkeys([*indexnow_urls, *baidu_urls]))

    if args.skip_live_check:
        live_urls, live_statuses = urls, {}
    else:
        live_urls, live_statuses = filter_live_urls(urls)
    live_set = set(live_urls)
    indexnow_live = [url for url in indexnow_urls if url in live_set]
    baidu_live = [url for url in baidu_urls if url in live_set]
    indexnow_not_live = [url for url in indexnow_urls if url not in live_set]
    baidu_not_live = [url for url in baidu_urls if url not in live_set]

    indexnow_result = submit_indexnow(indexnow_live)
    baidu_result = submit_baidu(baidu_live)
    indexnow_pending = indexnow_live if isinstance(indexnow_result, dict) and indexnow_result.get("error") else []
    indexnow_pending = list(dict.fromkeys([*indexnow_pending, *indexnow_not_live]))
    baidu_pending = baidu_result.get("pending", []) if isinstance(baidu_result, dict) else []
    baidu_pending = list(dict.fromkeys([*baidu_pending, *baidu_not_live]))

    result = {
        "site_url": SITE_URL,
        "new_urls": new_urls,
        "urls_considered": urls,
        "live_statuses": live_statuses,
        "skipped_not_live": [url for url in urls if url not in live_urls],
        "indexnow": indexnow_result,
        "baidu": baidu_result,
        "pending": {
            "indexnow": indexnow_pending,
            "baidu": baidu_pending,
        },
    }

    output_dir = args.output_dir
    save_json(output_dir / "search_push_results.json", result)
    save_pending(output_dir / "pending_push_urls_indexnow.json", indexnow_pending)
    save_pending(output_dir / "pending_push_urls_baidu.json", baidu_pending)
    if pending_dir != output_dir:
        save_pending(pending_indexnow_path, indexnow_pending)
        save_pending(pending_baidu_path, baidu_pending)

    print(f"Search push URLs: {len(new_urls)} new, {len(urls)} total considered, {len(live_urls)} live")
    print(f"IndexNow: {result['indexnow']}")
    print(f"Baidu: {result['baidu']}")
    if result["skipped_not_live"]:
        print(f"Skipped not-live URLs: {len(result['skipped_not_live'])}")


if __name__ == "__main__":
    main()

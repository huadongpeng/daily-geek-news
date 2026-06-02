#!/usr/bin/env python3
# NOTE: must stay compatible with the VPS Python (3.6) — no PEP 585 builtin generics
# (dict[...]/list[...]) and no `from __future__ import annotations` (added in 3.7).
import argparse
import html
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET", "")
WECHAT_AUTHOR = os.environ.get("WECHAT_AUTHOR", "老花")
WECHAT_TITLE_MAX_BYTES = 48
WECHAT_DIGEST_MAX_BYTES = 120


def clean_text(value: Any) -> str:
    """Drop invalid surrogate fragments that can appear in historical model output."""
    return str(value or "").encode("utf-8", "replace").decode("utf-8")


def clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return {clean_text(key): clean_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json_value(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(clean_json_value(value), ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_utf8_stdio() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if getattr(stream, "encoding", None) and stream.encoding.lower().replace("-", "") == "utf8":
            continue
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            setattr(sys, name, io.TextIOWrapper(buffer, encoding="utf-8", errors="backslashreplace"))


def load_server_config() -> None:
    global WECHAT_APP_ID, WECHAT_APP_SECRET, WECHAT_AUTHOR
    secrets_py = SCRIPT_DIR / "wechat_draft_secrets.py"
    if secrets_py.exists():
        namespace: Dict[str, Any] = {}
        exec(secrets_py.read_text(encoding="utf-8"), namespace)
        WECHAT_APP_ID = WECHAT_APP_ID or str(namespace.get("WECHAT_APP_ID", ""))
        WECHAT_APP_SECRET = WECHAT_APP_SECRET or str(namespace.get("WECHAT_APP_SECRET", ""))
        WECHAT_AUTHOR = str(namespace.get("WECHAT_AUTHOR", WECHAT_AUTHOR))

    config_json = SCRIPT_DIR / "wechat_draft_config.json"
    if config_json.exists():
        data = json.loads(config_json.read_text(encoding="utf-8"))
        WECHAT_APP_ID = WECHAT_APP_ID or str(data.get("WECHAT_APP_ID", ""))
        WECHAT_APP_SECRET = WECHAT_APP_SECRET or str(data.get("WECHAT_APP_SECRET", ""))
        WECHAT_AUTHOR = str(data.get("WECHAT_AUTHOR", WECHAT_AUTHOR))


def truncate_by_bytes(text: str, max_bytes: int) -> str:
    """WeChat counts title length in UTF-8 bytes (ASCII=1, CJK/full-width=3, emoji=4) and
    rejects over-limit titles with errcode 45003. Trim on a char boundary, append ... if cut."""
    text = clean_text(text)
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    ellipsis = "..."
    budget = max_bytes - len(ellipsis.encode("utf-8"))
    out = []
    total = 0
    for ch in text:
        b = len(ch.encode("utf-8"))
        if total + b > budget:
            break
        out.append(ch)
        total += b
    return "".join(out) + ellipsis


def inline_markdown(text: str) -> str:
    escaped = html.escape(clean_text(text).strip())
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_wechat_html(md: str) -> str:
    blocks: List[str] = []
    list_items: List[str] = []

    def flush_list() -> None:
        nonlocal list_items
        if not list_items:
            return
        blocks.append(
            '<ul style="margin: 0 0 16px 1.2em; padding: 0;">'
            + "".join(f'<li style="margin: 0 0 6px 0;">{item}</li>' for item in list_items)
            + "</ul>"
        )
        list_items = []

    for raw in clean_text(md).splitlines():
        line = raw.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("!["):
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_list()
            level = len(heading.group(1))
            text = inline_markdown(heading.group(2))
            if level <= 2:
                blocks.append(f'<h2 style="font-size: 18px; font-weight: 700; margin: 28px 0 12px;">{text}</h2>')
            else:
                blocks.append(f'<p style="font-weight: 700; margin: 22px 0 10px;">{text}</p>')
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet:
            list_items.append(inline_markdown(bullet.group(1)))
            continue
        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if ordered:
            list_items.append(inline_markdown(ordered.group(1)))
            continue
        quote = re.match(r"^>\s*(.+)$", line)
        if quote:
            flush_list()
            text = inline_markdown(quote.group(1))
            blocks.append(
                '<blockquote style="margin: 18px 0; padding: 10px 14px; '
                f'border-left: 3px solid #d0d7de; color: #57606a;">{text}</blockquote>'
            )
            continue
        flush_list()
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        blocks.append(f'<p style="margin: 0 0 16px; line-height: 1.8;">{inline_markdown(line)}</p>')

    flush_list()
    return "\n".join(blocks)


def get_access_token() -> str:
    if not WECHAT_APP_ID or not WECHAT_APP_SECRET:
        raise RuntimeError("missing WECHAT_APP_ID / WECHAT_APP_SECRET on server")
    resp = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": WECHAT_APP_ID, "secret": WECHAT_APP_SECRET},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"get access_token failed: {data}")
    return str(token)


def download_cover(cover_url: str) -> Path:
    resp = requests.get(cover_url, timeout=60)
    resp.raise_for_status()
    suffix = ".jpg"
    content_type = resp.headers.get("content-type", "")
    if "png" in content_type:
        suffix = ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(resp.content)
    tmp.close()
    return Path(tmp.name)


def upload_cover(access_token: str, cover_path: Path) -> str:
    with cover_path.open("rb") as file_obj:
        resp = requests.post(
            "https://api.weixin.qq.com/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "image"},
            files={"media": (cover_path.name, file_obj, "image/jpeg")},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    media_id = data.get("media_id")
    if not media_id:
        raise RuntimeError(f"upload cover failed: {data}")
    return str(media_id)


def add_draft(access_token: str, payload: Dict[str, Any], thumb_media_id: str) -> str:
    payload = clean_json_value(payload)
    title = clean_text(payload.get("wechat_title") or payload.get("title") or "公众号文章")
    summary = clean_text(payload.get("wechat_digest") or payload.get("summary") or "")
    safe_title = truncate_by_bytes(title.strip(), WECHAT_TITLE_MAX_BYTES)
    safe_digest = truncate_by_bytes(summary.strip(), WECHAT_DIGEST_MAX_BYTES)
    print(
        "Draft title bytes: original=%d sent=%d; digest bytes: original=%d sent=%d"
        % (
            len(title.encode("utf-8")),
            len(safe_title.encode("utf-8")),
            len(summary.encode("utf-8")),
            len(safe_digest.encode("utf-8")),
        )
    )
    data = {
        "articles": [
            {
                "title": safe_title,
                "author": WECHAT_AUTHOR,
                "digest": safe_digest,
                "content": markdown_to_wechat_html(payload.get("content_md") or ""),
                "content_source_url": clean_text(payload.get("site_url") or ""),
                "thumb_media_id": thumb_media_id,
                "show_cover_pic": 1,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }
    resp = requests.post(
        "https://api.weixin.qq.com/cgi-bin/draft/add",
        params={"access_token": access_token},
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    media_id = result.get("media_id")
    if not media_id:
        raise RuntimeError(f"add draft failed: {result}")
    return str(media_id)


def iter_payloads(input_dir: Path) -> List[Path]:
    return sorted(path for path in input_dir.glob("*-draft.json") if path.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description="Push Easton Radar articles to WeChat draft box from VPS.")
    parser.add_argument("input_dir", type=Path)
    args = parser.parse_args()

    load_server_config()
    payload_paths = iter_payloads(args.input_dir)
    results_path = args.input_dir / "wechat_draft_results.json"
    if not payload_paths:
        print(f"No draft payloads found in {args.input_dir}")
        write_json(results_path, {"results": []})
        return

    results: List[Dict[str, Any]] = []
    errors: List[Exception] = []
    try:
        access_token = get_access_token()
    except Exception as exc:
        write_json(results_path, {"results": [], "error": clean_text(exc)})
        raise
    for payload_path in payload_paths:
        payload = clean_json_value(json.loads(payload_path.read_text(encoding="utf-8")))
        title = clean_text(payload.get("title") or payload_path.stem)
        wechat_title = clean_text(payload.get("wechat_title") or title)
        cover_url = clean_text(payload.get("cover_url") or "")
        if not cover_url:
            print(f"SKIP {title}: missing cover_url")
            results.append(
                {
                    "payload": payload_path.name,
                    "title": title,
                    "wechat_title": wechat_title,
                    "status": "skipped",
                    "reason": "missing cover_url",
                }
            )
            continue
        cover_path = download_cover(cover_url)
        try:
            thumb_media_id = upload_cover(access_token, cover_path)
            draft_media_id = add_draft(access_token, payload, thumb_media_id)
            print(f"OK {clean_text(title)}: {draft_media_id}")
            results.append(
                {
                    "payload": payload_path.name,
                    "title": title,
                    "wechat_title": wechat_title,
                    "status": "ok",
                    "draft_media_id": draft_media_id,
                }
            )
        except Exception as exc:
            print(f"FAIL {clean_text(title)}: {clean_text(exc)}")
            results.append(
                {
                    "payload": payload_path.name,
                    "title": title,
                    "wechat_title": wechat_title,
                    "status": "failed",
                    "error": clean_text(exc),
                }
            )
            errors.append(exc)
        finally:
            try:
                cover_path.unlink()
            except OSError:
                pass
    write_json(results_path, {"results": results})
    if errors:
        raise errors[0]


if __name__ == "__main__":
    ensure_utf8_stdio()
    main()

#!/usr/bin/env python3
"""Sync @NekoStranding recent & pinned X posts into assets/x-recent.json and index.html fallback."""

from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import re
import sys
import urllib.request

HANDLE = "NekoStranding"
DEFAULT_PINNED_ID = "2042286373609365593"
ROOT = pathlib.Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "assets" / "x-recent.json"
INDEX_PATH = ROOT / "index.html"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> bytes:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def discover_profile_status_ids(handle: str) -> tuple[str, list[str]]:
    """Return (pinned_id, chronological_recent_ids) from X profile via Jina Reader."""
    raw = ""
    for hdrs in (
        {"X-Return-Format": "html", "X-No-Cache": "true"},
        {"X-Return-Format": "html"},
        {},
    ):
        try:
            raw = http_get(
                f"https://r.jina.ai/https://x.com/{handle}",
                headers=hdrs,
                timeout=25,
            ).decode("utf-8", errors="replace")
            if f"/{handle}/status/" in raw or f"/{handle.lower()}/status/" in raw.lower():
                break
        except Exception:
            continue

    pattern = re.compile(rf"/{re.escape(handle)}/status/(\d+)", re.IGNORECASE)
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(raw):
        tid = match.group(1)
        if tid not in seen:
            seen.add(tid)
            ordered_ids.append(tid)

    if not ordered_ids:
        raise RuntimeError("No status IDs discovered from profile page")

    # If the first status on the profile is older than any later status, it is the Pinned post
    if len(ordered_ids) >= 2 and int(ordered_ids[0]) < max(int(x) for x in ordered_ids[1:]):
        pinned_id = ordered_ids[0]
        rest = ordered_ids[1:]
    else:
        pinned_id = DEFAULT_PINNED_ID
        rest = [tid for tid in ordered_ids if tid != pinned_id]

    recent_ids = sorted(rest, key=lambda x: int(x), reverse=True)
    return pinned_id, recent_ids[:4]


def clean_tweet_text(text: str) -> str:
    """Strip trailing t.co media shortlinks while preserving normal text."""
    if not text:
        return ""
    cleaned = re.sub(r"\s*https://t\.co/[A-Za-z0-9]+\s*$", "", text.strip())
    return cleaned.strip()


def format_date_label(created_timestamp: int | None, created_at: str | None) -> str:
    if created_timestamp:
        d = dt.datetime.fromtimestamp(created_timestamp, tz=dt.timezone.utc)
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    if created_at:
        try:
            d = dt.datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
            return f"{d.strftime('%b')} {d.day}, {d.year}"
        except ValueError:
            pass
    return "Recent"


def extract_media(media_obj: dict | None) -> dict | None:
    if not media_obj:
        return None
    items = media_obj.get("all") or []
    if not items:
        return None
    first = items[0]
    mtype = first.get("type", "photo")
    if mtype in ("video", "gif"):
        thumb = first.get("thumbnail_url") or ""
        if "pbs.twimg.com" in thumb and "?" not in thumb:
            thumb = f"{thumb}?format=jpg&name=medium"
        return {
            "type": "video",
            "thumb_url": thumb,
            "video_url": first.get("url") or "",
            "width": first.get("width"),
            "height": first.get("height"),
        }
    url = first.get("url") or ""
    if "pbs.twimg.com/media/" in url:
        base = url.split("?")[0]
        url = f"{base}?name=medium"
    return {
        "type": "photo",
        "thumb_url": url,
        "width": first.get("width"),
        "height": first.get("height"),
    }


def fetch_normalized_tweet(handle: str, tid: str) -> dict:
    raw = http_get(f"https://api.fxtwitter.com/{handle}/status/{tid}", timeout=15)
    payload = json.loads(raw.decode("utf-8"))
    t = payload.get("tweet") or {}
    author = t.get("author") or {}

    quote_data = None
    q = t.get("quote")
    if q:
        q_author = q.get("author") or {}
        q_handle = q_author.get("screen_name") or ""
        q_id = q.get("id") or ""
        quote_data = {
            "id": q_id,
            "url": q.get("url") or (f"https://x.com/{q_handle}/status/{q_id}" if q_handle and q_id else ""),
            "author_name": q_author.get("name") or q_handle,
            "author_handle": q_handle,
            "text": clean_tweet_text(q.get("text") or ""),
            "media": extract_media(q.get("media")),
        }

    created_ts = t.get("created_timestamp")
    created_at = t.get("created_at")
    return {
        "id": str(t.get("id") or tid),
        "url": t.get("url") or f"https://x.com/{handle}/status/{tid}",
        "author_name": author.get("name") or "毒猫猫 | 量化摸鱼师",
        "author_handle": author.get("screen_name") or handle,
        "created_at": created_at,
        "created_timestamp": created_ts,
        "date_label": format_date_label(created_ts, created_at),
        "text": clean_tweet_text(t.get("text") or ""),
        "media": extract_media(t.get("media")),
        "quote": quote_data,
        "likes": t.get("likes") or 0,
        "retweets": t.get("retweets") or 0,
        "replies": t.get("replies") or 0,
    }


def render_paragraphs(text: str) -> str:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if not blocks:
        return ""
    out: list[str] = []
    for block in blocks:
        escaped = html.escape(block).replace("\n", "<br>")
        escaped = re.sub(
            r"(https?://[^\s<]+)",
            r'<a href="\1" target="_blank" rel="noopener">\1</a>',
            escaped,
        )
        out.append(f"<p>{escaped}</p>")
    return "\n            ".join(out)


def render_quote_box(quote: dict | None, show_media: bool = True) -> str:
    if not quote:
        return ""
    q_url = html.escape(quote.get("url") or f"https://x.com/{HANDLE}")
    q_name = html.escape(quote.get("author_name") or "")
    q_handle = html.escape(quote.get("author_handle") or "")
    q_text = html.escape(quote.get("text") or "").replace("\n", "<br>")
    q_media = quote.get("media") if show_media else None
    media_html = ""
    if q_media and q_media.get("thumb_url"):
        m_url = html.escape(q_media["thumb_url"])
        media_html = (
            f'\n              <div class="quote-media">'
            f'<img src="{m_url}" alt="Quoted media" loading="lazy">'
            f"</div>"
        )
    text_html = f'\n              <p class="quote-text">{q_text}</p>' if q_text else ""
    return (
        f'\n            <a class="tweet-quote" href="{q_url}" target="_blank" rel="noopener">'
        f'\n              <div class="quote-head">'
        f'<span class="quote-author">{q_name}</span>'
        f'<span class="quote-handle">@{q_handle}</span>'
        f"</div>"
        f"{text_html}"
        f"{media_html}"
        f"\n            </a>"
    )


def render_latest_card(recent: list[dict]) -> str:
    latest = recent[0]
    url = html.escape(latest["url"])
    author_name = html.escape(latest["author_name"])
    badge = f"Latest · {html.escape(latest['date_label'])}"

    media_html = ""
    if latest.get("media") and latest["media"].get("thumb_url"):
        m_url = html.escape(latest["media"]["thumb_url"])
        media_html = (
            f'\n          <a class="preview-frame preview-frame-x" href="{url}" target="_blank" rel="noopener" aria-label="View post on X">'
            f'\n            <img src="{m_url}" alt="Post media on X" loading="lazy">'
            f"\n          </a>\n"
        )

    has_own_media = bool(latest.get("media") and latest["media"].get("thumb_url"))
    body_html = render_paragraphs(latest.get("text") or "")
    quote_html = render_quote_box(latest.get("quote"), show_media=not has_own_media)

    # If the top post has no direct image and no quote image, include the next recent post
    # so the card has rich visual density and matches the Pinned card height cleanly.
    has_visual = bool(
        has_own_media
        or (latest.get("quote") and latest["quote"].get("media"))
    )
    secondary_html = ""
    quoted_id = (latest.get("quote") or {}).get("id")
    prev_candidates = [item for item in recent[1:] if item.get("id") != quoted_id]
    if not has_visual and prev_candidates:
        prev = prev_candidates[0]
        prev_url = html.escape(prev["url"])
        prev_date = html.escape(prev["date_label"])
        prev_body = render_paragraphs(prev.get("text") or "")
        prev_quote = render_quote_box(prev.get("quote"), show_media=True)
        secondary_html = (
            f'\n            <div class="tweet-secondary">'
            f'\n              <div class="tweet-secondary-meta">'
            f'<a href="{prev_url}" target="_blank" rel="noopener">Earlier · {prev_date} ↗</a>'
            f"</div>"
            f"\n              {prev_body}"
            f"{prev_quote}"
            f"\n            </div>"
        )

    return f"""        <!-- Latest X Post Card -->
        <article class="surface-card" id="x-card-latest">
          <div class="card-head">
            <img class="app-icon app-icon-round" src="assets/avatar.jpg" alt="@NekoStranding" width="42" height="42">
            <div class="card-title-group">
              <div class="card-title-row">
                <h3><a href="{url}" target="_blank" rel="noopener">{author_name}</a></h3>
                <span class="badge">{badge}</span>
              </div>
              <p class="card-tagline">@NekoStranding on X</p>
            </div>
          </div>
{media_html}          <div class="tweet-body">
            {body_html}{quote_html}{secondary_html}
          </div>

          <div class="card-actions">
            <a class="btn btn-outline" href="{url}" target="_blank" rel="noopener">View Post on X</a>
            <a class="btn btn-ghost" href="https://x.com/NekoStranding" target="_blank" rel="noopener">Follow @NekoStranding →</a>
          </div>
        </article>"""


def render_pinned_card(pinned: dict) -> str:
    url = html.escape(pinned["url"])
    author_name = html.escape(pinned["author_name"])
    is_default_vibe = pinned.get("id") == DEFAULT_PINNED_ID
    thumb_src = (
        "assets/x-pinned-thumb.jpg"
        if is_default_vibe
        else (
            html.escape(pinned["media"]["thumb_url"])
            if (pinned.get("media") and pinned["media"].get("thumb_url"))
            else ""
        )
    )
    badge_label = (
        "Pinned · Vibe99 Preview"
        if is_default_vibe
        else f"Pinned · {html.escape(pinned.get('date_label') or 'Recent')}"
    )
    media_html = ""
    if thumb_src:
        aria_label = "Watch Vibe99 preview video on X" if is_default_vibe else "View pinned post on X"
        alt_text = "Vibe99 preview demo on X" if is_default_vibe else "Pinned post media on X"
        media_html = (
            f'\n          <a class="preview-frame preview-frame-x" href="{url}" target="_blank" rel="noopener" aria-label="{aria_label}">'
            f'\n            <img src="{thumb_src}" alt="{alt_text}" loading="lazy">'
            f"\n          </a>\n"
        )

    body_html = render_paragraphs(pinned.get("text") or "")
    quote_html = render_quote_box(pinned.get("quote"), show_media=not bool(thumb_src))
    primary_cta = "Watch Video on X" if is_default_vibe else "View Post on X"

    return f"""        <!-- Pinned X Post Card -->
        <article class="surface-card" id="x-card-pinned">
          <div class="card-head">
            <img class="app-icon app-icon-round" src="assets/avatar.jpg" alt="@NekoStranding" width="42" height="42">
            <div class="card-title-group">
              <div class="card-title-row">
                <h3><a href="{url}" target="_blank" rel="noopener">{author_name}</a></h3>
                <span class="badge">{badge_label}</span>
              </div>
              <p class="card-tagline">@NekoStranding on X</p>
            </div>
          </div>
{media_html}
          <div class="tweet-body">
            {body_html}{quote_html}
          </div>

          <div class="card-actions">
            <a class="btn btn-outline" href="{url}" target="_blank" rel="noopener">{primary_cta}</a>
            <a class="btn btn-ghost" href="https://github.com/NekoApocalypse/Vibe99/releases">Download Vibe99 →</a>
          </div>
        </article>"""


def _content_fingerprint(payload: dict) -> dict:
    """Return a copy of payload with volatile engagement/timestamp fields stripped."""
    def _strip_tweet(t: dict | None) -> dict | None:
        if not t:
            return None
        return {
            k: v
            for k, v in t.items()
            if k not in ("likes", "retweets", "replies")
        }

    return {
        "handle": payload.get("handle"),
        "latest": _strip_tweet(payload.get("latest")),
        "recent": [_strip_tweet(r) for r in (payload.get("recent") or [])],
        "pinned": _strip_tweet(payload.get("pinned")),
    }


def main() -> int:
    pinned_id, recent_ids = discover_profile_status_ids(HANDLE)
    if not recent_ids:
        print("No recent tweet IDs found", file=sys.stderr)
        return 1

    prev_data: dict | None = None
    if JSON_PATH.exists():
        try:
            prev_data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev_data = None

    prev_latest_id = int(((prev_data or {}).get("latest") or {}).get("id") or 0)
    if prev_latest_id > int(recent_ids[0]):
        print(
            f"Keeping existing newer snapshot {prev_latest_id} > discovered {recent_ids[0]}"
        )
        return 0

    pinned = fetch_normalized_tweet(HANDLE, pinned_id)
    recent = [fetch_normalized_tweet(HANDLE, tid) for tid in recent_ids[:3]]

    data = {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "handle": HANDLE,
        "latest": recent[0],
        "recent": recent,
        "pinned": pinned,
    }

    html_changed = False
    if INDEX_PATH.exists():
        index_html = INDEX_PATH.read_text(encoding="utf-8")
        cards_block = (
            "<!-- BEGIN_X_RECENT_CARDS -->\n"
            f"{render_latest_card(recent)}\n\n"
            f"{render_pinned_card(pinned)}\n"
            "        <!-- END_X_RECENT_CARDS -->"
        )
        new_html, count = re.subn(
            r"<!-- BEGIN_X_RECENT_CARDS -->.*?<!-- END_X_RECENT_CARDS -->",
            cards_block,
            index_html,
            flags=re.DOTALL,
        )
        if count and new_html != index_html:
            INDEX_PATH.write_text(new_html, encoding="utf-8")
            html_changed = True

    json_changed = (
        prev_data is None
        or _content_fingerprint(prev_data) != _content_fingerprint(data)
    )
    if json_changed or html_changed:
        JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"Synced @NekoStranding: latest={recent[0]['id']} ({recent[0]['date_label']}), pinned={pinned['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

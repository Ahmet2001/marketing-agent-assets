"""[MODE: HYBRID — Browser + Official API] TikTok toolbox.

The tools use the application's shared Selenium session.  They intentionally
do not try to bypass TikTok login, CAPTCHA, rate limits, or other protections:
sign in normally in the opened browser before using actions that require an
account.

Official API tools use TikTok's Content Posting and Display APIs at
``open.tiktokapis.com``. Set ``TIKTOK_ACCESS_TOKEN`` to a user OAuth token.
The authorized scopes determine which operations are available: ``user.info.*``
for profile data, ``video.list`` for video metadata, ``video.publish`` for
direct posts, and ``video.upload`` for inbox drafts.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

import requests
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from ..araclar.browser_araclari import (
    _get_driver,
    _human_click,
    _type_into_element,
    browser_baslat,
    browser_kapat,
    get_browser_runtime_state,
)

# Browser tools use the normal logged-in Selenium session. API tools use a
# TikTok OAuth user access token and only call documented TikTok endpoints.
TOOLBOX_ACCESS_MODE = "hybrid"


_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SOCIAL_DIR = os.path.join(_APP_ROOT, "workspace", "social")
_SNAPSHOT_PATH = os.path.join(_SOCIAL_DIR, "tiktok_feed_snapshot.json")
_TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,24}$")
_VIDEO_RE = re.compile(r"/@[A-Za-z0-9._]+/video/(\d+)", re.I)
_DEFAULT_TIKTOK_API_BASE_URL = "https://open.tiktokapis.com"
_DEFAULT_TIKTOK_API_TIMEOUT = 30
_DEFAULT_TIKTOK_CHUNK_SIZE = 10 * 1024 * 1024


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limit(value: Any, default: int = 20, maximum: int = 100) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _compact(value: Any, limit: int = 800) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _normalize_handle(value: str) -> str:
    text = str(value or "").strip()
    if "://" in text:
        parsed = urlparse(text)
        if (parsed.hostname or "").lower() not in _TIKTOK_HOSTS:
            raise ValueError("Only TikTok profile URLs are accepted.")
        parts = [part for part in parsed.path.split("/") if part]
        text = parts[0] if parts else ""
    text = text.lstrip("@").strip("/")
    if not _HANDLE_RE.fullmatch(text):
        raise ValueError("A valid TikTok handle is required.")
    return text


def _normalize_url(value: str, *, require_video: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("A TikTok URL is required.")
    if text.startswith("/"):
        text = f"https://www.tiktok.com{text}"
    parsed = urlparse(text)
    if (parsed.hostname or "").lower() not in _TIKTOK_HOSTS:
        raise ValueError("Only tiktok.com URLs are accepted.")
    if require_video and not _VIDEO_RE.search(parsed.path):
        raise ValueError("A TikTok video URL is required.")
    return text


def _video_id(video_url: str) -> str:
    match = _VIDEO_RE.search(urlparse(_normalize_url(video_url, require_video=True)).path)
    if not match:
        raise ValueError("Could not determine the TikTok video ID.")
    return match.group(1)


def _page_ready(driver) -> bool:
    try:
        return driver.execute_script(
            "return document.readyState !== 'loading' && !!document.querySelector('main, [data-e2e], #app');"
        )
    except Exception:
        return False


def _open(url: str, timeout: int = 20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_page_ready)
    except TimeoutException:
        pass
    return driver


def _visible(driver, selectors: tuple[str, ...]):
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                continue
    return None


def _control(driver, markers: tuple[str, ...]):
    wanted = tuple(marker.casefold() for marker in markers)
    for element in driver.find_elements(By.CSS_SELECTOR, "button, [role='button'], a"):
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue
            label = " ".join((element.text or "", element.get_attribute("aria-label") or "", element.get_attribute("title") or "")).casefold()
            if any(marker in label for marker in wanted):
                return element
        except Exception:
            continue
    return None


def _videos(driver, limit: int) -> list[dict[str, Any]]:
    rows = driver.execute_script(
        r"""
        const max = arguments[0], seen = new Set(), result = [];
        for (const link of document.querySelectorAll("a[href*='/video/']")) {
          if (result.length >= max) break;
          const href = link.href || link.getAttribute('href') || '';
          const match = href.match(/@([^/]+)\/video\/(\d+)/i);
          if (!match || seen.has(match[2])) continue;
          seen.add(match[2]);
          const root = link.closest("[data-e2e*='item'], article") || link.parentElement || link;
          const image = root.querySelector('img');
          const text = (root.innerText || root.textContent || '').trim();
          result.push({ video_id: match[2], author: match[1], url: href,
            caption: text.slice(0, 1200), thumbnail_url: image?.currentSrc || image?.src || '' });
        }
        return result;
        """,
        _limit(limit),
    ) or []
    return [{**row, "caption": _compact(row.get("caption"), 1200)} for row in rows]


def get_tiktok_browser_status() -> dict[str, Any]:
    """Return shared-browser state and whether it is currently on TikTok."""
    state = get_browser_runtime_state()
    if not state.get("ready"):
        return {**state, "platform": "tiktok", "on_tiktok": False, "url": ""}
    driver = _get_driver()
    url = str(driver.current_url or "")
    return {**state, "platform": "tiktok", "on_tiktok": (urlparse(url).hostname or "").lower() in _TIKTOK_HOSTS, "url": url, "title": str(driver.title or "")}


def launch_tiktok_browser(headless: bool = False) -> dict[str, Any]:
    """Launch the shared browser and open TikTok's For You page."""
    browser_baslat(headless=headless)
    _open("https://www.tiktok.com/foryou")
    return get_tiktok_browser_status()


def close_tiktok_browser() -> str:
    """Close the shared browser session."""
    return browser_kapat()


def open_tiktok_page(destination: str = "foryou", query: str = "", handle: str = "", video_url: str = "") -> dict[str, Any]:
    """Open a TikTok feed, search, profile, video, inbox, or upload page."""
    destination = str(destination or "foryou").strip().lower()
    if destination in {"foryou", "for_you", "feed"}:
        url = "https://www.tiktok.com/foryou"
    elif destination == "following":
        url = "https://www.tiktok.com/following"
    elif destination == "search":
        if not str(query or "").strip():
            raise ValueError("query is required for a TikTok search.")
        url = f"https://www.tiktok.com/search?q={quote_plus(query.strip())}"
    elif destination == "profile":
        url = f"https://www.tiktok.com/@{quote(_normalize_handle(handle), safe='')}"
    elif destination == "video":
        url = _normalize_url(video_url, require_video=True)
    elif destination == "inbox":
        url = "https://www.tiktok.com/messages"
    elif destination == "upload":
        url = "https://www.tiktok.com/tiktokstudio/upload"
    else:
        raise ValueError("destination must be foryou, following, search, profile, video, inbox, or upload.")
    driver = _open(url)
    return {"status": "opened", "destination": destination, "url": str(driver.current_url or url)}


def scan_tiktok_videos(limit: int = 20) -> dict[str, Any]:
    """Extract visible TikTok video cards from the current page."""
    driver = _get_driver()
    videos = _videos(driver, limit)
    return {"status": "ok", "url": str(driver.current_url or ""), "count": len(videos), "videos": videos}


def snapshot_tiktok_feed(destination: str = "foryou", query: str = "", limit: int = 20) -> dict[str, Any]:
    """Open a feed/search page and save its visible-video snapshot to workspace."""
    opened = open_tiktok_page(destination=destination, query=query)
    snapshot = {"captured_at": _now(), **opened, **scan_tiktok_videos(limit)}
    os.makedirs(_SOCIAL_DIR, exist_ok=True)
    with open(_SNAPSHOT_PATH, "w", encoding="utf-8") as output:
        json.dump(snapshot, output, ensure_ascii=False, indent=2)
    return {**snapshot, "snapshot_path": _SNAPSHOT_PATH}


def search_tiktok_videos(query: str, limit: int = 20) -> dict[str, Any]:
    """Search TikTok and return visible matching videos."""
    open_tiktok_page(destination="search", query=query)
    return {"query": query.strip(), **scan_tiktok_videos(limit)}


def inspect_tiktok_profile(handle: str, limit: int = 20) -> dict[str, Any]:
    """Open a profile and return visible profile text plus recent videos."""
    user = _normalize_handle(handle)
    driver = _open(f"https://www.tiktok.com/@{quote(user, safe='')}")
    profile_text = _compact(driver.execute_script("return document.querySelector('main')?.innerText || document.body?.innerText || ''"), 3000)
    return {"status": "ok", "handle": user, "url": str(driver.current_url or ""), "profile_text": profile_text, "videos": _videos(driver, limit)}


def inspect_tiktok_video(video_url: str) -> dict[str, Any]:
    """Open a TikTok video and return its visible text and metadata."""
    target = _normalize_url(video_url, require_video=True)
    driver = _open(target)
    return {"status": "ok", "video_id": _video_id(target), "url": str(driver.current_url or target), "title": str(driver.title or ""), "text": _compact(driver.execute_script("return document.querySelector('main')?.innerText || document.body?.innerText || ''"), 4000)}


def _video_action(video_url: str, action: str, markers: tuple[str, ...]) -> dict[str, Any]:
    driver = _open(_normalize_url(video_url, require_video=True))
    control = _control(driver, markers)
    if not control:
        return {"status": "not_found", "action": action, "video_id": _video_id(video_url), "error": "Could not locate the TikTok control. Sign in if required."}
    _human_click(driver, control)
    time.sleep(0.5)
    return {"status": "ok", "action": action, "video_id": _video_id(video_url), "url": str(driver.current_url or "")}


def like_tiktok_video(video_url: str) -> dict[str, Any]:
    return _video_action(video_url, "like", ("like", "beğen"))


def unlike_tiktok_video(video_url: str) -> dict[str, Any]:
    return _video_action(video_url, "unlike", ("unlike", "remove like", "beğenmekten vazgeç"))


def follow_tiktok_account(handle: str) -> dict[str, Any]:
    user = _normalize_handle(handle)
    driver = _open(f"https://www.tiktok.com/@{quote(user, safe='')}")
    control = _control(driver, ("follow", "takip et"))
    if not control:
        return {"status": "not_found", "handle": user, "error": "Could not locate a Follow control."}
    _human_click(driver, control)
    return {"status": "ok", "action": "follow", "handle": user}


def unfollow_tiktok_account(handle: str) -> dict[str, Any]:
    user = _normalize_handle(handle)
    driver = _open(f"https://www.tiktok.com/@{quote(user, safe='')}")
    control = _control(driver, ("following", "unfollow", "takip ediliyor", "takiptesin"))
    if not control:
        return {"status": "not_found", "handle": user, "error": "Could not locate a Following control."}
    _human_click(driver, control)
    return {"status": "ok", "action": "unfollow", "handle": user}


def comment_tiktok_video(video_url: str, message: str) -> dict[str, Any]:
    """Post a comment through the normal logged-in TikTok browser session."""
    text = str(message or "").strip()
    if not text:
        raise ValueError("A non-empty comment message is required.")
    driver = _open(_normalize_url(video_url, require_video=True))
    box = _visible(driver, ("[data-e2e='comment-input']", "div[contenteditable='true'][data-e2e*='comment']", "textarea[placeholder*='comment' i]"))
    if not box:
        trigger = _control(driver, ("comment", "yorum"))
        if trigger:
            _human_click(driver, trigger)
            box = _visible(driver, ("[data-e2e='comment-input']", "div[contenteditable='true']", "textarea"))
    if not box:
        return {"status": "not_found", "error": "Could not locate the comment editor. Sign in if required."}
    _type_into_element(driver, box, text)
    submit = _control(driver, ("post", "send", "comment", "yorum yap", "gönder"))
    if submit:
        _human_click(driver, submit)
    else:
        box.send_keys(Keys.CONTROL, Keys.ENTER)
    return {"status": "submitted", "video_id": _video_id(video_url), "message": text}


def publish_tiktok_video(video_path: str, caption: str = "", submit: bool = False) -> dict[str, Any]:
    """Upload a local video to TikTok Studio; set ``submit=True`` to publish.

    The default only prepares the upload and caption, providing a deliberate
    human-review checkpoint before the irreversible publish action.
    """
    path = os.path.abspath(os.path.expanduser(str(video_path or "")))
    if not os.path.isfile(path):
        raise ValueError("video_path must point to an existing local video file.")
    driver = _open("https://www.tiktok.com/tiktokstudio/upload", timeout=30)
    upload = _visible(driver, ("input[type='file']", "input[data-e2e*='upload']"))
    if not upload:
        return {"status": "not_found", "error": "Could not locate TikTok Studio's file input. Sign in and complete any prompts."}
    upload.send_keys(path)
    if caption.strip():
        editor = _visible(driver, ("div[contenteditable='true']", "textarea"))
        if editor:
            _type_into_element(driver, editor, caption.strip())
    if not submit:
        return {"status": "draft_ready", "video_path": path, "caption": caption.strip(), "message": "Upload prepared. Review it in TikTok Studio, then call again with submit=True to publish."}
    publish = _control(driver, ("post", "publish", "share", "paylaş", "yayınla"))
    if not publish:
        return {"status": "ready_to_publish", "video_path": path, "error": "Upload is prepared but the Publish button was not found."}
    _human_click(driver, publish)
    return {"status": "submitted", "video_path": path, "caption": caption.strip()}


def _tiktok_api_token() -> str:
    return (os.getenv("TIKTOK_ACCESS_TOKEN") or os.getenv("TIKTOK_API_ACCESS_TOKEN") or "").strip()


def _tiktok_api_base_url() -> str:
    return (os.getenv("TIKTOK_API_BASE_URL") or _DEFAULT_TIKTOK_API_BASE_URL).strip().rstrip("/")


def _tiktok_api_timeout() -> int:
    try:
        return max(5, min(int(os.getenv("TIKTOK_API_TIMEOUT", _DEFAULT_TIKTOK_API_TIMEOUT)), 120))
    except (TypeError, ValueError):
        return _DEFAULT_TIKTOK_API_TIMEOUT


def _tiktok_api_error(message: str, *, endpoint: str = "", status_code: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "status": "error", "error": message}
    if endpoint:
        result["endpoint"] = endpoint
    if status_code is not None:
        result["status_code"] = status_code
    return result


def _tiktok_api_request(
    method: str,
    endpoint: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = _tiktok_api_token()
    if not token:
        return _tiktok_api_error(
            "TikTok API access token is not configured. Set TIKTOK_ACCESS_TOKEN.",
            endpoint=endpoint,
        )
    normalized_endpoint = "/" + endpoint.lstrip("/")
    try:
        response = requests.request(
            method.upper(),
            f"{_tiktok_api_base_url()}{normalized_endpoint}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            params=params,
            json=payload,
            timeout=_tiktok_api_timeout(),
        )
    except requests.RequestException as exc:
        return _tiktok_api_error(f"TikTok API request failed: {exc}", endpoint=normalized_endpoint)
    try:
        body = response.json()
    except ValueError:
        body = {"raw_response": _compact(response.text, 1000)}
    api_error = body.get("error") if isinstance(body, dict) else None
    api_code = api_error.get("code") if isinstance(api_error, dict) else ""
    ok = response.ok and api_code in {"", "ok"}
    result = {
        "ok": ok,
        "status": "ok" if ok else "error",
        "status_code": response.status_code,
        "endpoint": normalized_endpoint,
        "response": body,
    }
    if not ok:
        result["error"] = (
            api_error.get("message") if isinstance(api_error, dict) else ""
        ) or f"TikTok API returned HTTP {response.status_code}."
    return result


def get_tiktok_api_status(verify_token: bool = False) -> dict[str, Any]:
    """Report API configuration without exposing credential values.

    Set ``verify_token=True`` to call the official User Info endpoint. The
    token needs at least the ``user.info.basic`` scope for verification.
    """
    result = {
        "configured": bool(_tiktok_api_token()),
        "api_base_url": _tiktok_api_base_url(),
        "timeout_seconds": _tiktok_api_timeout(),
        "required_scopes": {
            "profile": "user.info.basic (plus user.info.profile/user.info.stats for extra fields)",
            "videos": "video.list",
            "direct_post": "video.publish",
            "inbox_draft": "video.upload",
        },
    }
    if verify_token and result["configured"]:
        result["verification"] = get_tiktok_api_user_info("open_id,display_name")
    return result


def get_tiktok_api_user_info(
    fields: str = "open_id,avatar_url,display_name",
) -> dict[str, Any]:
    """Get the authorized user's profile through TikTok's official API."""
    if not str(fields or "").strip():
        raise ValueError("At least one user-info field is required.")
    return _tiktok_api_request("GET", "/v2/user/info/", params={"fields": fields.strip()})


def list_tiktok_api_videos(
    fields: str = "id,title,video_description,duration,cover_image_url,share_url,create_time,view_count,like_count,comment_count,share_count",
    cursor: int = 0,
    max_count: int = 20,
) -> dict[str, Any]:
    """List the authorized user's public videos (requires ``video.list``)."""
    if not str(fields or "").strip():
        raise ValueError("At least one video field is required.")
    return _tiktok_api_request(
        "POST",
        "/v2/video/list/",
        params={"fields": fields.strip()},
        payload={"cursor": max(0, int(cursor)), "max_count": _limit(max_count, default=20, maximum=20)},
    )


def get_tiktok_api_creator_info() -> dict[str, Any]:
    """Get current creator settings before a Direct Post (``video.publish``)."""
    return _tiktok_api_request("POST", "/v2/post/publish/creator_info/query/", payload={})


def get_tiktok_api_post_status(publish_id: str) -> dict[str, Any]:
    """Get Content Posting API processing status for a publish/upload ID."""
    if not str(publish_id or "").strip():
        raise ValueError("publish_id is required.")
    return _tiktok_api_request(
        "POST", "/v2/post/publish/status/fetch/", payload={"publish_id": publish_id.strip()}
    )


def _tiktok_video_source(path: str, chunk_size: int) -> tuple[str, int, int, int]:
    absolute_path = os.path.abspath(os.path.expanduser(str(path or "")))
    if not os.path.isfile(absolute_path):
        raise ValueError("video_path must point to an existing local video file.")
    size = os.path.getsize(absolute_path)
    if size <= 0:
        raise ValueError("video_path must not be empty.")
    chunk_size = max(1, min(int(chunk_size), 64 * 1024 * 1024))
    return absolute_path, size, chunk_size, math.ceil(size / chunk_size)


def init_tiktok_api_video_post(
    video_path: str,
    title: str,
    privacy_level: str = "SELF_ONLY",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    video_cover_timestamp_ms: int = 0,
    chunk_size: int = _DEFAULT_TIKTOK_CHUNK_SIZE,
) -> dict[str, Any]:
    """Initialize an official Direct Post upload (requires ``video.publish``).

    Call :func:`get_tiktok_api_creator_info` first and use one of the returned
    ``privacy_level_options``. The creator must have explicitly approved the
    post metadata before calling this action.
    """
    path, size, chunk_size, chunks = _tiktok_video_source(video_path, chunk_size)
    if len(str(title or "").encode("utf-16-le")) // 2 > 2200:
        raise ValueError("TikTok video title/caption must not exceed 2200 UTF-16 characters.")
    response = _tiktok_api_request(
        "POST",
        "/v2/post/publish/video/init/",
        payload={
            "post_info": {
                "title": str(title or ""),
                "privacy_level": privacy_level,
                "disable_comment": bool(disable_comment),
                "disable_duet": bool(disable_duet),
                "disable_stitch": bool(disable_stitch),
                "video_cover_timestamp_ms": max(0, int(video_cover_timestamp_ms)),
            },
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": chunks},
        },
    )
    if response.get("ok"):
        response["video_path"] = path
        response["video_size"] = size
        response["chunk_size"] = chunk_size
    return response


def upload_tiktok_api_video_file(video_path: str, upload_url: str, chunk_size: int = _DEFAULT_TIKTOK_CHUNK_SIZE) -> dict[str, Any]:
    """Transfer a local video to the one-hour TikTok upload URL from init."""
    path, total_size, chunk_size, _ = _tiktok_video_source(video_path, chunk_size)
    if not str(upload_url or "").startswith("https://"):
        raise ValueError("upload_url must be the HTTPS URL returned by TikTok's init endpoint.")
    media_type = mimetypes.guess_type(path)[0] or "video/mp4"
    uploaded = 0
    try:
        with open(path, "rb") as file_handle:
            while uploaded < total_size:
                chunk = file_handle.read(min(chunk_size, total_size - uploaded))
                end = uploaded + len(chunk) - 1
                response = requests.put(
                    upload_url,
                    headers={
                        "Content-Type": media_type,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {uploaded}-{end}/{total_size}",
                    },
                    data=chunk,
                    timeout=_tiktok_api_timeout(),
                )
                if response.status_code not in {200, 201, 206}:
                    return _tiktok_api_error(
                        f"TikTok upload returned HTTP {response.status_code}: {_compact(response.text, 500)}",
                        endpoint="upload_url",
                        status_code=response.status_code,
                    )
                uploaded += len(chunk)
    except OSError as exc:
        return _tiktok_api_error(f"Could not read local video: {exc}", endpoint="upload_url")
    except requests.RequestException as exc:
        return _tiktok_api_error(f"TikTok video upload failed: {exc}", endpoint="upload_url")
    return {"ok": True, "status": "uploaded", "video_path": path, "uploaded_bytes": uploaded, "total_bytes": total_size}


def publish_tiktok_api_video(
    video_path: str,
    title: str,
    privacy_level: str = "SELF_ONLY",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    video_cover_timestamp_ms: int = 0,
    chunk_size: int = _DEFAULT_TIKTOK_CHUNK_SIZE,
) -> dict[str, Any]:
    """Initialize and transfer a Direct Post video using TikTok's official API.

    TikTok processes the post asynchronously; use the returned ``publish_id``
    with :func:`get_tiktok_api_post_status` to learn the final outcome.
    """
    creator_info = get_tiktok_api_creator_info()
    if not creator_info.get("ok"):
        return {"status": "creator_info_failed", "creator_info": creator_info}
    creator_data = creator_info.get("response", {}).get("data", {})
    privacy_options = creator_data.get("privacy_level_options") or []
    if privacy_options and privacy_level not in privacy_options:
        return {
            "status": "invalid_privacy_level",
            "creator_info": creator_info,
            "error": f"privacy_level must be one of the creator's options: {', '.join(privacy_options)}",
        }
    initiated = init_tiktok_api_video_post(video_path, title, privacy_level, disable_comment, disable_duet, disable_stitch, video_cover_timestamp_ms, chunk_size)
    if not initiated.get("ok"):
        return {"status": "init_failed", "creator_info": creator_info, "init": initiated}
    data = initiated.get("response", {}).get("data", {})
    upload_url = str(data.get("upload_url") or "")
    publish_id = str(data.get("publish_id") or "")
    if not upload_url:
        return {"status": "init_failed", "creator_info": creator_info, "init": initiated, "error": "TikTok did not return an upload URL."}
    uploaded = upload_tiktok_api_video_file(video_path, upload_url, chunk_size)
    return {"status": "uploaded" if uploaded.get("ok") else "upload_failed", "publish_id": publish_id, "creator_info": creator_info, "init": initiated, "upload": uploaded}


TIKTOK_TOOLS = [
    get_tiktok_browser_status, launch_tiktok_browser, close_tiktok_browser,
    open_tiktok_page, scan_tiktok_videos, snapshot_tiktok_feed,
    search_tiktok_videos, inspect_tiktok_profile, inspect_tiktok_video,
    like_tiktok_video, unlike_tiktok_video, follow_tiktok_account,
    unfollow_tiktok_account, comment_tiktok_video, publish_tiktok_video,
]

TIKTOK_API_TOOLS = [
    get_tiktok_api_status, get_tiktok_api_user_info, list_tiktok_api_videos,
    get_tiktok_api_creator_info, get_tiktok_api_post_status,
    init_tiktok_api_video_post, upload_tiktok_api_video_file,
    publish_tiktok_api_video,
]

TIKTOK_TOOLS = [*TIKTOK_TOOLS, *TIKTOK_API_TOOLS]

__all__ = ["TOOLBOX_ACCESS_MODE", "TIKTOK_API_TOOLS", "TIKTOK_TOOLS", *(tool.__name__ for tool in TIKTOK_TOOLS)]

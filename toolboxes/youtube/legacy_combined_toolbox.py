"""[MODE: HYBRID — Browser + Official APIs] YouTube toolbox.

Browser tools operate on the project's shared Selenium session. API tools call
YouTube Data API v3 and YouTube Analytics API v2 directly. Public reads can use
``YOUTUBE_API_KEY``. User actions require ``YOUTUBE_ACCESS_TOKEN`` or OAuth
refresh credentials: ``YOUTUBE_CLIENT_ID``, ``YOUTUBE_CLIENT_SECRET``, and
``YOUTUBE_REFRESH_TOKEN``.

Video uploads use Google's official resumable upload protocol. All functions
are implemented in this file and do not redirect to another social workflow.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlparse

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

# Browser tools require a normal logged-in Selenium session. API tools require
# YOUTUBE_API_KEY for eligible reads and OAuth credentials for user actions.
TOOLBOX_ACCESS_MODE = "hybrid"


_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_YOUTUBE_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, "workspace", "social")
_YOUTUBE_SNAPSHOT_PATH = os.path.join(
    _YOUTUBE_WORKSPACE_DIR,
    "youtube_feed_snapshot.json",
)
_YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_YOUTUBE_UPLOAD_BASE_URL = "https://www.googleapis.com/upload/youtube/v3"
_YOUTUBE_ANALYTICS_BASE_URL = "https://youtubeanalytics.googleapis.com/v2"
_YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DEFAULT_YOUTUBE_TIMEOUT = 30
_TOKEN_CACHE: dict[str, Any] = {
    "access_token": "",
    "expires_at": 0.0,
    "fingerprint": "",
    "scope": "",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_limit(
    value: Any,
    default: int = 25,
    minimum: int = 1,
    maximum: int = 50,
) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _compact_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _normalize_youtube_video_id(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    if text.startswith("/"):
        text = f"https://www.youtube.com{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }:
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            match = re.search(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})", parsed.path)
            video_id = match.group(1) if match else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("A valid YouTube video ID or URL is required.")
    return video_id


def _youtube_video_url(value: str) -> str:
    return f"https://www.youtube.com/watch?v={_normalize_youtube_video_id(value)}"


def _normalize_youtube_channel(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("A YouTube channel ID, handle, or URL is required.")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if (parsed.hostname or "").lower() not in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        }:
            raise ValueError("Only youtube.com channel URLs are accepted.")
        return text.rstrip("/")
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", text):
        return f"https://www.youtube.com/channel/{text}"
    handle = text.lstrip("@").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", handle):
        raise ValueError("A valid YouTube channel handle is required.")
    return f"https://www.youtube.com/@{handle}"


def _youtube_page_ready(driver) -> bool:
    try:
        return driver.execute_script(
            """
            return document.readyState !== 'loading' &&
              !!document.querySelector(
                'ytd-app, ytd-watch-flexy, ytd-browse, ytd-search'
              );
            """
        )
    except Exception:
        return False


def _wait_for_youtube(url: str, timeout: int = 20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_youtube_page_ready)
    except TimeoutException:
        pass
    return driver


def _find_visible(driver, selectors: tuple[str, ...], require_enabled: bool = False):
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if not element.is_displayed():
                    continue
                if require_enabled and not element.is_enabled():
                    continue
                return element
            except Exception:
                continue
    return None


def _find_control_by_markers(
    driver,
    markers: tuple[str, ...],
    *,
    root=None,
    require_enabled: bool = True,
):
    normalized = tuple(marker.casefold() for marker in markers)
    scope = root or driver
    for element in scope.find_elements(
        By.CSS_SELECTOR,
        "button, [role='button'], tp-yt-paper-item, ytd-button-renderer, a",
    ):
        try:
            if not element.is_displayed():
                continue
            if require_enabled and not element.is_enabled():
                continue
            text = " ".join(
                (
                    element.text or "",
                    element.get_attribute("aria-label") or "",
                    element.get_attribute("title") or "",
                )
            ).casefold()
            if any(marker in text for marker in normalized):
                return element
        except Exception:
            continue
    return None


def _collect_youtube_videos(driver, limit: int = 20) -> list[dict[str, Any]]:
    return driver.execute_script(
        """
        const limit = arguments[0];
        const selectors = [
          'ytd-video-renderer',
          'ytd-rich-item-renderer',
          'ytd-grid-video-renderer',
          'ytd-compact-video-renderer'
        ];
        const nodes = selectors.flatMap((selector) => [...document.querySelectorAll(selector)]);
        const seen = new Set();
        const results = [];
        const text = (root, selector) => {
          const node = root.querySelector(selector);
          return (node?.innerText || node?.textContent || '').trim();
        };
        for (const node of nodes) {
          if (results.length >= limit) break;
          const link = node.querySelector(
            "a#video-title, a[href*='/watch?v='], a[href*='/shorts/']"
          );
          const href = link?.href || link?.getAttribute('href') || '';
          const match = href.match(/[?&]v=([A-Za-z0-9_-]{11})|\\/shorts\\/([A-Za-z0-9_-]{11})/);
          const id = match ? (match[1] || match[2]) : '';
          if (!id || seen.has(id)) continue;
          seen.add(id);
          const image = node.querySelector('img');
          results.push({
            video_id: id,
            title: (link?.getAttribute('title') || link?.innerText || '').trim(),
            url: `https://www.youtube.com/watch?v=${id}`,
            channel: text(node, '#channel-name, ytd-channel-name, #text-container'),
            metadata: text(node, '#metadata-line'),
            description: text(node, '#description-text, .metadata-snippet-text'),
            duration: text(node, 'ytd-thumbnail-overlay-time-status-renderer'),
            thumbnail_url: image?.currentSrc || image?.src || '',
          });
        }
        return results;
        """,
        _coerce_limit(limit, default=20, minimum=1, maximum=100),
    ) or []


def get_youtube_browser_status() -> dict[str, Any]:
    """Return shared browser status and whether it is currently on YouTube."""

    state = get_browser_runtime_state()
    if not state.get("ready"):
        return {
            **state,
            "platform": "youtube",
            "url": "",
            "title": "",
            "on_youtube": False,
        }
    driver = _get_driver()
    url = str(driver.current_url or "")
    return {
        **state,
        "platform": "youtube",
        "url": url,
        "title": str(driver.title or ""),
        "on_youtube": "youtube.com" in urlparse(url).netloc.lower(),
    }


def launch_youtube_browser(
    headless: bool = False,
    restart_if_needed: bool = True,
) -> dict[str, Any]:
    """Launch the shared browser and open YouTube."""

    state = get_browser_runtime_state()
    if state.get("ready") and restart_if_needed:
        active_headless = state.get("active_headless")
        if active_headless is not None and bool(active_headless) != bool(headless):
            browser_kapat()
            state = get_browser_runtime_state()
    launch_result = ""
    if not state.get("ready"):
        launch_result = browser_baslat(headless=headless)
        if not get_browser_runtime_state().get("ready"):
            return {
                "status": "error",
                "platform": "youtube",
                "error": launch_result or "Browser could not be launched.",
            }
    driver = _wait_for_youtube("https://www.youtube.com/")
    return {
        "status": "ready",
        "platform": "youtube",
        "url": str(driver.current_url or ""),
        "title": str(driver.title or ""),
        "launch_result": launch_result,
        **get_browser_runtime_state(),
    }


def close_youtube_browser() -> dict[str, Any]:
    """Close the shared browser session."""

    return {
        "status": "closed",
        "platform": "youtube",
        "result": browser_kapat(),
    }


def open_youtube_page(
    destination: str = "home",
    query: str = "",
    channel: str = "",
    video_url: str = "",
) -> dict[str, Any]:
    """Open a YouTube home, search, channel, video, Studio, or feed page."""

    target = str(destination or "home").strip().casefold()
    if target in {"home", "anasayfa"}:
        url = "https://www.youtube.com/"
    elif target in {"search", "ara"}:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise ValueError("A YouTube search query is required.")
        url = f"https://www.youtube.com/results?search_query={quote_plus(clean_query)}"
    elif target in {"channel", "profile", "kanal"}:
        url = _normalize_youtube_channel(channel)
    elif target in {"community", "topluluk"}:
        url = f"{_normalize_youtube_channel(channel)}/community"
    elif target in {"videos", "channel videos"}:
        url = f"{_normalize_youtube_channel(channel)}/videos"
    elif target in {"video", "watch", "short"}:
        url = _youtube_video_url(video_url)
    elif target in {"subscriptions", "abonelikler"}:
        url = "https://www.youtube.com/feed/subscriptions"
    elif target in {"notifications", "bildirimler"}:
        url = "https://www.youtube.com/feed/notifications"
    elif target in {"history", "gecmis"}:
        url = "https://www.youtube.com/feed/history"
    elif target in {"watch later", "daha sonra izle"}:
        url = "https://www.youtube.com/playlist?list=WL"
    elif target in {"studio", "upload", "publish"}:
        url = "https://studio.youtube.com/"
    else:
        parsed = urlparse(destination)
        if (parsed.hostname or "").lower() not in {
            "youtube.com",
            "www.youtube.com",
            "studio.youtube.com",
        }:
            raise ValueError("Only YouTube URLs are accepted.")
        url = destination
    driver = _wait_for_youtube(url)
    return {
        "status": "opened",
        "destination": target,
        "url": str(driver.current_url or ""),
        "title": str(driver.title or ""),
    }


def scan_youtube_videos(limit: int = 20) -> dict[str, Any]:
    """Extract visible YouTube video cards from the current page."""

    driver = _get_driver()
    videos = _collect_youtube_videos(driver, limit=limit)
    return {
        "status": "ok",
        "source_url": str(driver.current_url or ""),
        "count": len(videos),
        "videos": videos,
    }


def snapshot_youtube_feed(
    destination: str = "home",
    channel: str = "",
    limit: int = 20,
    write_to_file: bool = True,
) -> dict[str, Any]:
    """Open and snapshot a YouTube feed or channel."""

    opened = open_youtube_page(destination=destination, channel=channel)
    snapshot = scan_youtube_videos(limit=limit)
    result = {"captured_at": _now(), "opened": opened, **snapshot}
    if write_to_file:
        os.makedirs(_YOUTUBE_WORKSPACE_DIR, exist_ok=True)
        with open(_YOUTUBE_SNAPSHOT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        result["snapshot_path"] = _YOUTUBE_SNAPSHOT_PATH
    return result


def search_youtube_videos(query: str, limit: int = 20) -> dict[str, Any]:
    """Search YouTube in the browser and extract visible video results."""

    opened = open_youtube_page(destination="search", query=query)
    videos = _collect_youtube_videos(_get_driver(), limit=limit)
    return {"status": "ok", "opened": opened, "count": len(videos), "videos": videos}


def inspect_youtube_channel(channel: str, limit: int = 20) -> dict[str, Any]:
    """Inspect a YouTube channel through the browser."""

    driver = _wait_for_youtube(_normalize_youtube_channel(channel))
    snapshot = driver.execute_script(
        """
        const text = (selector) => {
          const node = document.querySelector(selector);
          return (node?.innerText || node?.textContent || '').trim();
        };
        return {
          channel_name: text('#channel-name #text, yt-formatted-string#text'),
          handle: text('#channel-handle, #channel-tagline'),
          subscribers: text('#subscriber-count'),
          description: text('#description, #description-inline-expander'),
          body_excerpt: (document.body?.innerText || '').trim().slice(0, 2200),
        };
        """
    ) or {}
    return {
        "status": "ok",
        "url": str(driver.current_url or ""),
        "videos": _collect_youtube_videos(driver, limit=limit),
        **snapshot,
    }


def inspect_youtube_video(video_url: str) -> dict[str, Any]:
    """Inspect one YouTube video through the browser."""

    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f"https://www.youtube.com/watch?v={video_id}")
    snapshot = driver.execute_script(
        """
        const text = (selector) => {
          const node = document.querySelector(selector);
          return (node?.innerText || node?.textContent || '').trim();
        };
        const labels = [...document.querySelectorAll('button, [role="button"]')]
          .map((node) => node.getAttribute('aria-label') || node.innerText || '')
          .filter(Boolean);
        return {
          video_title: text('h1.ytd-watch-metadata, h1.title'),
          channel_name: text('#channel-name #text, ytd-channel-name #text'),
          metadata: text('#info, #info-text, #count'),
          description: text('#description-inline-expander, #description'),
          liked: labels.some((value) => /remove like|unlike/i.test(value)),
          subscribed: labels.some((value) => /unsubscribe|subscribed/i.test(value)),
          body_excerpt: (document.body?.innerText || '').trim().slice(0, 2500),
        };
        """
    ) or {}
    return {
        "status": "ok",
        "video_id": video_id,
        "url": str(driver.current_url or ""),
        **snapshot,
    }


def _youtube_browser_video_action(
    video_url: str,
    *,
    action: str,
    selectors: tuple[str, ...],
    markers: tuple[str, ...],
    already_markers: tuple[str, ...] = (),
) -> dict[str, Any]:
    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f"https://www.youtube.com/watch?v={video_id}")
    if already_markers:
        already = _find_control_by_markers(
            driver,
            already_markers,
            require_enabled=False,
        )
        if already is not None:
            return {"status": f"already_{action}", "video_id": video_id}
    control = _find_visible(driver, selectors, require_enabled=True)
    if control is None:
        control = _find_control_by_markers(
            driver,
            markers,
            require_enabled=True,
        )
    if control is None:
        return {
            "status": "error",
            "video_id": video_id,
            "action": action,
            "error": f"Could not locate YouTube {action} control.",
        }
    _human_click(driver, control)
    time.sleep(0.7)
    return {
        "status": "attempted",
        "video_id": video_id,
        "action": action,
        "url": str(driver.current_url or ""),
    }


def like_youtube_video(video_url: str) -> dict[str, Any]:
    """Like a YouTube video through the browser."""

    return _youtube_browser_video_action(
        video_url,
        action="liked",
        selectors=(
            "like-button-view-model button[aria-pressed='false']",
            "#segmented-like-button button",
        ),
        markers=("like this video", "beğen", "begen"),
        already_markers=("remove like", "unlike", "beğenmekten vazgeç"),
    )


def unlike_youtube_video(video_url: str) -> dict[str, Any]:
    """Remove a Like from a YouTube video through the browser."""

    return _youtube_browser_video_action(
        video_url,
        action="unliked",
        selectors=(
            "like-button-view-model button[aria-pressed='true']",
            "#segmented-like-button button[aria-pressed='true']",
        ),
        markers=("remove like", "unlike", "beğenmekten vazgeç"),
    )


def _youtube_browser_subscription_action(
    channel: str,
    *,
    subscribe: bool,
) -> dict[str, Any]:
    driver = _wait_for_youtube(_normalize_youtube_channel(channel))
    if subscribe:
        already = _find_control_by_markers(
            driver,
            ("subscribed", "unsubscribe", "abone olundu"),
            require_enabled=False,
        )
        if already is not None:
            return {"status": "already_subscribed", "url": str(driver.current_url or "")}
        markers = ("subscribe", "abone ol")
    else:
        markers = ("subscribed", "unsubscribe", "abone olundu")
    control = _find_control_by_markers(driver, markers, require_enabled=True)
    if control is None:
        return {"status": "error", "error": "Could not locate subscription control."}
    _human_click(driver, control)
    time.sleep(0.5)
    if not subscribe:
        confirm = _find_control_by_markers(
            driver,
            ("unsubscribe", "abonelikten çık"),
            require_enabled=True,
        )
        if confirm is not None:
            _human_click(driver, confirm)
    return {
        "status": "attempted",
        "action": "subscribe" if subscribe else "unsubscribe",
        "url": str(driver.current_url or ""),
    }


def subscribe_youtube_channel(channel: str) -> dict[str, Any]:
    """Subscribe to a YouTube channel through the browser."""

    return _youtube_browser_subscription_action(channel, subscribe=True)


def unsubscribe_youtube_channel(channel: str) -> dict[str, Any]:
    """Unsubscribe from a YouTube channel through the browser."""

    return _youtube_browser_subscription_action(channel, subscribe=False)


def comment_youtube_video(video_url: str, message: str) -> dict[str, Any]:
    """Post a top-level YouTube comment through the browser."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("YouTube comment cannot be empty.")
    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f"https://www.youtube.com/watch?v={video_id}")
    driver.execute_script("window.scrollTo(0, Math.max(700, document.body.scrollHeight * 0.45));")
    time.sleep(0.8)
    placeholder = _find_visible(
        driver,
        (
            "#placeholder-area",
            "#simplebox-placeholder",
            "ytd-comment-simplebox-renderer #placeholder-area",
        ),
        require_enabled=True,
    )
    if placeholder is not None:
        _human_click(driver, placeholder)
    editor = _find_visible(
        driver,
        (
            "#contenteditable-root[contenteditable='true']",
            "div[contenteditable='true'][role='textbox']",
        ),
        require_enabled=True,
    )
    if editor is None:
        raise RuntimeError("Could not locate YouTube's comment editor.")
    type_method = _type_into_element(driver, editor, clean_message)
    submit = _find_control_by_markers(
        driver,
        ("comment", "yorum"),
        require_enabled=True,
    )
    if submit is None:
        return {
            "status": "drafted",
            "video_id": video_id,
            "warning": "Comment filled, but submit control was not found.",
        }
    _human_click(driver, submit)
    time.sleep(0.8)
    return {
        "status": "attempted",
        "video_id": video_id,
        "message": clean_message,
        "type_method": type_method,
    }


def save_youtube_video_to_watch_later(video_url: str) -> dict[str, Any]:
    """Save a YouTube video to Watch Later through the browser."""

    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f"https://www.youtube.com/watch?v={video_id}")
    save = _find_control_by_markers(driver, ("save", "kaydet"), require_enabled=True)
    if save is None:
        return {"status": "error", "video_id": video_id, "error": "Save control not found."}
    _human_click(driver, save)
    time.sleep(0.5)
    watch_later = _find_control_by_markers(
        driver,
        ("watch later", "daha sonra izle"),
        require_enabled=True,
    )
    if watch_later is None:
        return {
            "status": "dialog_opened",
            "video_id": video_id,
            "warning": "Watch Later option was not found.",
        }
    _human_click(driver, watch_later)
    return {"status": "attempted", "video_id": video_id, "playlist": "Watch Later"}


def publish_youtube_video(
    video_path: str,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    """Upload a local video through the YouTube Studio browser interface."""

    absolute_path = os.path.abspath(os.path.expanduser(str(video_path or "").strip()))
    if not os.path.isfile(absolute_path):
        raise ValueError(f"YouTube video file does not exist: {absolute_path}")
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("YouTube video title cannot be empty.")
    driver = _wait_for_youtube("https://studio.youtube.com/")
    create = _find_control_by_markers(
        driver,
        ("create", "oluştur", "olustur"),
        require_enabled=True,
    )
    if create is not None:
        _human_click(driver, create)
        time.sleep(0.5)
        upload = _find_control_by_markers(
            driver,
            ("upload videos", "video yükle"),
            require_enabled=True,
        )
        if upload is not None:
            _human_click(driver, upload)
            time.sleep(0.5)
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if not inputs:
        raise RuntimeError("Could not locate YouTube Studio's upload input.")
    inputs[0].send_keys(absolute_path)
    time.sleep(1.0)
    title_editor = _find_visible(
        driver,
        (
            "#textbox[contenteditable='true'][aria-label*='title' i]",
            "ytcp-social-suggestions-textbox#title-textarea #textbox",
        ),
        require_enabled=True,
    )
    if title_editor is not None:
        _type_into_element(driver, title_editor, clean_title)
    if description:
        description_editor = _find_visible(
            driver,
            (
                "#textbox[contenteditable='true'][aria-label*='description' i]",
                "ytcp-social-suggestions-textbox#description-textarea #textbox",
            ),
            require_enabled=True,
        )
        if description_editor is not None:
            _type_into_element(driver, description_editor, description)
    return {
        "status": "drafted",
        "video_path": absolute_path,
        "title": clean_title,
        "description": str(description or ""),
        "url": str(driver.current_url or ""),
        "note": "Upload started and metadata filled; review audience, checks, and visibility in Studio.",
    }


def _youtube_credentials() -> dict[str, str]:
    return {
        "api_key": os.getenv("YOUTUBE_API_KEY", "").strip(),
        "access_token": os.getenv("YOUTUBE_ACCESS_TOKEN", "").strip(),
        "client_id": os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
        "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip(),
    }


def _youtube_timeout() -> int:
    try:
        timeout = int(os.getenv("YOUTUBE_API_TIMEOUT", str(_DEFAULT_YOUTUBE_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_YOUTUBE_TIMEOUT
    return max(5, min(timeout, 600))


def _youtube_error(
    error: str,
    *,
    endpoint: str = "",
    status_code: int = 0,
    response: Any = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "status": "error",
        "status_code": status_code,
        "endpoint": endpoint,
        "error": error,
    }
    if response is not None:
        result["response"] = response
    return result


def _youtube_access_token() -> str:
    credentials = _youtube_credentials()
    if credentials["access_token"]:
        return credentials["access_token"]
    if not all(
        credentials[key]
        for key in ("client_id", "client_secret", "refresh_token")
    ):
        raise RuntimeError(
            "YouTube user authentication is not configured. Set "
            "YOUTUBE_ACCESS_TOKEN or YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
            "and YOUTUBE_REFRESH_TOKEN."
        )
    fingerprint = hashlib.sha256(
        "|".join(
            (
                credentials["client_id"],
                credentials["client_secret"],
                credentials["refresh_token"],
            )
        ).encode("utf-8")
    ).hexdigest()
    if (
        _TOKEN_CACHE["access_token"]
        and _TOKEN_CACHE["fingerprint"] == fingerprint
        and float(_TOKEN_CACHE["expires_at"]) > time.time() + 30
    ):
        return str(_TOKEN_CACHE["access_token"])
    response = requests.post(
        _YOUTUBE_TOKEN_URL,
        data={
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "refresh_token": credentials["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=_youtube_timeout(),
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:2000]}
    if not response.ok or not isinstance(payload, dict) or not payload.get("access_token"):
        detail = payload.get("error_description") if isinstance(payload, dict) else ""
        raise RuntimeError(
            str(detail or f"Google OAuth returned HTTP {response.status_code}")
        )
    _TOKEN_CACHE.update(
        {
            "access_token": str(payload["access_token"]),
            "expires_at": time.time() + int(payload.get("expires_in", 3600) or 3600),
            "fingerprint": fingerprint,
            "scope": str(payload.get("scope", "")),
        }
    )
    return str(payload["access_token"])


def _youtube_api_request(
    method: str,
    endpoint: str,
    *,
    require_user: bool = False,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    base_url: str = _YOUTUBE_API_BASE_URL,
) -> dict[str, Any]:
    normalized_method = str(method or "GET").upper()
    normalized_endpoint = "/" + str(endpoint or "").lstrip("/")
    if normalized_method not in {"GET", "POST", "PUT", "DELETE"}:
        return _youtube_error("Unsupported YouTube API method.", endpoint=normalized_endpoint)
    if "://" in normalized_endpoint or ".." in normalized_endpoint:
        return _youtube_error("YouTube endpoint must be relative.", endpoint=normalized_endpoint)
    credentials = _youtube_credentials()
    headers = {"Accept": "application/json", "User-Agent": "Ethos-MarketingAgent/1.0"}
    clean_params = {
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "", [], ())
    }
    try:
        if require_user:
            headers["Authorization"] = f"Bearer {_youtube_access_token()}"
        elif credentials["api_key"]:
            clean_params["key"] = credentials["api_key"]
        elif credentials["access_token"] or credentials["refresh_token"]:
            headers["Authorization"] = f"Bearer {_youtube_access_token()}"
        else:
            return _youtube_error(
                "Set YOUTUBE_API_KEY for public reads or configure OAuth.",
                endpoint=normalized_endpoint,
            )
    except (RuntimeError, requests.RequestException) as exc:
        return _youtube_error(str(exc), endpoint=normalized_endpoint)
    try:
        response = requests.request(
            normalized_method,
            f"{base_url.rstrip('/')}{normalized_endpoint}",
            params=clean_params or None,
            json=json_body,
            headers=headers,
            timeout=_youtube_timeout(),
        )
    except requests.RequestException as exc:
        return _youtube_error(
            f"YouTube API request failed: {exc}",
            endpoint=normalized_endpoint,
        )
    try:
        payload: Any = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:4000]}
    api_error = payload.get("error") if isinstance(payload, dict) else None
    ok = bool(response.ok and not api_error)
    result: dict[str, Any] = {
        "ok": ok,
        "status": "ok" if ok else "error",
        "status_code": response.status_code,
        "method": normalized_method,
        "endpoint": normalized_endpoint,
        "response": payload,
    }
    if isinstance(payload, dict):
        for key in ("items", "nextPageToken", "prevPageToken", "pageInfo", "id", "rows", "columnHeaders"):
            if key in payload:
                result[key] = payload[key]
        if isinstance(payload.get("items"), list):
            result["count"] = len(payload["items"])
    if not ok:
        if isinstance(api_error, dict):
            detail = api_error.get("message")
            result["api_error"] = api_error
        else:
            detail = api_error
        result["error"] = str(detail or f"YouTube API returned HTTP {response.status_code}")
    return result


def get_youtube_api_status(verify_credentials: bool = False) -> dict[str, Any]:
    """Report YouTube API configuration without exposing credentials."""

    credentials = _youtube_credentials()
    user_auth = bool(
        credentials["access_token"]
        or (
            credentials["client_id"]
            and credentials["client_secret"]
            and credentials["refresh_token"]
        )
    )
    result: dict[str, Any] = {
        "status": "configured" if credentials["api_key"] or user_auth else "not_configured",
        "api_key_configured": bool(credentials["api_key"]),
        "provided_access_token_configured": bool(credentials["access_token"]),
        "oauth_refresh_configured": bool(
            credentials["client_id"]
            and credentials["client_secret"]
            and credentials["refresh_token"]
        ),
        "user_actions_configured": user_auth,
        "data_api_base_url": _YOUTUBE_API_BASE_URL,
        "analytics_api_base_url": _YOUTUBE_ANALYTICS_BASE_URL,
    }
    if verify_credentials:
        verification = get_youtube_api_channels(mine=user_auth, channel_id="" if user_auth else "UC_x5XG1OV2P6uZZ5FSM9Ttw")
        result["verification"] = verification
        result["status"] = "verified" if verification.get("ok") else "verification_failed"
    return result


def get_youtube_api_channels(
    channel_id: str = "",
    handle: str = "",
    mine: bool = False,
    part: str = "snippet,contentDetails,statistics,status,brandingSettings",
) -> dict[str, Any]:
    """Get YouTube channel resources by ID, handle, or authenticated owner."""

    params: dict[str, Any] = {"part": part}
    require_user = bool(mine)
    if mine:
        params["mine"] = True
    elif channel_id:
        params["id"] = channel_id
    elif handle:
        params["forHandle"] = str(handle).lstrip("@")
    else:
        raise ValueError("Provide channel_id, handle, or mine=True.")
    return _youtube_api_request("GET", "/channels", require_user=require_user, params=params)


def search_youtube_api(
    query: str,
    resource_type: str = "video",
    max_results: int = 25,
    page_token: str = "",
    order: str = "relevance",
    published_after: str = "",
) -> dict[str, Any]:
    """Search YouTube videos, channels, or playlists through Data API v3."""

    clean_query = str(query or "").strip()
    if not clean_query:
        raise ValueError("YouTube API search query cannot be empty.")
    if resource_type not in {"video", "channel", "playlist"}:
        raise ValueError("resource_type must be video, channel, or playlist.")
    if order not in {"date", "rating", "relevance", "title", "videoCount", "viewCount"}:
        raise ValueError("Invalid YouTube search order.")
    return _youtube_api_request(
        "GET",
        "/search",
        params={
            "part": "snippet",
            "q": clean_query,
            "type": resource_type,
            "maxResults": _coerce_limit(max_results, default=25, minimum=1, maximum=50),
            "pageToken": page_token,
            "order": order,
            "publishedAfter": published_after,
        },
    )


def get_youtube_api_videos(
    video_ids: str,
    part: str = "snippet,contentDetails,statistics,status,topicDetails",
) -> dict[str, Any]:
    """Get one or more comma-separated YouTube video IDs or URLs."""

    ids = [
        _normalize_youtube_video_id(value.strip())
        for value in str(video_ids or "").split(",")
        if value.strip()
    ]
    if not ids or len(ids) > 50:
        raise ValueError("Provide 1 to 50 video IDs or URLs.")
    return _youtube_api_request(
        "GET",
        "/videos",
        params={"part": part, "id": ",".join(ids)},
    )


def get_youtube_api_playlist_items(
    playlist_id: str,
    max_results: int = 25,
    page_token: str = "",
) -> dict[str, Any]:
    """List videos in a YouTube playlist."""

    if not str(playlist_id or "").strip():
        raise ValueError("playlist_id is required.")
    return _youtube_api_request(
        "GET",
        "/playlistItems",
        params={
            "part": "snippet,contentDetails,status",
            "playlistId": playlist_id,
            "maxResults": _coerce_limit(max_results, default=25, minimum=1, maximum=50),
            "pageToken": page_token,
        },
    )


def get_youtube_api_comment_threads(
    video_id_or_url: str,
    max_results: int = 50,
    page_token: str = "",
    order: str = "relevance",
) -> dict[str, Any]:
    """Get top-level comments and embedded replies for a YouTube video."""

    if order not in {"time", "relevance"}:
        raise ValueError("order must be time or relevance.")
    return _youtube_api_request(
        "GET",
        "/commentThreads",
        params={
            "part": "snippet,replies",
            "videoId": _normalize_youtube_video_id(video_id_or_url),
            "maxResults": _coerce_limit(max_results, default=50, minimum=1, maximum=100),
            "pageToken": page_token,
            "order": order,
            "textFormat": "plainText",
        },
    )


def get_youtube_api_comment_replies(
    parent_comment_id: str,
    max_results: int = 50,
    page_token: str = "",
) -> dict[str, Any]:
    """Get all replies to a top-level YouTube comment."""

    if not str(parent_comment_id or "").strip():
        raise ValueError("parent_comment_id is required.")
    return _youtube_api_request(
        "GET",
        "/comments",
        params={
            "part": "snippet",
            "parentId": parent_comment_id,
            "maxResults": _coerce_limit(max_results, default=50, minimum=1, maximum=100),
            "pageToken": page_token,
            "textFormat": "plainText",
        },
    )


def get_youtube_api_subscriptions(
    mine: bool = True,
    channel_id: str = "",
    max_results: int = 25,
    page_token: str = "",
) -> dict[str, Any]:
    """List subscriptions for the authenticated user or a public channel."""

    params: dict[str, Any] = {
        "part": "snippet,contentDetails,subscriberSnippet",
        "maxResults": _coerce_limit(max_results, default=25, minimum=1, maximum=50),
        "pageToken": page_token,
    }
    if mine:
        params["mine"] = True
    elif channel_id:
        params["channelId"] = channel_id
    else:
        raise ValueError("Provide channel_id or use mine=True.")
    return _youtube_api_request("GET", "/subscriptions", require_user=mine, params=params)


def get_youtube_api_playlists(
    mine: bool = True,
    channel_id: str = "",
    max_results: int = 25,
    page_token: str = "",
) -> dict[str, Any]:
    """List playlists owned by an authenticated or public channel."""

    params: dict[str, Any] = {
        "part": "snippet,contentDetails,status,player",
        "maxResults": _coerce_limit(max_results, default=25, minimum=1, maximum=50),
        "pageToken": page_token,
    }
    if mine:
        params["mine"] = True
    elif channel_id:
        params["channelId"] = channel_id
    else:
        raise ValueError("Provide channel_id or use mine=True.")
    return _youtube_api_request("GET", "/playlists", require_user=mine, params=params)


def comment_youtube_api_video(video_id_or_url: str, message: str) -> dict[str, Any]:
    """Create a top-level comment on a YouTube video."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("YouTube comment cannot be empty.")
    return _youtube_api_request(
        "POST",
        "/commentThreads",
        require_user=True,
        params={"part": "snippet"},
        json_body={
            "snippet": {
                "videoId": _normalize_youtube_video_id(video_id_or_url),
                "topLevelComment": {"snippet": {"textOriginal": clean_message}},
            }
        },
    )


def reply_youtube_api_comment(parent_comment_id: str, message: str) -> dict[str, Any]:
    """Reply to a top-level YouTube comment."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("YouTube reply cannot be empty.")
    return _youtube_api_request(
        "POST",
        "/comments",
        require_user=True,
        params={"part": "snippet"},
        json_body={
            "snippet": {
                "parentId": str(parent_comment_id or "").strip(),
                "textOriginal": clean_message,
            }
        },
    )


def update_youtube_api_comment(comment_id: str, text: str) -> dict[str, Any]:
    """Update a comment owned by the authenticated user."""

    clean_text = str(text or "").strip()
    if not comment_id or not clean_text:
        raise ValueError("comment_id and text are required.")
    return _youtube_api_request(
        "PUT",
        "/comments",
        require_user=True,
        params={"part": "snippet"},
        json_body={"id": comment_id, "snippet": {"textOriginal": clean_text}},
    )


def delete_youtube_api_comment(comment_id: str) -> dict[str, Any]:
    """Delete a comment owned by the authenticated user."""

    if not str(comment_id or "").strip():
        raise ValueError("comment_id is required.")
    return _youtube_api_request(
        "DELETE",
        "/comments",
        require_user=True,
        params={"id": comment_id},
    )


def rate_youtube_api_video(video_id_or_url: str, rating: str = "like") -> dict[str, Any]:
    """Like, dislike, or clear a YouTube video rating."""

    normalized = str(rating or "like").lower()
    if normalized not in {"like", "dislike", "none"}:
        raise ValueError("rating must be like, dislike, or none.")
    return _youtube_api_request(
        "POST",
        "/videos/rate",
        require_user=True,
        params={"id": _normalize_youtube_video_id(video_id_or_url), "rating": normalized},
    )


def subscribe_youtube_api_channel(channel_id: str) -> dict[str, Any]:
    """Subscribe the authenticated user to a YouTube channel."""

    if not str(channel_id or "").strip():
        raise ValueError("channel_id is required.")
    return _youtube_api_request(
        "POST",
        "/subscriptions",
        require_user=True,
        params={"part": "snippet"},
        json_body={"snippet": {"resourceId": {"kind": "youtube#channel", "channelId": channel_id}}},
    )


def unsubscribe_youtube_api_channel(subscription_id: str) -> dict[str, Any]:
    """Delete an authenticated user's subscription by subscription resource ID."""

    if not str(subscription_id or "").strip():
        raise ValueError("subscription_id is required.")
    return _youtube_api_request(
        "DELETE",
        "/subscriptions",
        require_user=True,
        params={"id": subscription_id},
    )


def create_youtube_api_playlist(
    title: str,
    description: str = "",
    privacy_status: str = "private",
) -> dict[str, Any]:
    """Create a playlist for the authenticated YouTube channel."""

    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("Playlist title cannot be empty.")
    if privacy_status not in {"private", "public", "unlisted"}:
        raise ValueError("privacy_status must be private, public, or unlisted.")
    return _youtube_api_request(
        "POST",
        "/playlists",
        require_user=True,
        params={"part": "snippet,status"},
        json_body={
            "snippet": {"title": clean_title, "description": description},
            "status": {"privacyStatus": privacy_status},
        },
    )


def add_youtube_api_playlist_item(
    playlist_id: str,
    video_id_or_url: str,
    position: int = -1,
) -> dict[str, Any]:
    """Add a video to an authenticated user's playlist."""

    snippet: dict[str, Any] = {
        "playlistId": playlist_id,
        "resourceId": {
            "kind": "youtube#video",
            "videoId": _normalize_youtube_video_id(video_id_or_url),
        },
    }
    if int(position) >= 0:
        snippet["position"] = int(position)
    return _youtube_api_request(
        "POST",
        "/playlistItems",
        require_user=True,
        params={"part": "snippet"},
        json_body={"snippet": snippet},
    )


def delete_youtube_api_playlist_item(playlist_item_id: str) -> dict[str, Any]:
    """Remove an item from an authenticated user's playlist."""

    return _youtube_api_request(
        "DELETE",
        "/playlistItems",
        require_user=True,
        params={"id": playlist_item_id},
    )


def update_youtube_api_video(
    video_id_or_url: str,
    title: str,
    description: str = "",
    category_id: str = "22",
    privacy_status: str = "",
) -> dict[str, Any]:
    """Update metadata for a video owned by the authenticated channel."""

    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("Video title cannot be empty.")
    body: dict[str, Any] = {
        "id": _normalize_youtube_video_id(video_id_or_url),
        "snippet": {
            "title": clean_title,
            "description": description,
            "categoryId": str(category_id),
        },
    }
    parts = ["snippet"]
    if privacy_status:
        if privacy_status not in {"private", "public", "unlisted"}:
            raise ValueError("Invalid privacy_status.")
        body["status"] = {"privacyStatus": privacy_status}
        parts.append("status")
    return _youtube_api_request(
        "PUT",
        "/videos",
        require_user=True,
        params={"part": ",".join(parts)},
        json_body=body,
    )


def delete_youtube_api_video(video_id_or_url: str) -> dict[str, Any]:
    """Delete a video owned by the authenticated channel."""

    return _youtube_api_request(
        "DELETE",
        "/videos",
        require_user=True,
        params={"id": _normalize_youtube_video_id(video_id_or_url)},
    )


def upload_youtube_api_video(
    video_path: str,
    title: str,
    description: str = "",
    tags: str = "",
    category_id: str = "22",
    privacy_status: str = "private",
    made_for_kids: bool = False,
) -> dict[str, Any]:
    """Upload a local video with Google's resumable YouTube upload protocol."""

    absolute_path = os.path.abspath(os.path.expanduser(str(video_path or "").strip()))
    if not os.path.isfile(absolute_path):
        raise ValueError(f"YouTube video file does not exist: {absolute_path}")
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("Video title cannot be empty.")
    if privacy_status not in {"private", "public", "unlisted"}:
        raise ValueError("privacy_status must be private, public, or unlisted.")
    try:
        token = _youtube_access_token()
    except (RuntimeError, requests.RequestException) as exc:
        return _youtube_error(str(exc), endpoint="/videos")
    size = os.path.getsize(absolute_path)
    mime_type = mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
    metadata = {
        "snippet": {
            "title": clean_title,
            "description": str(description or ""),
            "tags": [tag.strip() for tag in str(tags or "").split(",") if tag.strip()],
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": mime_type,
    }
    try:
        initiation = requests.post(
            f"{_YOUTUBE_UPLOAD_BASE_URL}/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=metadata,
            headers=headers,
            timeout=_youtube_timeout(),
        )
    except requests.RequestException as exc:
        return _youtube_error(f"Upload initialization failed: {exc}", endpoint="/videos")
    upload_url = initiation.headers.get("Location", "")
    if not initiation.ok or not upload_url:
        try:
            payload = initiation.json()
        except ValueError:
            payload = {"raw_text": initiation.text[:4000]}
        return _youtube_error(
            "YouTube did not create a resumable upload session.",
            endpoint="/videos",
            status_code=initiation.status_code,
            response=payload,
        )
    try:
        with open(absolute_path, "rb") as media:
            uploaded = requests.put(
                upload_url,
                data=media,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": mime_type,
                    "Content-Length": str(size),
                },
                timeout=max(_youtube_timeout(), 600),
            )
    except (OSError, requests.RequestException) as exc:
        return _youtube_error(f"Video upload failed: {exc}", endpoint="/videos")
    try:
        payload = uploaded.json()
    except ValueError:
        payload = {"raw_text": uploaded.text[:4000]}
    return {
        "ok": uploaded.ok,
        "status": "uploaded" if uploaded.ok else "error",
        "status_code": uploaded.status_code,
        "video_path": absolute_path,
        "video_id": payload.get("id", "") if isinstance(payload, dict) else "",
        "response": payload,
        **(
            {}
            if uploaded.ok
            else {"error": f"YouTube upload returned HTTP {uploaded.status_code}"}
        ),
    }


def set_youtube_api_thumbnail(
    video_id_or_url: str,
    image_path: str,
) -> dict[str, Any]:
    """Upload a custom thumbnail for an owned YouTube video."""

    absolute_path = os.path.abspath(os.path.expanduser(str(image_path or "").strip()))
    if not os.path.isfile(absolute_path):
        raise ValueError(f"Thumbnail file does not exist: {absolute_path}")
    try:
        token = _youtube_access_token()
    except (RuntimeError, requests.RequestException) as exc:
        return _youtube_error(str(exc), endpoint="/thumbnails/set")
    mime_type = mimetypes.guess_type(absolute_path)[0] or "application/octet-stream"
    try:
        with open(absolute_path, "rb") as image:
            response = requests.post(
                f"{_YOUTUBE_UPLOAD_BASE_URL}/thumbnails/set",
                params={
                    "videoId": _normalize_youtube_video_id(video_id_or_url),
                    "uploadType": "media",
                },
                data=image,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": mime_type,
                },
                timeout=max(_youtube_timeout(), 120),
            )
    except (OSError, requests.RequestException) as exc:
        return _youtube_error(f"Thumbnail upload failed: {exc}", endpoint="/thumbnails/set")
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:4000]}
    return {
        "ok": response.ok,
        "status": "ok" if response.ok else "error",
        "status_code": response.status_code,
        "endpoint": "/thumbnails/set",
        "response": payload,
        **({} if response.ok else {"error": f"Thumbnail upload returned HTTP {response.status_code}"}),
    }


def get_youtube_api_analytics(
    start_date: str,
    end_date: str,
    metrics: str = "views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
    dimensions: str = "day",
    filters: str = "",
    sort: str = "day",
    channel_id: str = "MINE",
    max_results: int = 200,
) -> dict[str, Any]:
    """Query YouTube Analytics API v2 for an authenticated channel."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_date or ""):
        raise ValueError("start_date must use YYYY-MM-DD.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_date or ""):
        raise ValueError("end_date must use YYYY-MM-DD.")
    ids = "channel==MINE" if channel_id.upper() == "MINE" else f"channel=={channel_id}"
    return _youtube_api_request(
        "GET",
        "/reports",
        require_user=True,
        base_url=_YOUTUBE_ANALYTICS_BASE_URL,
        params={
            "ids": ids,
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
            "dimensions": dimensions,
            "filters": filters,
            "sort": sort,
            "maxResults": _coerce_limit(max_results, default=200, minimum=1, maximum=10000),
        },
    )


YOUTUBE_BROWSER_TOOLS = [
    get_youtube_browser_status,
    launch_youtube_browser,
    close_youtube_browser,
    open_youtube_page,
    scan_youtube_videos,
    snapshot_youtube_feed,
    search_youtube_videos,
    inspect_youtube_channel,
    inspect_youtube_video,
    like_youtube_video,
    unlike_youtube_video,
    subscribe_youtube_channel,
    unsubscribe_youtube_channel,
    comment_youtube_video,
    save_youtube_video_to_watch_later,
    publish_youtube_video,
]


YOUTUBE_API_TOOLS = [
    get_youtube_api_status,
    get_youtube_api_channels,
    search_youtube_api,
    get_youtube_api_videos,
    get_youtube_api_playlist_items,
    get_youtube_api_comment_threads,
    get_youtube_api_comment_replies,
    get_youtube_api_subscriptions,
    get_youtube_api_playlists,
    comment_youtube_api_video,
    reply_youtube_api_comment,
    update_youtube_api_comment,
    delete_youtube_api_comment,
    rate_youtube_api_video,
    subscribe_youtube_api_channel,
    unsubscribe_youtube_api_channel,
    create_youtube_api_playlist,
    add_youtube_api_playlist_item,
    delete_youtube_api_playlist_item,
    update_youtube_api_video,
    delete_youtube_api_video,
    upload_youtube_api_video,
    set_youtube_api_thumbnail,
    get_youtube_api_analytics,
]


YOUTUBE_TOOLS = [*YOUTUBE_BROWSER_TOOLS, *YOUTUBE_API_TOOLS]


__all__ = [
    "YOUTUBE_BROWSER_TOOLS",
    "YOUTUBE_API_TOOLS",
    "YOUTUBE_TOOLS",
    *(tool.__name__ for tool in YOUTUBE_TOOLS),
]

"""[MODE: HYBRID — Browser + Official API] Instagram toolbox.

Browser tools operate on the project's shared Selenium session and expect the
user to sign in normally. API tools call Meta's Instagram API with Instagram
Login directly at ``graph.instagram.com``. The official API is for Instagram
professional Business and Creator accounts, subject to Meta app permissions and
review.

Configure ``INSTAGRAM_ACCESS_TOKEN`` and ``INSTAGRAM_USER_ID``. The default API
version is v25.0 and can be overridden with ``INSTAGRAM_API_VERSION`` or a full
``INSTAGRAM_API_BASE_URL``.

This module contains the implementations; it does not redirect Instagram calls
to another social-workflow module.
"""

from __future__ import annotations

import json
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
    _read_element_value,
    _type_into_element,
    browser_baslat,
    browser_kapat,
    get_browser_runtime_state,
)

# Browser tools require a normal logged-in Selenium session. API tools require
# INSTAGRAM_ACCESS_TOKEN and an Instagram Business or Creator account ID.
TOOLBOX_ACCESS_MODE = "hybrid"


_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_INSTAGRAM_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, "workspace", "social")
_INSTAGRAM_SNAPSHOT_PATH = os.path.join(
    _INSTAGRAM_WORKSPACE_DIR,
    "instagram_feed_snapshot.json",
)
_DEFAULT_INSTAGRAM_API_HOST = "https://graph.instagram.com"
_DEFAULT_INSTAGRAM_API_VERSION = "v25.0"
_DEFAULT_INSTAGRAM_API_TIMEOUT = 30

_INSTAGRAM_POST_PATH_PATTERN = re.compile(
    r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)",
    re.I,
)
_INSTAGRAM_PROFILE_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_limit(
    value: Any,
    default: int = 20,
    minimum: int = 1,
    maximum: int = 100,
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


def _normalize_instagram_handle(value: str) -> str:
    text = str(value or "").strip()
    if "://" in text:
        parsed = urlparse(text)
        if (parsed.hostname or "").lower() not in {
            "instagram.com",
            "www.instagram.com",
        }:
            raise ValueError("Only instagram.com profile URLs are accepted.")
        parts = [part for part in parsed.path.split("/") if part]
        text = parts[0] if parts else ""
    text = text.lstrip("@").strip("/")
    if not _INSTAGRAM_PROFILE_HANDLE_PATTERN.fullmatch(text):
        raise ValueError("A valid Instagram handle is required.")
    return text


def _normalize_instagram_url(value: str, *, require_post: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("An Instagram URL is required.")
    if text.startswith("/"):
        text = f"https://www.instagram.com{text}"
    parsed = urlparse(text)
    if (parsed.hostname or "").lower() not in {
        "instagram.com",
        "www.instagram.com",
    }:
        raise ValueError("Only instagram.com URLs are accepted.")
    if require_post and not _INSTAGRAM_POST_PATH_PATTERN.search(parsed.path):
        raise ValueError("An Instagram Post, Reel, or video URL is required.")
    return text


def _instagram_shortcode(post_url: str) -> str:
    target = _normalize_instagram_url(post_url, require_post=True)
    match = _INSTAGRAM_POST_PATH_PATTERN.search(urlparse(target).path)
    if not match:
        raise ValueError("Could not determine the Instagram shortcode.")
    return match.group(1)


def _instagram_page_ready(driver) -> bool:
    try:
        return driver.execute_script(
            """
            return document.readyState !== 'loading' &&
              !!document.querySelector('main, article, nav, header');
            """
        )
    except Exception:
        return False


def _wait_for_instagram(url: str, timeout: int = 20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_instagram_page_ready)
    except TimeoutException:
        pass
    current_url = str(driver.current_url or "")
    if "/accounts/login" in current_url:
        raise RuntimeError(
            "Instagram requires login. Complete login in the shared browser session."
        )
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
    normalized_markers = tuple(marker.casefold() for marker in markers)
    scope = root or driver
    for element in scope.find_elements(
        By.CSS_SELECTOR,
        "button, [role='button'], svg[aria-label], a",
    ):
        try:
            if not element.is_displayed():
                continue
            if require_enabled and not element.is_enabled():
                continue
            combined = " ".join(
                (
                    element.text or "",
                    element.get_attribute("aria-label") or "",
                    element.get_attribute("title") or "",
                )
            ).casefold()
            if any(marker in combined for marker in normalized_markers):
                if element.tag_name.lower() == "svg":
                    try:
                        return element.find_element(By.XPATH, "./ancestor::*[@role='button' or self::button][1]")
                    except Exception:
                        return element
                return element
        except Exception:
            continue
    return None


def _collect_instagram_posts(driver, limit: int = 20) -> list[dict[str, Any]]:
    return driver.execute_script(
        """
        const limit = arguments[0];
        const anchors = [...document.querySelectorAll(
          "a[href*='/p/'], a[href*='/reel/'], a[href*='/tv/']"
        )];
        const seen = new Set();
        const results = [];
        for (const anchor of anchors) {
          if (results.length >= limit) break;
          const href = anchor.getAttribute('href') || '';
          const match = href.match(/\\/(p|reel|tv)\\/([^/?#]+)/i);
          if (!match || seen.has(match[2])) continue;
          seen.add(match[2]);
          const root = anchor.closest('article') || anchor.parentElement || anchor;
          const image = root.querySelector('img') || anchor.querySelector('img');
          const video = root.querySelector('video') || anchor.querySelector('video');
          const text = (root.innerText || root.textContent || '').trim();
          results.push({
            shortcode: match[2],
            media_type: match[1].toLowerCase() === 'reel' ? 'REEL' :
              video ? 'VIDEO' : 'IMAGE',
            url: href.startsWith('http')
              ? href
              : `https://www.instagram.com${href.startsWith('/') ? href : `/${href}`}`,
            caption: text.slice(0, 1200),
            image_url: image?.currentSrc || image?.src || '',
            alt_text: image?.alt || '',
            video_url: video?.currentSrc || video?.src || '',
          });
        }
        return results;
        """,
        _coerce_limit(limit, default=20, minimum=1, maximum=100),
    ) or []


def get_instagram_browser_status() -> dict[str, Any]:
    """Return the shared browser state and whether it is on Instagram."""

    state = get_browser_runtime_state()
    if not state.get("ready"):
        return {
            **state,
            "platform": "instagram",
            "url": "",
            "title": "",
            "on_instagram": False,
        }
    driver = _get_driver()
    url = str(driver.current_url or "")
    return {
        **state,
        "platform": "instagram",
        "url": url,
        "title": str(driver.title or ""),
        "on_instagram": "instagram.com" in urlparse(url).netloc.lower(),
    }


def launch_instagram_browser(
    headless: bool = False,
    restart_if_needed: bool = True,
) -> dict[str, Any]:
    """Launch the shared browser and open Instagram."""

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
                "platform": "instagram",
                "error": launch_result or "Browser could not be launched.",
            }
    driver = _wait_for_instagram("https://www.instagram.com/")
    return {
        "status": "ready",
        "platform": "instagram",
        "url": str(driver.current_url or ""),
        "title": str(driver.title or ""),
        "launch_result": launch_result,
        **get_browser_runtime_state(),
    }


def close_instagram_browser() -> dict[str, Any]:
    """Close the shared browser session."""

    result = browser_kapat()
    return {"status": "closed", "platform": "instagram", "result": result}


def open_instagram_page(
    destination: str = "home",
    query: str = "",
    handle_or_url: str = "",
    post_url: str = "",
) -> dict[str, Any]:
    """Open an Instagram home, Explore, search, profile, Post, Reel, or inbox page."""

    target = str(destination or "home").strip().casefold()
    if target in {"home", "anasayfa"}:
        url = "https://www.instagram.com/"
    elif target in {"explore", "kesfet", "keşfet"}:
        url = "https://www.instagram.com/explore/"
    elif target in {"reels", "reel"} and not post_url:
        url = "https://www.instagram.com/reels/"
    elif target in {"direct", "messages", "dm", "inbox"}:
        url = "https://www.instagram.com/direct/inbox/"
    elif target in {"notifications", "activity", "bildirimler"}:
        url = "https://www.instagram.com/accounts/activity/"
    elif target in {"profile", "profil"}:
        handle = _normalize_instagram_handle(handle_or_url)
        url = f"https://www.instagram.com/{quote(handle, safe='')}/"
    elif target in {"post", "reel", "media"}:
        url = _normalize_instagram_url(post_url, require_post=True)
    elif target in {"search", "arama"}:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise ValueError("An Instagram search query is required.")
        url = (
            "https://www.instagram.com/explore/search/keyword/"
            f"?q={quote_plus(clean_query)}"
        )
    elif target in {"create", "new post", "publish", "olustur"}:
        url = "https://www.instagram.com/"
    else:
        url = _normalize_instagram_url(destination)
    driver = _wait_for_instagram(url)
    return {
        "status": "opened",
        "destination": target,
        "url": str(driver.current_url or ""),
        "title": str(driver.title or ""),
    }


def scan_instagram_posts(limit: int = 20) -> dict[str, Any]:
    """Extract visible Instagram Posts and Reels from the current page."""

    driver = _get_driver()
    posts = _collect_instagram_posts(driver, limit=limit)
    return {
        "status": "ok",
        "source_url": str(driver.current_url or ""),
        "count": len(posts),
        "posts": posts,
    }


def snapshot_instagram_feed(
    destination: str = "home",
    handle_or_url: str = "",
    limit: int = 20,
    write_to_file: bool = True,
) -> dict[str, Any]:
    """Open and snapshot an Instagram feed or profile."""

    opened = open_instagram_page(
        destination=destination,
        handle_or_url=handle_or_url,
    )
    snapshot = scan_instagram_posts(limit=limit)
    result = {"captured_at": _now(), "opened": opened, **snapshot}
    if write_to_file:
        os.makedirs(_INSTAGRAM_WORKSPACE_DIR, exist_ok=True)
        with open(_INSTAGRAM_SNAPSHOT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        result["snapshot_path"] = _INSTAGRAM_SNAPSHOT_PATH
    return result


def search_instagram(
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Search Instagram in the browser and extract visible media results."""

    opened = open_instagram_page(destination="search", query=query)
    driver = _get_driver()
    posts = _collect_instagram_posts(driver, limit=limit)
    return {"status": "ok", "opened": opened, "count": len(posts), "posts": posts}


def inspect_instagram_profile(
    handle_or_url: str,
    media_limit: int = 20,
) -> dict[str, Any]:
    """Inspect an Instagram profile through the browser."""

    handle = _normalize_instagram_handle(handle_or_url)
    driver = _wait_for_instagram(
        f"https://www.instagram.com/{quote(handle, safe='')}/"
    )
    snapshot = driver.execute_script(
        """
        const text = (selector) => {
          const el = document.querySelector(selector);
          return (el?.innerText || el?.textContent || '').trim();
        };
        const stats = [...document.querySelectorAll('header ul li, header section ul li')]
          .map((el) => (el.innerText || el.textContent || '').trim())
          .filter(Boolean)
          .slice(0, 8);
        const body = (document.body?.innerText || '').trim();
        return {
          display_name: text('header h1, header h2'),
          bio: text('header section div span, header section h1 + div'),
          stats,
          body_excerpt: body.slice(0, 2000),
        };
        """
    ) or {}
    return {
        "status": "ok",
        "handle": handle,
        "url": str(driver.current_url or ""),
        "media": _collect_instagram_posts(driver, limit=media_limit),
        **snapshot,
    }


def inspect_instagram_post(post_url: str) -> dict[str, Any]:
    """Inspect one Instagram Post or Reel through the browser."""

    target_url = _normalize_instagram_url(post_url, require_post=True)
    driver = _wait_for_instagram(target_url)
    snapshot = driver.execute_script(
        """
        const article = document.querySelector('article') || document.querySelector('main');
        const body = (article?.innerText || article?.textContent || '').trim();
        const image = article?.querySelector('img');
        const video = article?.querySelector('video');
        const labels = [...document.querySelectorAll('button, svg[aria-label]')]
          .map((el) => el.getAttribute('aria-label') || el.innerText || '')
          .filter(Boolean);
        return {
          caption: body.slice(0, 2000),
          image_url: image?.currentSrc || image?.src || '',
          alt_text: image?.alt || '',
          video_url: video?.currentSrc || video?.src || '',
          liked: labels.some((value) => /unlike|beğenmekten vazgeç/i.test(value)),
          saved: labels.some((value) => /remove|unsave|collection/i.test(value)),
          comment_ready: !!document.querySelector(
            "textarea[aria-label*='comment' i], textarea[placeholder*='comment' i]"
          ),
        };
        """
    ) or {}
    return {
        "status": "ok",
        "shortcode": _instagram_shortcode(target_url),
        "url": str(driver.current_url or ""),
        **snapshot,
    }


def _instagram_browser_post_action(
    post_url: str,
    *,
    action: str,
    selectors: tuple[str, ...],
    markers: tuple[str, ...],
    already_markers: tuple[str, ...] = (),
) -> dict[str, Any]:
    target_url = _normalize_instagram_url(post_url, require_post=True)
    driver = _wait_for_instagram(target_url)
    if already_markers:
        already = _find_control_by_markers(
            driver,
            already_markers,
            require_enabled=False,
        )
        if already is not None:
            return {
                "status": f"already_{action}",
                "action": action,
                "url": str(driver.current_url or ""),
                "shortcode": _instagram_shortcode(target_url),
            }
    element = _find_visible(driver, selectors, require_enabled=True)
    if element is None:
        element = _find_control_by_markers(
            driver,
            markers,
            require_enabled=True,
        )
    if element is None:
        return {
            "status": "error",
            "action": action,
            "url": str(driver.current_url or ""),
            "error": f"Could not locate Instagram {action} control.",
        }
    _human_click(driver, element)
    time.sleep(0.7)
    return {
        "status": "attempted",
        "action": action,
        "url": str(driver.current_url or ""),
        "shortcode": _instagram_shortcode(target_url),
    }


def like_instagram_post(post_url: str) -> dict[str, Any]:
    """Like an Instagram Post through the browser."""

    return _instagram_browser_post_action(
        post_url,
        action="liked",
        selectors=("svg[aria-label='Like']",),
        markers=("like", "beğen", "begen"),
        already_markers=("unlike", "beğenmekten vazgeç"),
    )


def unlike_instagram_post(post_url: str) -> dict[str, Any]:
    """Remove a Like from an Instagram Post through the browser."""

    return _instagram_browser_post_action(
        post_url,
        action="unliked",
        selectors=("svg[aria-label='Unlike']",),
        markers=("unlike", "beğenmekten vazgeç"),
    )


def save_instagram_post(post_url: str) -> dict[str, Any]:
    """Save an Instagram Post through the browser."""

    return _instagram_browser_post_action(
        post_url,
        action="saved",
        selectors=("svg[aria-label='Save']",),
        markers=("save", "kaydet"),
        already_markers=("remove", "unsave", "koleksiyondan çıkar"),
    )


def unsave_instagram_post(post_url: str) -> dict[str, Any]:
    """Remove an Instagram Post from saved items through the browser."""

    return _instagram_browser_post_action(
        post_url,
        action="unsaved",
        selectors=("svg[aria-label*='Remove' i]",),
        markers=("remove", "unsave", "koleksiyondan çıkar"),
    )


def _instagram_browser_follow_action(
    handle_or_url: str,
    *,
    follow: bool,
) -> dict[str, Any]:
    handle = _normalize_instagram_handle(handle_or_url)
    driver = _wait_for_instagram(
        f"https://www.instagram.com/{quote(handle, safe='')}/"
    )
    if follow:
        already = _find_control_by_markers(
            driver,
            ("following", "requested", "takiptesin", "takip ediliyor"),
            require_enabled=False,
        )
        if already is not None:
            return {"status": "already_following", "handle": handle}
        markers = ("follow", "takip et")
    else:
        markers = ("following", "requested", "takiptesin", "takip ediliyor")
    control = _find_control_by_markers(driver, markers, require_enabled=True)
    if control is None:
        return {
            "status": "error",
            "handle": handle,
            "error": "Could not locate Instagram's follow control.",
        }
    _human_click(driver, control)
    time.sleep(0.5)
    if not follow:
        confirm = _find_control_by_markers(
            driver,
            ("unfollow", "takibi bırak", "takipten çık"),
            require_enabled=True,
        )
        if confirm is not None:
            _human_click(driver, confirm)
    return {
        "status": "attempted",
        "action": "follow" if follow else "unfollow",
        "handle": handle,
        "url": str(driver.current_url or ""),
    }


def follow_instagram_account(handle_or_url: str) -> dict[str, Any]:
    """Follow an Instagram account through the browser."""

    return _instagram_browser_follow_action(handle_or_url, follow=True)


def unfollow_instagram_account(handle_or_url: str) -> dict[str, Any]:
    """Unfollow an Instagram account through the browser."""

    return _instagram_browser_follow_action(handle_or_url, follow=False)


def comment_instagram_post(post_url: str, message: str) -> dict[str, Any]:
    """Comment on an Instagram Post through the browser."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Instagram comment cannot be empty.")
    target_url = _normalize_instagram_url(post_url, require_post=True)
    driver = _wait_for_instagram(target_url)
    textarea = _find_visible(
        driver,
        (
            "textarea[aria-label*='comment' i]",
            "textarea[placeholder*='comment' i]",
            "form textarea",
        ),
        require_enabled=True,
    )
    if textarea is None:
        raise RuntimeError("Could not locate Instagram's comment editor.")
    type_method = _type_into_element(driver, textarea, clean_message)
    submit = _find_control_by_markers(
        driver,
        ("post", "paylaş", "paylas"),
        require_enabled=True,
    )
    if submit is not None:
        _human_click(driver, submit)
        submit_method = "click"
    else:
        textarea.send_keys(Keys.ENTER)
        submit_method = "enter"
    time.sleep(0.8)
    return {
        "status": "attempted",
        "shortcode": _instagram_shortcode(target_url),
        "message": clean_message,
        "type_method": type_method,
        "submit_method": submit_method,
        "url": str(driver.current_url or ""),
    }


def send_instagram_message(handle_or_url: str, message: str) -> dict[str, Any]:
    """Send a direct message through Instagram's browser interface."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Instagram message cannot be empty.")
    handle = _normalize_instagram_handle(handle_or_url)
    driver = _wait_for_instagram(
        f"https://www.instagram.com/{quote(handle, safe='')}/"
    )
    message_button = _find_control_by_markers(
        driver,
        ("message", "mesaj"),
        require_enabled=True,
    )
    if message_button is None:
        return {
            "status": "error",
            "handle": handle,
            "error": "Could not locate Instagram's Message control.",
        }
    _human_click(driver, message_button)
    time.sleep(1.0)
    editor = _find_visible(
        driver,
        (
            "textarea[placeholder*='message' i]",
            "div[contenteditable='true'][role='textbox']",
        ),
        require_enabled=True,
    )
    if editor is None:
        raise RuntimeError("Could not locate Instagram's message editor.")
    type_method = _type_into_element(driver, editor, clean_message)
    editor.send_keys(Keys.ENTER)
    time.sleep(0.7)
    return {
        "status": "attempted",
        "handle": handle,
        "message": clean_message,
        "type_method": type_method,
        "url": str(driver.current_url or ""),
    }


def publish_instagram_post(
    media_path: str,
    caption: str = "",
) -> dict[str, Any]:
    """Publish a local image or video through Instagram's browser composer."""

    absolute_path = os.path.abspath(os.path.expanduser(str(media_path or "").strip()))
    if not os.path.isfile(absolute_path):
        raise ValueError(f"Instagram media file does not exist: {absolute_path}")
    if os.path.splitext(absolute_path)[1].lower() not in {
        ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"
    }:
        raise ValueError("Unsupported Instagram media file type.")
    driver = _wait_for_instagram("https://www.instagram.com/")
    create = _find_control_by_markers(
        driver,
        ("create", "new post", "oluştur", "olustur"),
        require_enabled=True,
    )
    if create is not None:
        _human_click(driver, create)
        time.sleep(0.7)
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    file_input = file_inputs[0] if file_inputs else None
    if file_input is None:
        raise RuntimeError("Could not locate Instagram's media upload input.")
    file_input.send_keys(absolute_path)
    time.sleep(1.2)
    for _ in range(2):
        next_button = _find_control_by_markers(
            driver,
            ("next", "ileri"),
            require_enabled=True,
        )
        if next_button is None:
            break
        _human_click(driver, next_button)
        time.sleep(0.8)
    clean_caption = str(caption or "").strip()
    if clean_caption:
        editor = _find_visible(
            driver,
            (
                "textarea[aria-label*='caption' i]",
                "div[contenteditable='true'][role='textbox']",
            ),
            require_enabled=True,
        )
        if editor is not None:
            _type_into_element(driver, editor, clean_caption)
    share = _find_control_by_markers(
        driver,
        ("share", "paylaş", "paylas"),
        require_enabled=True,
    )
    if share is None:
        return {
            "status": "drafted",
            "media_path": absolute_path,
            "caption": clean_caption,
            "warning": "Media loaded, but Instagram's Share control was not found.",
        }
    _human_click(driver, share)
    time.sleep(1.5)
    return {
        "status": "submitted",
        "media_path": absolute_path,
        "caption": clean_caption,
        "url": str(driver.current_url or ""),
    }


def _instagram_api_credentials() -> dict[str, str]:
    return {
        "access_token": os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
        "user_id": os.getenv("INSTAGRAM_USER_ID", "").strip(),
        "app_id": os.getenv("INSTAGRAM_APP_ID", "").strip(),
        "app_secret": os.getenv("INSTAGRAM_APP_SECRET", "").strip(),
    }


def _instagram_api_base_url() -> str:
    configured = os.getenv("INSTAGRAM_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    version = (
        os.getenv("INSTAGRAM_API_VERSION", _DEFAULT_INSTAGRAM_API_VERSION).strip()
        or _DEFAULT_INSTAGRAM_API_VERSION
    )
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("INSTAGRAM_API_VERSION must look like v25.0.")
    return f"{_DEFAULT_INSTAGRAM_API_HOST}/{version}"


def _instagram_api_timeout() -> int:
    try:
        timeout = int(
            os.getenv(
                "INSTAGRAM_API_TIMEOUT",
                str(_DEFAULT_INSTAGRAM_API_TIMEOUT),
            )
        )
    except (TypeError, ValueError):
        timeout = _DEFAULT_INSTAGRAM_API_TIMEOUT
    return max(5, min(timeout, 120))


def _instagram_api_user_id(user_id: str = "") -> str:
    value = str(user_id or _instagram_api_credentials()["user_id"]).strip()
    if not re.fullmatch(r"\d{1,30}", value):
        raise ValueError(
            "A numeric Instagram professional account ID is required. "
            "Set INSTAGRAM_USER_ID or pass user_id."
        )
    return value


def _instagram_api_object_id(value: str, label: str = "object") -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"\d{1,40}", normalized):
        raise ValueError(f"A valid numeric Instagram {label} ID is required.")
    return normalized


def _instagram_api_error(
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


def _instagram_api_request(
    method: str,
    endpoint: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    access_token: str = "",
) -> dict[str, Any]:
    normalized_method = str(method or "GET").upper().strip()
    normalized_endpoint = "/" + str(endpoint or "").lstrip("/")
    if normalized_method not in {"GET", "POST", "DELETE"}:
        return _instagram_api_error(
            f"Unsupported Instagram API method: {normalized_method}",
            endpoint=normalized_endpoint,
        )
    if "://" in normalized_endpoint or ".." in normalized_endpoint:
        return _instagram_api_error(
            "Instagram API endpoint must be a relative Graph path.",
            endpoint=normalized_endpoint,
        )
    token = str(
        access_token or _instagram_api_credentials()["access_token"]
    ).strip()
    if not token:
        return _instagram_api_error(
            "INSTAGRAM_ACCESS_TOKEN is not configured.",
            endpoint=normalized_endpoint,
        )
    clean_params = {
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "", [], ())
    }
    clean_data: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if value in (None, "", [], ()):
            continue
        clean_data[key] = str(value).lower() if isinstance(value, bool) else value
    try:
        response = requests.request(
            normalized_method,
            f"{_instagram_api_base_url()}{normalized_endpoint}",
            params=clean_params or None,
            data=clean_data or None,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "Ethos-MarketingAgent/1.0",
            },
            timeout=_instagram_api_timeout(),
        )
    except requests.RequestException as exc:
        return _instagram_api_error(
            f"Instagram API request failed: {exc}",
            endpoint=normalized_endpoint,
        )
    try:
        payload: Any = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:4000]}
    graph_error = payload.get("error") if isinstance(payload, dict) else None
    ok = bool(response.ok and not graph_error)
    result: dict[str, Any] = {
        "ok": ok,
        "status": "ok" if ok else "error",
        "status_code": response.status_code,
        "http_status_code": response.status_code,
        "method": normalized_method,
        "endpoint": normalized_endpoint,
        "rate_limit": {
            "app_usage": response.headers.get("x-app-usage", ""),
            "business_usage": response.headers.get(
                "x-business-use-case-usage",
                "",
            ),
            "instagram_usage": response.headers.get(
                "x-instagram-api-call-usage",
                "",
            ),
        },
        "response": payload,
    }
    if isinstance(payload, dict):
        for key in ("id", "data", "paging"):
            if key in payload:
                result[key] = payload[key]
        if "status_code" in payload:
            result["container_status_code"] = payload["status_code"]
        if "status" in payload:
            result["container_status"] = payload["status"]
    if not ok:
        if isinstance(graph_error, dict):
            detail = graph_error.get("message") or graph_error.get("error_user_msg")
            result["graph_error"] = graph_error
        else:
            detail = graph_error
        result["error"] = str(
            detail or f"Instagram API returned HTTP {response.status_code}"
        )
    return result


def get_instagram_api_status(verify_credentials: bool = False) -> dict[str, Any]:
    """Report official Instagram API configuration without exposing secrets."""

    credentials = _instagram_api_credentials()
    result: dict[str, Any] = {
        "status": "configured"
        if credentials["access_token"] and credentials["user_id"]
        else "not_configured",
        "api_base_url": _instagram_api_base_url(),
        "timeout_seconds": _instagram_api_timeout(),
        "access_token_configured": bool(credentials["access_token"]),
        "user_id_configured": bool(credentials["user_id"]),
        "app_credentials_configured": bool(
            credentials["app_id"] and credentials["app_secret"]
        ),
        "account_requirement": "Instagram Business or Creator professional account",
        "recommended_permissions": [
            "instagram_business_basic",
            "instagram_business_content_publish",
            "instagram_business_manage_comments",
            "instagram_business_manage_insights",
        ],
    }
    if not verify_credentials:
        return result
    verification = get_instagram_api_profile()
    result["verification"] = verification
    result["status"] = "verified" if verification.get("ok") else "verification_failed"
    return result


def get_instagram_api_profile(
    user_id: str = "",
    fields: str = (
        "id,user_id,username,name,profile_picture_url,followers_count,"
        "follows_count,media_count,account_type"
    ),
) -> dict[str, Any]:
    """Get an owned Instagram professional account profile."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_user_id(user_id)}",
        params={"fields": str(fields or "").strip()},
    )


def get_instagram_api_media(
    user_id: str = "",
    limit: int = 25,
    after: str = "",
    fields: str = (
        "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,"
        "username,children{id,media_type,media_url,permalink,thumbnail_url}"
    ),
) -> dict[str, Any]:
    """List media owned by the configured Instagram professional account."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_user_id(user_id)}/media",
        params={
            "fields": str(fields or "").strip(),
            "limit": _coerce_limit(limit, default=25, minimum=1, maximum=100),
            "after": str(after or "").strip(),
        },
    )


def get_instagram_api_media_details(
    media_id: str,
    fields: str = (
        "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,"
        "username,comments_count,like_count,children{id,media_type,media_url}"
    ),
) -> dict[str, Any]:
    """Get one owned Instagram media object."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_object_id(media_id, 'media')}",
        params={"fields": str(fields or "").strip()},
    )


def get_instagram_api_comments(
    media_id: str,
    limit: int = 50,
    after: str = "",
    fields: str = "id,from,text,timestamp,hidden,like_count,parent_id,username",
) -> dict[str, Any]:
    """Get comments on an owned Instagram media object."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_object_id(media_id, 'media')}/comments",
        params={
            "fields": str(fields or "").strip(),
            "limit": _coerce_limit(limit, default=50, minimum=1, maximum=100),
            "after": str(after or "").strip(),
        },
    )


def get_instagram_api_comment_replies(
    comment_id: str,
    limit: int = 50,
    after: str = "",
    fields: str = "id,from,text,timestamp,hidden,like_count,username",
) -> dict[str, Any]:
    """Get replies to an Instagram comment."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_object_id(comment_id, 'comment')}/replies",
        params={
            "fields": str(fields or "").strip(),
            "limit": _coerce_limit(limit, default=50, minimum=1, maximum=100),
            "after": str(after or "").strip(),
        },
    )


def reply_instagram_api_comment(
    comment_id: str,
    message: str,
) -> dict[str, Any]:
    """Reply publicly to a comment on owned Instagram media."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Instagram comment reply cannot be empty.")
    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_object_id(comment_id, 'comment')}/replies",
        data={"message": clean_message},
    )


def set_instagram_api_comment_hidden(
    comment_id: str,
    hidden: bool = True,
) -> dict[str, Any]:
    """Hide or unhide a comment on owned Instagram media."""

    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_object_id(comment_id, 'comment')}",
        data={"hide": bool(hidden)},
    )


def delete_instagram_api_comment(comment_id: str) -> dict[str, Any]:
    """Delete a comment on owned Instagram media when permitted."""

    return _instagram_api_request(
        "DELETE",
        f"/{_instagram_api_object_id(comment_id, 'comment')}",
    )


def set_instagram_api_comments_enabled(
    media_id: str,
    enabled: bool = True,
) -> dict[str, Any]:
    """Enable or disable comments on an owned Instagram media object."""

    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_object_id(media_id, 'media')}",
        data={"comments": bool(enabled)},
    )


def get_instagram_api_account_insights(
    metrics: str = "reach,views,accounts_engaged,total_interactions",
    period: str = "day",
    user_id: str = "",
    since: str = "",
    until: str = "",
) -> dict[str, Any]:
    """Get account-level insights for an Instagram professional account."""

    normalized_period = str(period or "day").strip().lower()
    if normalized_period not in {"day", "week", "days_28", "lifetime"}:
        raise ValueError("Unsupported Instagram insights period.")
    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_user_id(user_id)}/insights",
        params={
            "metric": str(metrics or "").strip(),
            "period": normalized_period,
            "since": str(since or "").strip(),
            "until": str(until or "").strip(),
        },
    )


def get_instagram_api_media_insights(
    media_id: str,
    metrics: str = "reach,views,likes,comments,saved,shares,total_interactions",
) -> dict[str, Any]:
    """Get insights for an owned Instagram media object."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_object_id(media_id, 'media')}/insights",
        params={"metric": str(metrics or "").strip()},
    )


def create_instagram_api_image_container(
    image_url: str,
    caption: str = "",
    user_id: str = "",
    is_carousel_item: bool = False,
) -> dict[str, Any]:
    """Create an Instagram image publishing container from a public URL."""

    parsed = urlparse(str(image_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("image_url must be a public HTTP(S) URL.")
    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_user_id(user_id)}/media",
        data={
            "image_url": image_url,
            "caption": str(caption or ""),
            "is_carousel_item": bool(is_carousel_item),
        },
    )


def create_instagram_api_reel_container(
    video_url: str,
    caption: str = "",
    user_id: str = "",
    share_to_feed: bool = True,
    cover_url: str = "",
    is_carousel_item: bool = False,
) -> dict[str, Any]:
    """Create an Instagram Reel/video publishing container from a public URL."""

    parsed = urlparse(str(video_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("video_url must be a public HTTP(S) URL.")
    if cover_url:
        cover = urlparse(cover_url)
        if cover.scheme not in {"http", "https"} or not cover.netloc:
            raise ValueError("cover_url must be a public HTTP(S) URL.")
    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_user_id(user_id)}/media",
        data={
            "media_type": "VIDEO" if is_carousel_item else "REELS",
            "video_url": video_url,
            "caption": str(caption or ""),
            "share_to_feed": bool(share_to_feed),
            "cover_url": str(cover_url or "").strip(),
            "is_carousel_item": bool(is_carousel_item),
        },
    )


def create_instagram_api_story_container(
    media_url: str,
    media_type: str = "image",
    user_id: str = "",
) -> dict[str, Any]:
    """Create an Instagram Story image or video publishing container."""

    parsed = urlparse(str(media_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("media_url must be a public HTTP(S) URL.")
    normalized_type = str(media_type or "image").strip().lower()
    if normalized_type not in {"image", "video"}:
        raise ValueError("media_type must be image or video.")
    field = "image_url" if normalized_type == "image" else "video_url"
    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_user_id(user_id)}/media",
        data={"media_type": "STORIES", field: media_url},
    )


def create_instagram_api_carousel_container(
    child_container_ids: str,
    caption: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Create a carousel container from 2–10 completed child container IDs."""

    children = [
        _instagram_api_object_id(value.strip(), "container")
        for value in str(child_container_ids or "").split(",")
        if value.strip()
    ]
    if not 2 <= len(children) <= 10:
        raise ValueError("A carousel requires 2 to 10 child container IDs.")
    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_user_id(user_id)}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": str(caption or ""),
        },
    )


def get_instagram_api_container_status(
    container_id: str,
) -> dict[str, Any]:
    """Get an Instagram publishing container's processing status."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_object_id(container_id, 'container')}",
        params={"fields": "id,status_code,status"},
    )


def publish_instagram_api_container(
    container_id: str,
    user_id: str = "",
) -> dict[str, Any]:
    """Publish a finished Instagram media container."""

    return _instagram_api_request(
        "POST",
        f"/{_instagram_api_user_id(user_id)}/media_publish",
        data={"creation_id": _instagram_api_object_id(container_id, "container")},
    )


def _wait_for_instagram_api_container(
    container_id: str,
    timeout_seconds: int = 120,
    poll_interval: int = 5,
) -> dict[str, Any]:
    deadline = time.time() + max(5, min(int(timeout_seconds), 600))
    interval = max(2, min(int(poll_interval), 30))
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = get_instagram_api_container_status(container_id)
        if not latest.get("ok"):
            return latest
        status_code = str(latest.get("container_status_code") or "").upper()
        if status_code == "FINISHED":
            return latest
        if status_code in {"ERROR", "EXPIRED"}:
            return _instagram_api_error(
                f"Instagram container entered {status_code} state.",
                endpoint=latest.get("endpoint", ""),
                status_code=int(latest.get("status_code", 0) or 0)
                if isinstance(latest.get("status_code"), int)
                else 0,
                response=latest.get("response"),
            )
        time.sleep(interval)
    return _instagram_api_error(
        "Timed out waiting for Instagram media processing.",
        response=latest.get("response") if latest else None,
    )


def publish_instagram_api_image(
    image_url: str,
    caption: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Create and publish an Instagram image Post from a public image URL."""

    created = create_instagram_api_image_container(
        image_url=image_url,
        caption=caption,
        user_id=user_id,
    )
    if not created.get("ok"):
        return {"status": "create_failed", "create": created}
    container_id = str(created.get("id") or "")
    if not container_id:
        return {
            "status": "create_failed",
            "create": created,
            "error": "Instagram returned no container ID.",
        }
    published = publish_instagram_api_container(container_id, user_id=user_id)
    return {
        "status": "published" if published.get("ok") else "publish_failed",
        "container_id": container_id,
        "create": created,
        "publish": published,
    }


def publish_instagram_api_reel(
    video_url: str,
    caption: str = "",
    user_id: str = "",
    share_to_feed: bool = True,
    cover_url: str = "",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Create, await, and publish an Instagram Reel from a public video URL."""

    created = create_instagram_api_reel_container(
        video_url=video_url,
        caption=caption,
        user_id=user_id,
        share_to_feed=share_to_feed,
        cover_url=cover_url,
    )
    if not created.get("ok"):
        return {"status": "create_failed", "create": created}
    container_id = str(created.get("id") or "")
    if not container_id:
        return {
            "status": "create_failed",
            "create": created,
            "error": "Instagram returned no container ID.",
        }
    processing = _wait_for_instagram_api_container(
        container_id,
        timeout_seconds=timeout_seconds,
    )
    if not processing.get("ok"):
        return {
            "status": "processing_failed",
            "container_id": container_id,
            "create": created,
            "processing": processing,
        }
    published = publish_instagram_api_container(container_id, user_id=user_id)
    return {
        "status": "published" if published.get("ok") else "publish_failed",
        "container_id": container_id,
        "create": created,
        "processing": processing,
        "publish": published,
    }


def publish_instagram_api_story(
    media_url: str,
    media_type: str = "image",
    user_id: str = "",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Create, await when needed, and publish an Instagram Story."""

    created = create_instagram_api_story_container(
        media_url=media_url,
        media_type=media_type,
        user_id=user_id,
    )
    if not created.get("ok"):
        return {"status": "create_failed", "create": created}
    container_id = str(created.get("id") or "")
    if not container_id:
        return {
            "status": "create_failed",
            "create": created,
            "error": "Instagram returned no container ID.",
        }
    processing: dict[str, Any] = {"ok": True, "status": "not_required"}
    if str(media_type or "image").lower() == "video":
        processing = _wait_for_instagram_api_container(
            container_id,
            timeout_seconds=timeout_seconds,
        )
        if not processing.get("ok"):
            return {
                "status": "processing_failed",
                "container_id": container_id,
                "create": created,
                "processing": processing,
            }
    published = publish_instagram_api_container(container_id, user_id=user_id)
    return {
        "status": "published" if published.get("ok") else "publish_failed",
        "container_id": container_id,
        "create": created,
        "processing": processing,
        "publish": published,
    }


def get_instagram_api_publishing_limit(
    user_id: str = "",
) -> dict[str, Any]:
    """Get the professional account's content publishing quota usage."""

    return _instagram_api_request(
        "GET",
        f"/{_instagram_api_user_id(user_id)}/content_publishing_limit",
        params={"fields": "config,quota_usage"},
    )


INSTAGRAM_BROWSER_TOOLS = [
    get_instagram_browser_status,
    launch_instagram_browser,
    close_instagram_browser,
    open_instagram_page,
    scan_instagram_posts,
    snapshot_instagram_feed,
    search_instagram,
    inspect_instagram_profile,
    inspect_instagram_post,
    like_instagram_post,
    unlike_instagram_post,
    save_instagram_post,
    unsave_instagram_post,
    follow_instagram_account,
    unfollow_instagram_account,
    comment_instagram_post,
    send_instagram_message,
    publish_instagram_post,
]


INSTAGRAM_API_TOOLS = [
    get_instagram_api_status,
    get_instagram_api_profile,
    get_instagram_api_media,
    get_instagram_api_media_details,
    get_instagram_api_comments,
    get_instagram_api_comment_replies,
    reply_instagram_api_comment,
    set_instagram_api_comment_hidden,
    delete_instagram_api_comment,
    set_instagram_api_comments_enabled,
    get_instagram_api_account_insights,
    get_instagram_api_media_insights,
    create_instagram_api_image_container,
    create_instagram_api_reel_container,
    create_instagram_api_story_container,
    create_instagram_api_carousel_container,
    get_instagram_api_container_status,
    publish_instagram_api_container,
    publish_instagram_api_image,
    publish_instagram_api_reel,
    publish_instagram_api_story,
    get_instagram_api_publishing_limit,
]


INSTAGRAM_TOOLS = [*INSTAGRAM_BROWSER_TOOLS, *INSTAGRAM_API_TOOLS]


__all__ = [
    "INSTAGRAM_BROWSER_TOOLS",
    "INSTAGRAM_API_TOOLS",
    "INSTAGRAM_TOOLS",
    *(tool.__name__ for tool in INSTAGRAM_TOOLS),
]

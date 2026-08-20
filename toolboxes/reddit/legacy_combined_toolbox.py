"""[MODE: HYBRID — Browser + Official API] Reddit toolbox.

Browser tools operate on the project's shared Selenium session and expect the
user to sign in through Reddit normally. API tools call Reddit directly:

* OAuth tokens: ``https://www.reddit.com/api/v1/access_token``
* API requests: ``https://oauth.reddit.com``

Set a truthful, unique ``REDDIT_USER_AGENT``. Authentication may be supplied as
``REDDIT_ACCESS_TOKEN``; ``REDDIT_CLIENT_ID`` + ``REDDIT_CLIENT_SECRET`` +
``REDDIT_REFRESH_TOKEN``; or personal-script username/password credentials.
App-only client credentials can perform eligible read operations.

The toolbox is intended for low-volume, supervised use that complies with
Reddit's Developer Terms, Data API Terms, community rules, and rate limits.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

import requests
from requests.auth import HTTPBasicAuth
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
    browser_git,
    browser_kapat,
    get_browser_runtime_state,
)

# Browser tools require a normal logged-in Selenium session. API tools use
# Reddit OAuth credentials (or an access token) and REDDIT_USER_AGENT.
TOOLBOX_ACCESS_MODE = "hybrid"


_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_REDDIT_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, "workspace", "social")
_REDDIT_SNAPSHOT_PATH = os.path.join(_REDDIT_WORKSPACE_DIR, "reddit_feed_snapshot.json")
_DEFAULT_REDDIT_API_BASE_URL = "https://oauth.reddit.com"
_DEFAULT_REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_DEFAULT_REDDIT_TIMEOUT = 30
_TOKEN_CACHE: dict[str, Any] = {
    "access_token": "",
    "expires_at": 0.0,
    "credential_fingerprint": "",
    "token_type": "",
    "scope": "",
}

_REDDIT_POST_SELECTORS = (
    "shreddit-post",
    "article[data-testid='post-container']",
    "div[data-testid='post-container']",
)
_REDDIT_COMMENT_SELECTORS = (
    "shreddit-comment",
    "div[data-testid='comment']",
    "article[data-testid='comment']",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_limit(
    value: Any,
    default: int = 10,
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


def _first_environment_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _normalize_subreddit(value: str) -> str:
    text = str(value or "").strip()
    if "://" in text:
        match = re.search(r"(?:www\.|old\.)?reddit\.com/r/([A-Za-z0-9_]{2,21})", text, re.I)
        text = match.group(1) if match else ""
    text = re.sub(r"^(?:/?r/|@)", "", text, flags=re.I).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", text):
        raise ValueError("A valid subreddit name is required.")
    return text


def _normalize_reddit_username(value: str) -> str:
    text = str(value or "").strip()
    if "://" in text:
        match = re.search(r"(?:www\.|old\.)?reddit\.com/u(?:ser)?/([A-Za-z0-9_-]{1,20})", text, re.I)
        text = match.group(1) if match else ""
    text = re.sub(r"^(?:/?u(?:ser)?/|@)", "", text, flags=re.I).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", text):
        raise ValueError("A valid Reddit username is required.")
    return text


def _normalize_reddit_url(value: str, *, require_post: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("A Reddit URL is required.")
    if text.startswith("/"):
        text = f"https://www.reddit.com{text}"
    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"}:
        raise ValueError("Only reddit.com or redd.it URLs are accepted.")
    if require_post and "/comments/" not in parsed.path and hostname != "redd.it":
        raise ValueError("A Reddit Post or comment URL is required.")
    return text


def _reddit_post_id(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"(?:t3_)?[A-Za-z0-9]{1,12}", text):
        return text.removeprefix("t3_").lower()
    match = re.search(r"(?:/comments/|redd\.it/)([A-Za-z0-9]{1,12})", text, re.I)
    if not match:
        raise ValueError("A valid Reddit Post ID, fullname, or URL is required.")
    return match.group(1).lower()


def _reddit_fullname(value: str, default_kind: str = "t3") -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"t[1-6]_[A-Za-z0-9]{1,12}", text):
        return text.lower()
    if "://" in text or text.startswith("/"):
        post_id = _reddit_post_id(text)
        parsed = urlparse(_normalize_reddit_url(text, require_post=True))
        parts = [part for part in parsed.path.split("/") if part]
        try:
            comments_index = parts.index("comments")
        except ValueError:
            comments_index = -1
        if comments_index >= 0 and len(parts) >= comments_index + 4:
            possible_comment_id = parts[comments_index + 3]
            if re.fullmatch(r"[A-Za-z0-9]{1,12}", possible_comment_id):
                return f"t1_{possible_comment_id.lower()}"
        return f"t3_{post_id}"
    if not re.fullmatch(r"[A-Za-z0-9]{1,12}", text):
        raise ValueError("A valid Reddit thing ID or fullname is required.")
    if default_kind not in {"t1", "t3", "t4"}:
        raise ValueError("default_kind must be t1, t3, or t4.")
    return f"{default_kind}_{text.lower()}"


def _reddit_page_ready(driver) -> bool:
    try:
        return driver.execute_script(
            """
            return document.readyState !== 'loading' &&
              !!document.querySelector(
                "shreddit-app, shreddit-post, article, main, #siteTable"
              );
            """
        )
    except Exception:
        return False


def _wait_for_reddit(url: str, timeout: int = 20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_reddit_page_ready)
    except TimeoutException:
        pass
    current_url = str(driver.current_url or "")
    if "reddit.com/login" in current_url:
        raise RuntimeError("Reddit requires login. Complete login in the shared browser session.")
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


def _find_button_by_text(
    driver,
    markers: tuple[str, ...],
    *,
    root=None,
    require_enabled: bool = True,
):
    normalized_markers = tuple(marker.casefold() for marker in markers)
    scope = root or driver
    selectors = "button, [role='button'], faceplate-tracker, a"
    for element in scope.find_elements(By.CSS_SELECTOR, selectors):
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
                    element.get_attribute("data-testid") or "",
                    element.get_attribute("action") or "",
                )
            ).casefold()
            if any(marker in combined for marker in normalized_markers):
                return element
        except Exception:
            continue
    return None


def _collect_reddit_posts(driver, limit: int = 20) -> list[dict[str, Any]]:
    return driver.execute_script(
        """
        const limit = arguments[0];
        const selectors = [
          'shreddit-post',
          "article[data-testid='post-container']",
          "div[data-testid='post-container']"
        ];
        const seen = new Set();
        const nodes = selectors.flatMap((selector) => [...document.querySelectorAll(selector)]);
        const results = [];
        const text = (root, selector) => {
          const node = root.querySelector(selector);
          return (node?.innerText || node?.textContent || '').trim();
        };
        for (const node of nodes) {
          if (results.length >= limit) break;
          const permalink =
            node.getAttribute('permalink') ||
            node.querySelector("a[href*='/comments/']")?.getAttribute('href') || '';
          const canonical = permalink.startsWith('http')
            ? permalink
            : permalink ? `https://www.reddit.com${permalink}` : '';
          const postId =
            node.getAttribute('id') ||
            node.getAttribute('thingid') ||
            (canonical.match(/\\/comments\\/([a-z0-9]+)/i) || [])[1] || '';
          const key = postId || canonical;
          if (!key || seen.has(key)) continue;
          seen.add(key);
          const title =
            node.getAttribute('post-title') ||
            text(node, '[slot="title"]') ||
            text(node, 'h1, h2, h3');
          const author =
            node.getAttribute('author') ||
            text(node, "a[href*='/user/'], a[href*='/u/']");
          const subreddit =
            node.getAttribute('subreddit-prefixed-name') ||
            node.getAttribute('subreddit-name') ||
            text(node, "a[href^='/r/']");
          const body =
            node.getAttribute('content-href') ||
            text(node, '[slot="text-body"]') ||
            text(node, '[data-post-click-location="text-body"]');
          const score =
            node.getAttribute('score') ||
            text(node, '[slot="vote-button"]') ||
            text(node, '[data-testid="post-container"] [id*="vote"]');
          results.push({
            post_id: String(postId).replace(/^t3_/, ''),
            fullname: String(postId).startsWith('t3_') ? postId : postId ? `t3_${postId}` : '',
            title,
            body,
            author: String(author).replace(/^u\\//, ''),
            subreddit: String(subreddit).replace(/^r\\//, ''),
            score,
            comments: text(node, "a[href*='/comments/']"),
            url: canonical,
          });
        }
        return results;
        """,
        _coerce_limit(limit, default=20, minimum=1, maximum=100),
    ) or []


def _collect_reddit_comments(driver, limit: int = 50) -> list[dict[str, Any]]:
    return driver.execute_script(
        """
        const limit = arguments[0];
        const nodes = [
          ...document.querySelectorAll(
            "shreddit-comment, div[data-testid='comment'], article[data-testid='comment']"
          )
        ];
        const seen = new Set();
        const results = [];
        for (const node of nodes) {
          if (results.length >= limit) break;
          const id =
            node.getAttribute('thingid') ||
            node.getAttribute('id') ||
            node.getAttribute('comment-id') || '';
          if (id && seen.has(id)) continue;
          if (id) seen.add(id);
          const author =
            node.getAttribute('author') ||
            node.querySelector("a[href*='/user/'], a[href*='/u/']")?.textContent || '';
          const bodyNode = node.querySelector(
            '[slot="comment"], [data-testid="comment"], .md, [id*="-post-rtjson-content"]'
          );
          const permalink = node.querySelector("a[href*='/comments/']")?.getAttribute('href') || '';
          results.push({
            comment_id: String(id).replace(/^t1_/, ''),
            fullname: String(id).startsWith('t1_') ? id : id ? `t1_${id}` : '',
            author: String(author).trim().replace(/^u\\//, ''),
            body: (bodyNode?.innerText || bodyNode?.textContent || '').trim(),
            score: node.getAttribute('score') || '',
            url: permalink.startsWith('http')
              ? permalink
              : permalink ? `https://www.reddit.com${permalink}` : '',
          });
        }
        return results;
        """,
        _coerce_limit(limit, default=50, minimum=1, maximum=100),
    ) or []


def get_reddit_browser_status() -> dict[str, Any]:
    """Return shared browser status and whether it is currently on Reddit."""

    state = get_browser_runtime_state()
    if not state.get("ready"):
        return {**state, "platform": "reddit", "url": "", "title": "", "on_reddit": False}
    driver = _get_driver()
    url = str(driver.current_url or "")
    return {
        **state,
        "platform": "reddit",
        "url": url,
        "title": str(driver.title or ""),
        "on_reddit": "reddit.com" in urlparse(url).netloc.lower(),
    }


def launch_reddit_browser(
    headless: bool = False,
    restart_if_needed: bool = True,
) -> dict[str, Any]:
    """Launch the shared browser and open Reddit."""

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
                "platform": "reddit",
                "error": launch_result or "Browser could not be launched.",
            }
    driver = _wait_for_reddit("https://www.reddit.com/", timeout=20)
    return {
        "status": "ready",
        "platform": "reddit",
        "url": str(driver.current_url or ""),
        "title": str(driver.title or ""),
        "launch_result": launch_result,
        **get_browser_runtime_state(),
    }


def close_reddit_browser() -> dict[str, Any]:
    """Close the shared browser session."""

    result = browser_kapat()
    return {"status": "closed", "platform": "reddit", "result": result}


def open_reddit_page(
    destination: str = "home",
    subreddit: str = "",
    query: str = "",
    username: str = "",
    post_url: str = "",
    sort: str = "hot",
    time_filter: str = "all",
) -> dict[str, Any]:
    """Open a Reddit home, community, search, profile, inbox, or Post page."""

    target = str(destination or "home").strip().casefold()
    normalized_sort = str(sort or "hot").strip().lower()
    if normalized_sort not in {"hot", "new", "top", "rising", "controversial"}:
        raise ValueError("sort must be hot, new, top, rising, or controversial.")
    normalized_time = str(time_filter or "all").strip().lower()
    if normalized_time not in {"hour", "day", "week", "month", "year", "all"}:
        raise ValueError("time_filter must be hour, day, week, month, year, or all.")

    if target in {"home", "frontpage", "ana sayfa"}:
        url = f"https://www.reddit.com/{normalized_sort}/"
    elif target in {"popular"}:
        url = f"https://www.reddit.com/r/popular/{normalized_sort}/"
    elif target in {"all"}:
        url = f"https://www.reddit.com/r/all/{normalized_sort}/"
    elif target in {"subreddit", "community", "topluluk"}:
        sr = _normalize_subreddit(subreddit)
        url = f"https://www.reddit.com/r/{quote(sr, safe='')}/{normalized_sort}/"
    elif target in {"search", "ara"}:
        if not str(query or "").strip():
            raise ValueError("A Reddit search query is required.")
        scope = f"r/{_normalize_subreddit(subreddit)}/" if subreddit else ""
        url = (
            f"https://www.reddit.com/{scope}search/?q={quote_plus(query.strip())}"
            f"&sort={normalized_sort}&t={normalized_time}"
        )
    elif target in {"profile", "user", "kullanici"}:
        user = _normalize_reddit_username(username)
        url = f"https://www.reddit.com/user/{quote(user, safe='')}/"
    elif target in {"post", "comments", "comment"}:
        url = _normalize_reddit_url(post_url, require_post=True)
    elif target in {"inbox", "messages"}:
        url = "https://www.reddit.com/message/inbox/"
    elif target in {"notifications", "bildirimler"}:
        url = "https://www.reddit.com/notifications/"
    elif target in {"saved", "kaydedilenler"}:
        url = "https://www.reddit.com/user/me/saved/"
    elif target in {"submit", "create", "new post", "post olustur"}:
        sr = _normalize_subreddit(subreddit)
        url = f"https://www.reddit.com/r/{quote(sr, safe='')}/submit/"
    else:
        url = _normalize_reddit_url(destination)

    driver = _wait_for_reddit(url)
    return {
        "status": "opened",
        "destination": target,
        "url": str(driver.current_url or ""),
        "title": str(driver.title or ""),
    }


def scan_reddit_posts(limit: int = 20) -> dict[str, Any]:
    """Extract visible Posts from the current Reddit page."""

    driver = _get_driver()
    posts = _collect_reddit_posts(driver, limit=limit)
    return {
        "status": "ok",
        "source_url": str(driver.current_url or ""),
        "count": len(posts),
        "posts": posts,
    }


def snapshot_reddit_feed(
    destination: str = "home",
    subreddit: str = "",
    sort: str = "hot",
    limit: int = 20,
    write_to_file: bool = True,
) -> dict[str, Any]:
    """Open and snapshot a Reddit listing, optionally writing workspace JSON."""

    opened = open_reddit_page(destination=destination, subreddit=subreddit, sort=sort)
    snapshot = scan_reddit_posts(limit=limit)
    result = {
        "captured_at": _now(),
        "opened": opened,
        **snapshot,
    }
    if write_to_file:
        os.makedirs(_REDDIT_WORKSPACE_DIR, exist_ok=True)
        with open(_REDDIT_SNAPSHOT_PATH, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        result["snapshot_path"] = _REDDIT_SNAPSHOT_PATH
    return result


def search_reddit_posts(
    query: str,
    subreddit: str = "",
    sort: str = "relevance",
    time_filter: str = "all",
    limit: int = 20,
) -> dict[str, Any]:
    """Search Reddit in the browser and extract visible results."""

    normalized_sort = str(sort or "relevance").lower()
    if normalized_sort not in {"relevance", "hot", "top", "new", "comments"}:
        raise ValueError("sort must be relevance, hot, top, new, or comments.")
    opened = open_reddit_page(
        destination="search",
        subreddit=subreddit,
        query=query,
        sort="hot" if normalized_sort == "relevance" else normalized_sort,
        time_filter=time_filter,
    )
    driver = _get_driver()
    if normalized_sort == "relevance":
        scope = f"r/{_normalize_subreddit(subreddit)}/" if subreddit else ""
        url = (
            f"https://www.reddit.com/{scope}search/?q={quote_plus(query.strip())}"
            f"&sort=relevance&t={time_filter}"
        )
        driver = _wait_for_reddit(url)
        opened["url"] = str(driver.current_url or "")
    posts = _collect_reddit_posts(driver, limit=limit)
    return {"status": "ok", "opened": opened, "count": len(posts), "posts": posts}


def inspect_reddit_post(
    post_url: str,
    comment_limit: int = 50,
) -> dict[str, Any]:
    """Open a Reddit Post and extract the Post plus visible comments."""

    target_url = _normalize_reddit_url(post_url, require_post=True)
    driver = _wait_for_reddit(target_url)
    posts = _collect_reddit_posts(driver, limit=1)
    comments = _collect_reddit_comments(driver, limit=comment_limit)
    return {
        "status": "ok",
        "url": str(driver.current_url or ""),
        "post": posts[0] if posts else {},
        "comment_count": len(comments),
        "comments": comments,
    }


def inspect_reddit_profile(username: str, limit: int = 20) -> dict[str, Any]:
    """Open a Reddit profile and extract visible activity."""

    user = _normalize_reddit_username(username)
    driver = _wait_for_reddit(f"https://www.reddit.com/user/{quote(user, safe='')}/")
    posts = _collect_reddit_posts(driver, limit=limit)
    body = str(driver.find_element(By.TAG_NAME, "body").text or "")
    return {
        "status": "ok",
        "username": user,
        "url": str(driver.current_url or ""),
        "profile_summary": _compact_text(body, 1200),
        "posts": posts,
    }


def inspect_reddit_community(subreddit: str, limit: int = 20) -> dict[str, Any]:
    """Open a subreddit and extract its visible summary and Posts."""

    sr = _normalize_subreddit(subreddit)
    driver = _wait_for_reddit(f"https://www.reddit.com/r/{quote(sr, safe='')}/")
    posts = _collect_reddit_posts(driver, limit=limit)
    body = str(driver.find_element(By.TAG_NAME, "body").text or "")
    return {
        "status": "ok",
        "subreddit": sr,
        "url": str(driver.current_url or ""),
        "community_summary": _compact_text(body, 1500),
        "posts": posts,
    }


def _reddit_browser_post_action(
    post_url: str,
    selectors: tuple[str, ...],
    markers: tuple[str, ...],
    action: str,
) -> dict[str, Any]:
    driver = _wait_for_reddit(_normalize_reddit_url(post_url, require_post=True))
    element = _find_visible(driver, selectors, require_enabled=True)
    if element is None:
        element = _find_button_by_text(driver, markers, require_enabled=True)
    if element is None:
        return {
            "status": "error",
            "action": action,
            "url": str(driver.current_url or ""),
            "error": f"Could not locate Reddit {action} control.",
        }
    _human_click(driver, element)
    time.sleep(0.7)
    return {
        "status": "attempted",
        "action": action,
        "url": str(driver.current_url or ""),
        "post_id": _reddit_post_id(post_url),
    }


def upvote_reddit_post(post_url: str) -> dict[str, Any]:
    """Upvote a Reddit Post through the browser."""

    return _reddit_browser_post_action(
        post_url,
        (
            "button[aria-label*='upvote' i]",
            "[data-testid='upvote-button']",
            "faceplate-tracker[noun='upvote'] button",
        ),
        ("upvote", "up vote"),
        "upvote",
    )


def downvote_reddit_post(post_url: str) -> dict[str, Any]:
    """Downvote a Reddit Post through the browser."""

    return _reddit_browser_post_action(
        post_url,
        (
            "button[aria-label*='downvote' i]",
            "[data-testid='downvote-button']",
            "faceplate-tracker[noun='downvote'] button",
        ),
        ("downvote", "down vote"),
        "downvote",
    )


def clear_reddit_post_vote(post_url: str) -> dict[str, Any]:
    """Clear the current vote by clicking the selected vote control."""

    return _reddit_browser_post_action(
        post_url,
        (
            "button[aria-pressed='true'][aria-label*='vote' i]",
            "[data-testid='upvote-button'][aria-pressed='true']",
            "[data-testid='downvote-button'][aria-pressed='true']",
        ),
        ("remove upvote", "remove downvote"),
        "clear_vote",
    )


def save_reddit_post(post_url: str) -> dict[str, Any]:
    """Save a Reddit Post through the browser."""

    return _reddit_browser_post_action(
        post_url,
        (
            "button[aria-label='Save' i]",
            "[data-testid='save-button']",
        ),
        ("save",),
        "save",
    )


def unsave_reddit_post(post_url: str) -> dict[str, Any]:
    """Remove a Reddit Post from saved items through the browser."""

    return _reddit_browser_post_action(
        post_url,
        (
            "button[aria-label='Unsave' i]",
            "[data-testid='unsave-button']",
        ),
        ("unsave",),
        "unsave",
    )


def _reddit_browser_community_action(
    subreddit: str,
    *,
    join: bool,
) -> dict[str, Any]:
    sr = _normalize_subreddit(subreddit)
    driver = _wait_for_reddit(f"https://www.reddit.com/r/{quote(sr, safe='')}/")
    markers = ("join", "katıl") if join else ("joined", "leave", "ayrıl")
    element = _find_button_by_text(driver, markers, require_enabled=True)
    if element is None:
        return {
            "status": "error",
            "action": "join" if join else "leave",
            "subreddit": sr,
            "error": "Could not locate the subreddit membership control.",
        }
    label = " ".join(
        (element.text or "", element.get_attribute("aria-label") or "")
    ).casefold()
    if join and ("joined" in label or "katıld" in label):
        return {"status": "already_joined", "subreddit": sr}
    _human_click(driver, element)
    time.sleep(0.7)
    return {
        "status": "attempted",
        "action": "join" if join else "leave",
        "subreddit": sr,
        "url": str(driver.current_url or ""),
    }


def join_reddit_community(subreddit: str) -> dict[str, Any]:
    """Join a subreddit through the browser."""

    return _reddit_browser_community_action(subreddit, join=True)


def leave_reddit_community(subreddit: str) -> dict[str, Any]:
    """Leave a subreddit through the browser."""

    return _reddit_browser_community_action(subreddit, join=False)


def _fill_reddit_submit_form(
    subreddit: str,
    title: str,
    *,
    body: str = "",
    url: str = "",
) -> dict[str, Any]:
    sr = _normalize_subreddit(subreddit)
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("Reddit Post title cannot be empty.")
    driver = _wait_for_reddit(f"https://www.reddit.com/r/{quote(sr, safe='')}/submit/")

    if url:
        tab = _find_button_by_text(driver, ("link",), require_enabled=True)
        if tab is not None:
            _human_click(driver, tab)
            time.sleep(0.5)
    elif body:
        tab = _find_button_by_text(driver, ("text", "post"), require_enabled=True)
        if tab is not None:
            _human_click(driver, tab)
            time.sleep(0.5)

    title_element = _find_visible(
        driver,
        (
            "textarea[name='title']",
            "input[name='title']",
            "textarea[placeholder*='title' i]",
            "input[placeholder*='title' i]",
        ),
        require_enabled=True,
    )
    if title_element is None:
        raise RuntimeError("Could not locate Reddit's Post title field.")
    _type_into_element(driver, title_element, clean_title)

    if url:
        url_element = _find_visible(
            driver,
            (
                "input[name='url']",
                "textarea[name='url']",
                "input[placeholder*='url' i]",
                "textarea[placeholder*='url' i]",
            ),
            require_enabled=True,
        )
        if url_element is None:
            raise RuntimeError("Could not locate Reddit's link URL field.")
        _type_into_element(driver, url_element, url)
    elif body:
        body_element = _find_visible(
            driver,
            (
                "div[contenteditable='true'][role='textbox']",
                "textarea[name='text']",
                "textarea[placeholder*='body' i]",
                "textarea[placeholder*='text' i]",
            ),
            require_enabled=True,
        )
        if body_element is None:
            raise RuntimeError("Could not locate Reddit's Post body editor.")
        _type_into_element(driver, body_element, body)

    submit = _find_visible(
        driver,
        (
            "button[type='submit']",
            "button[data-testid='submit-post-button']",
        ),
        require_enabled=True,
    )
    if submit is None:
        submit = _find_button_by_text(
            driver,
            ("post", "submit", "gönder"),
            require_enabled=True,
        )
    if submit is None:
        return {
            "status": "drafted",
            "subreddit": sr,
            "title": clean_title,
            "url": str(driver.current_url or ""),
            "warning": "Form filled, but the final submit control was not found.",
        }
    _human_click(driver, submit)
    time.sleep(1.2)
    current_url = str(driver.current_url or "")
    return {
        "status": "submitted" if "/comments/" in current_url else "pending_verify",
        "subreddit": sr,
        "title": clean_title,
        "url": current_url,
        "post_id": _reddit_post_id(current_url) if "/comments/" in current_url else "",
    }


def publish_reddit_text_post(
    subreddit: str,
    title: str,
    body: str = "",
) -> dict[str, Any]:
    """Publish a text Post through Reddit's browser composer."""

    return _fill_reddit_submit_form(subreddit, title, body=str(body or ""))


def publish_reddit_link_post(
    subreddit: str,
    title: str,
    url: str,
) -> dict[str, Any]:
    """Publish a link Post through Reddit's browser composer."""

    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("A valid HTTP(S) link is required.")
    return _fill_reddit_submit_form(subreddit, title, url=url)


def comment_reddit_post(post_url: str, message: str) -> dict[str, Any]:
    """Comment on a Reddit Post through the browser."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Reddit comment cannot be empty.")
    driver = _wait_for_reddit(_normalize_reddit_url(post_url, require_post=True))
    editor = _find_visible(
        driver,
        (
            "div[contenteditable='true'][role='textbox']",
            "textarea[placeholder*='comment' i]",
            "textarea[name='comment']",
        ),
        require_enabled=True,
    )
    if editor is None:
        raise RuntimeError("Could not locate Reddit's comment editor.")
    _type_into_element(driver, editor, clean_message)
    submit = _find_button_by_text(
        driver,
        ("comment", "reply", "yorum", "yanıtla"),
        require_enabled=True,
    )
    if submit is None:
        return {
            "status": "drafted",
            "url": str(driver.current_url or ""),
            "warning": "Comment filled, but the submit control was not found.",
        }
    _human_click(driver, submit)
    time.sleep(1.0)
    return {
        "status": "attempted",
        "post_id": _reddit_post_id(post_url),
        "message": clean_message,
        "url": str(driver.current_url or ""),
    }


def reply_reddit_comment(comment_url: str, message: str) -> dict[str, Any]:
    """Reply to a Reddit comment through the browser."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Reddit reply cannot be empty.")
    target_url = _normalize_reddit_url(comment_url, require_post=True)
    driver = _wait_for_reddit(target_url)
    comment_fullname = _reddit_fullname(target_url)
    comment_id = comment_fullname.removeprefix("t1_")
    root = None
    for selector in (
        f"shreddit-comment[thingid='{comment_fullname}']",
        f"shreddit-comment[comment-id='{comment_id}']",
        f"#{comment_fullname}",
    ):
        root = _find_visible(driver, (selector,))
        if root is not None:
            break
    reply_button = _find_button_by_text(
        driver,
        ("reply", "yanıtla"),
        root=root,
        require_enabled=True,
    )
    if reply_button is None:
        return {
            "status": "error",
            "comment_fullname": comment_fullname,
            "error": "Could not locate the comment Reply control.",
        }
    _human_click(driver, reply_button)
    time.sleep(0.5)
    editor = _find_visible(
        driver,
        (
            "div[contenteditable='true'][role='textbox']",
            "textarea[placeholder*='reply' i]",
            "textarea[placeholder*='comment' i]",
        ),
        require_enabled=True,
    )
    if editor is None:
        raise RuntimeError("Could not locate Reddit's reply editor.")
    _type_into_element(driver, editor, clean_message)
    submit = _find_button_by_text(
        driver,
        ("comment", "reply", "yanıtla"),
        require_enabled=True,
    )
    if submit is None:
        return {
            "status": "drafted",
            "comment_fullname": comment_fullname,
            "warning": "Reply filled, but the submit control was not found.",
        }
    _human_click(driver, submit)
    time.sleep(1.0)
    return {
        "status": "attempted",
        "comment_fullname": comment_fullname,
        "message": clean_message,
        "url": str(driver.current_url or ""),
    }


def _reddit_api_credentials() -> dict[str, str]:
    return {
        "client_id": _first_environment_value("REDDIT_CLIENT_ID"),
        "client_secret": _first_environment_value("REDDIT_CLIENT_SECRET"),
        "access_token": _first_environment_value("REDDIT_ACCESS_TOKEN"),
        "refresh_token": _first_environment_value("REDDIT_REFRESH_TOKEN"),
        "username": _first_environment_value("REDDIT_USERNAME"),
        "password": _first_environment_value("REDDIT_PASSWORD"),
        "user_agent": _first_environment_value("REDDIT_USER_AGENT"),
    }


def _reddit_api_base_url() -> str:
    return (
        os.getenv("REDDIT_API_BASE_URL", _DEFAULT_REDDIT_API_BASE_URL).strip()
        or _DEFAULT_REDDIT_API_BASE_URL
    ).rstrip("/")


def _reddit_token_url() -> str:
    return (
        os.getenv("REDDIT_TOKEN_URL", _DEFAULT_REDDIT_TOKEN_URL).strip()
        or _DEFAULT_REDDIT_TOKEN_URL
    )


def _reddit_api_timeout() -> int:
    try:
        timeout = int(os.getenv("REDDIT_API_TIMEOUT", str(_DEFAULT_REDDIT_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_REDDIT_TIMEOUT
    return max(5, min(timeout, 120))


def _reddit_api_error(
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


def _reddit_credential_fingerprint(credentials: dict[str, str], token_type: str) -> str:
    material = "|".join(
        (
            token_type,
            credentials["client_id"],
            credentials["client_secret"],
            credentials["access_token"],
            credentials["refresh_token"],
            credentials["username"],
            credentials["password"],
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _reddit_access_token(require_user: bool = False) -> tuple[str, str, str]:
    credentials = _reddit_api_credentials()
    if not credentials["user_agent"]:
        raise RuntimeError(
            "REDDIT_USER_AGENT is required. Use a truthful value such as "
            "'linux:EthosMarketingAgent:1.0 (by /u/YourUsername)'."
        )

    if credentials["access_token"]:
        return credentials["access_token"], "provided_access_token", ""

    if not credentials["client_id"]:
        raise RuntimeError("REDDIT_CLIENT_ID is required to obtain an OAuth token.")

    if credentials["refresh_token"]:
        token_type = "refresh_token"
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": credentials["refresh_token"],
        }
    elif credentials["username"] and credentials["password"]:
        token_type = "password"
        token_data = {
            "grant_type": "password",
            "username": credentials["username"],
            "password": credentials["password"],
        }
    elif not require_user:
        token_type = "client_credentials"
        token_data = {"grant_type": "client_credentials"}
    else:
        raise RuntimeError(
            "A user-context token is required. Configure REDDIT_ACCESS_TOKEN, "
            "REDDIT_REFRESH_TOKEN, or REDDIT_USERNAME and REDDIT_PASSWORD."
        )

    fingerprint = _reddit_credential_fingerprint(credentials, token_type)
    if (
        _TOKEN_CACHE["access_token"]
        and _TOKEN_CACHE["credential_fingerprint"] == fingerprint
        and float(_TOKEN_CACHE["expires_at"]) > time.time() + 30
    ):
        return (
            str(_TOKEN_CACHE["access_token"]),
            str(_TOKEN_CACHE["token_type"]),
            str(_TOKEN_CACHE["scope"]),
        )

    response = requests.post(
        _reddit_token_url(),
        auth=HTTPBasicAuth(credentials["client_id"], credentials["client_secret"]),
        data=token_data,
        headers={
            "User-Agent": credentials["user_agent"],
            "Accept": "application/json",
        },
        timeout=_reddit_api_timeout(),
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:2000]}
    if not response.ok or not isinstance(payload, dict) or not payload.get("access_token"):
        detail = payload.get("error") if isinstance(payload, dict) else ""
        raise RuntimeError(
            str(detail or f"Reddit OAuth returned HTTP {response.status_code}")
        )

    expires_in = int(payload.get("expires_in", 3600) or 3600)
    _TOKEN_CACHE.update(
        {
            "access_token": str(payload["access_token"]),
            "expires_at": time.time() + max(60, expires_in),
            "credential_fingerprint": fingerprint,
            "token_type": token_type,
            "scope": str(payload.get("scope", "")),
        }
    )
    return str(payload["access_token"]), token_type, str(payload.get("scope", ""))


def _listing_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    children = data.get("children")
    if not isinstance(children, list):
        return []
    items: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_data = child.get("data")
        if not isinstance(child_data, dict):
            continue
        item = dict(child_data)
        item["kind"] = child.get("kind", "")
        items.append(item)
    return items


def _reddit_api_request(
    method: str,
    endpoint: str,
    *,
    require_user: bool = False,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_method = str(method or "GET").upper().strip()
    normalized_endpoint = "/" + str(endpoint or "").lstrip("/")
    if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return _reddit_api_error(
            f"Unsupported Reddit API method: {normalized_method}",
            endpoint=normalized_endpoint,
        )
    if "://" in normalized_endpoint or ".." in normalized_endpoint:
        return _reddit_api_error(
            "Reddit API endpoint must be a relative OAuth path.",
            endpoint=normalized_endpoint,
        )

    try:
        access_token, token_type, scope = _reddit_access_token(require_user=require_user)
    except (RuntimeError, requests.RequestException) as exc:
        return _reddit_api_error(str(exc), endpoint=normalized_endpoint)

    credentials = _reddit_api_credentials()
    clean_params = {
        "raw_json": 1,
        **{
            key: value
            for key, value in (params or {}).items()
            if value not in (None, "", [], ())
        },
    }
    clean_data = {"raw_json": 1}
    for key, value in (data or {}).items():
        if value in (None, "", [], ()):
            continue
        clean_data[key] = str(value).lower() if isinstance(value, bool) else value
    try:
        response = requests.request(
            normalized_method,
            f"{_reddit_api_base_url()}{normalized_endpoint}",
            params=clean_params if normalized_method == "GET" else None,
            data=clean_data if normalized_method != "GET" else None,
            headers={
                "Authorization": f"bearer {access_token}",
                "User-Agent": credentials["user_agent"],
                "Accept": "application/json",
            },
            timeout=_reddit_api_timeout(),
        )
    except requests.RequestException as exc:
        return _reddit_api_error(
            f"Reddit API request failed: {exc}",
            endpoint=normalized_endpoint,
        )

    try:
        payload: Any = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:4000]}

    api_errors: list[Any] = []
    if isinstance(payload, dict):
        json_block = payload.get("json")
        if isinstance(json_block, dict) and isinstance(json_block.get("errors"), list):
            api_errors = json_block["errors"]
    ok = bool(response.ok and not api_errors)
    result: dict[str, Any] = {
        "ok": ok,
        "status": "ok" if ok else "error",
        "status_code": response.status_code,
        "method": normalized_method,
        "endpoint": normalized_endpoint,
        "token_type": token_type,
        "scope": scope,
        "rate_limit": {
            "used": response.headers.get("x-ratelimit-used", ""),
            "remaining": response.headers.get("x-ratelimit-remaining", ""),
            "reset_seconds": response.headers.get("x-ratelimit-reset", ""),
        },
        "response": payload,
    }
    items = _listing_items(payload)
    if items:
        result["items"] = items
        result["count"] = len(items)
    if isinstance(payload, dict) and "data" in payload:
        result["data"] = payload["data"]
    if api_errors:
        result["errors"] = api_errors
    if not ok:
        if api_errors:
            detail = "; ".join(
                ": ".join(str(part) for part in error)
                if isinstance(error, (list, tuple))
                else str(error)
                for error in api_errors
            )
        elif isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error") or ""
        else:
            detail = ""
        result["error"] = str(
            detail or f"Reddit API returned HTTP {response.status_code}"
        )
    return result


def get_reddit_api_status(verify_credentials: bool = False) -> dict[str, Any]:
    """Report Reddit API configuration without exposing credential values."""

    credentials = _reddit_api_credentials()
    has_user_auth = bool(
        credentials["access_token"]
        or credentials["refresh_token"]
        or (credentials["username"] and credentials["password"])
    )
    configured = bool(
        credentials["user_agent"]
        and (
            credentials["access_token"]
            or credentials["client_id"]
        )
    )
    result: dict[str, Any] = {
        "status": "configured" if configured else "not_configured",
        "api_base_url": _reddit_api_base_url(),
        "token_url": _reddit_token_url(),
        "timeout_seconds": _reddit_api_timeout(),
        "user_agent_configured": bool(credentials["user_agent"]),
        "client_credentials_configured": bool(credentials["client_id"]),
        "provided_access_token_configured": bool(credentials["access_token"]),
        "refresh_token_configured": bool(credentials["refresh_token"]),
        "personal_script_credentials_configured": bool(
            credentials["username"] and credentials["password"]
        ),
        "user_actions_configured": has_user_auth,
    }
    if not verify_credentials:
        return result
    verification = get_reddit_api_me() if has_user_auth else get_reddit_api_listing(limit=1)
    result["verification"] = verification
    result["status"] = "verified" if verification.get("ok") else "verification_failed"
    return result


def get_reddit_api_me() -> dict[str, Any]:
    """Get the authenticated Reddit account."""

    return _reddit_api_request("GET", "/api/v1/me", require_user=True)


def get_reddit_api_listing(
    subreddit: str = "",
    sort: str = "hot",
    time_filter: str = "all",
    limit: int = 25,
    after: str = "",
) -> dict[str, Any]:
    """Get a Reddit front-page or subreddit listing through the Data API."""

    normalized_sort = str(sort or "hot").lower()
    if normalized_sort not in {"hot", "new", "top", "rising", "controversial", "best"}:
        raise ValueError("Invalid Reddit listing sort.")
    normalized_time = str(time_filter or "all").lower()
    if normalized_time not in {"hour", "day", "week", "month", "year", "all"}:
        raise ValueError("Invalid Reddit time_filter.")
    prefix = f"/r/{_normalize_subreddit(subreddit)}" if subreddit else ""
    return _reddit_api_request(
        "GET",
        f"{prefix}/{normalized_sort}",
        params={
            "limit": _coerce_limit(limit, default=25, minimum=1, maximum=100),
            "after": str(after or "").strip(),
            "t": normalized_time,
        },
    )


def search_reddit_api_posts(
    query: str,
    subreddit: str = "",
    sort: str = "relevance",
    time_filter: str = "all",
    limit: int = 25,
    after: str = "",
) -> dict[str, Any]:
    """Search Reddit Posts through the official Data API."""

    clean_query = str(query or "").strip()
    if not clean_query:
        raise ValueError("Reddit search query cannot be empty.")
    normalized_sort = str(sort or "relevance").lower()
    if normalized_sort not in {"relevance", "hot", "top", "new", "comments"}:
        raise ValueError("Invalid Reddit search sort.")
    normalized_time = str(time_filter or "all").lower()
    if normalized_time not in {"hour", "day", "week", "month", "year", "all"}:
        raise ValueError("Invalid Reddit time_filter.")
    prefix = f"/r/{_normalize_subreddit(subreddit)}" if subreddit else ""
    return _reddit_api_request(
        "GET",
        f"{prefix}/search",
        params={
            "q": clean_query,
            "restrict_sr": bool(subreddit),
            "sort": normalized_sort,
            "t": normalized_time,
            "limit": _coerce_limit(limit, default=25, minimum=1, maximum=100),
            "after": str(after or "").strip(),
        },
    )


def get_reddit_api_post(
    post_id_or_url: str,
    comment_sort: str = "confidence",
    comment_limit: int = 50,
    depth: int = 4,
) -> dict[str, Any]:
    """Get a Reddit Post and its comments through the official Data API."""

    post_id = _reddit_post_id(post_id_or_url)
    normalized_sort = str(comment_sort or "confidence").lower()
    if normalized_sort not in {
        "confidence", "top", "new", "controversial", "old", "random", "qa", "live"
    }:
        raise ValueError("Invalid Reddit comment sort.")
    result = _reddit_api_request(
        "GET",
        f"/comments/{post_id}",
        params={
            "sort": normalized_sort,
            "limit": _coerce_limit(comment_limit, default=50, minimum=1, maximum=500),
            "depth": _coerce_limit(depth, default=4, minimum=0, maximum=10),
        },
    )
    payload = result.get("response")
    if isinstance(payload, list):
        result["post_items"] = _listing_items(payload[0]) if payload else []
        result["comment_items"] = _listing_items(payload[1]) if len(payload) > 1 else []
    return result


def get_reddit_api_user_activity(
    username: str,
    activity: str = "overview",
    sort: str = "new",
    time_filter: str = "all",
    limit: int = 25,
    after: str = "",
) -> dict[str, Any]:
    """Get a Reddit user's public overview, Posts, or comments."""

    user = _normalize_reddit_username(username)
    normalized_activity = str(activity or "overview").lower()
    if normalized_activity not in {"overview", "submitted", "comments"}:
        raise ValueError("activity must be overview, submitted, or comments.")
    normalized_sort = str(sort or "new").lower()
    if normalized_sort not in {"hot", "new", "top", "controversial"}:
        raise ValueError("Invalid Reddit user activity sort.")
    return _reddit_api_request(
        "GET",
        f"/user/{quote(user, safe='')}/{normalized_activity}",
        params={
            "sort": normalized_sort,
            "t": str(time_filter or "all").lower(),
            "limit": _coerce_limit(limit, default=25, minimum=1, maximum=100),
            "after": str(after or "").strip(),
        },
    )


def get_reddit_api_inbox(
    mailbox: str = "inbox",
    limit: int = 25,
    after: str = "",
) -> dict[str, Any]:
    """Get authenticated Reddit messages or unread inbox items."""

    normalized = str(mailbox or "inbox").lower()
    if normalized not in {"inbox", "unread", "sent"}:
        raise ValueError("mailbox must be inbox, unread, or sent.")
    return _reddit_api_request(
        "GET",
        f"/message/{normalized}",
        require_user=True,
        params={
            "limit": _coerce_limit(limit, default=25, minimum=1, maximum=100),
            "after": str(after or "").strip(),
        },
    )


def publish_reddit_api_text_post(
    subreddit: str,
    title: str,
    body: str = "",
    send_replies: bool = True,
    nsfw: bool = False,
    spoiler: bool = False,
) -> dict[str, Any]:
    """Submit a text Post through Reddit's official API."""

    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("Reddit Post title cannot be empty.")
    return _reddit_api_request(
        "POST",
        "/api/submit",
        require_user=True,
        data={
            "api_type": "json",
            "kind": "self",
            "sr": _normalize_subreddit(subreddit),
            "title": clean_title,
            "text": str(body or ""),
            "sendreplies": bool(send_replies),
            "nsfw": bool(nsfw),
            "spoiler": bool(spoiler),
            "resubmit": True,
        },
    )


def publish_reddit_api_link_post(
    subreddit: str,
    title: str,
    url: str,
    send_replies: bool = True,
    nsfw: bool = False,
    spoiler: bool = False,
) -> dict[str, Any]:
    """Submit a link Post through Reddit's official API."""

    clean_title = str(title or "").strip()
    parsed = urlparse(str(url or "").strip())
    if not clean_title:
        raise ValueError("Reddit Post title cannot be empty.")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("A valid HTTP(S) link is required.")
    return _reddit_api_request(
        "POST",
        "/api/submit",
        require_user=True,
        data={
            "api_type": "json",
            "kind": "link",
            "sr": _normalize_subreddit(subreddit),
            "title": clean_title,
            "url": url,
            "sendreplies": bool(send_replies),
            "nsfw": bool(nsfw),
            "spoiler": bool(spoiler),
            "resubmit": True,
        },
    )


def comment_reddit_api_post(
    post_id_or_url: str,
    message: str,
) -> dict[str, Any]:
    """Comment on a Reddit Post through the official API."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Reddit comment cannot be empty.")
    return _reddit_api_request(
        "POST",
        "/api/comment",
        require_user=True,
        data={
            "api_type": "json",
            "thing_id": _reddit_fullname(post_id_or_url, default_kind="t3"),
            "text": clean_message,
        },
    )


def reply_reddit_api_comment(
    comment_id_or_url: str,
    message: str,
) -> dict[str, Any]:
    """Reply to a Reddit comment through the official API."""

    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Reddit reply cannot be empty.")
    return _reddit_api_request(
        "POST",
        "/api/comment",
        require_user=True,
        data={
            "api_type": "json",
            "thing_id": _reddit_fullname(comment_id_or_url, default_kind="t1"),
            "text": clean_message,
        },
    )


def edit_reddit_api_content(thing_id_or_url: str, text: str) -> dict[str, Any]:
    """Edit an authenticated user's Reddit Post body or comment."""

    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("Edited Reddit text cannot be empty.")
    return _reddit_api_request(
        "POST",
        "/api/editusertext",
        require_user=True,
        data={
            "api_type": "json",
            "thing_id": _reddit_fullname(thing_id_or_url),
            "text": clean_text,
        },
    )


def delete_reddit_api_content(
    thing_id_or_url: str,
    kind: str = "post",
) -> dict[str, Any]:
    """Delete an authenticated user's Reddit Post or comment."""

    normalized_kind = str(kind or "post").lower()
    if normalized_kind not in {"post", "comment"}:
        raise ValueError("kind must be post or comment.")
    return _reddit_api_request(
        "POST",
        "/api/del",
        require_user=True,
        data={
            "id": _reddit_fullname(
                thing_id_or_url,
                default_kind="t1" if normalized_kind == "comment" else "t3",
            ),
        },
    )


def vote_reddit_api(
    thing_id_or_url: str,
    direction: str = "up",
    kind: str = "post",
) -> dict[str, Any]:
    """Upvote, downvote, or clear a vote through Reddit's official API."""

    normalized_direction = str(direction or "up").lower()
    directions = {
        "up": 1,
        "upvote": 1,
        "down": -1,
        "downvote": -1,
        "clear": 0,
        "none": 0,
    }
    if normalized_direction not in directions:
        raise ValueError("direction must be up, down, or clear.")
    normalized_kind = str(kind or "post").lower()
    if normalized_kind not in {"post", "comment"}:
        raise ValueError("kind must be post or comment.")
    return _reddit_api_request(
        "POST",
        "/api/vote",
        require_user=True,
        data={
            "id": _reddit_fullname(
                thing_id_or_url,
                default_kind="t1" if normalized_kind == "comment" else "t3",
            ),
            "dir": directions[normalized_direction],
        },
    )


def save_reddit_api_content(
    thing_id_or_url: str,
    kind: str = "post",
) -> dict[str, Any]:
    """Save a Reddit Post or comment through the official API."""

    normalized_kind = str(kind or "post").lower()
    if normalized_kind not in {"post", "comment"}:
        raise ValueError("kind must be post or comment.")
    return _reddit_api_request(
        "POST",
        "/api/save",
        require_user=True,
        data={
            "id": _reddit_fullname(
                thing_id_or_url,
                default_kind="t1" if normalized_kind == "comment" else "t3",
            ),
        },
    )


def unsave_reddit_api_content(
    thing_id_or_url: str,
    kind: str = "post",
) -> dict[str, Any]:
    """Unsave a Reddit Post or comment through the official API."""

    normalized_kind = str(kind or "post").lower()
    if normalized_kind not in {"post", "comment"}:
        raise ValueError("kind must be post or comment.")
    return _reddit_api_request(
        "POST",
        "/api/unsave",
        require_user=True,
        data={
            "id": _reddit_fullname(
                thing_id_or_url,
                default_kind="t1" if normalized_kind == "comment" else "t3",
            ),
        },
    )


def join_reddit_api_community(subreddit: str) -> dict[str, Any]:
    """Subscribe to a subreddit through the official API."""

    return _reddit_api_request(
        "POST",
        "/api/subscribe",
        require_user=True,
        data={"action": "sub", "sr_name": _normalize_subreddit(subreddit)},
    )


def leave_reddit_api_community(subreddit: str) -> dict[str, Any]:
    """Unsubscribe from a subreddit through the official API."""

    return _reddit_api_request(
        "POST",
        "/api/subscribe",
        require_user=True,
        data={"action": "unsub", "sr_name": _normalize_subreddit(subreddit)},
    )


def hide_reddit_api_post(post_id_or_url: str) -> dict[str, Any]:
    """Hide a Reddit Post through the official API."""

    return _reddit_api_request(
        "POST",
        "/api/hide",
        require_user=True,
        data={"id": _reddit_fullname(post_id_or_url, default_kind="t3")},
    )


def unhide_reddit_api_post(post_id_or_url: str) -> dict[str, Any]:
    """Unhide a Reddit Post through the official API."""

    return _reddit_api_request(
        "POST",
        "/api/unhide",
        require_user=True,
        data={"id": _reddit_fullname(post_id_or_url, default_kind="t3")},
    )


REDDIT_BROWSER_TOOLS = [
    get_reddit_browser_status,
    launch_reddit_browser,
    close_reddit_browser,
    open_reddit_page,
    scan_reddit_posts,
    snapshot_reddit_feed,
    search_reddit_posts,
    inspect_reddit_post,
    inspect_reddit_profile,
    inspect_reddit_community,
    upvote_reddit_post,
    downvote_reddit_post,
    clear_reddit_post_vote,
    save_reddit_post,
    unsave_reddit_post,
    join_reddit_community,
    leave_reddit_community,
    publish_reddit_text_post,
    publish_reddit_link_post,
    comment_reddit_post,
    reply_reddit_comment,
]


REDDIT_API_TOOLS = [
    get_reddit_api_status,
    get_reddit_api_me,
    get_reddit_api_listing,
    search_reddit_api_posts,
    get_reddit_api_post,
    get_reddit_api_user_activity,
    get_reddit_api_inbox,
    publish_reddit_api_text_post,
    publish_reddit_api_link_post,
    comment_reddit_api_post,
    reply_reddit_api_comment,
    edit_reddit_api_content,
    delete_reddit_api_content,
    vote_reddit_api,
    save_reddit_api_content,
    unsave_reddit_api_content,
    join_reddit_api_community,
    leave_reddit_api_community,
    hide_reddit_api_post,
    unhide_reddit_api_post,
]


REDDIT_TOOLS = [*REDDIT_BROWSER_TOOLS, *REDDIT_API_TOOLS]


__all__ = [
    "REDDIT_BROWSER_TOOLS",
    "REDDIT_API_TOOLS",
    "REDDIT_TOOLS",
    *(tool.__name__ for tool in REDDIT_TOOLS),
]

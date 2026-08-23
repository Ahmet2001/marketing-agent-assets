"""Generated browser surface from the original MarketingApp toolbox.

Do not mix browser and API actions in a worker process.
"""

from __future__ import annotations

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

from MarketingApp.araclar.browser_araclari import _get_driver, _human_click, _type_into_element, browser_baslat, browser_kapat, get_browser_runtime_state

TOOLBOX_ACCESS_MODE = 'hybrid'

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SOCIAL_DIR = os.path.join(_APP_ROOT, 'workspace', 'social')

_SNAPSHOT_PATH = os.path.join(_SOCIAL_DIR, 'tiktok_feed_snapshot.json')

_TIKTOK_HOSTS = {'tiktok.com', 'www.tiktok.com', 'm.tiktok.com'}

_HANDLE_RE = re.compile('^[A-Za-z0-9._]{1,24}$')

_VIDEO_RE = re.compile('/@[A-Za-z0-9._]+/video/(\\d+)', re.I)

_DEFAULT_TIKTOK_API_BASE_URL = 'https://open.tiktokapis.com'

_DEFAULT_TIKTOK_API_TIMEOUT = 30

_DEFAULT_TIKTOK_CHUNK_SIZE = 10 * 1024 * 1024

def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')

def _limit(value: Any, default: int=20, maximum: int=100) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))

def _compact(value: Any, limit: int=800) -> str:
    text = re.sub('\\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'

def _normalize_handle(value: str) -> str:
    text = str(value or '').strip()
    if '://' in text:
        parsed = urlparse(text)
        if (parsed.hostname or '').lower() not in _TIKTOK_HOSTS:
            raise ValueError('Only TikTok profile URLs are accepted.')
        parts = [part for part in parsed.path.split('/') if part]
        text = parts[0] if parts else ''
    text = text.lstrip('@').strip('/')
    if not _HANDLE_RE.fullmatch(text):
        raise ValueError('A valid TikTok handle is required.')
    return text

def _normalize_url(value: str, *, require_video: bool=False) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError('A TikTok URL is required.')
    if text.startswith('/'):
        text = f'https://www.tiktok.com{text}'
    parsed = urlparse(text)
    if (parsed.hostname or '').lower() not in _TIKTOK_HOSTS:
        raise ValueError('Only tiktok.com URLs are accepted.')
    if require_video and (not _VIDEO_RE.search(parsed.path)):
        raise ValueError('A TikTok video URL is required.')
    return text

def _video_id(video_url: str) -> str:
    match = _VIDEO_RE.search(urlparse(_normalize_url(video_url, require_video=True)).path)
    if not match:
        raise ValueError('Could not determine the TikTok video ID.')
    return match.group(1)

def _page_ready(driver) -> bool:
    try:
        return driver.execute_script("return document.readyState !== 'loading' && !!document.querySelector('main, [data-e2e], #app');")
    except Exception:
        return False

def _open(url: str, timeout: int=20):
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
    wanted = tuple((marker.casefold() for marker in markers))
    for element in driver.find_elements(By.CSS_SELECTOR, "button, [role='button'], a"):
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue
            label = ' '.join((element.text or '', element.get_attribute('aria-label') or '', element.get_attribute('title') or '')).casefold()
            if any((marker in label for marker in wanted)):
                return element
        except Exception:
            continue
    return None

def _videos(driver, limit: int) -> list[dict[str, Any]]:
    rows = driver.execute_script('\n        const max = arguments[0], seen = new Set(), result = [];\n        for (const link of document.querySelectorAll("a[href*=\'/video/\']")) {\n          if (result.length >= max) break;\n          const href = link.href || link.getAttribute(\'href\') || \'\';\n          const match = href.match(/@([^/]+)\\/video\\/(\\d+)/i);\n          if (!match || seen.has(match[2])) continue;\n          seen.add(match[2]);\n          const root = link.closest("[data-e2e*=\'item\'], article") || link.parentElement || link;\n          const image = root.querySelector(\'img\');\n          const text = (root.innerText || root.textContent || \'\').trim();\n          result.push({ video_id: match[2], author: match[1], url: href,\n            caption: text.slice(0, 1200), thumbnail_url: image?.currentSrc || image?.src || \'\' });\n        }\n        return result;\n        ', _limit(limit)) or []
    return [{**row, 'caption': _compact(row.get('caption'), 1200)} for row in rows]

def get_tiktok_browser_status() -> dict[str, Any]:
    """Return shared-browser state and whether it is currently on TikTok."""
    state = get_browser_runtime_state()
    if not state.get('ready'):
        return {**state, 'platform': 'tiktok', 'on_tiktok': False, 'url': ''}
    driver = _get_driver()
    url = str(driver.current_url or '')
    return {**state, 'platform': 'tiktok', 'on_tiktok': (urlparse(url).hostname or '').lower() in _TIKTOK_HOSTS, 'url': url, 'title': str(driver.title or '')}

def launch_tiktok_browser(headless: bool=False) -> dict[str, Any]:
    """Launch the shared browser and open TikTok's For You page."""
    browser_baslat(headless=headless)
    _open('https://www.tiktok.com/foryou')
    return get_tiktok_browser_status()

def close_tiktok_browser() -> str:
    """Close the shared browser session."""
    return browser_kapat()

def open_tiktok_page(destination: str='foryou', query: str='', handle: str='', video_url: str='') -> dict[str, Any]:
    """Open a TikTok feed, search, profile, video, inbox, or upload page."""
    destination = str(destination or 'foryou').strip().lower()
    if destination in {'foryou', 'for_you', 'feed'}:
        url = 'https://www.tiktok.com/foryou'
    elif destination == 'following':
        url = 'https://www.tiktok.com/following'
    elif destination == 'search':
        if not str(query or '').strip():
            raise ValueError('query is required for a TikTok search.')
        url = f'https://www.tiktok.com/search?q={quote_plus(query.strip())}'
    elif destination == 'profile':
        url = f'https://www.tiktok.com/@{quote(_normalize_handle(handle), safe='')}'
    elif destination == 'video':
        url = _normalize_url(video_url, require_video=True)
    elif destination == 'inbox':
        url = 'https://www.tiktok.com/messages'
    elif destination == 'upload':
        url = 'https://www.tiktok.com/tiktokstudio/upload'
    else:
        raise ValueError('destination must be foryou, following, search, profile, video, inbox, or upload.')
    driver = _open(url)
    return {'status': 'opened', 'destination': destination, 'url': str(driver.current_url or url)}

def scan_tiktok_videos(limit: int=20) -> dict[str, Any]:
    """Extract visible TikTok video cards from the current page."""
    driver = _get_driver()
    videos = _videos(driver, limit)
    return {'status': 'ok', 'url': str(driver.current_url or ''), 'count': len(videos), 'videos': videos}

def snapshot_tiktok_feed(destination: str='foryou', query: str='', limit: int=20) -> dict[str, Any]:
    """Open a feed/search page and save its visible-video snapshot to workspace."""
    opened = open_tiktok_page(destination=destination, query=query)
    snapshot = {'captured_at': _now(), **opened, **scan_tiktok_videos(limit)}
    os.makedirs(_SOCIAL_DIR, exist_ok=True)
    with open(_SNAPSHOT_PATH, 'w', encoding='utf-8') as output:
        json.dump(snapshot, output, ensure_ascii=False, indent=2)
    return {**snapshot, 'snapshot_path': _SNAPSHOT_PATH}

def search_tiktok_videos(query: str, limit: int=20) -> dict[str, Any]:
    """Search TikTok and return visible matching videos."""
    open_tiktok_page(destination='search', query=query)
    return {'query': query.strip(), **scan_tiktok_videos(limit)}

def inspect_tiktok_profile(handle: str, limit: int=20) -> dict[str, Any]:
    """Open a profile and return visible profile text plus recent videos."""
    user = _normalize_handle(handle)
    driver = _open(f'https://www.tiktok.com/@{quote(user, safe='')}')
    profile_text = _compact(driver.execute_script("return document.querySelector('main')?.innerText || document.body?.innerText || ''"), 3000)
    return {'status': 'ok', 'handle': user, 'url': str(driver.current_url or ''), 'profile_text': profile_text, 'videos': _videos(driver, limit)}

def inspect_tiktok_video(video_url: str) -> dict[str, Any]:
    """Open a TikTok video and return its visible text and metadata."""
    target = _normalize_url(video_url, require_video=True)
    driver = _open(target)
    return {'status': 'ok', 'video_id': _video_id(target), 'url': str(driver.current_url or target), 'title': str(driver.title or ''), 'text': _compact(driver.execute_script("return document.querySelector('main')?.innerText || document.body?.innerText || ''"), 4000)}

def _video_action(video_url: str, action: str, markers: tuple[str, ...]) -> dict[str, Any]:
    driver = _open(_normalize_url(video_url, require_video=True))
    control = _control(driver, markers)
    if not control:
        return {'status': 'not_found', 'action': action, 'video_id': _video_id(video_url), 'error': 'Could not locate the TikTok control. Sign in if required.'}
    _human_click(driver, control)
    time.sleep(0.5)
    return {'status': 'ok', 'action': action, 'video_id': _video_id(video_url), 'url': str(driver.current_url or '')}

def like_tiktok_video(video_url: str) -> dict[str, Any]:
    return _video_action(video_url, 'like', ('like', 'beğen'))

def unlike_tiktok_video(video_url: str) -> dict[str, Any]:
    return _video_action(video_url, 'unlike', ('unlike', 'remove like', 'beğenmekten vazgeç'))

def follow_tiktok_account(handle: str) -> dict[str, Any]:
    user = _normalize_handle(handle)
    driver = _open(f'https://www.tiktok.com/@{quote(user, safe='')}')
    control = _control(driver, ('follow', 'takip et'))
    if not control:
        return {'status': 'not_found', 'handle': user, 'error': 'Could not locate a Follow control.'}
    _human_click(driver, control)
    return {'status': 'ok', 'action': 'follow', 'handle': user}

def unfollow_tiktok_account(handle: str) -> dict[str, Any]:
    user = _normalize_handle(handle)
    driver = _open(f'https://www.tiktok.com/@{quote(user, safe='')}')
    control = _control(driver, ('following', 'unfollow', 'takip ediliyor', 'takiptesin'))
    if not control:
        return {'status': 'not_found', 'handle': user, 'error': 'Could not locate a Following control.'}
    _human_click(driver, control)
    return {'status': 'ok', 'action': 'unfollow', 'handle': user}

def comment_tiktok_video(video_url: str, message: str) -> dict[str, Any]:
    """Post a comment through the normal logged-in TikTok browser session."""
    text = str(message or '').strip()
    if not text:
        raise ValueError('A non-empty comment message is required.')
    driver = _open(_normalize_url(video_url, require_video=True))
    box = _visible(driver, ("[data-e2e='comment-input']", "div[contenteditable='true'][data-e2e*='comment']", "textarea[placeholder*='comment' i]"))
    if not box:
        trigger = _control(driver, ('comment', 'yorum'))
        if trigger:
            _human_click(driver, trigger)
            box = _visible(driver, ("[data-e2e='comment-input']", "div[contenteditable='true']", 'textarea'))
    if not box:
        return {'status': 'not_found', 'error': 'Could not locate the comment editor. Sign in if required.'}
    _type_into_element(driver, box, text)
    submit = _control(driver, ('post', 'send', 'comment', 'yorum yap', 'gönder'))
    if submit:
        _human_click(driver, submit)
    else:
        box.send_keys(Keys.CONTROL, Keys.ENTER)
    return {'status': 'submitted', 'video_id': _video_id(video_url), 'message': text}

def publish_tiktok_video(video_path: str, caption: str='', submit: bool=False) -> dict[str, Any]:
    """Upload a local video to TikTok Studio; set ``submit=True`` to publish.

    The default only prepares the upload and caption, providing a deliberate
    human-review checkpoint before the irreversible publish action.
    """
    path = os.path.abspath(os.path.expanduser(str(video_path or '')))
    if not os.path.isfile(path):
        raise ValueError('video_path must point to an existing local video file.')
    driver = _open('https://www.tiktok.com/tiktokstudio/upload', timeout=30)
    upload = _visible(driver, ("input[type='file']", "input[data-e2e*='upload']"))
    if not upload:
        return {'status': 'not_found', 'error': "Could not locate TikTok Studio's file input. Sign in and complete any prompts."}
    upload.send_keys(path)
    if caption.strip():
        editor = _visible(driver, ("div[contenteditable='true']", 'textarea'))
        if editor:
            _type_into_element(driver, editor, caption.strip())
    if not submit:
        return {'status': 'draft_ready', 'video_path': path, 'caption': caption.strip(), 'message': 'Upload prepared. Review it in TikTok Studio, then call again with submit=True to publish.'}
    publish = _control(driver, ('post', 'publish', 'share', 'paylaş', 'yayınla'))
    if not publish:
        return {'status': 'ready_to_publish', 'video_path': path, 'error': 'Upload is prepared but the Publish button was not found.'}
    _human_click(driver, publish)
    return {'status': 'submitted', 'video_path': path, 'caption': caption.strip()}

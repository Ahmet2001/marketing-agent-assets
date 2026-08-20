"""Generated browser surface from the original MarketingApp toolbox.

Do not mix browser and API actions in a worker process.
"""

from __future__ import annotations

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

from MarketingApp.araclar.browser_araclari import _get_driver, _human_click, _type_into_element, browser_baslat, browser_kapat, get_browser_runtime_state

TOOLBOX_ACCESS_MODE = 'hybrid'

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_YOUTUBE_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, 'workspace', 'social')

_YOUTUBE_SNAPSHOT_PATH = os.path.join(_YOUTUBE_WORKSPACE_DIR, 'youtube_feed_snapshot.json')

_YOUTUBE_API_BASE_URL = 'https://www.googleapis.com/youtube/v3'

_YOUTUBE_UPLOAD_BASE_URL = 'https://www.googleapis.com/upload/youtube/v3'

_YOUTUBE_ANALYTICS_BASE_URL = 'https://youtubeanalytics.googleapis.com/v2'

_YOUTUBE_TOKEN_URL = 'https://oauth2.googleapis.com/token'

_DEFAULT_YOUTUBE_TIMEOUT = 30

_TOKEN_CACHE: dict[str, Any] = {'access_token': '', 'expires_at': 0.0, 'fingerprint': '', 'scope': ''}

def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')

def _coerce_limit(value: Any, default: int=25, minimum: int=1, maximum: int=50) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))

def _normalize_youtube_video_id(value: str) -> str:
    text = str(value or '').strip()
    if re.fullmatch('[A-Za-z0-9_-]{11}', text):
        return text
    if text.startswith('/'):
        text = f'https://www.youtube.com{text}'
    parsed = urlparse(text)
    host = (parsed.hostname or '').lower()
    video_id = ''
    if host in {'youtu.be', 'www.youtu.be'}:
        video_id = parsed.path.strip('/').split('/')[0]
    elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
        if parsed.path == '/watch':
            video_id = (parse_qs(parsed.query).get('v') or [''])[0]
        else:
            match = re.search('/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})', parsed.path)
            video_id = match.group(1) if match else ''
    if not re.fullmatch('[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('A valid YouTube video ID or URL is required.')
    return video_id

def _youtube_video_url(value: str) -> str:
    return f'https://www.youtube.com/watch?v={_normalize_youtube_video_id(value)}'

def _normalize_youtube_channel(value: str) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError('A YouTube channel ID, handle, or URL is required.')
    if text.startswith('http://') or text.startswith('https://'):
        parsed = urlparse(text)
        if (parsed.hostname or '').lower() not in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
            raise ValueError('Only youtube.com channel URLs are accepted.')
        return text.rstrip('/')
    if re.fullmatch('UC[A-Za-z0-9_-]{22}', text):
        return f'https://www.youtube.com/channel/{text}'
    handle = text.lstrip('@').strip('/')
    if not re.fullmatch('[A-Za-z0-9._-]{1,100}', handle):
        raise ValueError('A valid YouTube channel handle is required.')
    return f'https://www.youtube.com/@{handle}'

def _youtube_page_ready(driver) -> bool:
    try:
        return driver.execute_script("\n            return document.readyState !== 'loading' &&\n              !!document.querySelector(\n                'ytd-app, ytd-watch-flexy, ytd-browse, ytd-search'\n              );\n            ")
    except Exception:
        return False

def _wait_for_youtube(url: str, timeout: int=20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_youtube_page_ready)
    except TimeoutException:
        pass
    return driver

def _find_visible(driver, selectors: tuple[str, ...], require_enabled: bool=False):
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if not element.is_displayed():
                    continue
                if require_enabled and (not element.is_enabled()):
                    continue
                return element
            except Exception:
                continue
    return None

def _find_control_by_markers(driver, markers: tuple[str, ...], *, root=None, require_enabled: bool=True):
    normalized = tuple((marker.casefold() for marker in markers))
    scope = root or driver
    for element in scope.find_elements(By.CSS_SELECTOR, "button, [role='button'], tp-yt-paper-item, ytd-button-renderer, a"):
        try:
            if not element.is_displayed():
                continue
            if require_enabled and (not element.is_enabled()):
                continue
            text = ' '.join((element.text or '', element.get_attribute('aria-label') or '', element.get_attribute('title') or '')).casefold()
            if any((marker in text for marker in normalized)):
                return element
        except Exception:
            continue
    return None

def _collect_youtube_videos(driver, limit: int=20) -> list[dict[str, Any]]:
    return driver.execute_script('\n        const limit = arguments[0];\n        const selectors = [\n          \'ytd-video-renderer\',\n          \'ytd-rich-item-renderer\',\n          \'ytd-grid-video-renderer\',\n          \'ytd-compact-video-renderer\'\n        ];\n        const nodes = selectors.flatMap((selector) => [...document.querySelectorAll(selector)]);\n        const seen = new Set();\n        const results = [];\n        const text = (root, selector) => {\n          const node = root.querySelector(selector);\n          return (node?.innerText || node?.textContent || \'\').trim();\n        };\n        for (const node of nodes) {\n          if (results.length >= limit) break;\n          const link = node.querySelector(\n            "a#video-title, a[href*=\'/watch?v=\'], a[href*=\'/shorts/\']"\n          );\n          const href = link?.href || link?.getAttribute(\'href\') || \'\';\n          const match = href.match(/[?&]v=([A-Za-z0-9_-]{11})|\\/shorts\\/([A-Za-z0-9_-]{11})/);\n          const id = match ? (match[1] || match[2]) : \'\';\n          if (!id || seen.has(id)) continue;\n          seen.add(id);\n          const image = node.querySelector(\'img\');\n          results.push({\n            video_id: id,\n            title: (link?.getAttribute(\'title\') || link?.innerText || \'\').trim(),\n            url: `https://www.youtube.com/watch?v=${id}`,\n            channel: text(node, \'#channel-name, ytd-channel-name, #text-container\'),\n            metadata: text(node, \'#metadata-line\'),\n            description: text(node, \'#description-text, .metadata-snippet-text\'),\n            duration: text(node, \'ytd-thumbnail-overlay-time-status-renderer\'),\n            thumbnail_url: image?.currentSrc || image?.src || \'\',\n          });\n        }\n        return results;\n        ', _coerce_limit(limit, default=20, minimum=1, maximum=100)) or []

def get_youtube_browser_status() -> dict[str, Any]:
    """Return shared browser status and whether it is currently on YouTube."""
    state = get_browser_runtime_state()
    if not state.get('ready'):
        return {**state, 'platform': 'youtube', 'url': '', 'title': '', 'on_youtube': False}
    driver = _get_driver()
    url = str(driver.current_url or '')
    return {**state, 'platform': 'youtube', 'url': url, 'title': str(driver.title or ''), 'on_youtube': 'youtube.com' in urlparse(url).netloc.lower()}

def launch_youtube_browser(headless: bool=False, restart_if_needed: bool=True) -> dict[str, Any]:
    """Launch the shared browser and open YouTube."""
    state = get_browser_runtime_state()
    if state.get('ready') and restart_if_needed:
        active_headless = state.get('active_headless')
        if active_headless is not None and bool(active_headless) != bool(headless):
            browser_kapat()
            state = get_browser_runtime_state()
    launch_result = ''
    if not state.get('ready'):
        launch_result = browser_baslat(headless=headless)
        if not get_browser_runtime_state().get('ready'):
            return {'status': 'error', 'platform': 'youtube', 'error': launch_result or 'Browser could not be launched.'}
    driver = _wait_for_youtube('https://www.youtube.com/')
    return {'status': 'ready', 'platform': 'youtube', 'url': str(driver.current_url or ''), 'title': str(driver.title or ''), 'launch_result': launch_result, **get_browser_runtime_state()}

def close_youtube_browser() -> dict[str, Any]:
    """Close the shared browser session."""
    return {'status': 'closed', 'platform': 'youtube', 'result': browser_kapat()}

def open_youtube_page(destination: str='home', query: str='', channel: str='', video_url: str='') -> dict[str, Any]:
    """Open a YouTube home, search, channel, video, Studio, or feed page."""
    target = str(destination or 'home').strip().casefold()
    if target in {'home', 'anasayfa'}:
        url = 'https://www.youtube.com/'
    elif target in {'search', 'ara'}:
        clean_query = str(query or '').strip()
        if not clean_query:
            raise ValueError('A YouTube search query is required.')
        url = f'https://www.youtube.com/results?search_query={quote_plus(clean_query)}'
    elif target in {'channel', 'profile', 'kanal'}:
        url = _normalize_youtube_channel(channel)
    elif target in {'community', 'topluluk'}:
        url = f'{_normalize_youtube_channel(channel)}/community'
    elif target in {'videos', 'channel videos'}:
        url = f'{_normalize_youtube_channel(channel)}/videos'
    elif target in {'video', 'watch', 'short'}:
        url = _youtube_video_url(video_url)
    elif target in {'subscriptions', 'abonelikler'}:
        url = 'https://www.youtube.com/feed/subscriptions'
    elif target in {'notifications', 'bildirimler'}:
        url = 'https://www.youtube.com/feed/notifications'
    elif target in {'history', 'gecmis'}:
        url = 'https://www.youtube.com/feed/history'
    elif target in {'watch later', 'daha sonra izle'}:
        url = 'https://www.youtube.com/playlist?list=WL'
    elif target in {'studio', 'upload', 'publish'}:
        url = 'https://studio.youtube.com/'
    else:
        parsed = urlparse(destination)
        if (parsed.hostname or '').lower() not in {'youtube.com', 'www.youtube.com', 'studio.youtube.com'}:
            raise ValueError('Only YouTube URLs are accepted.')
        url = destination
    driver = _wait_for_youtube(url)
    return {'status': 'opened', 'destination': target, 'url': str(driver.current_url or ''), 'title': str(driver.title or '')}

def scan_youtube_videos(limit: int=20) -> dict[str, Any]:
    """Extract visible YouTube video cards from the current page."""
    driver = _get_driver()
    videos = _collect_youtube_videos(driver, limit=limit)
    return {'status': 'ok', 'source_url': str(driver.current_url or ''), 'count': len(videos), 'videos': videos}

def snapshot_youtube_feed(destination: str='home', channel: str='', limit: int=20, write_to_file: bool=True) -> dict[str, Any]:
    """Open and snapshot a YouTube feed or channel."""
    opened = open_youtube_page(destination=destination, channel=channel)
    snapshot = scan_youtube_videos(limit=limit)
    result = {'captured_at': _now(), 'opened': opened, **snapshot}
    if write_to_file:
        os.makedirs(_YOUTUBE_WORKSPACE_DIR, exist_ok=True)
        with open(_YOUTUBE_SNAPSHOT_PATH, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        result['snapshot_path'] = _YOUTUBE_SNAPSHOT_PATH
    return result

def search_youtube_videos(query: str, limit: int=20) -> dict[str, Any]:
    """Search YouTube in the browser and extract visible video results."""
    opened = open_youtube_page(destination='search', query=query)
    videos = _collect_youtube_videos(_get_driver(), limit=limit)
    return {'status': 'ok', 'opened': opened, 'count': len(videos), 'videos': videos}

def inspect_youtube_channel(channel: str, limit: int=20) -> dict[str, Any]:
    """Inspect a YouTube channel through the browser."""
    driver = _wait_for_youtube(_normalize_youtube_channel(channel))
    snapshot = driver.execute_script("\n        const text = (selector) => {\n          const node = document.querySelector(selector);\n          return (node?.innerText || node?.textContent || '').trim();\n        };\n        return {\n          channel_name: text('#channel-name #text, yt-formatted-string#text'),\n          handle: text('#channel-handle, #channel-tagline'),\n          subscribers: text('#subscriber-count'),\n          description: text('#description, #description-inline-expander'),\n          body_excerpt: (document.body?.innerText || '').trim().slice(0, 2200),\n        };\n        ") or {}
    return {'status': 'ok', 'url': str(driver.current_url or ''), 'videos': _collect_youtube_videos(driver, limit=limit), **snapshot}

def inspect_youtube_video(video_url: str) -> dict[str, Any]:
    """Inspect one YouTube video through the browser."""
    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f'https://www.youtube.com/watch?v={video_id}')
    snapshot = driver.execute_script('\n        const text = (selector) => {\n          const node = document.querySelector(selector);\n          return (node?.innerText || node?.textContent || \'\').trim();\n        };\n        const labels = [...document.querySelectorAll(\'button, [role="button"]\')]\n          .map((node) => node.getAttribute(\'aria-label\') || node.innerText || \'\')\n          .filter(Boolean);\n        return {\n          video_title: text(\'h1.ytd-watch-metadata, h1.title\'),\n          channel_name: text(\'#channel-name #text, ytd-channel-name #text\'),\n          metadata: text(\'#info, #info-text, #count\'),\n          description: text(\'#description-inline-expander, #description\'),\n          liked: labels.some((value) => /remove like|unlike/i.test(value)),\n          subscribed: labels.some((value) => /unsubscribe|subscribed/i.test(value)),\n          body_excerpt: (document.body?.innerText || \'\').trim().slice(0, 2500),\n        };\n        ') or {}
    return {'status': 'ok', 'video_id': video_id, 'url': str(driver.current_url or ''), **snapshot}

def _youtube_browser_video_action(video_url: str, *, action: str, selectors: tuple[str, ...], markers: tuple[str, ...], already_markers: tuple[str, ...]=()) -> dict[str, Any]:
    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f'https://www.youtube.com/watch?v={video_id}')
    if already_markers:
        already = _find_control_by_markers(driver, already_markers, require_enabled=False)
        if already is not None:
            return {'status': f'already_{action}', 'video_id': video_id}
    control = _find_visible(driver, selectors, require_enabled=True)
    if control is None:
        control = _find_control_by_markers(driver, markers, require_enabled=True)
    if control is None:
        return {'status': 'error', 'video_id': video_id, 'action': action, 'error': f'Could not locate YouTube {action} control.'}
    _human_click(driver, control)
    time.sleep(0.7)
    return {'status': 'attempted', 'video_id': video_id, 'action': action, 'url': str(driver.current_url or '')}

def like_youtube_video(video_url: str) -> dict[str, Any]:
    """Like a YouTube video through the browser."""
    return _youtube_browser_video_action(video_url, action='liked', selectors=("like-button-view-model button[aria-pressed='false']", '#segmented-like-button button'), markers=('like this video', 'beğen', 'begen'), already_markers=('remove like', 'unlike', 'beğenmekten vazgeç'))

def unlike_youtube_video(video_url: str) -> dict[str, Any]:
    """Remove a Like from a YouTube video through the browser."""
    return _youtube_browser_video_action(video_url, action='unliked', selectors=("like-button-view-model button[aria-pressed='true']", "#segmented-like-button button[aria-pressed='true']"), markers=('remove like', 'unlike', 'beğenmekten vazgeç'))

def _youtube_browser_subscription_action(channel: str, *, subscribe: bool) -> dict[str, Any]:
    driver = _wait_for_youtube(_normalize_youtube_channel(channel))
    if subscribe:
        already = _find_control_by_markers(driver, ('subscribed', 'unsubscribe', 'abone olundu'), require_enabled=False)
        if already is not None:
            return {'status': 'already_subscribed', 'url': str(driver.current_url or '')}
        markers = ('subscribe', 'abone ol')
    else:
        markers = ('subscribed', 'unsubscribe', 'abone olundu')
    control = _find_control_by_markers(driver, markers, require_enabled=True)
    if control is None:
        return {'status': 'error', 'error': 'Could not locate subscription control.'}
    _human_click(driver, control)
    time.sleep(0.5)
    if not subscribe:
        confirm = _find_control_by_markers(driver, ('unsubscribe', 'abonelikten çık'), require_enabled=True)
        if confirm is not None:
            _human_click(driver, confirm)
    return {'status': 'attempted', 'action': 'subscribe' if subscribe else 'unsubscribe', 'url': str(driver.current_url or '')}

def subscribe_youtube_channel(channel: str) -> dict[str, Any]:
    """Subscribe to a YouTube channel through the browser."""
    return _youtube_browser_subscription_action(channel, subscribe=True)

def unsubscribe_youtube_channel(channel: str) -> dict[str, Any]:
    """Unsubscribe from a YouTube channel through the browser."""
    return _youtube_browser_subscription_action(channel, subscribe=False)

def comment_youtube_video(video_url: str, message: str) -> dict[str, Any]:
    """Post a top-level YouTube comment through the browser."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('YouTube comment cannot be empty.')
    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f'https://www.youtube.com/watch?v={video_id}')
    driver.execute_script('window.scrollTo(0, Math.max(700, document.body.scrollHeight * 0.45));')
    time.sleep(0.8)
    placeholder = _find_visible(driver, ('#placeholder-area', '#simplebox-placeholder', 'ytd-comment-simplebox-renderer #placeholder-area'), require_enabled=True)
    if placeholder is not None:
        _human_click(driver, placeholder)
    editor = _find_visible(driver, ("#contenteditable-root[contenteditable='true']", "div[contenteditable='true'][role='textbox']"), require_enabled=True)
    if editor is None:
        raise RuntimeError("Could not locate YouTube's comment editor.")
    type_method = _type_into_element(driver, editor, clean_message)
    submit = _find_control_by_markers(driver, ('comment', 'yorum'), require_enabled=True)
    if submit is None:
        return {'status': 'drafted', 'video_id': video_id, 'warning': 'Comment filled, but submit control was not found.'}
    _human_click(driver, submit)
    time.sleep(0.8)
    return {'status': 'attempted', 'video_id': video_id, 'message': clean_message, 'type_method': type_method}

def save_youtube_video_to_watch_later(video_url: str) -> dict[str, Any]:
    """Save a YouTube video to Watch Later through the browser."""
    video_id = _normalize_youtube_video_id(video_url)
    driver = _wait_for_youtube(f'https://www.youtube.com/watch?v={video_id}')
    save = _find_control_by_markers(driver, ('save', 'kaydet'), require_enabled=True)
    if save is None:
        return {'status': 'error', 'video_id': video_id, 'error': 'Save control not found.'}
    _human_click(driver, save)
    time.sleep(0.5)
    watch_later = _find_control_by_markers(driver, ('watch later', 'daha sonra izle'), require_enabled=True)
    if watch_later is None:
        return {'status': 'dialog_opened', 'video_id': video_id, 'warning': 'Watch Later option was not found.'}
    _human_click(driver, watch_later)
    return {'status': 'attempted', 'video_id': video_id, 'playlist': 'Watch Later'}

def publish_youtube_video(video_path: str, title: str, description: str='') -> dict[str, Any]:
    """Upload a local video through the YouTube Studio browser interface."""
    absolute_path = os.path.abspath(os.path.expanduser(str(video_path or '').strip()))
    if not os.path.isfile(absolute_path):
        raise ValueError(f'YouTube video file does not exist: {absolute_path}')
    clean_title = str(title or '').strip()
    if not clean_title:
        raise ValueError('YouTube video title cannot be empty.')
    driver = _wait_for_youtube('https://studio.youtube.com/')
    create = _find_control_by_markers(driver, ('create', 'oluştur', 'olustur'), require_enabled=True)
    if create is not None:
        _human_click(driver, create)
        time.sleep(0.5)
        upload = _find_control_by_markers(driver, ('upload videos', 'video yükle'), require_enabled=True)
        if upload is not None:
            _human_click(driver, upload)
            time.sleep(0.5)
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if not inputs:
        raise RuntimeError("Could not locate YouTube Studio's upload input.")
    inputs[0].send_keys(absolute_path)
    time.sleep(1.0)
    title_editor = _find_visible(driver, ("#textbox[contenteditable='true'][aria-label*='title' i]", 'ytcp-social-suggestions-textbox#title-textarea #textbox'), require_enabled=True)
    if title_editor is not None:
        _type_into_element(driver, title_editor, clean_title)
    if description:
        description_editor = _find_visible(driver, ("#textbox[contenteditable='true'][aria-label*='description' i]", 'ytcp-social-suggestions-textbox#description-textarea #textbox'), require_enabled=True)
        if description_editor is not None:
            _type_into_element(driver, description_editor, description)
    return {'status': 'drafted', 'video_path': absolute_path, 'title': clean_title, 'description': str(description or ''), 'url': str(driver.current_url or ''), 'note': 'Upload started and metadata filled; review audience, checks, and visibility in Studio.'}

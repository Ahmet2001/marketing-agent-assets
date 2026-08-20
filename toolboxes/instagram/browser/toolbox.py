"""Generated browser surface from the original MarketingApp toolbox.

Do not mix browser and API actions in a worker process.
"""

from __future__ import annotations

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

from MarketingApp.araclar.browser_araclari import _get_driver, _human_click, _read_element_value, _type_into_element, browser_baslat, browser_kapat, get_browser_runtime_state

TOOLBOX_ACCESS_MODE = 'hybrid'

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_INSTAGRAM_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, 'workspace', 'social')

_INSTAGRAM_SNAPSHOT_PATH = os.path.join(_INSTAGRAM_WORKSPACE_DIR, 'instagram_feed_snapshot.json')

_DEFAULT_INSTAGRAM_API_HOST = 'https://graph.instagram.com'

_DEFAULT_INSTAGRAM_API_VERSION = 'v25.0'

_DEFAULT_INSTAGRAM_API_TIMEOUT = 30

_INSTAGRAM_POST_PATH_PATTERN = re.compile('/(?:p|reel|tv)/([A-Za-z0-9_-]+)', re.I)

_INSTAGRAM_PROFILE_HANDLE_PATTERN = re.compile('^[A-Za-z0-9._]{1,30}$')

def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')

def _coerce_limit(value: Any, default: int=20, minimum: int=1, maximum: int=100) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))

def _normalize_instagram_handle(value: str) -> str:
    text = str(value or '').strip()
    if '://' in text:
        parsed = urlparse(text)
        if (parsed.hostname or '').lower() not in {'instagram.com', 'www.instagram.com'}:
            raise ValueError('Only instagram.com profile URLs are accepted.')
        parts = [part for part in parsed.path.split('/') if part]
        text = parts[0] if parts else ''
    text = text.lstrip('@').strip('/')
    if not _INSTAGRAM_PROFILE_HANDLE_PATTERN.fullmatch(text):
        raise ValueError('A valid Instagram handle is required.')
    return text

def _normalize_instagram_url(value: str, *, require_post: bool=False) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError('An Instagram URL is required.')
    if text.startswith('/'):
        text = f'https://www.instagram.com{text}'
    parsed = urlparse(text)
    if (parsed.hostname or '').lower() not in {'instagram.com', 'www.instagram.com'}:
        raise ValueError('Only instagram.com URLs are accepted.')
    if require_post and (not _INSTAGRAM_POST_PATH_PATTERN.search(parsed.path)):
        raise ValueError('An Instagram Post, Reel, or video URL is required.')
    return text

def _instagram_shortcode(post_url: str) -> str:
    target = _normalize_instagram_url(post_url, require_post=True)
    match = _INSTAGRAM_POST_PATH_PATTERN.search(urlparse(target).path)
    if not match:
        raise ValueError('Could not determine the Instagram shortcode.')
    return match.group(1)

def _instagram_page_ready(driver) -> bool:
    try:
        return driver.execute_script("\n            return document.readyState !== 'loading' &&\n              !!document.querySelector('main, article, nav, header');\n            ")
    except Exception:
        return False

def _wait_for_instagram(url: str, timeout: int=20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_instagram_page_ready)
    except TimeoutException:
        pass
    current_url = str(driver.current_url or '')
    if '/accounts/login' in current_url:
        raise RuntimeError('Instagram requires login. Complete login in the shared browser session.')
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
    normalized_markers = tuple((marker.casefold() for marker in markers))
    scope = root or driver
    for element in scope.find_elements(By.CSS_SELECTOR, "button, [role='button'], svg[aria-label], a"):
        try:
            if not element.is_displayed():
                continue
            if require_enabled and (not element.is_enabled()):
                continue
            combined = ' '.join((element.text or '', element.get_attribute('aria-label') or '', element.get_attribute('title') or '')).casefold()
            if any((marker in combined for marker in normalized_markers)):
                if element.tag_name.lower() == 'svg':
                    try:
                        return element.find_element(By.XPATH, "./ancestor::*[@role='button' or self::button][1]")
                    except Exception:
                        return element
                return element
        except Exception:
            continue
    return None

def _collect_instagram_posts(driver, limit: int=20) -> list[dict[str, Any]]:
    return driver.execute_script('\n        const limit = arguments[0];\n        const anchors = [...document.querySelectorAll(\n          "a[href*=\'/p/\'], a[href*=\'/reel/\'], a[href*=\'/tv/\']"\n        )];\n        const seen = new Set();\n        const results = [];\n        for (const anchor of anchors) {\n          if (results.length >= limit) break;\n          const href = anchor.getAttribute(\'href\') || \'\';\n          const match = href.match(/\\/(p|reel|tv)\\/([^/?#]+)/i);\n          if (!match || seen.has(match[2])) continue;\n          seen.add(match[2]);\n          const root = anchor.closest(\'article\') || anchor.parentElement || anchor;\n          const image = root.querySelector(\'img\') || anchor.querySelector(\'img\');\n          const video = root.querySelector(\'video\') || anchor.querySelector(\'video\');\n          const text = (root.innerText || root.textContent || \'\').trim();\n          results.push({\n            shortcode: match[2],\n            media_type: match[1].toLowerCase() === \'reel\' ? \'REEL\' :\n              video ? \'VIDEO\' : \'IMAGE\',\n            url: href.startsWith(\'http\')\n              ? href\n              : `https://www.instagram.com${href.startsWith(\'/\') ? href : `/${href}`}`,\n            caption: text.slice(0, 1200),\n            image_url: image?.currentSrc || image?.src || \'\',\n            alt_text: image?.alt || \'\',\n            video_url: video?.currentSrc || video?.src || \'\',\n          });\n        }\n        return results;\n        ', _coerce_limit(limit, default=20, minimum=1, maximum=100)) or []

def get_instagram_browser_status() -> dict[str, Any]:
    """Return the shared browser state and whether it is on Instagram."""
    state = get_browser_runtime_state()
    if not state.get('ready'):
        return {**state, 'platform': 'instagram', 'url': '', 'title': '', 'on_instagram': False}
    driver = _get_driver()
    url = str(driver.current_url or '')
    return {**state, 'platform': 'instagram', 'url': url, 'title': str(driver.title or ''), 'on_instagram': 'instagram.com' in urlparse(url).netloc.lower()}

def launch_instagram_browser(headless: bool=False, restart_if_needed: bool=True) -> dict[str, Any]:
    """Launch the shared browser and open Instagram."""
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
            return {'status': 'error', 'platform': 'instagram', 'error': launch_result or 'Browser could not be launched.'}
    driver = _wait_for_instagram('https://www.instagram.com/')
    return {'status': 'ready', 'platform': 'instagram', 'url': str(driver.current_url or ''), 'title': str(driver.title or ''), 'launch_result': launch_result, **get_browser_runtime_state()}

def close_instagram_browser() -> dict[str, Any]:
    """Close the shared browser session."""
    result = browser_kapat()
    return {'status': 'closed', 'platform': 'instagram', 'result': result}

def open_instagram_page(destination: str='home', query: str='', handle_or_url: str='', post_url: str='') -> dict[str, Any]:
    """Open an Instagram home, Explore, search, profile, Post, Reel, or inbox page."""
    target = str(destination or 'home').strip().casefold()
    if target in {'home', 'anasayfa'}:
        url = 'https://www.instagram.com/'
    elif target in {'explore', 'kesfet', 'keşfet'}:
        url = 'https://www.instagram.com/explore/'
    elif target in {'reels', 'reel'} and (not post_url):
        url = 'https://www.instagram.com/reels/'
    elif target in {'direct', 'messages', 'dm', 'inbox'}:
        url = 'https://www.instagram.com/direct/inbox/'
    elif target in {'notifications', 'activity', 'bildirimler'}:
        url = 'https://www.instagram.com/accounts/activity/'
    elif target in {'profile', 'profil'}:
        handle = _normalize_instagram_handle(handle_or_url)
        url = f'https://www.instagram.com/{quote(handle, safe='')}/'
    elif target in {'post', 'reel', 'media'}:
        url = _normalize_instagram_url(post_url, require_post=True)
    elif target in {'search', 'arama'}:
        clean_query = str(query or '').strip()
        if not clean_query:
            raise ValueError('An Instagram search query is required.')
        url = f'https://www.instagram.com/explore/search/keyword/?q={quote_plus(clean_query)}'
    elif target in {'create', 'new post', 'publish', 'olustur'}:
        url = 'https://www.instagram.com/'
    else:
        url = _normalize_instagram_url(destination)
    driver = _wait_for_instagram(url)
    return {'status': 'opened', 'destination': target, 'url': str(driver.current_url or ''), 'title': str(driver.title or '')}

def scan_instagram_posts(limit: int=20) -> dict[str, Any]:
    """Extract visible Instagram Posts and Reels from the current page."""
    driver = _get_driver()
    posts = _collect_instagram_posts(driver, limit=limit)
    return {'status': 'ok', 'source_url': str(driver.current_url or ''), 'count': len(posts), 'posts': posts}

def snapshot_instagram_feed(destination: str='home', handle_or_url: str='', limit: int=20, write_to_file: bool=True) -> dict[str, Any]:
    """Open and snapshot an Instagram feed or profile."""
    opened = open_instagram_page(destination=destination, handle_or_url=handle_or_url)
    snapshot = scan_instagram_posts(limit=limit)
    result = {'captured_at': _now(), 'opened': opened, **snapshot}
    if write_to_file:
        os.makedirs(_INSTAGRAM_WORKSPACE_DIR, exist_ok=True)
        with open(_INSTAGRAM_SNAPSHOT_PATH, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        result['snapshot_path'] = _INSTAGRAM_SNAPSHOT_PATH
    return result

def search_instagram(query: str, limit: int=20) -> dict[str, Any]:
    """Search Instagram in the browser and extract visible media results."""
    opened = open_instagram_page(destination='search', query=query)
    driver = _get_driver()
    posts = _collect_instagram_posts(driver, limit=limit)
    return {'status': 'ok', 'opened': opened, 'count': len(posts), 'posts': posts}

def inspect_instagram_profile(handle_or_url: str, media_limit: int=20) -> dict[str, Any]:
    """Inspect an Instagram profile through the browser."""
    handle = _normalize_instagram_handle(handle_or_url)
    driver = _wait_for_instagram(f'https://www.instagram.com/{quote(handle, safe='')}/')
    snapshot = driver.execute_script("\n        const text = (selector) => {\n          const el = document.querySelector(selector);\n          return (el?.innerText || el?.textContent || '').trim();\n        };\n        const stats = [...document.querySelectorAll('header ul li, header section ul li')]\n          .map((el) => (el.innerText || el.textContent || '').trim())\n          .filter(Boolean)\n          .slice(0, 8);\n        const body = (document.body?.innerText || '').trim();\n        return {\n          display_name: text('header h1, header h2'),\n          bio: text('header section div span, header section h1 + div'),\n          stats,\n          body_excerpt: body.slice(0, 2000),\n        };\n        ") or {}
    return {'status': 'ok', 'handle': handle, 'url': str(driver.current_url or ''), 'media': _collect_instagram_posts(driver, limit=media_limit), **snapshot}

def inspect_instagram_post(post_url: str) -> dict[str, Any]:
    """Inspect one Instagram Post or Reel through the browser."""
    target_url = _normalize_instagram_url(post_url, require_post=True)
    driver = _wait_for_instagram(target_url)
    snapshot = driver.execute_script('\n        const article = document.querySelector(\'article\') || document.querySelector(\'main\');\n        const body = (article?.innerText || article?.textContent || \'\').trim();\n        const image = article?.querySelector(\'img\');\n        const video = article?.querySelector(\'video\');\n        const labels = [...document.querySelectorAll(\'button, svg[aria-label]\')]\n          .map((el) => el.getAttribute(\'aria-label\') || el.innerText || \'\')\n          .filter(Boolean);\n        return {\n          caption: body.slice(0, 2000),\n          image_url: image?.currentSrc || image?.src || \'\',\n          alt_text: image?.alt || \'\',\n          video_url: video?.currentSrc || video?.src || \'\',\n          liked: labels.some((value) => /unlike|beğenmekten vazgeç/i.test(value)),\n          saved: labels.some((value) => /remove|unsave|collection/i.test(value)),\n          comment_ready: !!document.querySelector(\n            "textarea[aria-label*=\'comment\' i], textarea[placeholder*=\'comment\' i]"\n          ),\n        };\n        ') or {}
    return {'status': 'ok', 'shortcode': _instagram_shortcode(target_url), 'url': str(driver.current_url or ''), **snapshot}

def _instagram_browser_post_action(post_url: str, *, action: str, selectors: tuple[str, ...], markers: tuple[str, ...], already_markers: tuple[str, ...]=()) -> dict[str, Any]:
    target_url = _normalize_instagram_url(post_url, require_post=True)
    driver = _wait_for_instagram(target_url)
    if already_markers:
        already = _find_control_by_markers(driver, already_markers, require_enabled=False)
        if already is not None:
            return {'status': f'already_{action}', 'action': action, 'url': str(driver.current_url or ''), 'shortcode': _instagram_shortcode(target_url)}
    element = _find_visible(driver, selectors, require_enabled=True)
    if element is None:
        element = _find_control_by_markers(driver, markers, require_enabled=True)
    if element is None:
        return {'status': 'error', 'action': action, 'url': str(driver.current_url or ''), 'error': f'Could not locate Instagram {action} control.'}
    _human_click(driver, element)
    time.sleep(0.7)
    return {'status': 'attempted', 'action': action, 'url': str(driver.current_url or ''), 'shortcode': _instagram_shortcode(target_url)}

def like_instagram_post(post_url: str) -> dict[str, Any]:
    """Like an Instagram Post through the browser."""
    return _instagram_browser_post_action(post_url, action='liked', selectors=("svg[aria-label='Like']",), markers=('like', 'beğen', 'begen'), already_markers=('unlike', 'beğenmekten vazgeç'))

def unlike_instagram_post(post_url: str) -> dict[str, Any]:
    """Remove a Like from an Instagram Post through the browser."""
    return _instagram_browser_post_action(post_url, action='unliked', selectors=("svg[aria-label='Unlike']",), markers=('unlike', 'beğenmekten vazgeç'))

def save_instagram_post(post_url: str) -> dict[str, Any]:
    """Save an Instagram Post through the browser."""
    return _instagram_browser_post_action(post_url, action='saved', selectors=("svg[aria-label='Save']",), markers=('save', 'kaydet'), already_markers=('remove', 'unsave', 'koleksiyondan çıkar'))

def unsave_instagram_post(post_url: str) -> dict[str, Any]:
    """Remove an Instagram Post from saved items through the browser."""
    return _instagram_browser_post_action(post_url, action='unsaved', selectors=("svg[aria-label*='Remove' i]",), markers=('remove', 'unsave', 'koleksiyondan çıkar'))

def _instagram_browser_follow_action(handle_or_url: str, *, follow: bool) -> dict[str, Any]:
    handle = _normalize_instagram_handle(handle_or_url)
    driver = _wait_for_instagram(f'https://www.instagram.com/{quote(handle, safe='')}/')
    if follow:
        already = _find_control_by_markers(driver, ('following', 'requested', 'takiptesin', 'takip ediliyor'), require_enabled=False)
        if already is not None:
            return {'status': 'already_following', 'handle': handle}
        markers = ('follow', 'takip et')
    else:
        markers = ('following', 'requested', 'takiptesin', 'takip ediliyor')
    control = _find_control_by_markers(driver, markers, require_enabled=True)
    if control is None:
        return {'status': 'error', 'handle': handle, 'error': "Could not locate Instagram's follow control."}
    _human_click(driver, control)
    time.sleep(0.5)
    if not follow:
        confirm = _find_control_by_markers(driver, ('unfollow', 'takibi bırak', 'takipten çık'), require_enabled=True)
        if confirm is not None:
            _human_click(driver, confirm)
    return {'status': 'attempted', 'action': 'follow' if follow else 'unfollow', 'handle': handle, 'url': str(driver.current_url or '')}

def follow_instagram_account(handle_or_url: str) -> dict[str, Any]:
    """Follow an Instagram account through the browser."""
    return _instagram_browser_follow_action(handle_or_url, follow=True)

def unfollow_instagram_account(handle_or_url: str) -> dict[str, Any]:
    """Unfollow an Instagram account through the browser."""
    return _instagram_browser_follow_action(handle_or_url, follow=False)

def comment_instagram_post(post_url: str, message: str) -> dict[str, Any]:
    """Comment on an Instagram Post through the browser."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Instagram comment cannot be empty.')
    target_url = _normalize_instagram_url(post_url, require_post=True)
    driver = _wait_for_instagram(target_url)
    textarea = _find_visible(driver, ("textarea[aria-label*='comment' i]", "textarea[placeholder*='comment' i]", 'form textarea'), require_enabled=True)
    if textarea is None:
        raise RuntimeError("Could not locate Instagram's comment editor.")
    type_method = _type_into_element(driver, textarea, clean_message)
    submit = _find_control_by_markers(driver, ('post', 'paylaş', 'paylas'), require_enabled=True)
    if submit is not None:
        _human_click(driver, submit)
        submit_method = 'click'
    else:
        textarea.send_keys(Keys.ENTER)
        submit_method = 'enter'
    time.sleep(0.8)
    return {'status': 'attempted', 'shortcode': _instagram_shortcode(target_url), 'message': clean_message, 'type_method': type_method, 'submit_method': submit_method, 'url': str(driver.current_url or '')}

def send_instagram_message(handle_or_url: str, message: str) -> dict[str, Any]:
    """Send a direct message through Instagram's browser interface."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Instagram message cannot be empty.')
    handle = _normalize_instagram_handle(handle_or_url)
    driver = _wait_for_instagram(f'https://www.instagram.com/{quote(handle, safe='')}/')
    message_button = _find_control_by_markers(driver, ('message', 'mesaj'), require_enabled=True)
    if message_button is None:
        return {'status': 'error', 'handle': handle, 'error': "Could not locate Instagram's Message control."}
    _human_click(driver, message_button)
    time.sleep(1.0)
    editor = _find_visible(driver, ("textarea[placeholder*='message' i]", "div[contenteditable='true'][role='textbox']"), require_enabled=True)
    if editor is None:
        raise RuntimeError("Could not locate Instagram's message editor.")
    type_method = _type_into_element(driver, editor, clean_message)
    editor.send_keys(Keys.ENTER)
    time.sleep(0.7)
    return {'status': 'attempted', 'handle': handle, 'message': clean_message, 'type_method': type_method, 'url': str(driver.current_url or '')}

def publish_instagram_post(media_path: str, caption: str='') -> dict[str, Any]:
    """Publish a local image or video through Instagram's browser composer."""
    absolute_path = os.path.abspath(os.path.expanduser(str(media_path or '').strip()))
    if not os.path.isfile(absolute_path):
        raise ValueError(f'Instagram media file does not exist: {absolute_path}')
    if os.path.splitext(absolute_path)[1].lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'}:
        raise ValueError('Unsupported Instagram media file type.')
    driver = _wait_for_instagram('https://www.instagram.com/')
    create = _find_control_by_markers(driver, ('create', 'new post', 'oluştur', 'olustur'), require_enabled=True)
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
        next_button = _find_control_by_markers(driver, ('next', 'ileri'), require_enabled=True)
        if next_button is None:
            break
        _human_click(driver, next_button)
        time.sleep(0.8)
    clean_caption = str(caption or '').strip()
    if clean_caption:
        editor = _find_visible(driver, ("textarea[aria-label*='caption' i]", "div[contenteditable='true'][role='textbox']"), require_enabled=True)
        if editor is not None:
            _type_into_element(driver, editor, clean_caption)
    share = _find_control_by_markers(driver, ('share', 'paylaş', 'paylas'), require_enabled=True)
    if share is None:
        return {'status': 'drafted', 'media_path': absolute_path, 'caption': clean_caption, 'warning': "Media loaded, but Instagram's Share control was not found."}
    _human_click(driver, share)
    time.sleep(1.5)
    return {'status': 'submitted', 'media_path': absolute_path, 'caption': clean_caption, 'url': str(driver.current_url or '')}

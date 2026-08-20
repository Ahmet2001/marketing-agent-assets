"""Generated browser surface from the original MarketingApp toolbox.

Do not mix browser and API actions in a worker process.
"""

from __future__ import annotations

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

from MarketingApp.araclar.browser_araclari import _get_driver, _human_click, _read_element_value, _type_into_element, browser_baslat, browser_git, browser_kapat, get_browser_runtime_state

TOOLBOX_ACCESS_MODE = 'hybrid'

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_REDDIT_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, 'workspace', 'social')

_REDDIT_SNAPSHOT_PATH = os.path.join(_REDDIT_WORKSPACE_DIR, 'reddit_feed_snapshot.json')

_DEFAULT_REDDIT_API_BASE_URL = 'https://oauth.reddit.com'

_DEFAULT_REDDIT_TOKEN_URL = 'https://www.reddit.com/api/v1/access_token'

_DEFAULT_REDDIT_TIMEOUT = 30

_TOKEN_CACHE: dict[str, Any] = {'access_token': '', 'expires_at': 0.0, 'credential_fingerprint': '', 'token_type': '', 'scope': ''}

_REDDIT_POST_SELECTORS = ('shreddit-post', "article[data-testid='post-container']", "div[data-testid='post-container']")

_REDDIT_COMMENT_SELECTORS = ('shreddit-comment', "div[data-testid='comment']", "article[data-testid='comment']")

def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')

def _coerce_limit(value: Any, default: int=10, minimum: int=1, maximum: int=100) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))

def _compact_text(value: Any, limit: int=500) -> str:
    text = re.sub('\\s+', ' ', str(value or '')).strip()
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + '…'

def _normalize_subreddit(value: str) -> str:
    text = str(value or '').strip()
    if '://' in text:
        match = re.search('(?:www\\.|old\\.)?reddit\\.com/r/([A-Za-z0-9_]{2,21})', text, re.I)
        text = match.group(1) if match else ''
    text = re.sub('^(?:/?r/|@)', '', text, flags=re.I).strip('/')
    if not re.fullmatch('[A-Za-z0-9_]{2,21}', text):
        raise ValueError('A valid subreddit name is required.')
    return text

def _normalize_reddit_username(value: str) -> str:
    text = str(value or '').strip()
    if '://' in text:
        match = re.search('(?:www\\.|old\\.)?reddit\\.com/u(?:ser)?/([A-Za-z0-9_-]{1,20})', text, re.I)
        text = match.group(1) if match else ''
    text = re.sub('^(?:/?u(?:ser)?/|@)', '', text, flags=re.I).strip('/')
    if not re.fullmatch('[A-Za-z0-9_-]{1,20}', text):
        raise ValueError('A valid Reddit username is required.')
    return text

def _normalize_reddit_url(value: str, *, require_post: bool=False) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError('A Reddit URL is required.')
    if text.startswith('/'):
        text = f'https://www.reddit.com{text}'
    parsed = urlparse(text)
    hostname = (parsed.hostname or '').lower()
    if hostname not in {'reddit.com', 'www.reddit.com', 'old.reddit.com', 'redd.it'}:
        raise ValueError('Only reddit.com or redd.it URLs are accepted.')
    if require_post and '/comments/' not in parsed.path and (hostname != 'redd.it'):
        raise ValueError('A Reddit Post or comment URL is required.')
    return text

def _reddit_post_id(value: str) -> str:
    text = str(value or '').strip()
    if re.fullmatch('(?:t3_)?[A-Za-z0-9]{1,12}', text):
        return text.removeprefix('t3_').lower()
    match = re.search('(?:/comments/|redd\\.it/)([A-Za-z0-9]{1,12})', text, re.I)
    if not match:
        raise ValueError('A valid Reddit Post ID, fullname, or URL is required.')
    return match.group(1).lower()

def _reddit_fullname(value: str, default_kind: str='t3') -> str:
    text = str(value or '').strip()
    if re.fullmatch('t[1-6]_[A-Za-z0-9]{1,12}', text):
        return text.lower()
    if '://' in text or text.startswith('/'):
        post_id = _reddit_post_id(text)
        parsed = urlparse(_normalize_reddit_url(text, require_post=True))
        parts = [part for part in parsed.path.split('/') if part]
        try:
            comments_index = parts.index('comments')
        except ValueError:
            comments_index = -1
        if comments_index >= 0 and len(parts) >= comments_index + 4:
            possible_comment_id = parts[comments_index + 3]
            if re.fullmatch('[A-Za-z0-9]{1,12}', possible_comment_id):
                return f't1_{possible_comment_id.lower()}'
        return f't3_{post_id}'
    if not re.fullmatch('[A-Za-z0-9]{1,12}', text):
        raise ValueError('A valid Reddit thing ID or fullname is required.')
    if default_kind not in {'t1', 't3', 't4'}:
        raise ValueError('default_kind must be t1, t3, or t4.')
    return f'{default_kind}_{text.lower()}'

def _reddit_page_ready(driver) -> bool:
    try:
        return driver.execute_script('\n            return document.readyState !== \'loading\' &&\n              !!document.querySelector(\n                "shreddit-app, shreddit-post, article, main, #siteTable"\n              );\n            ')
    except Exception:
        return False

def _wait_for_reddit(url: str, timeout: int=20):
    driver = _get_driver()
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(_reddit_page_ready)
    except TimeoutException:
        pass
    current_url = str(driver.current_url or '')
    if 'reddit.com/login' in current_url:
        raise RuntimeError('Reddit requires login. Complete login in the shared browser session.')
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

def _find_button_by_text(driver, markers: tuple[str, ...], *, root=None, require_enabled: bool=True):
    normalized_markers = tuple((marker.casefold() for marker in markers))
    scope = root or driver
    selectors = "button, [role='button'], faceplate-tracker, a"
    for element in scope.find_elements(By.CSS_SELECTOR, selectors):
        try:
            if not element.is_displayed():
                continue
            if require_enabled and (not element.is_enabled()):
                continue
            combined = ' '.join((element.text or '', element.get_attribute('aria-label') or '', element.get_attribute('title') or '', element.get_attribute('data-testid') or '', element.get_attribute('action') or '')).casefold()
            if any((marker in combined for marker in normalized_markers)):
                return element
        except Exception:
            continue
    return None

def _collect_reddit_posts(driver, limit: int=20) -> list[dict[str, Any]]:
    return driver.execute_script('\n        const limit = arguments[0];\n        const selectors = [\n          \'shreddit-post\',\n          "article[data-testid=\'post-container\']",\n          "div[data-testid=\'post-container\']"\n        ];\n        const seen = new Set();\n        const nodes = selectors.flatMap((selector) => [...document.querySelectorAll(selector)]);\n        const results = [];\n        const text = (root, selector) => {\n          const node = root.querySelector(selector);\n          return (node?.innerText || node?.textContent || \'\').trim();\n        };\n        for (const node of nodes) {\n          if (results.length >= limit) break;\n          const permalink =\n            node.getAttribute(\'permalink\') ||\n            node.querySelector("a[href*=\'/comments/\']")?.getAttribute(\'href\') || \'\';\n          const canonical = permalink.startsWith(\'http\')\n            ? permalink\n            : permalink ? `https://www.reddit.com${permalink}` : \'\';\n          const postId =\n            node.getAttribute(\'id\') ||\n            node.getAttribute(\'thingid\') ||\n            (canonical.match(/\\/comments\\/([a-z0-9]+)/i) || [])[1] || \'\';\n          const key = postId || canonical;\n          if (!key || seen.has(key)) continue;\n          seen.add(key);\n          const title =\n            node.getAttribute(\'post-title\') ||\n            text(node, \'[slot="title"]\') ||\n            text(node, \'h1, h2, h3\');\n          const author =\n            node.getAttribute(\'author\') ||\n            text(node, "a[href*=\'/user/\'], a[href*=\'/u/\']");\n          const subreddit =\n            node.getAttribute(\'subreddit-prefixed-name\') ||\n            node.getAttribute(\'subreddit-name\') ||\n            text(node, "a[href^=\'/r/\']");\n          const body =\n            node.getAttribute(\'content-href\') ||\n            text(node, \'[slot="text-body"]\') ||\n            text(node, \'[data-post-click-location="text-body"]\');\n          const score =\n            node.getAttribute(\'score\') ||\n            text(node, \'[slot="vote-button"]\') ||\n            text(node, \'[data-testid="post-container"] [id*="vote"]\');\n          results.push({\n            post_id: String(postId).replace(/^t3_/, \'\'),\n            fullname: String(postId).startsWith(\'t3_\') ? postId : postId ? `t3_${postId}` : \'\',\n            title,\n            body,\n            author: String(author).replace(/^u\\//, \'\'),\n            subreddit: String(subreddit).replace(/^r\\//, \'\'),\n            score,\n            comments: text(node, "a[href*=\'/comments/\']"),\n            url: canonical,\n          });\n        }\n        return results;\n        ', _coerce_limit(limit, default=20, minimum=1, maximum=100)) or []

def _collect_reddit_comments(driver, limit: int=50) -> list[dict[str, Any]]:
    return driver.execute_script('\n        const limit = arguments[0];\n        const nodes = [\n          ...document.querySelectorAll(\n            "shreddit-comment, div[data-testid=\'comment\'], article[data-testid=\'comment\']"\n          )\n        ];\n        const seen = new Set();\n        const results = [];\n        for (const node of nodes) {\n          if (results.length >= limit) break;\n          const id =\n            node.getAttribute(\'thingid\') ||\n            node.getAttribute(\'id\') ||\n            node.getAttribute(\'comment-id\') || \'\';\n          if (id && seen.has(id)) continue;\n          if (id) seen.add(id);\n          const author =\n            node.getAttribute(\'author\') ||\n            node.querySelector("a[href*=\'/user/\'], a[href*=\'/u/\']")?.textContent || \'\';\n          const bodyNode = node.querySelector(\n            \'[slot="comment"], [data-testid="comment"], .md, [id*="-post-rtjson-content"]\'\n          );\n          const permalink = node.querySelector("a[href*=\'/comments/\']")?.getAttribute(\'href\') || \'\';\n          results.push({\n            comment_id: String(id).replace(/^t1_/, \'\'),\n            fullname: String(id).startsWith(\'t1_\') ? id : id ? `t1_${id}` : \'\',\n            author: String(author).trim().replace(/^u\\//, \'\'),\n            body: (bodyNode?.innerText || bodyNode?.textContent || \'\').trim(),\n            score: node.getAttribute(\'score\') || \'\',\n            url: permalink.startsWith(\'http\')\n              ? permalink\n              : permalink ? `https://www.reddit.com${permalink}` : \'\',\n          });\n        }\n        return results;\n        ', _coerce_limit(limit, default=50, minimum=1, maximum=100)) or []

def get_reddit_browser_status() -> dict[str, Any]:
    """Return shared browser status and whether it is currently on Reddit."""
    state = get_browser_runtime_state()
    if not state.get('ready'):
        return {**state, 'platform': 'reddit', 'url': '', 'title': '', 'on_reddit': False}
    driver = _get_driver()
    url = str(driver.current_url or '')
    return {**state, 'platform': 'reddit', 'url': url, 'title': str(driver.title or ''), 'on_reddit': 'reddit.com' in urlparse(url).netloc.lower()}

def launch_reddit_browser(headless: bool=False, restart_if_needed: bool=True) -> dict[str, Any]:
    """Launch the shared browser and open Reddit."""
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
            return {'status': 'error', 'platform': 'reddit', 'error': launch_result or 'Browser could not be launched.'}
    driver = _wait_for_reddit('https://www.reddit.com/', timeout=20)
    return {'status': 'ready', 'platform': 'reddit', 'url': str(driver.current_url or ''), 'title': str(driver.title or ''), 'launch_result': launch_result, **get_browser_runtime_state()}

def close_reddit_browser() -> dict[str, Any]:
    """Close the shared browser session."""
    result = browser_kapat()
    return {'status': 'closed', 'platform': 'reddit', 'result': result}

def open_reddit_page(destination: str='home', subreddit: str='', query: str='', username: str='', post_url: str='', sort: str='hot', time_filter: str='all') -> dict[str, Any]:
    """Open a Reddit home, community, search, profile, inbox, or Post page."""
    target = str(destination or 'home').strip().casefold()
    normalized_sort = str(sort or 'hot').strip().lower()
    if normalized_sort not in {'hot', 'new', 'top', 'rising', 'controversial'}:
        raise ValueError('sort must be hot, new, top, rising, or controversial.')
    normalized_time = str(time_filter or 'all').strip().lower()
    if normalized_time not in {'hour', 'day', 'week', 'month', 'year', 'all'}:
        raise ValueError('time_filter must be hour, day, week, month, year, or all.')
    if target in {'home', 'frontpage', 'ana sayfa'}:
        url = f'https://www.reddit.com/{normalized_sort}/'
    elif target in {'popular'}:
        url = f'https://www.reddit.com/r/popular/{normalized_sort}/'
    elif target in {'all'}:
        url = f'https://www.reddit.com/r/all/{normalized_sort}/'
    elif target in {'subreddit', 'community', 'topluluk'}:
        sr = _normalize_subreddit(subreddit)
        url = f'https://www.reddit.com/r/{quote(sr, safe='')}/{normalized_sort}/'
    elif target in {'search', 'ara'}:
        if not str(query or '').strip():
            raise ValueError('A Reddit search query is required.')
        scope = f'r/{_normalize_subreddit(subreddit)}/' if subreddit else ''
        url = f'https://www.reddit.com/{scope}search/?q={quote_plus(query.strip())}&sort={normalized_sort}&t={normalized_time}'
    elif target in {'profile', 'user', 'kullanici'}:
        user = _normalize_reddit_username(username)
        url = f'https://www.reddit.com/user/{quote(user, safe='')}/'
    elif target in {'post', 'comments', 'comment'}:
        url = _normalize_reddit_url(post_url, require_post=True)
    elif target in {'inbox', 'messages'}:
        url = 'https://www.reddit.com/message/inbox/'
    elif target in {'notifications', 'bildirimler'}:
        url = 'https://www.reddit.com/notifications/'
    elif target in {'saved', 'kaydedilenler'}:
        url = 'https://www.reddit.com/user/me/saved/'
    elif target in {'submit', 'create', 'new post', 'post olustur'}:
        sr = _normalize_subreddit(subreddit)
        url = f'https://www.reddit.com/r/{quote(sr, safe='')}/submit/'
    else:
        url = _normalize_reddit_url(destination)
    driver = _wait_for_reddit(url)
    return {'status': 'opened', 'destination': target, 'url': str(driver.current_url or ''), 'title': str(driver.title or '')}

def scan_reddit_posts(limit: int=20) -> dict[str, Any]:
    """Extract visible Posts from the current Reddit page."""
    driver = _get_driver()
    posts = _collect_reddit_posts(driver, limit=limit)
    return {'status': 'ok', 'source_url': str(driver.current_url or ''), 'count': len(posts), 'posts': posts}

def snapshot_reddit_feed(destination: str='home', subreddit: str='', sort: str='hot', limit: int=20, write_to_file: bool=True) -> dict[str, Any]:
    """Open and snapshot a Reddit listing, optionally writing workspace JSON."""
    opened = open_reddit_page(destination=destination, subreddit=subreddit, sort=sort)
    snapshot = scan_reddit_posts(limit=limit)
    result = {'captured_at': _now(), 'opened': opened, **snapshot}
    if write_to_file:
        os.makedirs(_REDDIT_WORKSPACE_DIR, exist_ok=True)
        with open(_REDDIT_SNAPSHOT_PATH, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        result['snapshot_path'] = _REDDIT_SNAPSHOT_PATH
    return result

def search_reddit_posts(query: str, subreddit: str='', sort: str='relevance', time_filter: str='all', limit: int=20) -> dict[str, Any]:
    """Search Reddit in the browser and extract visible results."""
    normalized_sort = str(sort or 'relevance').lower()
    if normalized_sort not in {'relevance', 'hot', 'top', 'new', 'comments'}:
        raise ValueError('sort must be relevance, hot, top, new, or comments.')
    opened = open_reddit_page(destination='search', subreddit=subreddit, query=query, sort='hot' if normalized_sort == 'relevance' else normalized_sort, time_filter=time_filter)
    driver = _get_driver()
    if normalized_sort == 'relevance':
        scope = f'r/{_normalize_subreddit(subreddit)}/' if subreddit else ''
        url = f'https://www.reddit.com/{scope}search/?q={quote_plus(query.strip())}&sort=relevance&t={time_filter}'
        driver = _wait_for_reddit(url)
        opened['url'] = str(driver.current_url or '')
    posts = _collect_reddit_posts(driver, limit=limit)
    return {'status': 'ok', 'opened': opened, 'count': len(posts), 'posts': posts}

def inspect_reddit_post(post_url: str, comment_limit: int=50) -> dict[str, Any]:
    """Open a Reddit Post and extract the Post plus visible comments."""
    target_url = _normalize_reddit_url(post_url, require_post=True)
    driver = _wait_for_reddit(target_url)
    posts = _collect_reddit_posts(driver, limit=1)
    comments = _collect_reddit_comments(driver, limit=comment_limit)
    return {'status': 'ok', 'url': str(driver.current_url or ''), 'post': posts[0] if posts else {}, 'comment_count': len(comments), 'comments': comments}

def inspect_reddit_profile(username: str, limit: int=20) -> dict[str, Any]:
    """Open a Reddit profile and extract visible activity."""
    user = _normalize_reddit_username(username)
    driver = _wait_for_reddit(f'https://www.reddit.com/user/{quote(user, safe='')}/')
    posts = _collect_reddit_posts(driver, limit=limit)
    body = str(driver.find_element(By.TAG_NAME, 'body').text or '')
    return {'status': 'ok', 'username': user, 'url': str(driver.current_url or ''), 'profile_summary': _compact_text(body, 1200), 'posts': posts}

def inspect_reddit_community(subreddit: str, limit: int=20) -> dict[str, Any]:
    """Open a subreddit and extract its visible summary and Posts."""
    sr = _normalize_subreddit(subreddit)
    driver = _wait_for_reddit(f'https://www.reddit.com/r/{quote(sr, safe='')}/')
    posts = _collect_reddit_posts(driver, limit=limit)
    body = str(driver.find_element(By.TAG_NAME, 'body').text or '')
    return {'status': 'ok', 'subreddit': sr, 'url': str(driver.current_url or ''), 'community_summary': _compact_text(body, 1500), 'posts': posts}

def _reddit_browser_post_action(post_url: str, selectors: tuple[str, ...], markers: tuple[str, ...], action: str) -> dict[str, Any]:
    driver = _wait_for_reddit(_normalize_reddit_url(post_url, require_post=True))
    element = _find_visible(driver, selectors, require_enabled=True)
    if element is None:
        element = _find_button_by_text(driver, markers, require_enabled=True)
    if element is None:
        return {'status': 'error', 'action': action, 'url': str(driver.current_url or ''), 'error': f'Could not locate Reddit {action} control.'}
    _human_click(driver, element)
    time.sleep(0.7)
    return {'status': 'attempted', 'action': action, 'url': str(driver.current_url or ''), 'post_id': _reddit_post_id(post_url)}

def upvote_reddit_post(post_url: str) -> dict[str, Any]:
    """Upvote a Reddit Post through the browser."""
    return _reddit_browser_post_action(post_url, ("button[aria-label*='upvote' i]", "[data-testid='upvote-button']", "faceplate-tracker[noun='upvote'] button"), ('upvote', 'up vote'), 'upvote')

def downvote_reddit_post(post_url: str) -> dict[str, Any]:
    """Downvote a Reddit Post through the browser."""
    return _reddit_browser_post_action(post_url, ("button[aria-label*='downvote' i]", "[data-testid='downvote-button']", "faceplate-tracker[noun='downvote'] button"), ('downvote', 'down vote'), 'downvote')

def clear_reddit_post_vote(post_url: str) -> dict[str, Any]:
    """Clear the current vote by clicking the selected vote control."""
    return _reddit_browser_post_action(post_url, ("button[aria-pressed='true'][aria-label*='vote' i]", "[data-testid='upvote-button'][aria-pressed='true']", "[data-testid='downvote-button'][aria-pressed='true']"), ('remove upvote', 'remove downvote'), 'clear_vote')

def save_reddit_post(post_url: str) -> dict[str, Any]:
    """Save a Reddit Post through the browser."""
    return _reddit_browser_post_action(post_url, ("button[aria-label='Save' i]", "[data-testid='save-button']"), ('save',), 'save')

def unsave_reddit_post(post_url: str) -> dict[str, Any]:
    """Remove a Reddit Post from saved items through the browser."""
    return _reddit_browser_post_action(post_url, ("button[aria-label='Unsave' i]", "[data-testid='unsave-button']"), ('unsave',), 'unsave')

def _reddit_browser_community_action(subreddit: str, *, join: bool) -> dict[str, Any]:
    sr = _normalize_subreddit(subreddit)
    driver = _wait_for_reddit(f'https://www.reddit.com/r/{quote(sr, safe='')}/')
    markers = ('join', 'katıl') if join else ('joined', 'leave', 'ayrıl')
    element = _find_button_by_text(driver, markers, require_enabled=True)
    if element is None:
        return {'status': 'error', 'action': 'join' if join else 'leave', 'subreddit': sr, 'error': 'Could not locate the subreddit membership control.'}
    label = ' '.join((element.text or '', element.get_attribute('aria-label') or '')).casefold()
    if join and ('joined' in label or 'katıld' in label):
        return {'status': 'already_joined', 'subreddit': sr}
    _human_click(driver, element)
    time.sleep(0.7)
    return {'status': 'attempted', 'action': 'join' if join else 'leave', 'subreddit': sr, 'url': str(driver.current_url or '')}

def join_reddit_community(subreddit: str) -> dict[str, Any]:
    """Join a subreddit through the browser."""
    return _reddit_browser_community_action(subreddit, join=True)

def leave_reddit_community(subreddit: str) -> dict[str, Any]:
    """Leave a subreddit through the browser."""
    return _reddit_browser_community_action(subreddit, join=False)

def _fill_reddit_submit_form(subreddit: str, title: str, *, body: str='', url: str='') -> dict[str, Any]:
    sr = _normalize_subreddit(subreddit)
    clean_title = str(title or '').strip()
    if not clean_title:
        raise ValueError('Reddit Post title cannot be empty.')
    driver = _wait_for_reddit(f'https://www.reddit.com/r/{quote(sr, safe='')}/submit/')
    if url:
        tab = _find_button_by_text(driver, ('link',), require_enabled=True)
        if tab is not None:
            _human_click(driver, tab)
            time.sleep(0.5)
    elif body:
        tab = _find_button_by_text(driver, ('text', 'post'), require_enabled=True)
        if tab is not None:
            _human_click(driver, tab)
            time.sleep(0.5)
    title_element = _find_visible(driver, ("textarea[name='title']", "input[name='title']", "textarea[placeholder*='title' i]", "input[placeholder*='title' i]"), require_enabled=True)
    if title_element is None:
        raise RuntimeError("Could not locate Reddit's Post title field.")
    _type_into_element(driver, title_element, clean_title)
    if url:
        url_element = _find_visible(driver, ("input[name='url']", "textarea[name='url']", "input[placeholder*='url' i]", "textarea[placeholder*='url' i]"), require_enabled=True)
        if url_element is None:
            raise RuntimeError("Could not locate Reddit's link URL field.")
        _type_into_element(driver, url_element, url)
    elif body:
        body_element = _find_visible(driver, ("div[contenteditable='true'][role='textbox']", "textarea[name='text']", "textarea[placeholder*='body' i]", "textarea[placeholder*='text' i]"), require_enabled=True)
        if body_element is None:
            raise RuntimeError("Could not locate Reddit's Post body editor.")
        _type_into_element(driver, body_element, body)
    submit = _find_visible(driver, ("button[type='submit']", "button[data-testid='submit-post-button']"), require_enabled=True)
    if submit is None:
        submit = _find_button_by_text(driver, ('post', 'submit', 'gönder'), require_enabled=True)
    if submit is None:
        return {'status': 'drafted', 'subreddit': sr, 'title': clean_title, 'url': str(driver.current_url or ''), 'warning': 'Form filled, but the final submit control was not found.'}
    _human_click(driver, submit)
    time.sleep(1.2)
    current_url = str(driver.current_url or '')
    return {'status': 'submitted' if '/comments/' in current_url else 'pending_verify', 'subreddit': sr, 'title': clean_title, 'url': current_url, 'post_id': _reddit_post_id(current_url) if '/comments/' in current_url else ''}

def publish_reddit_text_post(subreddit: str, title: str, body: str='') -> dict[str, Any]:
    """Publish a text Post through Reddit's browser composer."""
    return _fill_reddit_submit_form(subreddit, title, body=str(body or ''))

def publish_reddit_link_post(subreddit: str, title: str, url: str) -> dict[str, Any]:
    """Publish a link Post through Reddit's browser composer."""
    parsed = urlparse(str(url or '').strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('A valid HTTP(S) link is required.')
    return _fill_reddit_submit_form(subreddit, title, url=url)

def comment_reddit_post(post_url: str, message: str) -> dict[str, Any]:
    """Comment on a Reddit Post through the browser."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Reddit comment cannot be empty.')
    driver = _wait_for_reddit(_normalize_reddit_url(post_url, require_post=True))
    editor = _find_visible(driver, ("div[contenteditable='true'][role='textbox']", "textarea[placeholder*='comment' i]", "textarea[name='comment']"), require_enabled=True)
    if editor is None:
        raise RuntimeError("Could not locate Reddit's comment editor.")
    _type_into_element(driver, editor, clean_message)
    submit = _find_button_by_text(driver, ('comment', 'reply', 'yorum', 'yanıtla'), require_enabled=True)
    if submit is None:
        return {'status': 'drafted', 'url': str(driver.current_url or ''), 'warning': 'Comment filled, but the submit control was not found.'}
    _human_click(driver, submit)
    time.sleep(1.0)
    return {'status': 'attempted', 'post_id': _reddit_post_id(post_url), 'message': clean_message, 'url': str(driver.current_url or '')}

def reply_reddit_comment(comment_url: str, message: str) -> dict[str, Any]:
    """Reply to a Reddit comment through the browser."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Reddit reply cannot be empty.')
    target_url = _normalize_reddit_url(comment_url, require_post=True)
    driver = _wait_for_reddit(target_url)
    comment_fullname = _reddit_fullname(target_url)
    comment_id = comment_fullname.removeprefix('t1_')
    root = None
    for selector in (f"shreddit-comment[thingid='{comment_fullname}']", f"shreddit-comment[comment-id='{comment_id}']", f'#{comment_fullname}'):
        root = _find_visible(driver, (selector,))
        if root is not None:
            break
    reply_button = _find_button_by_text(driver, ('reply', 'yanıtla'), root=root, require_enabled=True)
    if reply_button is None:
        return {'status': 'error', 'comment_fullname': comment_fullname, 'error': 'Could not locate the comment Reply control.'}
    _human_click(driver, reply_button)
    time.sleep(0.5)
    editor = _find_visible(driver, ("div[contenteditable='true'][role='textbox']", "textarea[placeholder*='reply' i]", "textarea[placeholder*='comment' i]"), require_enabled=True)
    if editor is None:
        raise RuntimeError("Could not locate Reddit's reply editor.")
    _type_into_element(driver, editor, clean_message)
    submit = _find_button_by_text(driver, ('comment', 'reply', 'yanıtla'), require_enabled=True)
    if submit is None:
        return {'status': 'drafted', 'comment_fullname': comment_fullname, 'warning': 'Reply filled, but the submit control was not found.'}
    _human_click(driver, submit)
    time.sleep(1.0)
    return {'status': 'attempted', 'comment_fullname': comment_fullname, 'message': clean_message, 'url': str(driver.current_url or '')}

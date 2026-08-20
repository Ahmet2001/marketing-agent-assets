"""Generated api surface from the original MarketingApp toolbox.

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

def _coerce_limit(value: Any, default: int=10, minimum: int=1, maximum: int=100) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))

def _first_environment_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, '').strip()
        if value:
            return value
    return ''

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

def _reddit_api_credentials() -> dict[str, str]:
    return {'client_id': _first_environment_value('REDDIT_CLIENT_ID'), 'client_secret': _first_environment_value('REDDIT_CLIENT_SECRET'), 'access_token': _first_environment_value('REDDIT_ACCESS_TOKEN'), 'refresh_token': _first_environment_value('REDDIT_REFRESH_TOKEN'), 'username': _first_environment_value('REDDIT_USERNAME'), 'password': _first_environment_value('REDDIT_PASSWORD'), 'user_agent': _first_environment_value('REDDIT_USER_AGENT')}

def _reddit_api_base_url() -> str:
    return (os.getenv('REDDIT_API_BASE_URL', _DEFAULT_REDDIT_API_BASE_URL).strip() or _DEFAULT_REDDIT_API_BASE_URL).rstrip('/')

def _reddit_token_url() -> str:
    return os.getenv('REDDIT_TOKEN_URL', _DEFAULT_REDDIT_TOKEN_URL).strip() or _DEFAULT_REDDIT_TOKEN_URL

def _reddit_api_timeout() -> int:
    try:
        timeout = int(os.getenv('REDDIT_API_TIMEOUT', str(_DEFAULT_REDDIT_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_REDDIT_TIMEOUT
    return max(5, min(timeout, 120))

def _reddit_api_error(error: str, *, endpoint: str='', status_code: int=0, response: Any=None) -> dict[str, Any]:
    result: dict[str, Any] = {'ok': False, 'status': 'error', 'status_code': status_code, 'endpoint': endpoint, 'error': error}
    if response is not None:
        result['response'] = response
    return result

def _reddit_credential_fingerprint(credentials: dict[str, str], token_type: str) -> str:
    material = '|'.join((token_type, credentials['client_id'], credentials['client_secret'], credentials['access_token'], credentials['refresh_token'], credentials['username'], credentials['password']))
    return hashlib.sha256(material.encode('utf-8')).hexdigest()

def _reddit_access_token(require_user: bool=False) -> tuple[str, str, str]:
    credentials = _reddit_api_credentials()
    if not credentials['user_agent']:
        raise RuntimeError("REDDIT_USER_AGENT is required. Use a truthful value such as 'linux:EthosMarketingAgent:1.0 (by /u/YourUsername)'.")
    if credentials['access_token']:
        return (credentials['access_token'], 'provided_access_token', '')
    if not credentials['client_id']:
        raise RuntimeError('REDDIT_CLIENT_ID is required to obtain an OAuth token.')
    if credentials['refresh_token']:
        token_type = 'refresh_token'
        token_data = {'grant_type': 'refresh_token', 'refresh_token': credentials['refresh_token']}
    elif credentials['username'] and credentials['password']:
        token_type = 'password'
        token_data = {'grant_type': 'password', 'username': credentials['username'], 'password': credentials['password']}
    elif not require_user:
        token_type = 'client_credentials'
        token_data = {'grant_type': 'client_credentials'}
    else:
        raise RuntimeError('A user-context token is required. Configure REDDIT_ACCESS_TOKEN, REDDIT_REFRESH_TOKEN, or REDDIT_USERNAME and REDDIT_PASSWORD.')
    fingerprint = _reddit_credential_fingerprint(credentials, token_type)
    if _TOKEN_CACHE['access_token'] and _TOKEN_CACHE['credential_fingerprint'] == fingerprint and (float(_TOKEN_CACHE['expires_at']) > time.time() + 30):
        return (str(_TOKEN_CACHE['access_token']), str(_TOKEN_CACHE['token_type']), str(_TOKEN_CACHE['scope']))
    response = requests.post(_reddit_token_url(), auth=HTTPBasicAuth(credentials['client_id'], credentials['client_secret']), data=token_data, headers={'User-Agent': credentials['user_agent'], 'Accept': 'application/json'}, timeout=_reddit_api_timeout())
    try:
        payload = response.json()
    except ValueError:
        payload = {'raw_text': response.text[:2000]}
    if not response.ok or not isinstance(payload, dict) or (not payload.get('access_token')):
        detail = payload.get('error') if isinstance(payload, dict) else ''
        raise RuntimeError(str(detail or f'Reddit OAuth returned HTTP {response.status_code}'))
    expires_in = int(payload.get('expires_in', 3600) or 3600)
    _TOKEN_CACHE.update({'access_token': str(payload['access_token']), 'expires_at': time.time() + max(60, expires_in), 'credential_fingerprint': fingerprint, 'token_type': token_type, 'scope': str(payload.get('scope', ''))})
    return (str(payload['access_token']), token_type, str(payload.get('scope', '')))

def _listing_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get('data')
    if not isinstance(data, dict):
        return []
    children = data.get('children')
    if not isinstance(children, list):
        return []
    items: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_data = child.get('data')
        if not isinstance(child_data, dict):
            continue
        item = dict(child_data)
        item['kind'] = child.get('kind', '')
        items.append(item)
    return items

def _reddit_api_request(method: str, endpoint: str, *, require_user: bool=False, params: dict[str, Any] | None=None, data: dict[str, Any] | None=None) -> dict[str, Any]:
    normalized_method = str(method or 'GET').upper().strip()
    normalized_endpoint = '/' + str(endpoint or '').lstrip('/')
    if normalized_method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
        return _reddit_api_error(f'Unsupported Reddit API method: {normalized_method}', endpoint=normalized_endpoint)
    if '://' in normalized_endpoint or '..' in normalized_endpoint:
        return _reddit_api_error('Reddit API endpoint must be a relative OAuth path.', endpoint=normalized_endpoint)
    try:
        access_token, token_type, scope = _reddit_access_token(require_user=require_user)
    except (RuntimeError, requests.RequestException) as exc:
        return _reddit_api_error(str(exc), endpoint=normalized_endpoint)
    credentials = _reddit_api_credentials()
    clean_params = {'raw_json': 1, **{key: value for key, value in (params or {}).items() if value not in (None, '', [], ())}}
    clean_data = {'raw_json': 1}
    for key, value in (data or {}).items():
        if value in (None, '', [], ()):
            continue
        clean_data[key] = str(value).lower() if isinstance(value, bool) else value
    try:
        response = requests.request(normalized_method, f'{_reddit_api_base_url()}{normalized_endpoint}', params=clean_params if normalized_method == 'GET' else None, data=clean_data if normalized_method != 'GET' else None, headers={'Authorization': f'bearer {access_token}', 'User-Agent': credentials['user_agent'], 'Accept': 'application/json'}, timeout=_reddit_api_timeout())
    except requests.RequestException as exc:
        return _reddit_api_error(f'Reddit API request failed: {exc}', endpoint=normalized_endpoint)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = {'raw_text': response.text[:4000]}
    api_errors: list[Any] = []
    if isinstance(payload, dict):
        json_block = payload.get('json')
        if isinstance(json_block, dict) and isinstance(json_block.get('errors'), list):
            api_errors = json_block['errors']
    ok = bool(response.ok and (not api_errors))
    result: dict[str, Any] = {'ok': ok, 'status': 'ok' if ok else 'error', 'status_code': response.status_code, 'method': normalized_method, 'endpoint': normalized_endpoint, 'token_type': token_type, 'scope': scope, 'rate_limit': {'used': response.headers.get('x-ratelimit-used', ''), 'remaining': response.headers.get('x-ratelimit-remaining', ''), 'reset_seconds': response.headers.get('x-ratelimit-reset', '')}, 'response': payload}
    items = _listing_items(payload)
    if items:
        result['items'] = items
        result['count'] = len(items)
    if isinstance(payload, dict) and 'data' in payload:
        result['data'] = payload['data']
    if api_errors:
        result['errors'] = api_errors
    if not ok:
        if api_errors:
            detail = '; '.join((': '.join((str(part) for part in error)) if isinstance(error, (list, tuple)) else str(error) for error in api_errors))
        elif isinstance(payload, dict):
            detail = payload.get('message') or payload.get('error') or ''
        else:
            detail = ''
        result['error'] = str(detail or f'Reddit API returned HTTP {response.status_code}')
    return result

def get_reddit_api_status(verify_credentials: bool=False) -> dict[str, Any]:
    """Report Reddit API configuration without exposing credential values."""
    credentials = _reddit_api_credentials()
    has_user_auth = bool(credentials['access_token'] or credentials['refresh_token'] or (credentials['username'] and credentials['password']))
    configured = bool(credentials['user_agent'] and (credentials['access_token'] or credentials['client_id']))
    result: dict[str, Any] = {'status': 'configured' if configured else 'not_configured', 'api_base_url': _reddit_api_base_url(), 'token_url': _reddit_token_url(), 'timeout_seconds': _reddit_api_timeout(), 'user_agent_configured': bool(credentials['user_agent']), 'client_credentials_configured': bool(credentials['client_id']), 'provided_access_token_configured': bool(credentials['access_token']), 'refresh_token_configured': bool(credentials['refresh_token']), 'personal_script_credentials_configured': bool(credentials['username'] and credentials['password']), 'user_actions_configured': has_user_auth}
    if not verify_credentials:
        return result
    verification = get_reddit_api_me() if has_user_auth else get_reddit_api_listing(limit=1)
    result['verification'] = verification
    result['status'] = 'verified' if verification.get('ok') else 'verification_failed'
    return result

def get_reddit_api_me() -> dict[str, Any]:
    """Get the authenticated Reddit account."""
    return _reddit_api_request('GET', '/api/v1/me', require_user=True)

def get_reddit_api_listing(subreddit: str='', sort: str='hot', time_filter: str='all', limit: int=25, after: str='') -> dict[str, Any]:
    """Get a Reddit front-page or subreddit listing through the Data API."""
    normalized_sort = str(sort or 'hot').lower()
    if normalized_sort not in {'hot', 'new', 'top', 'rising', 'controversial', 'best'}:
        raise ValueError('Invalid Reddit listing sort.')
    normalized_time = str(time_filter or 'all').lower()
    if normalized_time not in {'hour', 'day', 'week', 'month', 'year', 'all'}:
        raise ValueError('Invalid Reddit time_filter.')
    prefix = f'/r/{_normalize_subreddit(subreddit)}' if subreddit else ''
    return _reddit_api_request('GET', f'{prefix}/{normalized_sort}', params={'limit': _coerce_limit(limit, default=25, minimum=1, maximum=100), 'after': str(after or '').strip(), 't': normalized_time})

def search_reddit_api_posts(query: str, subreddit: str='', sort: str='relevance', time_filter: str='all', limit: int=25, after: str='') -> dict[str, Any]:
    """Search Reddit Posts through the official Data API."""
    clean_query = str(query or '').strip()
    if not clean_query:
        raise ValueError('Reddit search query cannot be empty.')
    normalized_sort = str(sort or 'relevance').lower()
    if normalized_sort not in {'relevance', 'hot', 'top', 'new', 'comments'}:
        raise ValueError('Invalid Reddit search sort.')
    normalized_time = str(time_filter or 'all').lower()
    if normalized_time not in {'hour', 'day', 'week', 'month', 'year', 'all'}:
        raise ValueError('Invalid Reddit time_filter.')
    prefix = f'/r/{_normalize_subreddit(subreddit)}' if subreddit else ''
    return _reddit_api_request('GET', f'{prefix}/search', params={'q': clean_query, 'restrict_sr': bool(subreddit), 'sort': normalized_sort, 't': normalized_time, 'limit': _coerce_limit(limit, default=25, minimum=1, maximum=100), 'after': str(after or '').strip()})

def get_reddit_api_post(post_id_or_url: str, comment_sort: str='confidence', comment_limit: int=50, depth: int=4) -> dict[str, Any]:
    """Get a Reddit Post and its comments through the official Data API."""
    post_id = _reddit_post_id(post_id_or_url)
    normalized_sort = str(comment_sort or 'confidence').lower()
    if normalized_sort not in {'confidence', 'top', 'new', 'controversial', 'old', 'random', 'qa', 'live'}:
        raise ValueError('Invalid Reddit comment sort.')
    result = _reddit_api_request('GET', f'/comments/{post_id}', params={'sort': normalized_sort, 'limit': _coerce_limit(comment_limit, default=50, minimum=1, maximum=500), 'depth': _coerce_limit(depth, default=4, minimum=0, maximum=10)})
    payload = result.get('response')
    if isinstance(payload, list):
        result['post_items'] = _listing_items(payload[0]) if payload else []
        result['comment_items'] = _listing_items(payload[1]) if len(payload) > 1 else []
    return result

def get_reddit_api_user_activity(username: str, activity: str='overview', sort: str='new', time_filter: str='all', limit: int=25, after: str='') -> dict[str, Any]:
    """Get a Reddit user's public overview, Posts, or comments."""
    user = _normalize_reddit_username(username)
    normalized_activity = str(activity or 'overview').lower()
    if normalized_activity not in {'overview', 'submitted', 'comments'}:
        raise ValueError('activity must be overview, submitted, or comments.')
    normalized_sort = str(sort or 'new').lower()
    if normalized_sort not in {'hot', 'new', 'top', 'controversial'}:
        raise ValueError('Invalid Reddit user activity sort.')
    return _reddit_api_request('GET', f'/user/{quote(user, safe='')}/{normalized_activity}', params={'sort': normalized_sort, 't': str(time_filter or 'all').lower(), 'limit': _coerce_limit(limit, default=25, minimum=1, maximum=100), 'after': str(after or '').strip()})

def get_reddit_api_inbox(mailbox: str='inbox', limit: int=25, after: str='') -> dict[str, Any]:
    """Get authenticated Reddit messages or unread inbox items."""
    normalized = str(mailbox or 'inbox').lower()
    if normalized not in {'inbox', 'unread', 'sent'}:
        raise ValueError('mailbox must be inbox, unread, or sent.')
    return _reddit_api_request('GET', f'/message/{normalized}', require_user=True, params={'limit': _coerce_limit(limit, default=25, minimum=1, maximum=100), 'after': str(after or '').strip()})

def publish_reddit_api_text_post(subreddit: str, title: str, body: str='', send_replies: bool=True, nsfw: bool=False, spoiler: bool=False) -> dict[str, Any]:
    """Submit a text Post through Reddit's official API."""
    clean_title = str(title or '').strip()
    if not clean_title:
        raise ValueError('Reddit Post title cannot be empty.')
    return _reddit_api_request('POST', '/api/submit', require_user=True, data={'api_type': 'json', 'kind': 'self', 'sr': _normalize_subreddit(subreddit), 'title': clean_title, 'text': str(body or ''), 'sendreplies': bool(send_replies), 'nsfw': bool(nsfw), 'spoiler': bool(spoiler), 'resubmit': True})

def publish_reddit_api_link_post(subreddit: str, title: str, url: str, send_replies: bool=True, nsfw: bool=False, spoiler: bool=False) -> dict[str, Any]:
    """Submit a link Post through Reddit's official API."""
    clean_title = str(title or '').strip()
    parsed = urlparse(str(url or '').strip())
    if not clean_title:
        raise ValueError('Reddit Post title cannot be empty.')
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('A valid HTTP(S) link is required.')
    return _reddit_api_request('POST', '/api/submit', require_user=True, data={'api_type': 'json', 'kind': 'link', 'sr': _normalize_subreddit(subreddit), 'title': clean_title, 'url': url, 'sendreplies': bool(send_replies), 'nsfw': bool(nsfw), 'spoiler': bool(spoiler), 'resubmit': True})

def comment_reddit_api_post(post_id_or_url: str, message: str) -> dict[str, Any]:
    """Comment on a Reddit Post through the official API."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Reddit comment cannot be empty.')
    return _reddit_api_request('POST', '/api/comment', require_user=True, data={'api_type': 'json', 'thing_id': _reddit_fullname(post_id_or_url, default_kind='t3'), 'text': clean_message})

def reply_reddit_api_comment(comment_id_or_url: str, message: str) -> dict[str, Any]:
    """Reply to a Reddit comment through the official API."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Reddit reply cannot be empty.')
    return _reddit_api_request('POST', '/api/comment', require_user=True, data={'api_type': 'json', 'thing_id': _reddit_fullname(comment_id_or_url, default_kind='t1'), 'text': clean_message})

def edit_reddit_api_content(thing_id_or_url: str, text: str) -> dict[str, Any]:
    """Edit an authenticated user's Reddit Post body or comment."""
    clean_text = str(text or '').strip()
    if not clean_text:
        raise ValueError('Edited Reddit text cannot be empty.')
    return _reddit_api_request('POST', '/api/editusertext', require_user=True, data={'api_type': 'json', 'thing_id': _reddit_fullname(thing_id_or_url), 'text': clean_text})

def delete_reddit_api_content(thing_id_or_url: str, kind: str='post') -> dict[str, Any]:
    """Delete an authenticated user's Reddit Post or comment."""
    normalized_kind = str(kind or 'post').lower()
    if normalized_kind not in {'post', 'comment'}:
        raise ValueError('kind must be post or comment.')
    return _reddit_api_request('POST', '/api/del', require_user=True, data={'id': _reddit_fullname(thing_id_or_url, default_kind='t1' if normalized_kind == 'comment' else 't3')})

def vote_reddit_api(thing_id_or_url: str, direction: str='up', kind: str='post') -> dict[str, Any]:
    """Upvote, downvote, or clear a vote through Reddit's official API."""
    normalized_direction = str(direction or 'up').lower()
    directions = {'up': 1, 'upvote': 1, 'down': -1, 'downvote': -1, 'clear': 0, 'none': 0}
    if normalized_direction not in directions:
        raise ValueError('direction must be up, down, or clear.')
    normalized_kind = str(kind or 'post').lower()
    if normalized_kind not in {'post', 'comment'}:
        raise ValueError('kind must be post or comment.')
    return _reddit_api_request('POST', '/api/vote', require_user=True, data={'id': _reddit_fullname(thing_id_or_url, default_kind='t1' if normalized_kind == 'comment' else 't3'), 'dir': directions[normalized_direction]})

def save_reddit_api_content(thing_id_or_url: str, kind: str='post') -> dict[str, Any]:
    """Save a Reddit Post or comment through the official API."""
    normalized_kind = str(kind or 'post').lower()
    if normalized_kind not in {'post', 'comment'}:
        raise ValueError('kind must be post or comment.')
    return _reddit_api_request('POST', '/api/save', require_user=True, data={'id': _reddit_fullname(thing_id_or_url, default_kind='t1' if normalized_kind == 'comment' else 't3')})

def unsave_reddit_api_content(thing_id_or_url: str, kind: str='post') -> dict[str, Any]:
    """Unsave a Reddit Post or comment through the official API."""
    normalized_kind = str(kind or 'post').lower()
    if normalized_kind not in {'post', 'comment'}:
        raise ValueError('kind must be post or comment.')
    return _reddit_api_request('POST', '/api/unsave', require_user=True, data={'id': _reddit_fullname(thing_id_or_url, default_kind='t1' if normalized_kind == 'comment' else 't3')})

def join_reddit_api_community(subreddit: str) -> dict[str, Any]:
    """Subscribe to a subreddit through the official API."""
    return _reddit_api_request('POST', '/api/subscribe', require_user=True, data={'action': 'sub', 'sr_name': _normalize_subreddit(subreddit)})

def leave_reddit_api_community(subreddit: str) -> dict[str, Any]:
    """Unsubscribe from a subreddit through the official API."""
    return _reddit_api_request('POST', '/api/subscribe', require_user=True, data={'action': 'unsub', 'sr_name': _normalize_subreddit(subreddit)})

def hide_reddit_api_post(post_id_or_url: str) -> dict[str, Any]:
    """Hide a Reddit Post through the official API."""
    return _reddit_api_request('POST', '/api/hide', require_user=True, data={'id': _reddit_fullname(post_id_or_url, default_kind='t3')})

def unhide_reddit_api_post(post_id_or_url: str) -> dict[str, Any]:
    """Unhide a Reddit Post through the official API."""
    return _reddit_api_request('POST', '/api/unhide', require_user=True, data={'id': _reddit_fullname(post_id_or_url, default_kind='t3')})

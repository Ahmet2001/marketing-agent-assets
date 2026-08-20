"""Generated api surface from the original MarketingApp toolbox.

Do not mix browser and API actions in a worker process.
"""

from __future__ import annotations

from __future__ import annotations

import json

import os

import re

import time

from collections import Counter

from datetime import datetime

from typing import Any

from urllib.parse import quote, quote_plus

import requests

try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

TOOLBOX_ACCESS_MODE = 'hybrid'

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_SOCIAL_DIR = os.path.join(_PROJECT_ROOT, 'workspace', 'social')

_QUEUE_PATH = os.path.join(_SOCIAL_DIR, 'x_reply_queue.json')

_MARKET_STATE_PATH = os.path.join(_SOCIAL_DIR, 'market_state.md')

_IDEA_POOL_PATH = os.path.join(_SOCIAL_DIR, 'idea_pool.md')

_FEED_SNAPSHOT_PATH = os.path.join(_SOCIAL_DIR, 'x_feed_snapshot.json')

_ACTIVE_PROFILE_PATH = os.path.join(_PROJECT_ROOT, 'workspace', 'orchestration', 'active_profile.json')

_DEFAULT_X_API_BASE_URL = 'https://api.x.com/2'

_DEFAULT_X_API_TIMEOUT = 30

_DEFAULT_X_TWEET_FIELDS = 'attachments,author_id,conversation_id,created_at,entities,lang,public_metrics,referenced_tweets'

_DEFAULT_X_USER_FIELDS = 'created_at,description,location,name,profile_image_url,protected,public_metrics,url,username,verified'

_DEFAULT_X_MEDIA_FIELDS = 'alt_text,height,media_key,preview_image_url,type,url,width'

_DEFAULT_TOPIC_KEYWORDS = {'product': ('product', 'urun', 'özellik', 'feature', 'launch'), 'customer': ('customer', 'musteri', 'kullanici', 'feedback'), 'growth': ('growth', 'buyume', 'dagitim', 'funnel', 'retention'), 'brand': ('brand', 'marka', 'positioning', 'story'), 'community': ('community', 'topluluk', 'yorum', 'reply')}

_BULLISH_WORDS = ('breakout', 'up only', 'bullish', 'bid', 'strength', 'bounce', 'higher', 'accumulation', 'squeeze', 'rip', 'green')

_BEARISH_WORDS = ('breakdown', 'bearish', 'selloff', 'dump', 'weakness', 'lower', 'risk off', 'liquidation', 'rejection', 'red', 'panic')

_SYSTEM_NOTIFICATION_MARKERS = ('liked your post', 'liked your reply', 'reposted your post', 'reposted your reply', 'followed you', 'following you', 'beğendi', 'begendi', 'yeniden paylasti', 'repostladi', 'takip etti')

_MENTION_MARKERS = ('mentioned you', 'senden bahsetti', 'sana mention')

_REPLY_MARKERS = ('replied to you', 'replied', 'yanit verdi', 'yanıt verdi', 'yanitladi', 'yanıtladı')

_ERROR_ALERT_MARKERS = ('try again', 'something went wrong', 'unable to', 'cannot', "can't send", 'rate limit', 'too many', 'bir sorun olustu', 'daha sonra tekrar dene', 'gonderilemedi')

_LOGIN_WALL_MARKERS = ('sign in', 'log in', 'giris yap', 'oturum ac', 'join x')

_X_COMPOSER_SELECTORS = ("[data-testid='tweetTextarea_0'] [role='textbox']", "[data-testid='tweetTextarea_0'][role='textbox']", "[data-testid='tweetTextarea_0'][contenteditable='true']", "[data-testid='tweetTextarea_0']", "div[role='textbox'][contenteditable='true']")

_X_SUBMIT_SELECTORS = ("[data-testid='tweetButtonInline']", "[data-testid='tweetButton']")

_X_SUBMIT_TEXT_MARKERS = ('post', 'tweet', 'reply', 'send', 'gonder', 'gönder', 'yanitla', 'yanıtla', 'paylas', 'paylaş')

_X_SUBMIT_EXCLUDE_MARKERS = ('schedule', 'schedule post', 'scheduled', 'calendar', 'takvim', 'zamanla', 'planla', 'taslak', 'draft')

_X_MEDIA_INPUT_SELECTORS = ("input[data-testid='fileInput']", "input[type='file'][accept*='image']", "input[type='file']")

_X_QUOTE_MARKERS = ('quote', 'quote post', 'post with quote', 'alıntı', 'alıntıyla', 'alıntıla')

_X_FOLLOW_MARKERS = ('follow', 'takip et')

_X_UNFOLLOW_MARKERS = ('following', 'takip ediliyor', 'takiptesin', 'unfollow')

def _first_environment_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, '').strip()
        if value:
            return value
    return ''

def _x_api_credentials() -> dict[str, str]:
    return {'bearer_token': _first_environment_value('X_API_BEARER_TOKEN', 'X_BEARER_TOKEN', 'TWITTER_BEARER_TOKEN'), 'user_bearer_token': _first_environment_value('X_API_USER_BEARER_TOKEN', 'X_USER_BEARER_TOKEN', 'X_OAUTH2_USER_TOKEN'), 'api_key': _first_environment_value('X_API_KEY', 'X_CONSUMER_KEY', 'TWITTER_API_KEY', 'TWITTER_CONSUMER_KEY'), 'api_secret': _first_environment_value('X_API_SECRET', 'X_API_KEY_SECRET', 'X_CONSUMER_SECRET', 'TWITTER_API_SECRET', 'TWITTER_CONSUMER_SECRET'), 'access_token': _first_environment_value('X_ACCESS_TOKEN', 'X_API_ACCESS_TOKEN', 'TWITTER_ACCESS_TOKEN'), 'access_token_secret': _first_environment_value('X_ACCESS_TOKEN_SECRET', 'X_API_ACCESS_TOKEN_SECRET', 'TWITTER_ACCESS_TOKEN_SECRET')}

def _x_api_base_url() -> str:
    configured = os.getenv('X_API_BASE_URL', _DEFAULT_X_API_BASE_URL).strip()
    return (configured or _DEFAULT_X_API_BASE_URL).rstrip('/')

def _x_api_timeout() -> int:
    try:
        timeout = int(os.getenv('X_API_TIMEOUT', str(_DEFAULT_X_API_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_X_API_TIMEOUT
    return max(5, min(timeout, 120))

def _x_api_auth(auth_mode: str):
    credentials = _x_api_credentials()
    oauth1_ready = all((credentials[key] for key in ('api_key', 'api_secret', 'access_token', 'access_token_secret'))) and OAuth1 is not None
    if auth_mode == 'user':
        if credentials['user_bearer_token']:
            return ({'Authorization': f'Bearer {credentials['user_bearer_token']}'}, None, 'oauth2_user')
        if oauth1_ready:
            return ({}, OAuth1(credentials['api_key'], credentials['api_secret'], credentials['access_token'], credentials['access_token_secret']), 'oauth1_user')
        raise RuntimeError('X user authentication is not configured. Set X_API_USER_BEARER_TOKEN or all of X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET.')
    if credentials['bearer_token']:
        return ({'Authorization': f'Bearer {credentials['bearer_token']}'}, None, 'app_bearer')
    if credentials['user_bearer_token']:
        return ({'Authorization': f'Bearer {credentials['user_bearer_token']}'}, None, 'oauth2_user')
    if oauth1_ready:
        return ({}, OAuth1(credentials['api_key'], credentials['api_secret'], credentials['access_token'], credentials['access_token_secret']), 'oauth1_user')
    raise RuntimeError('X API authentication is not configured. Set X_API_BEARER_TOKEN for public reads, or configure user authentication credentials.')

def _x_api_error(error: str, *, endpoint: str='', status_code: int=0, response: Any=None) -> dict[str, Any]:
    result: dict[str, Any] = {'ok': False, 'status': 'error', 'status_code': status_code, 'endpoint': endpoint, 'error': error}
    if response is not None:
        result['response'] = response
    return result

def _x_api_request(method: str, endpoint: str, *, auth_mode: str='read', params: dict[str, Any] | None=None, json_body: dict[str, Any] | None=None) -> dict[str, Any]:
    normalized_method = (method or 'GET').upper().strip()
    normalized_endpoint = '/' + (endpoint or '').lstrip('/')
    if normalized_method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
        return _x_api_error(f'Unsupported X API method: {normalized_method}', endpoint=normalized_endpoint)
    if '://' in normalized_endpoint or '..' in normalized_endpoint:
        return _x_api_error('X API endpoint must be a relative v2 path.', endpoint=normalized_endpoint)
    try:
        auth_headers, oauth_auth, auth_type = _x_api_auth(auth_mode)
    except RuntimeError as exc:
        return _x_api_error(str(exc), endpoint=normalized_endpoint)
    headers = {'Accept': 'application/json', 'User-Agent': 'Ethos-MarketingAgent/1.0', **auth_headers}
    clean_params = {key: value for key, value in (params or {}).items() if value not in (None, '', [], ())}
    try:
        response = requests.request(normalized_method, f'{_x_api_base_url()}{normalized_endpoint}', params=clean_params or None, json=json_body, headers=headers, auth=oauth_auth, timeout=_x_api_timeout())
    except requests.RequestException as exc:
        return _x_api_error(f'X API request failed: {exc}', endpoint=normalized_endpoint)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = {'raw_text': response.text[:4000]}
    rate_limit = {'limit': response.headers.get('x-rate-limit-limit', ''), 'remaining': response.headers.get('x-rate-limit-remaining', ''), 'reset': response.headers.get('x-rate-limit-reset', '')}
    result: dict[str, Any] = {'ok': response.ok, 'status': 'ok' if response.ok else 'error', 'status_code': response.status_code, 'method': normalized_method, 'endpoint': normalized_endpoint, 'auth_type': auth_type, 'rate_limit': rate_limit, 'response': payload}
    if isinstance(payload, dict):
        for key in ('data', 'includes', 'meta', 'errors'):
            if key in payload:
                result[key] = payload[key]
    if not response.ok:
        if isinstance(payload, dict):
            detail = payload.get('detail') or payload.get('title') or payload.get('error')
        else:
            detail = ''
        result['error'] = str(detail or f'X API returned HTTP {response.status_code}')
    return result

def _x_api_post_id(tweet_id_or_url: str) -> str:
    value = str(tweet_id_or_url or '').strip()
    match = re.search('(?:/status/|^)(\\d{1,19})(?:[/?#]|$)', value)
    if not match:
        raise ValueError('A valid numeric X Post ID or status URL is required.')
    return match.group(1)

def _x_api_user_id(user_id: str) -> str:
    value = str(user_id or '').strip()
    if not re.fullmatch('\\d{1,19}', value):
        raise ValueError('A valid numeric X User ID is required.')
    return value

def _x_api_username(username: str) -> str:
    value = str(username or '').strip()
    if '://' in value:
        match = re.search('(?:x|twitter)\\.com/([A-Za-z0-9_]{1,15})', value, re.I)
        value = match.group(1) if match else ''
    value = value.lstrip('@')
    if not re.fullmatch('[A-Za-z0-9_]{1,15}', value):
        raise ValueError('A valid X username is required.')
    return value

def _x_api_csv(value: str, default: str='') -> str:
    normalized = ','.join((part.strip() for part in str(value or default).split(',') if part.strip()))
    return normalized

def _x_api_media_ids(media_ids: str) -> list[str]:
    if not str(media_ids or '').strip():
        return []
    values = _x_api_csv(media_ids).split(',')
    if not all((re.fullmatch('\\d{1,30}', value) for value in values)):
        raise ValueError('media_ids must be comma-separated numeric X media IDs.')
    if len(values) > 4:
        raise ValueError('A Post can contain at most four media IDs.')
    return values

def _x_api_resolve_user_id(*, user_id: str='', username: str='', authenticated_user: bool=False) -> tuple[str, dict[str, Any] | None]:
    if user_id:
        return (_x_api_user_id(user_id), None)
    if username:
        lookup = get_x_api_user(username=username)
    elif authenticated_user:
        lookup = get_x_api_me()
    else:
        return ('', _x_api_error('Provide either user_id or username.'))
    if not lookup.get('ok'):
        return ('', lookup)
    data = lookup.get('data')
    resolved_id = str(data.get('id', '')) if isinstance(data, dict) else ''
    if not re.fullmatch('\\d{1,19}', resolved_id):
        return ('', _x_api_error('The X API response did not contain a valid user ID.', endpoint=lookup.get('endpoint', ''), status_code=int(lookup.get('status_code', 0) or 0), response=lookup.get('response')))
    return (resolved_id, None)

def _coerce_limit(value: Any, default: int=10, minimum: int=1, maximum: int=50) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(number, maximum))

def _parse_thread_parts(thread_parts: str) -> list[str]:
    raw = str(thread_parts or '').strip()
    if not raw:
        return []
    if re.search('(?m)^\\s*---+\\s*$', raw):
        parts = [part.strip() for part in re.split('(?m)^\\s*---+\\s*$', raw)]
    else:
        parts = [part.strip() for part in raw.split('\n\n') if part.strip()]
    return [part for part in parts if part]

def get_x_api_status(verify_credentials: bool=False) -> dict[str, Any]:
    """Report official X API configuration without exposing credential values.

    Set ``verify_credentials`` to make one read-only request to X. User
    credentials are verified through ``/users/me``; app-only credentials are
    verified through a public user lookup.
    """
    credentials = _x_api_credentials()
    oauth1_ready = all((credentials[key] for key in ('api_key', 'api_secret', 'access_token', 'access_token_secret'))) and OAuth1 is not None
    result: dict[str, Any] = {'status': 'configured' if credentials['bearer_token'] or credentials['user_bearer_token'] or oauth1_ready else 'not_configured', 'base_url': _x_api_base_url(), 'timeout_seconds': _x_api_timeout(), 'app_bearer_configured': bool(credentials['bearer_token']), 'oauth2_user_configured': bool(credentials['user_bearer_token']), 'oauth1_user_configured': oauth1_ready, 'oauth1_dependency_available': OAuth1 is not None, 'write_access_configured': bool(credentials['user_bearer_token'] or oauth1_ready), 'required_environment': {'read_only': 'X_API_BEARER_TOKEN', 'oauth2_user': 'X_API_USER_BEARER_TOKEN', 'oauth1_user': 'X_API_KEY + X_API_SECRET + X_ACCESS_TOKEN + X_ACCESS_TOKEN_SECRET'}}
    if not verify_credentials:
        return result
    if credentials['user_bearer_token'] or oauth1_ready:
        verification = get_x_api_me()
    elif credentials['bearer_token']:
        verification = get_x_api_user(username='XDevelopers')
    else:
        verification = _x_api_error('No X API credentials are configured.')
    result['verification'] = verification
    result['status'] = 'verified' if verification.get('ok') else 'verification_failed'
    return result

def get_x_api_me(user_fields: str=_DEFAULT_X_USER_FIELDS) -> dict[str, Any]:
    """Get the user associated with the configured user-context credentials."""
    return _x_api_request('GET', '/users/me', auth_mode='user', params={'user.fields': _x_api_csv(user_fields, _DEFAULT_X_USER_FIELDS)})

def get_x_api_user(username: str='', user_id: str='', user_fields: str=_DEFAULT_X_USER_FIELDS) -> dict[str, Any]:
    """Look up an X account by username or numeric user ID."""
    fields = _x_api_csv(user_fields, _DEFAULT_X_USER_FIELDS)
    if user_id:
        normalized_id = _x_api_user_id(user_id)
        endpoint = f'/users/{normalized_id}'
    elif username:
        normalized_username = _x_api_username(username)
        endpoint = f'/users/by/username/{quote(normalized_username, safe='')}'
    else:
        return _x_api_error('Provide username or user_id.')
    return _x_api_request('GET', endpoint, params={'user.fields': fields})

def get_x_api_post(tweet_id_or_url: str, tweet_fields: str=_DEFAULT_X_TWEET_FIELDS, expansions: str='author_id,attachments.media_keys') -> dict[str, Any]:
    """Retrieve one X Post through the official v2 API."""
    tweet_id = _x_api_post_id(tweet_id_or_url)
    return _x_api_request('GET', f'/tweets/{tweet_id}', params={'tweet.fields': _x_api_csv(tweet_fields, _DEFAULT_X_TWEET_FIELDS), 'expansions': _x_api_csv(expansions), 'user.fields': _DEFAULT_X_USER_FIELDS, 'media.fields': _DEFAULT_X_MEDIA_FIELDS})

def search_x_api_posts(query: str, max_results: int=10, next_token: str='', sort_order: str='recency', tweet_fields: str=_DEFAULT_X_TWEET_FIELDS) -> dict[str, Any]:
    """Search Posts from the last seven days through X API v2."""
    normalized_query = str(query or '').strip()
    if not normalized_query:
        raise ValueError('X API search query cannot be empty.')
    normalized_sort = str(sort_order or 'recency').strip().lower()
    if normalized_sort not in {'recency', 'relevancy'}:
        raise ValueError("sort_order must be 'recency' or 'relevancy'.")
    return _x_api_request('GET', '/tweets/search/recent', params={'query': normalized_query, 'max_results': _coerce_limit(max_results, default=10, minimum=10, maximum=100), 'next_token': str(next_token or '').strip(), 'sort_order': normalized_sort, 'tweet.fields': _x_api_csv(tweet_fields, _DEFAULT_X_TWEET_FIELDS), 'expansions': 'author_id,attachments.media_keys', 'user.fields': _DEFAULT_X_USER_FIELDS, 'media.fields': _DEFAULT_X_MEDIA_FIELDS})

def get_x_api_user_posts(username: str='', user_id: str='', max_results: int=10, pagination_token: str='', exclude_replies: bool=False, exclude_reposts: bool=False, tweet_fields: str=_DEFAULT_X_TWEET_FIELDS) -> dict[str, Any]:
    """Get Posts authored by an X account through the official API."""
    resolved_id, error = _x_api_resolve_user_id(user_id=user_id, username=username)
    if error:
        return error
    exclude: list[str] = []
    if exclude_replies:
        exclude.append('replies')
    if exclude_reposts:
        exclude.append('retweets')
    return _x_api_request('GET', f'/users/{resolved_id}/tweets', params={'max_results': _coerce_limit(max_results, default=10, minimum=5, maximum=100), 'pagination_token': str(pagination_token or '').strip(), 'exclude': ','.join(exclude), 'tweet.fields': _x_api_csv(tweet_fields, _DEFAULT_X_TWEET_FIELDS), 'expansions': 'attachments.media_keys', 'media.fields': _DEFAULT_X_MEDIA_FIELDS})

def publish_x_api_post(text: str, reply_to_tweet_id: str='', quote_tweet_id: str='', media_ids: str='') -> dict[str, Any]:
    """Publish a Post with the official X API using user-context credentials."""
    message = str(text or '').strip()
    normalized_media_ids = _x_api_media_ids(media_ids)
    if not message and (not normalized_media_ids):
        raise ValueError('A Post requires text or at least one media ID.')
    if reply_to_tweet_id and quote_tweet_id:
        raise ValueError('A Post cannot be both a reply and a quote Post.')
    body: dict[str, Any] = {}
    if message:
        body['text'] = message
    if reply_to_tweet_id:
        body['reply'] = {'in_reply_to_tweet_id': _x_api_post_id(reply_to_tweet_id)}
    if quote_tweet_id:
        body['quote_tweet_id'] = _x_api_post_id(quote_tweet_id)
    if normalized_media_ids:
        body['media'] = {'media_ids': normalized_media_ids}
    return _x_api_request('POST', '/tweets', auth_mode='user', json_body=body)

def reply_to_x_api_post(tweet_id_or_url: str, message: str) -> dict[str, Any]:
    """Reply to an X Post through the official API."""
    return publish_x_api_post(text=message, reply_to_tweet_id=_x_api_post_id(tweet_id_or_url))

def quote_x_api_post(tweet_id_or_url: str, message: str) -> dict[str, Any]:
    """Quote an X Post through the official API."""
    return publish_x_api_post(text=message, quote_tweet_id=_x_api_post_id(tweet_id_or_url))

def publish_x_api_thread(thread_parts: str) -> dict[str, Any]:
    """Publish newline- or JSON-separated thread parts through the X API."""
    parts = _parse_thread_parts(thread_parts)
    if not parts:
        raise ValueError('Thread parts cannot be empty.')
    results: list[dict[str, Any]] = []
    parent_id = ''
    for index, part in enumerate(parts, start=1):
        result = publish_x_api_post(part, reply_to_tweet_id=parent_id)
        result['thread_index'] = index
        results.append(result)
        if not result.get('ok'):
            return {'status': 'partial' if index > 1 else 'error', 'sent_count': index - 1, 'results': results, 'error': result.get('error', f'Thread part {index} failed.')}
        data = result.get('data')
        parent_id = str(data.get('id', '')) if isinstance(data, dict) else ''
        if not parent_id:
            return {'status': 'partial', 'sent_count': index, 'results': results, 'error': f'Thread part {index} returned no Post ID.'}
    root_data = results[0].get('data')
    root_tweet_id = str(root_data.get('id', '')) if isinstance(root_data, dict) else ''
    return {'status': 'posted', 'sent_count': len(results), 'root_tweet_id': root_tweet_id, 'last_tweet_id': parent_id, 'results': results}

def delete_x_api_post(tweet_id_or_url: str) -> dict[str, Any]:
    """Delete a Post authored by the authenticated user through X API v2."""
    tweet_id = _x_api_post_id(tweet_id_or_url)
    return _x_api_request('DELETE', f'/tweets/{tweet_id}', auth_mode='user')

def like_x_api_post(tweet_id_or_url: str, user_id: str='') -> dict[str, Any]:
    """Like an X Post as the authenticated user through the official API."""
    source_id, error = _x_api_resolve_user_id(user_id=user_id, authenticated_user=True)
    if error:
        return error
    tweet_id = _x_api_post_id(tweet_id_or_url)
    return _x_api_request('POST', f'/users/{source_id}/likes', auth_mode='user', json_body={'tweet_id': tweet_id})

def unlike_x_api_post(tweet_id_or_url: str, user_id: str='') -> dict[str, Any]:
    """Remove the authenticated user's Like through the official X API."""
    source_id, error = _x_api_resolve_user_id(user_id=user_id, authenticated_user=True)
    if error:
        return error
    tweet_id = _x_api_post_id(tweet_id_or_url)
    return _x_api_request('DELETE', f'/users/{source_id}/likes/{tweet_id}', auth_mode='user')

def repost_x_api_post(tweet_id_or_url: str, user_id: str='') -> dict[str, Any]:
    """Repost an X Post as the authenticated user through the official API."""
    source_id, error = _x_api_resolve_user_id(user_id=user_id, authenticated_user=True)
    if error:
        return error
    tweet_id = _x_api_post_id(tweet_id_or_url)
    return _x_api_request('POST', f'/users/{source_id}/retweets', auth_mode='user', json_body={'tweet_id': tweet_id})

def undo_x_api_repost(tweet_id_or_url: str, user_id: str='') -> dict[str, Any]:
    """Undo the authenticated user's repost through the official X API."""
    source_id, error = _x_api_resolve_user_id(user_id=user_id, authenticated_user=True)
    if error:
        return error
    tweet_id = _x_api_post_id(tweet_id_or_url)
    return _x_api_request('DELETE', f'/users/{source_id}/retweets/{tweet_id}', auth_mode='user')

def follow_x_api_account(username: str='', target_user_id: str='', source_user_id: str='') -> dict[str, Any]:
    """Follow an X account as the authenticated user through the official API."""
    source_id, source_error = _x_api_resolve_user_id(user_id=source_user_id, authenticated_user=True)
    if source_error:
        return source_error
    target_id, target_error = _x_api_resolve_user_id(user_id=target_user_id, username=username)
    if target_error:
        return target_error
    return _x_api_request('POST', f'/users/{source_id}/following', auth_mode='user', json_body={'target_user_id': target_id})

def unfollow_x_api_account(username: str='', target_user_id: str='', source_user_id: str='') -> dict[str, Any]:
    """Unfollow an X account as the authenticated user through the official API."""
    source_id, source_error = _x_api_resolve_user_id(user_id=source_user_id, authenticated_user=True)
    if source_error:
        return source_error
    target_id, target_error = _x_api_resolve_user_id(user_id=target_user_id, username=username)
    if target_error:
        return target_error
    return _x_api_request('DELETE', f'/users/{source_id}/following/{target_id}', auth_mode='user')

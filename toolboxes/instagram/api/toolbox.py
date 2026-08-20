"""Generated api surface from the original MarketingApp toolbox.

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

TOOLBOX_ACCESS_MODE = 'hybrid'

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

_INSTAGRAM_WORKSPACE_DIR = os.path.join(_PROJECT_ROOT, 'workspace', 'social')

_INSTAGRAM_SNAPSHOT_PATH = os.path.join(_INSTAGRAM_WORKSPACE_DIR, 'instagram_feed_snapshot.json')

_DEFAULT_INSTAGRAM_API_HOST = 'https://graph.instagram.com'

_DEFAULT_INSTAGRAM_API_VERSION = 'v25.0'

_DEFAULT_INSTAGRAM_API_TIMEOUT = 30

_INSTAGRAM_POST_PATH_PATTERN = re.compile('/(?:p|reel|tv)/([A-Za-z0-9_-]+)', re.I)

_INSTAGRAM_PROFILE_HANDLE_PATTERN = re.compile('^[A-Za-z0-9._]{1,30}$')

def _coerce_limit(value: Any, default: int=20, minimum: int=1, maximum: int=100) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))

def _instagram_api_credentials() -> dict[str, str]:
    return {'access_token': os.getenv('INSTAGRAM_ACCESS_TOKEN', '').strip(), 'user_id': os.getenv('INSTAGRAM_USER_ID', '').strip(), 'app_id': os.getenv('INSTAGRAM_APP_ID', '').strip(), 'app_secret': os.getenv('INSTAGRAM_APP_SECRET', '').strip()}

def _instagram_api_base_url() -> str:
    configured = os.getenv('INSTAGRAM_API_BASE_URL', '').strip()
    if configured:
        return configured.rstrip('/')
    version = os.getenv('INSTAGRAM_API_VERSION', _DEFAULT_INSTAGRAM_API_VERSION).strip() or _DEFAULT_INSTAGRAM_API_VERSION
    if not re.fullmatch('v\\d+\\.\\d+', version):
        raise ValueError('INSTAGRAM_API_VERSION must look like v25.0.')
    return f'{_DEFAULT_INSTAGRAM_API_HOST}/{version}'

def _instagram_api_timeout() -> int:
    try:
        timeout = int(os.getenv('INSTAGRAM_API_TIMEOUT', str(_DEFAULT_INSTAGRAM_API_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_INSTAGRAM_API_TIMEOUT
    return max(5, min(timeout, 120))

def _instagram_api_user_id(user_id: str='') -> str:
    value = str(user_id or _instagram_api_credentials()['user_id']).strip()
    if not re.fullmatch('\\d{1,30}', value):
        raise ValueError('A numeric Instagram professional account ID is required. Set INSTAGRAM_USER_ID or pass user_id.')
    return value

def _instagram_api_object_id(value: str, label: str='object') -> str:
    normalized = str(value or '').strip()
    if not re.fullmatch('\\d{1,40}', normalized):
        raise ValueError(f'A valid numeric Instagram {label} ID is required.')
    return normalized

def _instagram_api_error(error: str, *, endpoint: str='', status_code: int=0, response: Any=None) -> dict[str, Any]:
    result: dict[str, Any] = {'ok': False, 'status': 'error', 'status_code': status_code, 'endpoint': endpoint, 'error': error}
    if response is not None:
        result['response'] = response
    return result

def _instagram_api_request(method: str, endpoint: str, *, params: dict[str, Any] | None=None, data: dict[str, Any] | None=None, access_token: str='') -> dict[str, Any]:
    normalized_method = str(method or 'GET').upper().strip()
    normalized_endpoint = '/' + str(endpoint or '').lstrip('/')
    if normalized_method not in {'GET', 'POST', 'DELETE'}:
        return _instagram_api_error(f'Unsupported Instagram API method: {normalized_method}', endpoint=normalized_endpoint)
    if '://' in normalized_endpoint or '..' in normalized_endpoint:
        return _instagram_api_error('Instagram API endpoint must be a relative Graph path.', endpoint=normalized_endpoint)
    token = str(access_token or _instagram_api_credentials()['access_token']).strip()
    if not token:
        return _instagram_api_error('INSTAGRAM_ACCESS_TOKEN is not configured.', endpoint=normalized_endpoint)
    clean_params = {key: value for key, value in (params or {}).items() if value not in (None, '', [], ())}
    clean_data: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if value in (None, '', [], ()):
            continue
        clean_data[key] = str(value).lower() if isinstance(value, bool) else value
    try:
        response = requests.request(normalized_method, f'{_instagram_api_base_url()}{normalized_endpoint}', params=clean_params or None, data=clean_data or None, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'User-Agent': 'Ethos-MarketingAgent/1.0'}, timeout=_instagram_api_timeout())
    except requests.RequestException as exc:
        return _instagram_api_error(f'Instagram API request failed: {exc}', endpoint=normalized_endpoint)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = {'raw_text': response.text[:4000]}
    graph_error = payload.get('error') if isinstance(payload, dict) else None
    ok = bool(response.ok and (not graph_error))
    result: dict[str, Any] = {'ok': ok, 'status': 'ok' if ok else 'error', 'status_code': response.status_code, 'http_status_code': response.status_code, 'method': normalized_method, 'endpoint': normalized_endpoint, 'rate_limit': {'app_usage': response.headers.get('x-app-usage', ''), 'business_usage': response.headers.get('x-business-use-case-usage', ''), 'instagram_usage': response.headers.get('x-instagram-api-call-usage', '')}, 'response': payload}
    if isinstance(payload, dict):
        for key in ('id', 'data', 'paging'):
            if key in payload:
                result[key] = payload[key]
        if 'status_code' in payload:
            result['container_status_code'] = payload['status_code']
        if 'status' in payload:
            result['container_status'] = payload['status']
    if not ok:
        if isinstance(graph_error, dict):
            detail = graph_error.get('message') or graph_error.get('error_user_msg')
            result['graph_error'] = graph_error
        else:
            detail = graph_error
        result['error'] = str(detail or f'Instagram API returned HTTP {response.status_code}')
    return result

def get_instagram_api_status(verify_credentials: bool=False) -> dict[str, Any]:
    """Report official Instagram API configuration without exposing secrets."""
    credentials = _instagram_api_credentials()
    result: dict[str, Any] = {'status': 'configured' if credentials['access_token'] and credentials['user_id'] else 'not_configured', 'api_base_url': _instagram_api_base_url(), 'timeout_seconds': _instagram_api_timeout(), 'access_token_configured': bool(credentials['access_token']), 'user_id_configured': bool(credentials['user_id']), 'app_credentials_configured': bool(credentials['app_id'] and credentials['app_secret']), 'account_requirement': 'Instagram Business or Creator professional account', 'recommended_permissions': ['instagram_business_basic', 'instagram_business_content_publish', 'instagram_business_manage_comments', 'instagram_business_manage_insights']}
    if not verify_credentials:
        return result
    verification = get_instagram_api_profile()
    result['verification'] = verification
    result['status'] = 'verified' if verification.get('ok') else 'verification_failed'
    return result

def get_instagram_api_profile(user_id: str='', fields: str='id,user_id,username,name,profile_picture_url,followers_count,follows_count,media_count,account_type') -> dict[str, Any]:
    """Get an owned Instagram professional account profile."""
    return _instagram_api_request('GET', f'/{_instagram_api_user_id(user_id)}', params={'fields': str(fields or '').strip()})

def get_instagram_api_media(user_id: str='', limit: int=25, after: str='', fields: str='id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,username,children{id,media_type,media_url,permalink,thumbnail_url}') -> dict[str, Any]:
    """List media owned by the configured Instagram professional account."""
    return _instagram_api_request('GET', f'/{_instagram_api_user_id(user_id)}/media', params={'fields': str(fields or '').strip(), 'limit': _coerce_limit(limit, default=25, minimum=1, maximum=100), 'after': str(after or '').strip()})

def get_instagram_api_media_details(media_id: str, fields: str='id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,username,comments_count,like_count,children{id,media_type,media_url}') -> dict[str, Any]:
    """Get one owned Instagram media object."""
    return _instagram_api_request('GET', f'/{_instagram_api_object_id(media_id, 'media')}', params={'fields': str(fields or '').strip()})

def get_instagram_api_comments(media_id: str, limit: int=50, after: str='', fields: str='id,from,text,timestamp,hidden,like_count,parent_id,username') -> dict[str, Any]:
    """Get comments on an owned Instagram media object."""
    return _instagram_api_request('GET', f'/{_instagram_api_object_id(media_id, 'media')}/comments', params={'fields': str(fields or '').strip(), 'limit': _coerce_limit(limit, default=50, minimum=1, maximum=100), 'after': str(after or '').strip()})

def get_instagram_api_comment_replies(comment_id: str, limit: int=50, after: str='', fields: str='id,from,text,timestamp,hidden,like_count,username') -> dict[str, Any]:
    """Get replies to an Instagram comment."""
    return _instagram_api_request('GET', f'/{_instagram_api_object_id(comment_id, 'comment')}/replies', params={'fields': str(fields or '').strip(), 'limit': _coerce_limit(limit, default=50, minimum=1, maximum=100), 'after': str(after or '').strip()})

def reply_instagram_api_comment(comment_id: str, message: str) -> dict[str, Any]:
    """Reply publicly to a comment on owned Instagram media."""
    clean_message = str(message or '').strip()
    if not clean_message:
        raise ValueError('Instagram comment reply cannot be empty.')
    return _instagram_api_request('POST', f'/{_instagram_api_object_id(comment_id, 'comment')}/replies', data={'message': clean_message})

def set_instagram_api_comment_hidden(comment_id: str, hidden: bool=True) -> dict[str, Any]:
    """Hide or unhide a comment on owned Instagram media."""
    return _instagram_api_request('POST', f'/{_instagram_api_object_id(comment_id, 'comment')}', data={'hide': bool(hidden)})

def delete_instagram_api_comment(comment_id: str) -> dict[str, Any]:
    """Delete a comment on owned Instagram media when permitted."""
    return _instagram_api_request('DELETE', f'/{_instagram_api_object_id(comment_id, 'comment')}')

def set_instagram_api_comments_enabled(media_id: str, enabled: bool=True) -> dict[str, Any]:
    """Enable or disable comments on an owned Instagram media object."""
    return _instagram_api_request('POST', f'/{_instagram_api_object_id(media_id, 'media')}', data={'comments': bool(enabled)})

def get_instagram_api_account_insights(metrics: str='reach,views,accounts_engaged,total_interactions', period: str='day', user_id: str='', since: str='', until: str='') -> dict[str, Any]:
    """Get account-level insights for an Instagram professional account."""
    normalized_period = str(period or 'day').strip().lower()
    if normalized_period not in {'day', 'week', 'days_28', 'lifetime'}:
        raise ValueError('Unsupported Instagram insights period.')
    return _instagram_api_request('GET', f'/{_instagram_api_user_id(user_id)}/insights', params={'metric': str(metrics or '').strip(), 'period': normalized_period, 'since': str(since or '').strip(), 'until': str(until or '').strip()})

def get_instagram_api_media_insights(media_id: str, metrics: str='reach,views,likes,comments,saved,shares,total_interactions') -> dict[str, Any]:
    """Get insights for an owned Instagram media object."""
    return _instagram_api_request('GET', f'/{_instagram_api_object_id(media_id, 'media')}/insights', params={'metric': str(metrics or '').strip()})

def create_instagram_api_image_container(image_url: str, caption: str='', user_id: str='', is_carousel_item: bool=False) -> dict[str, Any]:
    """Create an Instagram image publishing container from a public URL."""
    parsed = urlparse(str(image_url or '').strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('image_url must be a public HTTP(S) URL.')
    return _instagram_api_request('POST', f'/{_instagram_api_user_id(user_id)}/media', data={'image_url': image_url, 'caption': str(caption or ''), 'is_carousel_item': bool(is_carousel_item)})

def create_instagram_api_reel_container(video_url: str, caption: str='', user_id: str='', share_to_feed: bool=True, cover_url: str='', is_carousel_item: bool=False) -> dict[str, Any]:
    """Create an Instagram Reel/video publishing container from a public URL."""
    parsed = urlparse(str(video_url or '').strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('video_url must be a public HTTP(S) URL.')
    if cover_url:
        cover = urlparse(cover_url)
        if cover.scheme not in {'http', 'https'} or not cover.netloc:
            raise ValueError('cover_url must be a public HTTP(S) URL.')
    return _instagram_api_request('POST', f'/{_instagram_api_user_id(user_id)}/media', data={'media_type': 'VIDEO' if is_carousel_item else 'REELS', 'video_url': video_url, 'caption': str(caption or ''), 'share_to_feed': bool(share_to_feed), 'cover_url': str(cover_url or '').strip(), 'is_carousel_item': bool(is_carousel_item)})

def create_instagram_api_story_container(media_url: str, media_type: str='image', user_id: str='') -> dict[str, Any]:
    """Create an Instagram Story image or video publishing container."""
    parsed = urlparse(str(media_url or '').strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('media_url must be a public HTTP(S) URL.')
    normalized_type = str(media_type or 'image').strip().lower()
    if normalized_type not in {'image', 'video'}:
        raise ValueError('media_type must be image or video.')
    field = 'image_url' if normalized_type == 'image' else 'video_url'
    return _instagram_api_request('POST', f'/{_instagram_api_user_id(user_id)}/media', data={'media_type': 'STORIES', field: media_url})

def create_instagram_api_carousel_container(child_container_ids: str, caption: str='', user_id: str='') -> dict[str, Any]:
    """Create a carousel container from 2–10 completed child container IDs."""
    children = [_instagram_api_object_id(value.strip(), 'container') for value in str(child_container_ids or '').split(',') if value.strip()]
    if not 2 <= len(children) <= 10:
        raise ValueError('A carousel requires 2 to 10 child container IDs.')
    return _instagram_api_request('POST', f'/{_instagram_api_user_id(user_id)}/media', data={'media_type': 'CAROUSEL', 'children': ','.join(children), 'caption': str(caption or '')})

def get_instagram_api_container_status(container_id: str) -> dict[str, Any]:
    """Get an Instagram publishing container's processing status."""
    return _instagram_api_request('GET', f'/{_instagram_api_object_id(container_id, 'container')}', params={'fields': 'id,status_code,status'})

def publish_instagram_api_container(container_id: str, user_id: str='') -> dict[str, Any]:
    """Publish a finished Instagram media container."""
    return _instagram_api_request('POST', f'/{_instagram_api_user_id(user_id)}/media_publish', data={'creation_id': _instagram_api_object_id(container_id, 'container')})

def _wait_for_instagram_api_container(container_id: str, timeout_seconds: int=120, poll_interval: int=5) -> dict[str, Any]:
    deadline = time.time() + max(5, min(int(timeout_seconds), 600))
    interval = max(2, min(int(poll_interval), 30))
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = get_instagram_api_container_status(container_id)
        if not latest.get('ok'):
            return latest
        status_code = str(latest.get('container_status_code') or '').upper()
        if status_code == 'FINISHED':
            return latest
        if status_code in {'ERROR', 'EXPIRED'}:
            return _instagram_api_error(f'Instagram container entered {status_code} state.', endpoint=latest.get('endpoint', ''), status_code=int(latest.get('status_code', 0) or 0) if isinstance(latest.get('status_code'), int) else 0, response=latest.get('response'))
        time.sleep(interval)
    return _instagram_api_error('Timed out waiting for Instagram media processing.', response=latest.get('response') if latest else None)

def publish_instagram_api_image(image_url: str, caption: str='', user_id: str='') -> dict[str, Any]:
    """Create and publish an Instagram image Post from a public image URL."""
    created = create_instagram_api_image_container(image_url=image_url, caption=caption, user_id=user_id)
    if not created.get('ok'):
        return {'status': 'create_failed', 'create': created}
    container_id = str(created.get('id') or '')
    if not container_id:
        return {'status': 'create_failed', 'create': created, 'error': 'Instagram returned no container ID.'}
    published = publish_instagram_api_container(container_id, user_id=user_id)
    return {'status': 'published' if published.get('ok') else 'publish_failed', 'container_id': container_id, 'create': created, 'publish': published}

def publish_instagram_api_reel(video_url: str, caption: str='', user_id: str='', share_to_feed: bool=True, cover_url: str='', timeout_seconds: int=120) -> dict[str, Any]:
    """Create, await, and publish an Instagram Reel from a public video URL."""
    created = create_instagram_api_reel_container(video_url=video_url, caption=caption, user_id=user_id, share_to_feed=share_to_feed, cover_url=cover_url)
    if not created.get('ok'):
        return {'status': 'create_failed', 'create': created}
    container_id = str(created.get('id') or '')
    if not container_id:
        return {'status': 'create_failed', 'create': created, 'error': 'Instagram returned no container ID.'}
    processing = _wait_for_instagram_api_container(container_id, timeout_seconds=timeout_seconds)
    if not processing.get('ok'):
        return {'status': 'processing_failed', 'container_id': container_id, 'create': created, 'processing': processing}
    published = publish_instagram_api_container(container_id, user_id=user_id)
    return {'status': 'published' if published.get('ok') else 'publish_failed', 'container_id': container_id, 'create': created, 'processing': processing, 'publish': published}

def publish_instagram_api_story(media_url: str, media_type: str='image', user_id: str='', timeout_seconds: int=120) -> dict[str, Any]:
    """Create, await when needed, and publish an Instagram Story."""
    created = create_instagram_api_story_container(media_url=media_url, media_type=media_type, user_id=user_id)
    if not created.get('ok'):
        return {'status': 'create_failed', 'create': created}
    container_id = str(created.get('id') or '')
    if not container_id:
        return {'status': 'create_failed', 'create': created, 'error': 'Instagram returned no container ID.'}
    processing: dict[str, Any] = {'ok': True, 'status': 'not_required'}
    if str(media_type or 'image').lower() == 'video':
        processing = _wait_for_instagram_api_container(container_id, timeout_seconds=timeout_seconds)
        if not processing.get('ok'):
            return {'status': 'processing_failed', 'container_id': container_id, 'create': created, 'processing': processing}
    published = publish_instagram_api_container(container_id, user_id=user_id)
    return {'status': 'published' if published.get('ok') else 'publish_failed', 'container_id': container_id, 'create': created, 'processing': processing, 'publish': published}

def get_instagram_api_publishing_limit(user_id: str='') -> dict[str, Any]:
    """Get the professional account's content publishing quota usage."""
    return _instagram_api_request('GET', f'/{_instagram_api_user_id(user_id)}/content_publishing_limit', params={'fields': 'config,quota_usage'})

"""Generated api surface from the original MarketingApp toolbox.

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

def _limit(value: Any, default: int=20, maximum: int=100) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))

def _compact(value: Any, limit: int=800) -> str:
    text = re.sub('\\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'

def _tiktok_api_token() -> str:
    return (os.getenv('TIKTOK_ACCESS_TOKEN') or os.getenv('TIKTOK_API_ACCESS_TOKEN') or '').strip()

def _tiktok_api_base_url() -> str:
    return (os.getenv('TIKTOK_API_BASE_URL') or _DEFAULT_TIKTOK_API_BASE_URL).strip().rstrip('/')

def _tiktok_api_timeout() -> int:
    try:
        return max(5, min(int(os.getenv('TIKTOK_API_TIMEOUT', _DEFAULT_TIKTOK_API_TIMEOUT)), 120))
    except (TypeError, ValueError):
        return _DEFAULT_TIKTOK_API_TIMEOUT

def _tiktok_api_error(message: str, *, endpoint: str='', status_code: int | None=None) -> dict[str, Any]:
    result: dict[str, Any] = {'ok': False, 'status': 'error', 'error': message}
    if endpoint:
        result['endpoint'] = endpoint
    if status_code is not None:
        result['status_code'] = status_code
    return result

def _tiktok_api_request(method: str, endpoint: str, *, params: dict[str, Any] | None=None, payload: dict[str, Any] | None=None) -> dict[str, Any]:
    token = _tiktok_api_token()
    if not token:
        return _tiktok_api_error('TikTok API access token is not configured. Set TIKTOK_ACCESS_TOKEN.', endpoint=endpoint)
    normalized_endpoint = '/' + endpoint.lstrip('/')
    try:
        response = requests.request(method.upper(), f'{_tiktok_api_base_url()}{normalized_endpoint}', headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=UTF-8'}, params=params, json=payload, timeout=_tiktok_api_timeout())
    except requests.RequestException as exc:
        return _tiktok_api_error(f'TikTok API request failed: {exc}', endpoint=normalized_endpoint)
    try:
        body = response.json()
    except ValueError:
        body = {'raw_response': _compact(response.text, 1000)}
    api_error = body.get('error') if isinstance(body, dict) else None
    api_code = api_error.get('code') if isinstance(api_error, dict) else ''
    ok = response.ok and api_code in {'', 'ok'}
    result = {'ok': ok, 'status': 'ok' if ok else 'error', 'status_code': response.status_code, 'endpoint': normalized_endpoint, 'response': body}
    if not ok:
        result['error'] = (api_error.get('message') if isinstance(api_error, dict) else '') or f'TikTok API returned HTTP {response.status_code}.'
    return result

def get_tiktok_api_status(verify_token: bool=False) -> dict[str, Any]:
    """Report API configuration without exposing credential values.

    Set ``verify_token=True`` to call the official User Info endpoint. The
    token needs at least the ``user.info.basic`` scope for verification.
    """
    result = {'configured': bool(_tiktok_api_token()), 'api_base_url': _tiktok_api_base_url(), 'timeout_seconds': _tiktok_api_timeout(), 'required_scopes': {'profile': 'user.info.basic (plus user.info.profile/user.info.stats for extra fields)', 'videos': 'video.list', 'direct_post': 'video.publish', 'inbox_draft': 'video.upload'}}
    if verify_token and result['configured']:
        result['verification'] = get_tiktok_api_user_info('open_id,display_name')
    return result

def get_tiktok_api_user_info(fields: str='open_id,avatar_url,display_name') -> dict[str, Any]:
    """Get the authorized user's profile through TikTok's official API."""
    if not str(fields or '').strip():
        raise ValueError('At least one user-info field is required.')
    return _tiktok_api_request('GET', '/v2/user/info/', params={'fields': fields.strip()})

def list_tiktok_api_videos(fields: str='id,title,video_description,duration,cover_image_url,share_url,create_time,view_count,like_count,comment_count,share_count', cursor: int=0, max_count: int=20) -> dict[str, Any]:
    """List the authorized user's public videos (requires ``video.list``)."""
    if not str(fields or '').strip():
        raise ValueError('At least one video field is required.')
    return _tiktok_api_request('POST', '/v2/video/list/', params={'fields': fields.strip()}, payload={'cursor': max(0, int(cursor)), 'max_count': _limit(max_count, default=20, maximum=20)})

def get_tiktok_api_creator_info() -> dict[str, Any]:
    """Get current creator settings before a Direct Post (``video.publish``)."""
    return _tiktok_api_request('POST', '/v2/post/publish/creator_info/query/', payload={})

def get_tiktok_api_post_status(publish_id: str) -> dict[str, Any]:
    """Get Content Posting API processing status for a publish/upload ID."""
    if not str(publish_id or '').strip():
        raise ValueError('publish_id is required.')
    return _tiktok_api_request('POST', '/v2/post/publish/status/fetch/', payload={'publish_id': publish_id.strip()})

def _tiktok_video_source(path: str, chunk_size: int) -> tuple[str, int, int, int]:
    absolute_path = os.path.abspath(os.path.expanduser(str(path or '')))
    if not os.path.isfile(absolute_path):
        raise ValueError('video_path must point to an existing local video file.')
    size = os.path.getsize(absolute_path)
    if size <= 0:
        raise ValueError('video_path must not be empty.')
    chunk_size = max(1, min(int(chunk_size), 64 * 1024 * 1024))
    return (absolute_path, size, chunk_size, math.ceil(size / chunk_size))

def init_tiktok_api_video_post(video_path: str, title: str, privacy_level: str='SELF_ONLY', disable_comment: bool=False, disable_duet: bool=False, disable_stitch: bool=False, video_cover_timestamp_ms: int=0, chunk_size: int=_DEFAULT_TIKTOK_CHUNK_SIZE) -> dict[str, Any]:
    """Initialize an official Direct Post upload (requires ``video.publish``).

    Call :func:`get_tiktok_api_creator_info` first and use one of the returned
    ``privacy_level_options``. The creator must have explicitly approved the
    post metadata before calling this action.
    """
    path, size, chunk_size, chunks = _tiktok_video_source(video_path, chunk_size)
    if len(str(title or '').encode('utf-16-le')) // 2 > 2200:
        raise ValueError('TikTok video title/caption must not exceed 2200 UTF-16 characters.')
    response = _tiktok_api_request('POST', '/v2/post/publish/video/init/', payload={'post_info': {'title': str(title or ''), 'privacy_level': privacy_level, 'disable_comment': bool(disable_comment), 'disable_duet': bool(disable_duet), 'disable_stitch': bool(disable_stitch), 'video_cover_timestamp_ms': max(0, int(video_cover_timestamp_ms))}, 'source_info': {'source': 'FILE_UPLOAD', 'video_size': size, 'chunk_size': chunk_size, 'total_chunk_count': chunks}})
    if response.get('ok'):
        response['video_path'] = path
        response['video_size'] = size
        response['chunk_size'] = chunk_size
    return response

def upload_tiktok_api_video_file(video_path: str, upload_url: str, chunk_size: int=_DEFAULT_TIKTOK_CHUNK_SIZE) -> dict[str, Any]:
    """Transfer a local video to the one-hour TikTok upload URL from init."""
    path, total_size, chunk_size, _ = _tiktok_video_source(video_path, chunk_size)
    if not str(upload_url or '').startswith('https://'):
        raise ValueError("upload_url must be the HTTPS URL returned by TikTok's init endpoint.")
    media_type = mimetypes.guess_type(path)[0] or 'video/mp4'
    uploaded = 0
    try:
        with open(path, 'rb') as file_handle:
            while uploaded < total_size:
                chunk = file_handle.read(min(chunk_size, total_size - uploaded))
                end = uploaded + len(chunk) - 1
                response = requests.put(upload_url, headers={'Content-Type': media_type, 'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {uploaded}-{end}/{total_size}'}, data=chunk, timeout=_tiktok_api_timeout())
                if response.status_code not in {200, 201, 206}:
                    return _tiktok_api_error(f'TikTok upload returned HTTP {response.status_code}: {_compact(response.text, 500)}', endpoint='upload_url', status_code=response.status_code)
                uploaded += len(chunk)
    except OSError as exc:
        return _tiktok_api_error(f'Could not read local video: {exc}', endpoint='upload_url')
    except requests.RequestException as exc:
        return _tiktok_api_error(f'TikTok video upload failed: {exc}', endpoint='upload_url')
    return {'ok': True, 'status': 'uploaded', 'video_path': path, 'uploaded_bytes': uploaded, 'total_bytes': total_size}

def publish_tiktok_api_video(video_path: str, title: str, privacy_level: str='SELF_ONLY', disable_comment: bool=False, disable_duet: bool=False, disable_stitch: bool=False, video_cover_timestamp_ms: int=0, chunk_size: int=_DEFAULT_TIKTOK_CHUNK_SIZE) -> dict[str, Any]:
    """Initialize and transfer a Direct Post video using TikTok's official API.

    TikTok processes the post asynchronously; use the returned ``publish_id``
    with :func:`get_tiktok_api_post_status` to learn the final outcome.
    """
    creator_info = get_tiktok_api_creator_info()
    if not creator_info.get('ok'):
        return {'status': 'creator_info_failed', 'creator_info': creator_info}
    creator_data = creator_info.get('response', {}).get('data', {})
    privacy_options = creator_data.get('privacy_level_options') or []
    if privacy_options and privacy_level not in privacy_options:
        return {'status': 'invalid_privacy_level', 'creator_info': creator_info, 'error': f"privacy_level must be one of the creator's options: {', '.join(privacy_options)}"}
    initiated = init_tiktok_api_video_post(video_path, title, privacy_level, disable_comment, disable_duet, disable_stitch, video_cover_timestamp_ms, chunk_size)
    if not initiated.get('ok'):
        return {'status': 'init_failed', 'creator_info': creator_info, 'init': initiated}
    data = initiated.get('response', {}).get('data', {})
    upload_url = str(data.get('upload_url') or '')
    publish_id = str(data.get('publish_id') or '')
    if not upload_url:
        return {'status': 'init_failed', 'creator_info': creator_info, 'init': initiated, 'error': 'TikTok did not return an upload URL.'}
    uploaded = upload_tiktok_api_video_file(video_path, upload_url, chunk_size)
    return {'status': 'uploaded' if uploaded.get('ok') else 'upload_failed', 'publish_id': publish_id, 'creator_info': creator_info, 'init': initiated, 'upload': uploaded}

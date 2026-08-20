"""Generated browser surface from the original MarketingApp toolbox.

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

from selenium.webdriver.common.by import By

from selenium.webdriver.common.action_chains import ActionChains

from selenium.webdriver.common.keys import Keys

from selenium.webdriver.support.ui import WebDriverWait

from selenium.webdriver.support import expected_conditions as EC

from selenium.common.exceptions import TimeoutException

from MarketingApp.araclar.browser_araclari import _get_driver, _human_click, _read_element_value, _type_into_element, browser_baslat, browser_git, browser_kapat, get_browser_runtime_state

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

def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')

def _ensure_social_dir():
    os.makedirs(_SOCIAL_DIR, exist_ok=True)

def _compact_text(text: str, limit: int=220) -> str:
    text = re.sub('\\s+', ' ', text or '').strip()
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + '…'

def _coerce_limit(value: Any, default: int=10, minimum: int=1, maximum: int=50) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(number, maximum))

def _write_json(path: str, payload: Any):
    _ensure_social_dir()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def _write_text(path: str, content: str):
    _ensure_social_dir()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def _normalize_token(text: str) -> str:
    text = (text or '').lower()
    text = text.replace('ı', 'i').replace('ğ', 'g').replace('ü', 'u')
    text = text.replace('ş', 's').replace('ö', 'o').replace('ç', 'c')
    return re.sub('[^a-z0-9\\s#@/$.-]+', ' ', text)

def _normalize_compact(text: str) -> str:
    return re.sub('\\s+', ' ', _normalize_token(text or '')).strip()

def _contains_non_bmp(text: str) -> bool:
    return any((ord(char) > 65535 for char in str(text or '')))

def _looks_recently_processed(existing: dict[str, Any] | None) -> bool:
    if not existing:
        return False
    return existing.get('status') in {'sent', 'skipped'}

def _classify_notification_candidate(entry: dict[str, Any], *, own_handle: str='', existing: dict[str, Any] | None=None) -> dict[str, Any]:
    handle = _normalize_compact(entry.get('handle', '')).lstrip('@')
    own = _normalize_compact(own_handle).lstrip('@')
    text = _normalize_compact(entry.get('text', ''))
    article_text = _normalize_compact(entry.get('article_text') or entry.get('text', ''))
    if _looks_recently_processed(existing):
        return {'candidate_type': 'ignore', 'confidence': 0.0, 'reason': 'zaten_islenmis'}
    if own and handle and (handle == own):
        return {'candidate_type': 'ignore', 'confidence': 0.0, 'reason': 'kendi_hesabi'}
    if not text:
        return {'candidate_type': 'ignore', 'confidence': 0.0, 'reason': 'metinsiz_kart'}
    if any((marker in article_text for marker in _SYSTEM_NOTIFICATION_MARKERS)):
        return {'candidate_type': 'ignore', 'confidence': 0.0, 'reason': 'sistem_bildirimi'}
    if any((marker in article_text for marker in _MENTION_MARKERS)):
        return {'candidate_type': 'mention', 'confidence': 0.98, 'reason': 'mention_marker'}
    if any((marker in article_text for marker in _REPLY_MARKERS)):
        return {'candidate_type': 'reply', 'confidence': 0.92, 'reason': 'reply_marker'}
    if '@' in text and entry.get('reply_available'):
        return {'candidate_type': 'ambiguous', 'confidence': 0.68, 'reason': 'replyable_mention_text'}
    if entry.get('reply_available') and len(text) >= 24 and handle:
        return {'candidate_type': 'ambiguous', 'confidence': 0.56, 'reason': 'replyable_text_card'}
    return {'candidate_type': 'ignore', 'confidence': 0.0, 'reason': 'dusuk_guven'}

def _extract_topics(entries: list[dict[str, Any]]) -> dict[str, int]:
    combined = ' '.join((_normalize_token(entry.get('text', '')) for entry in entries))
    counts: dict[str, int] = {}
    for topic, keywords in _active_topic_keywords().items():
        counts[topic] = sum((combined.count(str(keyword).lower()) for keyword in keywords))
    return {topic: count for topic, count in counts.items() if count > 0}

def _active_topic_keywords() -> dict[str, tuple[str, ...]]:
    if os.path.exists(_ACTIVE_PROFILE_PATH):
        try:
            with open(_ACTIVE_PROFILE_PATH, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            raw_keywords = profile.get('topic_keywords') if isinstance(profile, dict) else {}
            if isinstance(raw_keywords, dict) and raw_keywords:
                parsed: dict[str, tuple[str, ...]] = {}
                for topic, keywords in raw_keywords.items():
                    if isinstance(keywords, list):
                        values = tuple((str(item).lower() for item in keywords if str(item).strip()))
                    else:
                        values = (str(keywords).lower(),)
                    if values:
                        parsed[str(topic)] = values
                if parsed:
                    return parsed
        except Exception:
            pass
    return _DEFAULT_TOPIC_KEYWORDS

def _detect_market_mood(entries: list[dict[str, Any]]) -> str:
    combined = ' '.join((_normalize_token(entry.get('text', '')) for entry in entries))
    bullish = sum((combined.count(word) for word in _BULLISH_WORDS))
    bearish = sum((combined.count(word) for word in _BEARISH_WORDS))
    if bullish > bearish + 1:
        return 'risk-on / bullish'
    if bearish > bullish + 1:
        return 'risk-off / bearish'
    return 'mixed / waiting'

def _idea_templates_for_topic(topic: str) -> list[str]:
    return [f'{topic} tarafinda kalabaligin neye odaklandigini tek gozlemle acikla.', f'{topic} icin piyasanin atladigi tek riski veya firsati sade dille anlat.', f'{topic} konusunda bugunun akisindan cikabilecek tek net sonucu yaz.', f'{topic} basliginda yeni baslayanlarin yanlis okudugu noktayi duzelt.']

def _build_market_files(source: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    topics = _extract_topics(entries)
    top_topics = sorted(topics.items(), key=lambda item: (-item[1], item[0]))[:6]
    mood = _detect_market_mood(entries)
    handles = Counter((entry.get('handle', '') for entry in entries if entry.get('handle'))).most_common(6)
    samples = []
    for entry in entries[:12]:
        handle = entry.get('handle') or 'unknown'
        samples.append(f'- @{handle} | {entry.get('tweet_id', '')} | {_compact_text(entry.get('text', ''), 180)}')
    idea_lines = []
    used = set()
    topic_order = [topic for topic, _ in top_topics] or list(_active_topic_keywords().keys())[:4] or ['general']
    for topic in topic_order:
        for template in _idea_templates_for_topic(topic):
            if template in used:
                continue
            idea_lines.append(f'- [fresh] {template}')
            used.add(template)
            if len(idea_lines) >= 12:
                break
        if len(idea_lines) >= 12:
            break
    market_state = '\n'.join(['# Market State', '', f'- updated_at: {_now()}', f'- source: {source}', f'- visible_posts: {len(entries)}', f'- market_mood: {mood}', f'- top_topics: {', '.join((f'{topic}({count})' for topic, count in top_topics)) or 'belirgin tema yok'}', f'- active_handles: {', '.join((f'@{handle}({count})' for handle, count in handles)) or 'yok'}', '', '## Feed Samples', *samples, '', '## Usage', '- Yeni post veya yorum yazmadan once burayi oku.', '- Ayni aciyi ust uste kullanma.', '- Tek postta tek bir ana fikir sec.'])
    idea_pool = '\n'.join(['# Idea Pool', '', f'- updated_at: {_now()}', f'- source: {source}', '', '## Fresh Angles', *idea_lines, '', '## Rotation Rule', '- Aynı etiketi [used] olmadan art arda kullanma.', '- Son 10 aksiyonda benzer cümle varsa başka fikre geç.'])
    _write_text(_MARKET_STATE_PATH, market_state)
    _write_text(_IDEA_POOL_PATH, idea_pool)
    return {'market_mood': mood, 'top_topics': top_topics, 'idea_count': len(idea_lines)}

def _load_queue() -> dict[str, Any]:
    _ensure_social_dir()
    if not os.path.exists(_QUEUE_PATH):
        return {'platform': 'x', 'updated_at': _now(), 'items': []}
    try:
        with open(_QUEUE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('Queue format bozuk')
        data.setdefault('platform', 'x')
        data.setdefault('updated_at', _now())
        data.setdefault('items', [])
        return data
    except Exception:
        return {'platform': 'x', 'updated_at': _now(), 'items': []}

def _save_queue(data: dict[str, Any]):
    _ensure_social_dir()
    data['updated_at'] = _now()
    with open(_QUEUE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_x_queue() -> dict[str, Any]:
    data = _load_queue()
    data['items'] = sorted(data['items'], key=lambda item: (item.get('status') == 'sent', item.get('discovered_at', '')), reverse=False)
    data['summary'] = {'total': len(data['items']), 'new': sum((1 for item in data['items'] if item.get('status') == 'new')), 'drafted': sum((1 for item in data['items'] if item.get('status') == 'drafted')), 'pending_verify': sum((1 for item in data['items'] if item.get('status') == 'pending_verify')), 'sent': sum((1 for item in data['items'] if item.get('status') == 'sent')), 'preview': [{'queue_id': item.get('queue_id', ''), 'status': item.get('status', ''), 'author_handle': item.get('author_handle', ''), 'text': _compact_text(item.get('text', ''), 160)} for item in data['items'][:12]]}
    return data

def get_browser_status() -> dict[str, Any]:
    runtime = get_browser_runtime_state()
    try:
        driver = _get_driver()
        return {'ready': True, 'title': driver.title, 'url': driver.current_url, 'window_count': len(driver.window_handles), 'headless': runtime.get('active_headless'), 'preferred_headless': runtime.get('preferred_headless'), 'visibility_label': runtime.get('visibility_label')}
    except Exception as e:
        return {'ready': False, 'error': str(e), 'title': '', 'url': '', 'window_count': 0, 'headless': runtime.get('active_headless'), 'preferred_headless': runtime.get('preferred_headless'), 'visibility_label': runtime.get('visibility_label')}

def launch_x_browser(headless: bool=False, restart_if_needed: bool=True) -> dict[str, Any]:
    """
    X otomasyon tarayıcısını görünür veya headless modda başlatır.
    Gerekirse açık oturumu aynı URL'de yeniden başlatır.

    Args:
        headless: True ise pencere açılmaz, False ise görünür modda açılır
        restart_if_needed: Mod farklıysa açık tarayıcıyı kapatıp yeniden başlat
    """
    requested_headless = bool(headless)
    desired_headless = False
    current_status = get_browser_status()
    current_url = current_status.get('url', '') if current_status.get('ready') else ''
    current_headless = current_status.get('headless')
    if current_status.get('ready'):
        if current_headless == desired_headless:
            return {'status': 'already_running', 'message': 'Tarayıcı zaten görünür modda açık.', 'browser': current_status, 'headless_forced_off': requested_headless}
        if not restart_if_needed:
            return {'status': 'restart_required', 'message': 'Sosyal otomasyon için görünür mod zorunlu. Yeniden başlatma gerekiyor.', 'browser': current_status, 'headless_forced_off': requested_headless}
        close_result = browser_kapat()
        start_result = browser_baslat(headless=desired_headless)
        reopen_result = ''
        if start_result.startswith('✅') and current_url.startswith('http'):
            reopen_result = browser_git(current_url)
        return {'status': 'restarted', 'message': start_result, 'close_result': close_result, 'reopen_result': reopen_result, 'browser': get_browser_status(), 'headless_forced_off': requested_headless}
    start_result = browser_baslat(headless=desired_headless)
    return {'status': 'started' if start_result.startswith('✅') else 'error', 'message': start_result, 'browser': get_browser_status(), 'headless_forced_off': requested_headless}

def close_x_browser() -> dict[str, Any]:
    """X otomasyon tarayıcısını kapatır."""
    result = browser_kapat()
    return {'status': 'closed' if str(result).startswith('✅') else 'error', 'message': result, 'browser': get_browser_status()}

def _normalize_x_handle(value: str) -> str:
    raw = (value or '').strip()
    if not raw:
        return ''
    if raw.startswith('http://') or raw.startswith('https://'):
        match = re.search('x\\.com/([^/?#]+)', raw)
        if match:
            return match.group(1).strip().lstrip('@')
        return ''
    return raw.lstrip('@')

def _build_x_destination_url(destination: str, *, query: str='', handle_or_url: str='', tweet_url: str='', tab: str='latest') -> str:
    target = _normalize_compact(destination or 'home')
    if target in {'home', 'anasayfa'}:
        return 'https://x.com/home'
    if target in {'explore', 'kesfet'}:
        return 'https://x.com/explore'
    if target in {'notifications', 'bildirimler'}:
        return 'https://x.com/notifications'
    if target in {'mentions', 'bildirim-mentions'}:
        return 'https://x.com/notifications/mentions'
    if target in {'bookmarks', 'yer_isaretleri'}:
        return 'https://x.com/i/bookmarks'
    if target in {'compose', 'yaz', 'new post', 'yeni post', 'post at', 'tweet at', 'gonder', 'gönder', 'paylas', 'paylaş'}:
        return 'https://x.com/compose/post'
    if target in {'post', 'tweet', 'status'}:
        return _normalize_x_status_url(tweet_url) if tweet_url else 'https://x.com/compose/post'
    if not tweet_url and any((marker in target for marker in ('post', 'tweet', 'gonder', 'gönder', 'paylas', 'paylaş'))):
        return 'https://x.com/compose/post'
    if target in {'profile', 'profil'}:
        handle = _normalize_x_handle(handle_or_url)
        return f'https://x.com/{handle}' if handle else ''
    if target in {'search', 'arama'}:
        query_text = (query or '').strip()
        if not query_text:
            return ''
        tab_map = {'top': '', 'latest': 'live', 'people': 'user', 'media': 'image', 'videos': 'video'}
        filter_value = tab_map.get((tab or 'latest').strip().lower(), 'live')
        suffix = f'&f={filter_value}' if filter_value else ''
        return f'https://x.com/search?q={quote_plus(query_text)}&src=typed_query{suffix}'
    return ''

def open_x_page(destination: str='home', query: str='', handle_or_url: str='', tweet_url: str='', tab: str='latest') -> dict[str, Any]:
    """
    X içinde belirli bir sayfayı açar.

    Args:
        destination: home, explore, notifications, mentions, bookmarks, compose, profile, search, post
        query: search için sorgu
        handle_or_url: profile için handle veya profil URL'si
        tweet_url: post için hedef status URL'si
        tab: search sekmesi (latest, top, people, media, videos)
    """
    url = _build_x_destination_url(destination, query=query, handle_or_url=handle_or_url, tweet_url=tweet_url, tab=tab)
    if not url:
        raise ValueError('X hedefi olusturulamadi')
    result = browser_git(url)
    browser = get_browser_status()
    return {'status': 'opened' if str(result).startswith('✅') else 'error', 'destination': destination, 'message': result, 'browser': browser}

def _normalize_x_status_url(url: str) -> str:
    if not url:
        return ''
    if url.startswith('http://') or url.startswith('https://'):
        return url
    return f'https://x.com{url}'

def _extract_root_status_id(url: str) -> str | None:
    match = re.search('/status/(\\d+)', url or '')
    return match.group(1) if match else None

def _discover_current_x_handle(driver) -> str:
    try:
        handle = driver.execute_script('\n            const profileLink = document.querySelector(\'a[data-testid="AppTabBar_Profile_Link"]\');\n            if (profileLink) {\n                const href = profileLink.getAttribute(\'href\') || \'\';\n                const match = href.match(/^\\/([^/?#]+)/);\n                if (match) return match[1];\n            }\n            const accountLink = [...document.querySelectorAll(\'a[href^="/"]\')]\n                .map((a) => a.getAttribute(\'href\') || \'\')\n                .find((href) => /^\\/[^/?#]+$/.test(href) && !href.includes(\'/home\') && !href.includes(\'/explore\'));\n            if (!accountLink) return \'\';\n            const match = accountLink.match(/^\\/([^/?#]+)/);\n            return match ? match[1] : \'\';\n            ')
        return (handle or '').strip().lstrip('@')
    except Exception:
        return ''

def _find_first_visible(driver, selectors: tuple[str, ...], *, require_enabled: bool=False):
    js = "\n    const selectors = arguments[0] || [];\n    const requireEnabled = !!arguments[1];\n    const isVisible = (el) => {\n      if (!el) return false;\n      const rect = el.getBoundingClientRect();\n      const style = window.getComputedStyle(el);\n      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';\n    };\n    const isEnabled = (el) => {\n      const disabled = el.disabled === true || el.getAttribute('disabled') !== null || el.getAttribute('aria-disabled') === 'true';\n      return !disabled;\n    };\n\n    for (const selector of selectors) {\n      for (const el of document.querySelectorAll(selector)) {\n        if (!isVisible(el)) continue;\n        if (requireEnabled && !isEnabled(el)) continue;\n        return el;\n      }\n    }\n    return null;\n    "
    return driver.execute_script(js, list(selectors), require_enabled)

def _click_element_with_fallback(driver, element, label: str='x_action') -> str:
    last_error = None
    strategies = (('human_click', lambda: _human_click(driver, element)), ('native_click', lambda: element.click()), ('js_click', lambda: driver.execute_script('arguments[0].click();', element)))
    for method, strategy in strategies:
        try:
            strategy()
            return method
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f'{label} tıklanamadı: {last_error}')

def _wait_for_x_or_fail(url: str, *, expect_articles: bool=False):
    driver = _get_driver()
    driver.get(url)
    if expect_articles:
        _wait_for_x_articles()
        time.sleep(1.0)
    return driver

def _build_profile_snapshot(driver) -> dict[str, Any]:
    return driver.execute_script('\n        const getText = (selector) => {\n          const el = document.querySelector(selector);\n          return el ? (el.innerText || el.textContent || \'\').trim() : \'\';\n        };\n        const bodyText = document.body ? (document.body.innerText || \'\').trim() : \'\';\n        const links = [...document.querySelectorAll(\'a[href^="/"]\')].map((el) => el.getAttribute(\'href\') || \'\');\n        const profileMatch = links.find((href) => /^\\/[^/?#]+$/.test(href) && !href.includes(\'/home\') && !href.includes(\'/explore\'));\n        const countLinks = [...document.querySelectorAll(\'a[href$="/verified_followers"], a[href$="/followers"], a[href$="/following"]\')];\n        const counts = countLinks.map((el) => (el.innerText || el.textContent || \'\').trim()).filter(Boolean).slice(0, 3);\n        return {\n          page_url: window.location.href,\n          title: document.title || \'\',\n          display_name: getText(\'[data-testid="UserName"] span\') || getText(\'[data-testid="UserName"]\'),\n          handle: profileMatch || \'\',\n          bio: getText(\'[data-testid="UserDescription"]\'),\n          stats: counts,\n          body_excerpt: bodyText.slice(0, 1800),\n        };\n        ')

def _build_post_snapshot(driver) -> dict[str, Any]:
    return driver.execute_script('\n        const article = document.querySelector(\'article[data-testid="tweet"]\');\n        const getText = (root, selector) => {\n          if (!root) return \'\';\n          const el = root.querySelector(selector);\n          return el ? (el.innerText || el.textContent || \'\').trim() : \'\';\n        };\n        const articleText = article ? (article.innerText || \'\').trim() : \'\';\n        const links = article ? [...article.querySelectorAll(\'a[href*="/status/"]\')].map((el) => el.getAttribute(\'href\') || \'\') : [];\n        return {\n          page_url: window.location.href,\n          title: document.title || \'\',\n          tweet_url: links.find((href) => /\\/status\\/\\d+/.test(href)) || \'\',\n          author: getText(article, \'[data-testid="User-Name"]\'),\n          text: getText(article, \'[data-testid="tweetText"]\'),\n          article_text: articleText,\n          reply_ready: !!document.querySelector(\'[data-testid="reply"]\'),\n          like_ready: !!document.querySelector(\'[data-testid="like"], [data-testid="unlike"]\'),\n          repost_ready: !!document.querySelector(\'[data-testid="retweet"], [data-testid="unretweet"]\'),\n          bookmark_ready: !!document.querySelector(\'[data-testid="bookmark"], [data-testid="removeBookmark"]\'),\n        };\n        ')

def _resolve_recent_status_url(driver, message: str, *, prefer_current_url: bool=True) -> str:
    current_url = driver.current_url
    if prefer_current_url and re.search('/status/\\d+', current_url or ''):
        return _normalize_x_status_url(current_url)
    compact_message = _compact_text(message, 120)
    own_handle = _discover_current_x_handle(driver)
    result = driver.execute_script('\n        const target = arguments[0] || \'\';\n        const ownHandle = (arguments[1] || \'\').replace(/^@/, \'\').toLowerCase();\n        const normalize = (value) => (value || \'\')\n          .toLowerCase()\n          .replace(/[ı]/g, \'i\')\n          .replace(/[ğ]/g, \'g\')\n          .replace(/[ü]/g, \'u\')\n          .replace(/[ş]/g, \'s\')\n          .replace(/[ö]/g, \'o\')\n          .replace(/[ç]/g, \'c\')\n          .replace(/[^a-z0-9\\s#@/$.-]+/g, \' \')\n          .replace(/\\s+/g, \' \')\n          .trim();\n\n        const targetNorm = normalize(target);\n        const articles = [...document.querySelectorAll(\'article[data-testid="tweet"]\')];\n        for (const article of articles) {\n          const articleText = normalize(article.innerText || \'\');\n          if (targetNorm && !articleText.includes(targetNorm)) continue;\n          const statusLink = [...article.querySelectorAll(\'a[href*="/status/"]\')]\n            .map((a) => a.getAttribute(\'href\') || \'\')\n            .find((href) => /\\/status\\/\\d+/.test(href));\n          if (!statusLink) continue;\n          const handleMatch = statusLink.match(/^\\/([^/]+)\\/status\\/(\\d+)/);\n          const handle = handleMatch ? handleMatch[1].toLowerCase() : \'\';\n          if (ownHandle && handle && handle !== ownHandle) continue;\n          return statusLink;\n        }\n        return \'\';\n        ', compact_message, own_handle)
    return _normalize_x_status_url(result)

def _find_visible_button_by_markers(driver, markers: tuple[str, ...], *, require_enabled: bool=True):
    js = '\n    const markers = (arguments[0] || []).map((item) => String(item || \'\').toLowerCase());\n    const requireEnabled = !!arguments[1];\n    const normalize = (value) => (value || \'\').toLowerCase().replace(/\\s+/g, \' \').trim();\n    const isVisible = (el) => {\n      if (!el) return false;\n      const rect = el.getBoundingClientRect();\n      const style = window.getComputedStyle(el);\n      return rect.width > 0 && rect.height > 0 && style.visibility !== \'hidden\' && style.display !== \'none\';\n    };\n    const isEnabled = (el) => {\n      const disabled = el.disabled === true || el.getAttribute(\'disabled\') !== null || el.getAttribute(\'aria-disabled\') === \'true\';\n      return !disabled;\n    };\n    const candidates = [...document.querySelectorAll("button, a[role=\'link\'], div[role=\'button\'], [role=\'menuitem\']")];\n    for (const el of candidates) {\n      if (!isVisible(el)) continue;\n      if (requireEnabled && !isEnabled(el)) continue;\n      const childAria = [...el.querySelectorAll(\'[aria-label], [title]\')]\n        .map((node) => node.getAttribute(\'aria-label\') || node.getAttribute(\'title\') || \'\')\n        .filter(Boolean)\n        .join(\' \');\n      const text = normalize(el.innerText || el.textContent || el.getAttribute(\'aria-label\') || el.getAttribute(\'title\') || childAria || \'\');\n      if (!text) continue;\n      if (markers.some((marker) => marker && text.includes(marker))) return el;\n    }\n    return null;\n    '
    return driver.execute_script(js, list(markers), require_enabled)

def _extract_profile_url(handle_or_url: str) -> str:
    handle = _normalize_x_handle(handle_or_url)
    return f'https://x.com/{handle}' if handle else ''

def _build_submission_snapshot(driver, message: str) -> dict[str, Any]:
    message = (message or '').strip()
    return driver.execute_script('\n        const target = arguments[0] || \'\';\n        const normalize = (value) => (value || \'\')\n          .toLowerCase()\n          .replace(/[ı]/g, \'i\')\n          .replace(/[ğ]/g, \'g\')\n          .replace(/[ü]/g, \'u\')\n          .replace(/[ş]/g, \'s\')\n          .replace(/[ö]/g, \'o\')\n          .replace(/[ç]/g, \'c\')\n          .replace(/[^a-z0-9\\s#@/$.-]+/g, \' \')\n          .replace(/\\s+/g, \' \')\n          .trim();\n\n        const bodyText = document.body ? (document.body.innerText || \'\').trim() : \'\';\n        const composer = document.querySelector("[data-testid=\'tweetTextarea_0\'] [role=\'textbox\'], [data-testid=\'tweetTextarea_0\'][role=\'textbox\'], [data-testid=\'tweetTextarea_0\'][contenteditable=\'true\'], [data-testid=\'tweetTextarea_0\'], div[role=\'textbox\'][contenteditable=\'true\']");\n        const composerText = composer ? ((composer.innerText || composer.textContent || composer.value || \'\').trim()) : \'\';\n        const alertTexts = [...document.querySelectorAll(\'[role="alert"], [aria-live="assertive"], [data-testid*="toast"]\')]\n          .map((el) => (el.innerText || el.textContent || \'\').trim())\n          .filter(Boolean)\n          .slice(0, 8);\n        const submitEnabled = !!document.querySelector(\n          "[data-testid=\'tweetButton\']:not([aria-disabled=\'true\']):not([disabled]), [data-testid=\'tweetButtonInline\']:not([aria-disabled=\'true\']):not([disabled])"\n        );\n\n        return {\n          page_url: window.location.href,\n          title: document.title || \'\',\n          body_text: bodyText,\n          body_excerpt: bodyText.slice(0, 2000),\n          composer_present: !!composer,\n          composer_text: composerText,\n          submit_enabled: submitEnabled,\n          alert_texts: alertTexts,\n          target_visible: target ? normalize(bodyText).includes(normalize(target)) : false,\n        };\n        ', message)

def _assess_submission_snapshot(snapshot: dict[str, Any], message: str) -> dict[str, Any]:
    page_text = _normalize_compact(snapshot.get('body_text', ''))
    composer_text = _normalize_compact(snapshot.get('composer_text', ''))
    alerts = [_normalize_compact(item) for item in snapshot.get('alert_texts', []) if item]
    evidence: list[str] = []
    if any((marker in page_text for marker in _LOGIN_WALL_MARKERS)):
        return {'attempted': True, 'verified': False, 'verification_state': 'error', 'evidence': ['login_wall'], 'warning': '', 'error': 'X oturumu login duvarina dustu.'}
    if '/compose/post/schedule' in (snapshot.get('page_url', '') or ''):
        return {'attempted': True, 'verified': False, 'verification_state': 'error', 'evidence': ['schedule_screen'], 'warning': '', 'error': 'Post yerine X schedule ekrani acildi; otomasyon tekrar Post butonunu hedeflemeli.'}
    matched_alert = next((alert for alert in alerts if any((marker in alert for marker in _ERROR_ALERT_MARKERS))), '')
    if matched_alert:
        return {'attempted': True, 'verified': False, 'verification_state': 'error', 'evidence': ['error_alert', matched_alert[:180]], 'warning': '', 'error': matched_alert[:280] or 'X hata bildirimi algilandi.'}
    composer_cleared = not snapshot.get('composer_present') or not composer_text
    if composer_cleared:
        evidence.append('composer_cleared')
    if snapshot.get('target_visible'):
        evidence.append('target_visible')
    if composer_cleared and snapshot.get('target_visible'):
        return {'attempted': True, 'verified': True, 'verification_state': 'verified', 'evidence': evidence, 'warning': '', 'error': ''}
    warning_parts = []
    if not composer_cleared:
        warning_parts.append('composer_hala_dolu')
    if not snapshot.get('target_visible'):
        warning_parts.append('metin_domda_dogrulanamadi')
    return {'attempted': True, 'verified': False, 'verification_state': 'pending_verify', 'evidence': evidence, 'warning': ', '.join(warning_parts) or 'dogrulama_belirsiz', 'error': ''}

def _collect_x_articles(limit: int=20) -> list[dict[str, Any]]:
    driver = _get_driver()
    js_script = '\n    const results = [];\n    const articles = [...document.querySelectorAll(\'article[data-testid="tweet"]\')];\n\n    for (const [index, article] of articles.entries()) {\n        article.setAttribute(\'data-mimar-social-id\', String(index));\n\n        const statusLink = [...article.querySelectorAll(\'a[href*="/status/"]\')]\n            .map((a) => a.getAttribute(\'href\') || \'\')\n            .find((href) => /\\/status\\/\\d+/.test(href));\n\n        if (!statusLink) continue;\n\n        const textNode = article.querySelector(\'[data-testid="tweetText"]\');\n        const timeNode = article.querySelector(\'time\');\n        const userNameNode = article.querySelector(\'[data-testid="User-Name"]\');\n        const replyButton = article.querySelector(\'[data-testid="reply"]\');\n\n        const handleMatch = statusLink.match(/^\\/([^/]+)\\/status\\/(\\d+)/);\n        const handle = handleMatch ? handleMatch[1] : \'\';\n        const tweetId = handleMatch ? handleMatch[2] : \'\';\n\n        let displayName = \'\';\n        if (userNameNode) {\n            const spans = [...userNameNode.querySelectorAll(\'span\')].map((s) => (s.textContent || \'\').trim()).filter(Boolean);\n            displayName = spans[0] || \'\';\n        }\n\n        results.push({\n            article_index: index,\n            tweet_id: tweetId,\n            tweet_url: statusLink,\n            handle: handle,\n            display_name: displayName,\n            text: textNode ? (textNode.innerText || \'\').trim() : \'\',\n            article_text: (article.innerText || \'\').trim(),\n            time_text: timeNode ? (timeNode.getAttribute(\'datetime\') || timeNode.textContent || \'\').trim() : \'\',\n            reply_available: !!replyButton\n        });\n    }\n\n    return results;\n    '
    results = driver.execute_script(js_script)
    return results[:max(1, min(int(limit), 50))]

def _wait_for_x_articles(timeout: int=12):
    driver = _get_driver()
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-testid='tweet']")))

def _wait_for_x_content(timeout: int=12) -> str:
    driver = _get_driver()
    js = '\n    const bodyText = ((document.body && document.body.innerText) || \'\').trim();\n    if (document.querySelector("article[data-testid=\'tweet\']")) return \'articles\';\n    if (document.querySelector("[data-testid=\'primaryColumn\'], main[role=\'main\'], [aria-label*=\'Timeline\']")) return \'layout\';\n    if (bodyText.length > 120) return \'body\';\n    return \'\';\n    '
    try:
        return WebDriverWait(driver, timeout).until(lambda current_driver: current_driver.execute_script(js))
    except TimeoutException:
        return ''

def _describe_x_page(driver, *, readiness: str='') -> str:
    try:
        body_text = driver.execute_script("return ((document.body && document.body.innerText) || '').trim().slice(0, 280);")
    except Exception:
        body_text = ''
    return f'url={getattr(driver, 'current_url', '')!r}, title={getattr(driver, 'title', '')!r}, readiness={readiness or 'none'!r}, body_excerpt={_compact_text(body_text or '', 220)!r}'

def _ensure_x_compose_ready(timeout: int=15):
    driver = _get_driver()
    driver.get('https://x.com/compose/post')
    readiness = _wait_for_x_content(timeout=timeout)
    snapshot = _build_submission_snapshot(driver, '')
    page_text = _normalize_compact(snapshot.get('body_text', ''))
    if any((marker in page_text for marker in _LOGIN_WALL_MARKERS)):
        raise RuntimeError('X compose acilamadi: oturum login duvarina dustu. ' + _describe_x_page(driver, readiness=readiness))
    try:
        WebDriverWait(driver, timeout).until(lambda current_driver: _locate_x_composer(current_driver) is not None)
    except TimeoutException as exc:
        raise RuntimeError('X compose editoru bulunamadi. ' + _describe_x_page(driver, readiness=readiness)) from exc
    return driver

def _compact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {'tweet_id': entry.get('tweet_id', ''), 'tweet_url': _normalize_x_status_url(entry.get('tweet_url', '')), 'handle': entry.get('handle', ''), 'display_name': entry.get('display_name', ''), 'text': _compact_text(entry.get('text', ''), 220), 'time_text': entry.get('time_text', ''), 'reply_available': bool(entry.get('reply_available'))}

def snapshot_x_feed(source: str='home', limit: int=12, write_to_file: bool=True) -> dict[str, Any]:
    """
    X akışından küçük bir görünüm alır. Otomasyon görevleri bunu okuyup
    piyasa temasını anlamak ve tekrar etmeyen içerik seçmek için kullanabilir.

    Args:
        source: home, explore, notifications veya mevcut
        limit: En fazla okunacak post sayısı
        write_to_file: true ise kompakt snapshot dosyasını günceller
    """
    driver = _get_driver()
    normalized_source = (source or 'home').strip().lower()
    target_url = {'home': 'https://x.com/home', 'explore': 'https://x.com/explore', 'notifications': 'https://x.com/notifications', 'mentions': 'https://x.com/notifications/mentions'}.get(normalized_source, driver.current_url)
    if normalized_source != 'mevcut':
        driver.get(target_url)
        _wait_for_x_articles()
        time.sleep(1.2)
    entries = [_compact_entry(entry) for entry in _collect_x_articles(limit=limit)]
    payload = {'updated_at': _now(), 'source': normalized_source, 'page_url': driver.current_url, 'count': len(entries), 'items': entries}
    if write_to_file:
        _write_json(_FEED_SNAPSHOT_PATH, payload)
    return payload

def save_x_market_snapshot(source: str='home', limit: int=12) -> dict[str, Any]:
    """
    X akışındaki görünür postlardan küçük bir piyasa durumu ve fikir havuzu üretir.

    Args:
        source: home, explore, notifications veya mevcut
        limit: Örnek alınacak post sayısı
    """
    snapshot = snapshot_x_feed(source=source, limit=limit, write_to_file=True)
    summary = _build_market_files(snapshot.get('page_url', ''), snapshot.get('items', []))
    return {'snapshot_count': snapshot.get('count', 0), 'page_url': snapshot.get('page_url', ''), 'market_state_path': _MARKET_STATE_PATH, 'idea_pool_path': _IDEA_POOL_PATH, **summary}

def search_x_posts(query: str, tab: str='latest', limit: int=12, write_to_file: bool=False) -> dict[str, Any]:
    """
    X aramasinda guncel postlari toplar.

    Args:
        query: Aranacak ifade veya anahtar kelime
        tab: latest, top, people, media veya videos
        limit: En fazla kac post okunacagi
        write_to_file: true ise x_feed_snapshot.json dosyasina da yazar
    """
    query_text = (query or '').strip()
    if not query_text:
        raise ValueError('Arama sorgusu bos olamaz')
    url = _build_x_destination_url('search', query=query_text, tab=tab)
    driver = _wait_for_x_or_fail(url, expect_articles=True)
    entries = [_compact_entry(entry) for entry in _collect_x_articles(limit=limit)]
    payload = {'updated_at': _now(), 'source': 'search', 'tab': tab, 'query': query_text, 'page_url': driver.current_url, 'count': len(entries), 'items': entries}
    if write_to_file:
        _write_json(_FEED_SNAPSHOT_PATH, payload)
    return payload

def get_x_trends(limit: int=10) -> dict[str, Any]:
    """
    X Explore sayfasindaki gorunur trend basliklarini toplar.
    """
    limit = _coerce_limit(limit, default=10, minimum=1, maximum=30)
    driver = _wait_for_x_or_fail('https://x.com/explore', expect_articles=False)
    time.sleep(1.2)
    trends = driver.execute_script('\n        const normalize = (value) => (value || \'\').replace(/\\s+/g, \' \').trim();\n        const items = [];\n        const seen = new Set();\n        for (const link of document.querySelectorAll("a[href*=\'/search?q=\']")) {\n          const text = normalize(link.innerText || link.textContent || \'\');\n          const href = link.getAttribute(\'href\') || \'\';\n          if (!text || !href) continue;\n          const key = `${text}|${href}`;\n          if (seen.has(key)) continue;\n          seen.add(key);\n          items.push({ text, href });\n          if (items.length >= 30) break;\n        }\n        return items;\n        ') or []
    return {'updated_at': _now(), 'page_url': driver.current_url, 'count': min(len(trends), limit), 'items': trends[:limit]}

def inspect_x_profile(handle_or_url: str) -> dict[str, Any]:
    """
    X profilinin gorunur bio ve takipci baglamini ozetler.
    """
    profile_url = _extract_profile_url(handle_or_url)
    if not profile_url:
        raise ValueError("Gecerli bir X handle veya profil URL'si gir")
    driver = _wait_for_x_or_fail(profile_url, expect_articles=False)
    time.sleep(1.0)
    snapshot = _build_profile_snapshot(driver)
    return {'updated_at': _now(), 'profile_url': profile_url, **snapshot}

def inspect_x_post(tweet_url: str) -> dict[str, Any]:
    """
    Belirli bir X postunun gorunur durumunu, metnini ve etkileşim butonlarini ozetler.
    """
    target_url = _normalize_x_status_url(tweet_url)
    if not target_url:
        raise ValueError("Gecerli bir status URL'si gir")
    driver = _wait_for_x_or_fail(target_url, expect_articles=True)
    snapshot = _build_post_snapshot(driver)
    return {'updated_at': _now(), 'tweet_url': target_url, **snapshot}

def like_x_post(tweet_url: str) -> dict[str, Any]:
    """
    Bir X postunu begenir.
    """
    target_url = _normalize_x_status_url(tweet_url)
    if not target_url:
        raise ValueError("Gecerli bir status URL'si gir")
    driver = _wait_for_x_or_fail(target_url, expect_articles=True)
    already = _find_first_visible(driver, ("[data-testid='unlike']",), require_enabled=False)
    if already is not None:
        return {'status': 'already_liked', 'tweet_url': target_url, 'liked': True}
    button = WebDriverWait(driver, 12).until(lambda current_driver: _find_first_visible(current_driver, ("[data-testid='like']",), require_enabled=True))
    method = _click_element_with_fallback(driver, button, 'x_like')
    time.sleep(1.0)
    liked = _find_first_visible(driver, ("[data-testid='unlike']",), require_enabled=False) is not None
    return {'status': 'liked' if liked else 'pending_verify', 'tweet_url': target_url, 'liked': liked, 'action_method': method}

def bookmark_x_post(tweet_url: str) -> dict[str, Any]:
    """
    Bir X postunu yer isaretlerine ekler.
    """
    target_url = _normalize_x_status_url(tweet_url)
    if not target_url:
        raise ValueError("Gecerli bir status URL'si gir")
    driver = _wait_for_x_or_fail(target_url, expect_articles=True)
    already = _find_first_visible(driver, ("[data-testid='removeBookmark']",), require_enabled=False)
    if already is not None:
        return {'status': 'already_bookmarked', 'tweet_url': target_url, 'bookmarked': True}
    button = WebDriverWait(driver, 12).until(lambda current_driver: _find_first_visible(current_driver, ("[data-testid='bookmark']",), require_enabled=True))
    method = _click_element_with_fallback(driver, button, 'x_bookmark')
    time.sleep(1.0)
    bookmarked = _find_first_visible(driver, ("[data-testid='removeBookmark']",), require_enabled=False) is not None
    return {'status': 'bookmarked' if bookmarked else 'pending_verify', 'tweet_url': target_url, 'bookmarked': bookmarked, 'action_method': method}

def repost_x_post(tweet_url: str) -> dict[str, Any]:
    """
    Bir X postunu native repost olarak paylasir.
    """
    target_url = _normalize_x_status_url(tweet_url)
    if not target_url:
        raise ValueError("Gecerli bir status URL'si gir")
    driver = _wait_for_x_or_fail(target_url, expect_articles=True)
    already = _find_first_visible(driver, ("[data-testid='unretweet']",), require_enabled=False)
    if already is not None:
        return {'status': 'already_reposted', 'tweet_url': target_url, 'reposted': True}
    button = WebDriverWait(driver, 12).until(lambda current_driver: _find_first_visible(current_driver, ("[data-testid='retweet']",), require_enabled=True))
    method = _click_element_with_fallback(driver, button, 'x_repost_menu')
    confirm = WebDriverWait(driver, 12).until(lambda current_driver: _find_first_visible(current_driver, ("[data-testid='retweetConfirm']",), require_enabled=True))
    confirm_method = _click_element_with_fallback(driver, confirm, 'x_repost_confirm')
    time.sleep(1.0)
    reposted = _find_first_visible(driver, ("[data-testid='unretweet']",), require_enabled=False) is not None
    return {'status': 'reposted' if reposted else 'pending_verify', 'tweet_url': target_url, 'reposted': reposted, 'action_method': method, 'confirm_method': confirm_method}

def follow_x_account(handle_or_url: str) -> dict[str, Any]:
    """
    Bir X hesabini takip eder.
    """
    profile_url = _extract_profile_url(handle_or_url)
    if not profile_url:
        raise ValueError("Gecerli bir X handle veya profil URL'si gir")
    driver = _wait_for_x_or_fail(profile_url, expect_articles=False)
    time.sleep(1.0)
    already = _find_visible_button_by_markers(driver, _X_UNFOLLOW_MARKERS, require_enabled=False)
    if already is not None:
        return {'status': 'already_following', 'profile_url': profile_url, 'following': True}
    button = WebDriverWait(driver, 12).until(lambda current_driver: _find_visible_button_by_markers(current_driver, _X_FOLLOW_MARKERS, require_enabled=True))
    method = _click_element_with_fallback(driver, button, 'x_follow')
    time.sleep(1.0)
    following = _find_visible_button_by_markers(driver, _X_UNFOLLOW_MARKERS, require_enabled=False) is not None
    return {'status': 'followed' if following else 'pending_verify', 'profile_url': profile_url, 'following': following, 'action_method': method}

def quote_x_post(tweet_url: str, message: str) -> dict[str, Any]:
    """
    Bir X postunu alintili paylasim mantigiyla yeni post olarak gonderir.
    Native quote menu acilamazsa hedef URL'yi metne ekleyerek fallback yapar.
    """
    target_url = _normalize_x_status_url(tweet_url)
    quote_text = (message or '').strip()
    if not target_url:
        raise ValueError("Gecerli bir status URL'si gir")
    if not quote_text:
        raise ValueError('Quote metni bos olamaz')
    combined = f'{quote_text} {target_url}'.strip()
    if len(combined) > 240:
        raise ValueError('Quote metni hedef URL ile birlikte 240 karakteri gecemez')
    return publish_x_post(combined)

def engage_with_x_post(tweet_url: str, like: bool=True, bookmark: bool=True, repost: bool=False, follow_author: bool=False) -> dict[str, Any]:
    """
    Bir X postunda birden fazla etkileşim aksiyonunu tek seferde uygular.
    """
    target_url = _normalize_x_status_url(tweet_url)
    if not target_url:
        raise ValueError("Gecerli bir status URL'si gir")
    driver = _wait_for_x_or_fail(target_url, expect_articles=True)
    post_snapshot = _build_post_snapshot(driver)
    author_handle = ''
    match = re.search('/([^/]+)/status/\\d+', post_snapshot.get('tweet_url') or target_url)
    if match:
        author_handle = match.group(1)
    actions: dict[str, Any] = {'tweet_url': target_url}
    if like:
        actions['like'] = like_x_post(target_url)
    if bookmark:
        actions['bookmark'] = bookmark_x_post(target_url)
    if repost:
        actions['repost'] = repost_x_post(target_url)
    if follow_author and author_handle:
        actions['follow'] = follow_x_account(author_handle)
    return {'status': 'ok', 'tweet_url': target_url, 'author_handle': author_handle, 'actions': actions}

def scan_x_page(limit: int=20, filter_mode: str='generic') -> dict[str, Any]:
    driver = _get_driver()
    browser = get_browser_status()
    current_url = driver.current_url
    root_status_id = _extract_root_status_id(current_url)
    entries = _collect_x_articles(limit=limit)
    own_handle = _discover_current_x_handle(driver) if filter_mode == 'notifications' else ''
    queue = _load_queue()
    by_tweet_id = {item.get('platform_comment_id'): item for item in queue['items']}
    discovered = 0
    refreshed = 0
    skipped = 0
    ignored = 0
    for entry in entries:
        tweet_id = entry.get('tweet_id')
        if not tweet_id:
            continue
        if root_status_id and tweet_id == root_status_id:
            skipped += 1
            continue
        normalized_url = _normalize_x_status_url(entry.get('tweet_url', ''))
        existing = by_tweet_id.get(tweet_id)
        candidate_info = {'candidate_type': 'generic', 'confidence': 1.0, 'reason': 'genel_tarama'}
        if filter_mode == 'notifications':
            candidate_info = _classify_notification_candidate(entry, own_handle=own_handle, existing=existing)
            if candidate_info['candidate_type'] == 'ignore':
                ignored += 1
                continue
        payload = {'queue_id': f'x-{tweet_id}', 'platform': 'x', 'platform_comment_id': tweet_id, 'tweet_url': normalized_url, 'author_handle': entry.get('handle', ''), 'author_name': entry.get('display_name', ''), 'text': entry.get('text', ''), 'status': 'new', 'reply_available': bool(entry.get('reply_available')), 'page_url': current_url, 'discovered_at': _now(), 'updated_at': _now(), 'draft_reply': existing.get('draft_reply', '') if existing else '', 'sent_reply': existing.get('sent_reply', '') if existing else '', 'last_error': existing.get('last_error', '') if existing else '', 'time_label': entry.get('time_text', ''), 'candidate_type': candidate_info['candidate_type'], 'confidence': candidate_info['confidence'], 'candidate_reason': candidate_info['reason']}
        if existing:
            existing.update({'tweet_url': payload['tweet_url'], 'author_handle': payload['author_handle'], 'author_name': payload['author_name'], 'text': payload['text'], 'reply_available': payload['reply_available'], 'page_url': payload['page_url'], 'time_label': payload['time_label'], 'candidate_type': payload['candidate_type'], 'confidence': payload['confidence'], 'candidate_reason': payload['candidate_reason'], 'updated_at': _now()})
            refreshed += 1
        else:
            queue['items'].append(payload)
            by_tweet_id[tweet_id] = payload
            discovered += 1
    _save_queue(queue)
    queue_summary = get_x_queue().get('summary', {})
    return {'browser': browser, 'source_url': current_url, 'root_status_id': root_status_id, 'scanned_count': len(entries), 'new_items': discovered, 'refreshed_items': refreshed, 'skipped_items': skipped, 'ignored_items': ignored, 'filter_mode': filter_mode, 'own_handle': own_handle, 'queue_summary': queue_summary, 'queue': queue}

def scan_x_notifications(limit: int=20, mentions_only: bool=True) -> dict[str, Any]:
    """
    X bildirimlerini tarar ve reply kuyruğunu günceller.

    Args:
        limit: En fazla okunacak bildirim postu sayısı
        mentions_only: true ise mentions sekmesine gider
    """
    limit = _coerce_limit(limit, default=20, minimum=1, maximum=50)
    driver = _get_driver()
    target_url = 'https://x.com/notifications/mentions' if mentions_only else 'https://x.com/notifications'
    driver.get(target_url)
    readiness = _wait_for_x_content(timeout=15)
    if not readiness:
        current_url = getattr(driver, 'current_url', target_url)
        title = getattr(driver, 'title', '')
        return {'browser': get_browser_status(), 'source_url': current_url, 'notification_mode': 'mentions' if mentions_only else 'all', 'scanned_count': 0, 'new_items': 0, 'refreshed_items': 0, 'skipped_items': 0, 'ignored_items': 0, 'filter_mode': 'notifications', 'own_handle': '', 'queue_summary': get_x_queue().get('summary', {}), 'queue': _load_queue(), 'warning': f"Bildirim sayfasi hazir gorunmedi. title='{title}'"}
    time.sleep(1.0)
    try:
        result = scan_x_page(limit=limit, filter_mode='notifications')
    except Exception as exc:
        time.sleep(1.0)
        try:
            result = scan_x_page(limit=limit, filter_mode='notifications')
        except Exception as retry_exc:
            return {'browser': get_browser_status(), 'source_url': getattr(driver, 'current_url', target_url), 'notification_mode': 'mentions' if mentions_only else 'all', 'scanned_count': 0, 'new_items': 0, 'refreshed_items': 0, 'skipped_items': 0, 'ignored_items': 0, 'filter_mode': 'notifications', 'own_handle': '', 'queue_summary': get_x_queue().get('summary', {}), 'queue': _load_queue(), 'warning': f"Bildirim taramasi fallback'e dustu: {exc}", 'error': str(retry_exc)}
    result['notification_mode'] = 'mentions' if mentions_only else 'all'
    result['readiness'] = readiness
    return result

def _find_queue_item(queue_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    queue = _load_queue()
    for item in queue['items']:
        if item.get('queue_id') == queue_id:
            return (queue, item)
    raise KeyError(f'Queue item bulunamadı: {queue_id}')

def update_queue_item(queue_id: str, draft_reply: str | None=None, status: str | None=None, note: str | None=None) -> dict[str, Any]:
    queue, item = _find_queue_item(queue_id)
    if draft_reply is not None:
        item['draft_reply'] = draft_reply.strip()
    if status is not None:
        item['status'] = status
    if note is not None:
        item['note'] = note
    item['updated_at'] = _now()
    _save_queue(queue)
    return item

def _locate_x_composer(driver):
    js = "\n    const selectors = arguments[0] || [];\n    const isVisible = (el) => {\n      if (!el) return false;\n      const rect = el.getBoundingClientRect();\n      const style = window.getComputedStyle(el);\n      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';\n    };\n\n    for (const selector of selectors) {\n      for (const el of document.querySelectorAll(selector)) {\n        if (isVisible(el)) return el;\n      }\n    }\n    return null;\n    "
    return driver.execute_script(js, list(_X_COMPOSER_SELECTORS))

def _locate_x_submit(driver, require_enabled: bool=True):
    js = '\n    const selectors = arguments[0] || [];\n    const markers = (arguments[1] || []).map((item) => String(item || \'\').toLowerCase());\n    const excludeMarkers = (arguments[2] || []).map((item) => String(item || \'\').toLowerCase());\n    const requireEnabled = !!arguments[3];\n    const normalize = (value) => (value || \'\')\n      .toLowerCase()\n      .replace(/[ı]/g, \'i\')\n      .replace(/[ğ]/g, \'g\')\n      .replace(/[ü]/g, \'u\')\n      .replace(/[ş]/g, \'s\')\n      .replace(/[ö]/g, \'o\')\n      .replace(/[ç]/g, \'c\')\n      .replace(/\\s+/g, \' \')\n      .trim();\n    const isVisible = (el) => {\n      if (!el) return false;\n      const rect = el.getBoundingClientRect();\n      const style = window.getComputedStyle(el);\n      return rect.width > 0 && rect.height > 0 && style.visibility !== \'hidden\' && style.display !== \'none\';\n    };\n    const isEnabled = (el) => {\n      const disabled = el.disabled === true || el.getAttribute(\'disabled\') !== null || el.getAttribute(\'aria-disabled\') === \'true\';\n      return !disabled;\n    };\n    const textFor = (el) => {\n      const childLabels = [...el.querySelectorAll(\'[aria-label], [title]\')]\n        .map((node) => node.getAttribute(\'aria-label\') || node.getAttribute(\'title\') || \'\')\n        .filter(Boolean)\n        .join(\' \');\n      return normalize([el.innerText, el.textContent, el.getAttribute(\'aria-label\'), el.getAttribute(\'title\'), childLabels].filter(Boolean).join(\' \'));\n    };\n    const isExcluded = (text) => excludeMarkers.some((marker) => marker && text.includes(normalize(marker)));\n    const markerScore = (text) => {\n      let best = 999;\n      for (const markerRaw of markers) {\n        const marker = normalize(markerRaw);\n        if (!marker) continue;\n        if (text === marker) best = Math.min(best, 0);\n        else if (text.startsWith(marker + \' \') || text.endsWith(\' \' + marker)) best = Math.min(best, 1);\n        else if (text.includes(marker)) best = Math.min(best, 2);\n      }\n      return best;\n    };\n\n    for (const selector of selectors) {\n      for (const el of document.querySelectorAll(selector)) {\n        if (!isVisible(el)) continue;\n        if (requireEnabled && !isEnabled(el)) continue;\n        const text = textFor(el);\n        if (isExcluded(text)) continue;\n        return el;\n      }\n    }\n\n    const candidates = [...document.querySelectorAll("button, div[role=\'button\'], [role=\'button\']")]\n      .filter((el) => isVisible(el) && (!requireEnabled || isEnabled(el)))\n      .map((el) => ({el, text: textFor(el), rect: el.getBoundingClientRect()}))\n      .filter((item) => {\n        if (!item.text) return false;\n        if (isExcluded(item.text)) return false;\n        return markerScore(item.text) < 999;\n      })\n      .sort((a, b) => {\n        const scoreDelta = markerScore(a.text) - markerScore(b.text);\n        if (scoreDelta !== 0) return scoreDelta;\n        const bottomDelta = b.rect.bottom - a.rect.bottom;\n        if (Math.abs(bottomDelta) > 4) return bottomDelta;\n        return b.rect.right - a.rect.right;\n      });\n\n    return candidates.length ? candidates[0].el : null;\n    '
    return driver.execute_script(js, list(_X_SUBMIT_SELECTORS), list(_X_SUBMIT_TEXT_MARKERS), list(_X_SUBMIT_EXCLUDE_MARKERS), require_enabled)

def _locate_x_media_input(driver):
    js = "\n    const selectors = arguments[0] || [];\n    for (const selector of selectors) {\n      for (const el of document.querySelectorAll(selector)) {\n        if (el && (el.tagName || '').toLowerCase() === 'input' && (el.getAttribute('type') || '').toLowerCase() === 'file') {\n          return el;\n        }\n      }\n    }\n    return null;\n    "
    return driver.execute_script(js, list(_X_MEDIA_INPUT_SELECTORS))

def _read_x_media_attach_state(driver) -> dict[str, Any]:
    js = '\n    const selectors = arguments[0] || [];\n    const normalize = (value) => (value || \'\')\n      .toLowerCase()\n      .replace(/[ı]/g, \'i\')\n      .replace(/[ğ]/g, \'g\')\n      .replace(/[ü]/g, \'u\')\n      .replace(/[ş]/g, \'s\')\n      .replace(/[ö]/g, \'o\')\n      .replace(/[ç]/g, \'c\')\n      .replace(/\\s+/g, \' \')\n      .trim();\n    const isVisible = (el) => {\n      if (!el) return false;\n      const rect = el.getBoundingClientRect();\n      const style = window.getComputedStyle(el);\n      return rect.width > 0 && rect.height > 0 && style.visibility !== \'hidden\' && style.display !== \'none\';\n    };\n\n    let input = null;\n    for (const selector of selectors) {\n      for (const el of document.querySelectorAll(selector)) {\n        if (el && (el.tagName || \'\').toLowerCase() === \'input\' && (el.getAttribute(\'type\') || \'\').toLowerCase() === \'file\') {\n          input = el;\n          break;\n        }\n      }\n      if (input) break;\n    }\n\n    const visibleButtons = [...document.querySelectorAll("button, div[role=\'button\'], [role=\'button\']")]\n      .filter((el) => isVisible(el))\n      .map((el) => normalize([el.innerText, el.textContent, el.getAttribute(\'aria-label\'), el.getAttribute(\'title\')].filter(Boolean).join(\' \')))\n      .filter(Boolean);\n\n    const mediaButtons = visibleButtons.filter((text) =>\n      text.includes(\'remove media\') ||\n      text.includes(\'remove image\') ||\n      text.includes(\'remove\') ||\n      text.includes(\'medyayi kaldir\') ||\n      text.includes(\'gorseli kaldir\') ||\n      text.includes(\'gorsel kaldir\') ||\n      text.includes(\'alt\')\n    );\n\n    const composerRoot =\n      document.querySelector("[data-testid=\'tweetTextarea_0\']") ||\n      document.querySelector("main[role=\'main\']") ||\n      document.body;\n    const previewImages = composerRoot\n      ? [...composerRoot.querySelectorAll("img")].filter((img) => {\n          if (!isVisible(img)) return false;\n          const src = img.getAttribute(\'src\') || \'\';\n          const alt = normalize(img.getAttribute(\'alt\') || \'\');\n          if (src.startsWith(\'blob:\')) return true;\n          if (src.includes(\'pbs.twimg.com/media\')) return true;\n          if (alt.includes(\'image\') || alt.includes(\'gorsel\')) return true;\n          return false;\n        }).length\n      : 0;\n    const progressCount = document.querySelectorAll("[role=\'progressbar\']").length;\n    const fileCount = input && input.files ? input.files.length : 0;\n    const inputValue = input ? (input.value || \'\') : \'\';\n\n    return {\n      file_count: fileCount,\n      has_value: !!String(inputValue || \'\').trim(),\n      preview_images: previewImages,\n      progress_count: progressCount,\n      media_button_count: mediaButtons.length,\n      media_button_sample: mediaButtons.slice(0, 4),\n      accepted: fileCount > 0 || !!String(inputValue || \'\').trim() || previewImages > 0 || progressCount > 0 || mediaButtons.length > 0\n    };\n    '
    return driver.execute_script(js, list(_X_MEDIA_INPUT_SELECTORS))

def _close_x_schedule_if_open(driver) -> bool:
    current_url = getattr(driver, 'current_url', '') or ''
    if '/compose/post/schedule' not in current_url:
        return False
    closed = False
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.4)
        closed = '/compose/post/schedule' not in (getattr(driver, 'current_url', '') or '')
    except Exception:
        closed = False
    if not closed:
        try:
            close_button = driver.execute_script('\n                const normalize = (value) => (value || \'\').toLowerCase().replace(/\\s+/g, \' \').trim();\n                const isVisible = (el) => {\n                  if (!el) return false;\n                  const rect = el.getBoundingClientRect();\n                  const style = window.getComputedStyle(el);\n                  return rect.width > 0 && rect.height > 0 && style.visibility !== \'hidden\' && style.display !== \'none\';\n                };\n                const candidates = [...document.querySelectorAll("button, div[role=\'button\'], [role=\'button\']")];\n                return candidates.find((el) => {\n                  if (!isVisible(el)) return false;\n                  const text = normalize([el.innerText, el.textContent, el.getAttribute(\'aria-label\'), el.getAttribute(\'title\')].filter(Boolean).join(\' \'));\n                  return text === \'close\' || text === \'kapat\' || text === \'back\' || text === \'geri\';\n                }) || null;\n                ')
            if close_button is not None:
                _human_click(driver, close_button)
                time.sleep(0.5)
                closed = '/compose/post/schedule' not in (getattr(driver, 'current_url', '') or '')
        except Exception:
            closed = False
    if not closed:
        try:
            driver.back()
            time.sleep(0.8)
            closed = '/compose/post/schedule' not in (getattr(driver, 'current_url', '') or '')
        except Exception:
            closed = False
    return closed

def _type_into_x_composer(message: str):
    driver = _get_driver()
    wait = WebDriverWait(driver, 12)
    try:
        composer = wait.until(lambda current_driver: _locate_x_composer(current_driver))
    except TimeoutException as exc:
        readiness = _wait_for_x_content(timeout=3)
        raise RuntimeError('X compose alani bulunamadi. ' + _describe_x_page(driver, readiness=readiness)) from exc
    ActionChains(driver).move_to_element(composer).click().perform()
    method = ''
    if _contains_non_bmp(message):
        driver.execute_script("\n            const el = arguments[0];\n            const value = arguments[1];\n            const editable = (el.getAttribute('contenteditable') || '').toLowerCase();\n            el.focus();\n            if (editable && editable !== 'false') {\n              el.innerHTML = '';\n              el.textContent = value;\n            } else {\n              const prototype = Object.getPrototypeOf(el);\n              const descriptor = prototype ? Object.getOwnPropertyDescriptor(prototype, 'value') : null;\n              if (descriptor && descriptor.set) descriptor.set.call(el, value);\n              else el.value = value;\n            }\n            el.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, cancelable: true, data: value, inputType: 'insertText'}));\n            el.dispatchEvent(new InputEvent('input', {bubbles: true, data: value, inputType: 'insertText'}));\n            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'Unidentified'}));\n            el.dispatchEvent(new Event('change', {bubbles: true}));\n            ", composer, message)
        method = 'js_non_bmp'
    else:
        method = _type_into_element(driver, composer, message)
    current_value = _normalize_compact(_read_element_value(driver, composer))
    target_value = _normalize_compact(message)
    if target_value and target_value not in current_value:
        if _contains_non_bmp(message):
            driver.execute_script("\n                const el = arguments[0];\n                const value = arguments[1];\n                if (document.activeElement !== el) el.focus();\n                if (document.execCommand) {\n                  try {\n                    document.execCommand('selectAll', false, null);\n                  } catch (e) {}\n                  try {\n                    document.execCommand('insertText', false, value);\n                  } catch (e) {}\n                }\n                el.dispatchEvent(new Event('input', {bubbles: true}));\n                el.dispatchEvent(new Event('change', {bubbles: true}));\n                ", composer, message)
            current_value = _normalize_compact(_read_element_value(driver, composer))
            if target_value and target_value in current_value:
                return 'execcommand_non_bmp'
        raise RuntimeError('X compose alanina metin yazildi ama dogrulanamadi.')
    return (composer, method)

def _attach_media_to_x_composer(media_path: str) -> dict[str, Any]:
    driver = _get_driver()
    abs_path = os.path.abspath(str(media_path or '').strip())
    if not abs_path:
        raise ValueError('Medya dosya yolu boş olamaz')
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f'Medya dosyası bulunamadı: {abs_path}')
    wait = WebDriverWait(driver, 15)
    try:
        media_input = wait.until(lambda current_driver: _locate_x_media_input(current_driver))
    except TimeoutException as exc:
        readiness = _wait_for_x_content(timeout=3)
        raise RuntimeError("X medya yukleme input'u bulunamadi. " + _describe_x_page(driver, readiness=readiness)) from exc
    media_input.send_keys(abs_path)

    def _media_selected(current_driver):
        state = _read_x_media_attach_state(current_driver)
        return state if state.get('accepted') else False
    try:
        media_state = wait.until(_media_selected)
    except TimeoutException as exc:
        state = _read_x_media_attach_state(driver)
        raise RuntimeError('Medya dosyasi secildi ama X yukleme durumunu dogrulayamadim. ' + _describe_x_page(driver, readiness='compose') + f', media_state={state!r}') from exc
    time.sleep(2.0)
    return {'media_path': abs_path, 'media_name': os.path.basename(abs_path), 'media_state': media_state}

def _submit_x_composer():
    driver = _get_driver()
    _close_x_schedule_if_open(driver)
    wait = WebDriverWait(driver, 12)
    submit = wait.until(lambda current_driver: _locate_x_submit(current_driver, require_enabled=True))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", submit)
    time.sleep(0.2)
    submit_method = ''
    last_error = None
    click_strategies = (('human_click', lambda: _human_click(driver, submit)), ('native_click', lambda: submit.click()), ('js_click', lambda: driver.execute_script('arguments[0].click();', submit)), ('pointer_mouse_js', lambda: driver.execute_script("\n                const el = arguments[0];\n                el.focus && el.focus();\n                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {\n                  const EventCtor = type.startsWith('pointer') ? PointerEvent : MouseEvent;\n                  el.dispatchEvent(new EventCtor(type, {bubbles: true, cancelable: true, view: window, pointerId: 1, button: 0}));\n                }\n                ", submit)))
    for name, strategy in click_strategies:
        try:
            strategy()
            time.sleep(0.8)
            if '/compose/post/schedule' in (getattr(driver, 'current_url', '') or ''):
                _close_x_schedule_if_open(driver)
                last_error = RuntimeError(f'{name} schedule ekranini acti; Post butonu degil schedule hedefi tiklanmis olabilir.')
                submit = wait.until(lambda current_driver: _locate_x_submit(current_driver, require_enabled=True))
                continue
            status_or_alert = driver.execute_script('\n                const alerts = [...document.querySelectorAll(\'[role="alert"], [aria-live="assertive"], [data-testid*="toast"]\')]\n                  .map((el) => (el.innerText || el.textContent || \'\').trim())\n                  .filter(Boolean);\n                const url = window.location.href || \'\';\n                return /\\/status\\/\\d+/.test(url) || alerts.length > 0;\n                ')
            composer_after_click = _locate_x_composer(driver)
            submit_after_click = _locate_x_submit(driver, require_enabled=True)
            took_effect = bool(status_or_alert or composer_after_click is None or submit_after_click is None)
            if took_effect:
                submit_method = name
                break
            last_error = RuntimeError(f"{name} tıklaması DOM'da gönderim etkisi oluşturmadı.")
        except Exception as exc:
            last_error = exc
    if not submit_method:
        composer = _locate_x_composer(driver)
        if composer is not None:
            try:
                ActionChains(driver).move_to_element(composer).click().key_down(Keys.CONTROL).send_keys(Keys.ENTER).key_up(Keys.CONTROL).perform()
                submit_method = 'ctrl_enter'
            except Exception as exc:
                last_error = exc
    if not submit_method:
        raise last_error or RuntimeError('X gonder butonuna basılamadı.')
    time.sleep(1.2)
    _close_x_schedule_if_open(driver)
    return {'url': driver.current_url, 'title': driver.title, 'submit_method': submit_method}

def _verify_x_submission(message: str, *, prefer_current_url: bool=True) -> dict[str, Any]:
    driver = _get_driver()
    last_verification: dict[str, Any] = {'attempted': True, 'verified': False, 'verification_state': 'pending_verify', 'evidence': [], 'warning': 'dogrulama_bekleniyor', 'error': ''}
    for attempt in range(5):
        time.sleep(1.2 if attempt == 0 else 0.9)
        snapshot = _build_submission_snapshot(driver, message)
        verification = _assess_submission_snapshot(snapshot, message)
        verification['snapshot_url'] = snapshot.get('page_url', '')
        verification['snapshot_title'] = snapshot.get('title', '')
        verification['snapshot_excerpt'] = _compact_text(snapshot.get('body_excerpt', ''), 240)
        evidence = list(verification.get('evidence') or [])
        composer_cleared = 'composer_cleared' in evidence
        if not verification.get('verified') and verification.get('verification_state') == 'pending_verify' and composer_cleared:
            resolved_url = _resolve_recent_status_url(driver, message, prefer_current_url=prefer_current_url)
            if resolved_url:
                if 'resolved_status_url' not in evidence:
                    evidence.append('resolved_status_url')
                verification.update({'verified': True, 'verification_state': 'verified', 'evidence': evidence, 'warning': '', 'error': '', 'resolved_tweet_url': resolved_url})
        last_verification = verification
        if verification.get('verified') or verification.get('verification_state') == 'error':
            return verification
    return last_verification

def _parse_thread_parts(thread_parts: str) -> list[str]:
    raw = str(thread_parts or '').strip()
    if not raw:
        return []
    if re.search('(?m)^\\s*---+\\s*$', raw):
        parts = [part.strip() for part in re.split('(?m)^\\s*---+\\s*$', raw)]
    else:
        parts = [part.strip() for part in raw.split('\n\n') if part.strip()]
    return [part for part in parts if part]

def publish_x_post(text: str) -> dict[str, Any]:
    """
    X üzerinde yeni bir post yayınlar.

    Args:
        text: Yayınlanacak metin. 240 karakteri geçmemesi önerilir.
    """
    message = (text or '').strip()
    if not message:
        raise ValueError('Post metni boş olamaz')
    if len(message) > 240:
        raise ValueError('Post metni 240 karakteri geçemez')
    driver = _ensure_x_compose_ready()
    _composer, type_method = _type_into_x_composer(message)
    result = _submit_x_composer()
    verification = _verify_x_submission(message, prefer_current_url=True)
    resolved_tweet_url = verification.get('resolved_tweet_url') or (_resolve_recent_status_url(driver, message, prefer_current_url=True) if verification.get('verified') else '')
    return {'status': 'posted' if verification['verified'] else verification['verification_state'], 'length': len(message), 'text': message, 'type_method': type_method, 'resolved_tweet_url': resolved_tweet_url, **verification, **result}

def publish_x_post_with_media(text: str, media_path: str) -> dict[str, Any]:
    """
    X üzerinde görselli yeni bir post icin draft/composer hazirlar.
    Son Post tusuna basmaz; bu adim agent tarafinda `submit_current_x_composer`
    ile ayri yonetilmelidir.

    Args:
        text: Yayınlanacak metin. 240 karakteri geçmemesi önerilir.
        media_path: Yüklenecek görselin yerel dosya yolu.
    """
    message = (text or '').strip()
    if not message:
        raise ValueError('Post metni boş olamaz')
    if len(message) > 240:
        raise ValueError('Post metni 240 karakteri geçemez')
    driver = _ensure_x_compose_ready()
    _composer, type_method = _type_into_x_composer(message)
    media_result = _attach_media_to_x_composer(media_path)
    return {'status': 'draft_ready', 'length': len(message), 'text': message, 'type_method': type_method, 'composer_url': driver.current_url, 'composer_title': driver.title, **media_result}

def submit_current_x_composer() -> dict[str, Any]:
    """
    X'te halihazırda açık olan compose/draft ekranındaki aktif Post/Reply butonuna basar.
    Metin ve medya zaten eklenmiş ama otomasyon son tuşa basamamışsa kurtarma aracı olarak kullan.
    Bu araç sadece submit dener; doğrulama ve tweet URL çözme agent tarafından ayrı yapılmalıdır.
    """
    driver = _get_driver()
    composer = _locate_x_composer(driver)
    if composer is None:
        raise RuntimeError('Açık X composer alanı bulunamadı.')
    message = (_read_element_value(driver, composer) or '').strip()
    result = _submit_x_composer()
    return {'status': 'submitted', 'text': message, 'length': len(message), **result}

def verify_current_x_submission(expected_text: str='', prefer_current_url: bool=True) -> dict[str, Any]:
    """
    Son X submit denemesinin gercekten gidip gitmedigini dogrular.

    Args:
        expected_text: Beklenen post/reply metni. Bos ise mevcut composer metni okunmaya calisilir.
        prefer_current_url: true ise mevcut sayfa URL'si oncelikli kanit olarak kullanilir.
    """
    driver = _get_driver()
    message = (expected_text or '').strip()
    if not message:
        composer = _locate_x_composer(driver)
        if composer is not None:
            message = (_read_element_value(driver, composer) or '').strip()
    if not message:
        return {'attempted': True, 'verified': False, 'verification_state': 'pending_verify', 'evidence': ['empty_or_unreadable_composer_text'], 'warning': 'Beklenen metin okunamadigi icin dogrulama sinirli.', 'error': ''}
    verification = _verify_x_submission(message, prefer_current_url=prefer_current_url)
    verification['expected_text'] = message
    return verification

def resolve_recent_x_status_url(expected_text: str='', prefer_current_url: bool=True) -> dict[str, Any]:
    """
    Son gonderilen X post/reply icin status URL'sini ayri olarak cozmeye calisir.

    Args:
        expected_text: Beklenen post/reply metni. Bos ise mevcut composer metni okunmaya calisilir.
        prefer_current_url: true ise mevcut URL status pattern tasiyorsa once onu dener.
    """
    driver = _get_driver()
    message = (expected_text or '').strip()
    if not message:
        composer = _locate_x_composer(driver)
        if composer is not None:
            message = (_read_element_value(driver, composer) or '').strip()
    resolved_url = _resolve_recent_status_url(driver, message, prefer_current_url=prefer_current_url)
    return {'status': 'resolved' if resolved_url else 'not_found', 'expected_text': message, 'resolved_tweet_url': resolved_url, 'current_url': driver.current_url, 'title': driver.title}

def reply_to_x_post(tweet_url: str, message: str) -> dict[str, Any]:
    """
    Belirli bir X postuna reply yollar.

    Args:
        tweet_url: Hedef post URL'si
        message: Reply metni
    """
    target_url = _normalize_x_status_url(tweet_url)
    reply_text = (message or '').strip()
    if not target_url:
        raise ValueError('Tweet URL boş olamaz')
    if not reply_text:
        raise ValueError('Reply metni boş olamaz')
    if len(reply_text) > 240:
        raise ValueError('Reply metni 240 karakteri geçemez')
    driver = _get_driver()
    driver.get(target_url)
    wait = WebDriverWait(driver, 12)
    reply_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='reply']")))
    _human_click(driver, reply_button)
    _composer, type_method = _type_into_x_composer(reply_text)
    result = _submit_x_composer()
    verification = _verify_x_submission(reply_text, prefer_current_url=False)
    resolved_tweet_url = verification.get('resolved_tweet_url') or (_resolve_recent_status_url(driver, reply_text, prefer_current_url=False) if verification.get('verified') else '')
    return {'status': 'sent' if verification['verified'] else verification['verification_state'], 'tweet_url': target_url, 'length': len(reply_text), 'text': reply_text, 'type_method': type_method, 'resolved_tweet_url': resolved_tweet_url, **verification, **result}

def publish_x_thread(thread_parts: str) -> dict[str, Any]:
    """
    Birden fazla parcayi art arda gondererek X thread olusturur.

    Args:
        thread_parts: Parcalari `---` satiri ile ayir. Her parca 240 karakteri gecmemeli.
    """
    parts = _parse_thread_parts(thread_parts)
    if len(parts) < 2:
        raise ValueError('Thread icin en az 2 parca gerekli. Parcalari `---` ile ayir.')
    results: list[dict[str, Any]] = []
    first = publish_x_post(parts[0])
    results.append(first)
    parent_url = first.get('resolved_tweet_url') or first.get('tweet_url') or ''
    if not first.get('verified') or not parent_url:
        return {'status': 'stopped_after_first_part', 'sent_count': 1 if first.get('verified') else 0, 'results': results, 'error': 'Ilk thread parcasi dogrulanamadi veya status URL cozulmedi.'}
    for index, part in enumerate(parts[1:], start=2):
        reply_result = reply_to_x_post(parent_url, part)
        reply_result['thread_index'] = index
        results.append(reply_result)
        if not reply_result.get('verified'):
            return {'status': 'partial', 'sent_count': sum((1 for item in results if item.get('verified'))), 'results': results, 'error': f'{index}. parca dogrulanamadi.'}
        parent_url = reply_result.get('resolved_tweet_url') or parent_url
    return {'status': 'posted', 'sent_count': len(results), 'results': results, 'root_tweet_url': first.get('resolved_tweet_url') or parent_url}

def send_x_reply(queue_id: str, message: str | None=None) -> dict[str, Any]:
    queue, item = _find_queue_item(queue_id)
    reply_text = (message or item.get('draft_reply') or '').strip()
    if not reply_text:
        raise ValueError('Gönderilecek reply metni boş olamaz')
    tweet_url = item.get('tweet_url')
    tweet_id = item.get('platform_comment_id')
    if not tweet_url or not tweet_id:
        raise ValueError('Tweet URL veya tweet ID eksik')
    result = reply_to_x_post(tweet_url, reply_text)
    verification_state = result.get('verification_state', 'pending_verify')
    item['status'] = 'sent' if result.get('verified') else verification_state
    item['sent_reply'] = reply_text if result.get('verified') else ''
    item['last_error'] = result.get('error', '') or result.get('warning', '')
    item['verification_state'] = verification_state
    item['verification_warning'] = result.get('warning', '')
    item['verification_evidence'] = result.get('evidence', [])
    item['updated_at'] = _now()
    _save_queue(queue)
    return {**item, 'result': result}

def mark_queue_item(queue_id: str, status: str, note: str='') -> dict[str, Any]:
    normalized = _normalize_compact(status)
    aliases = {'completed': 'sent', 'complete': 'sent', 'done': 'sent', 'gonderildi': 'sent', 'draft': 'drafted', 'taslak': 'drafted', 'ignore': 'skipped', 'ignored': 'skipped', 'gec': 'skipped', 'skip': 'skipped', 'verify': 'pending_verify'}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {'new', 'drafted', 'approved', 'pending_verify', 'sent', 'skipped', 'error'}:
        raise ValueError(f'Geçersiz status: {status}')
    return update_queue_item(queue_id, status=normalized, note=note)

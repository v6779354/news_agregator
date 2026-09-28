import ipaddress
import re
import socket
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode
import feedparser
import httpx

class FeedError(ValueError):
    pass

def public_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise FeedError('Введите публичный адрес сайта или RSS с https://')
    try:
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80))
        if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise FeedError('Разрешены только публичные адреса источников.')
    except (OSError, ValueError) as exc:
        raise FeedError('Не удалось проверить адрес источника.') from exc
    return url

def fetch(url):
    try:
        with httpx.Client(timeout=15, transport=httpx.HTTPTransport(retries=2), headers={'User-Agent': 'PulseNewsAggregator/1.0'}) as client:
            for _ in range(6):
                public_url(url)
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers['location'])
                        continue
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 4_000_000:
                            raise FeedError('Лента превышает лимит 4 МБ.')
                    return bytes(data), str(response.url)
        raise FeedError('Слишком много перенаправлений.')
    except httpx.HTTPError as exc:
        raise FeedError('Источник недоступен или вернул ошибку HTTP.') from exc

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and 'alternate' in a.get('rel', '').split() and a.get('type') in ('application/rss+xml', 'application/atom+xml') and a.get('href'):
            self.urls.append(a['href'])

class Plain(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def clean(value):
    p = Plain(); p.feed(value or '')
    return re.sub(r'\s+', ' ', unescape(' '.join(p.parts))).strip()

def normalize_url(url):
    p = urlsplit(url)
    query = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(query), ''))

def parse(data, base):
    feed = feedparser.parse(data)
    if not feed.version:
        raise FeedError('RSS/Atom не найдена. Укажите прямую ссылку на ленту. Проверьте адрес источника.')
    items = []
    for entry in feed.entries[:200]:
        title = clean(entry.get('title', ''))[:500]
        link = urljoin(base, entry.get('link', ''))
        if not title or not entry.get('link') or urlsplit(link).scheme not in ('http','https'):
            continue
        stamp = entry.get('published_parsed') or entry.get('updated_parsed')
        created = datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else datetime.now(timezone.utc)
        items.append(dict(title=title, url=normalize_url(link), description=clean(entry.get('summary',''))[:1500], created_at=created.isoformat(), title_key=' '.join(title.casefold().split())))
    return clean(feed.feed.get('title','')) or urlsplit(base).hostname, items

def discover(url):
    from collectors.telegram import channel_url, parse as parse_telegram
    telegram = channel_url(url)
    if telegram:
        data, final = fetch(telegram)
        name, items = parse_telegram(data, final)
        return telegram, name, items
    data, final = fetch(url.strip())
    try:
        name, items = parse(data, final)
        return final, name, items
    except FeedError:
        parser = Links(); parser.feed(data.decode('utf-8', errors='replace'))
        for link in parser.urls[:5]:
            try:
                body, rss_url = fetch(urljoin(final, link))
                name, items = parse(body, rss_url)
                return rss_url, name, items
            except FeedError:
                continue
        raise FeedError('RSS не найдена. Вставьте ссылку на RSS/Atom или публичный Telegram-канал.')

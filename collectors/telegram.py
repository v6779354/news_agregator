"""Read recent posts from public Telegram channel previews (no account required)."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from collectors.rss import FeedError

HOSTS = {'t.me', 'www.t.me', 'telegram.me', 'www.telegram.me'}

def channel_url(value):
    value = value.strip()
    if value.startswith('@'):
        value = 'https://t.me/' + value[1:]
    elif value.lower().startswith(('t.me/', 'telegram.me/')):
        value = 'https://' + value
    p = urlsplit(value)
    if p.hostname not in HOSTS:
        return None
    if p.scheme not in ('http', 'https') or p.username or p.password or p.port:
        raise FeedError('Укажите ссылку вида https://t.me/channel_name.')
    parts = p.path.strip('/').split('/')
    if parts[0] == 's':
        parts = parts[1:]
    if not parts or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', parts[0]) or parts[0].lower() in {'joinchat','share','proxy','socks','addstickers','addemoji','c'}:
        raise FeedError('Нужен публичный канал вида https://t.me/channel_name. Закрытые каналы и приглашения не поддерживаются.')
    if len(parts) > 2 or (len(parts) == 2 and not parts[1].isdigit()):
        raise FeedError('Укажите ссылку на публичный канал или его публикацию.')
    return 'https://t.me/s/' + parts[0].lower()


def parse(data, base):
    canonical = channel_url(base)
    if not canonical:
        raise FeedError('Не удалось открыть публичную страницу Telegram-канала.')
    username = canonical.rsplit('/', 1)[-1]
    soup = BeautifulSoup(data, 'html.parser')
    heading = soup.select_one('.tgme_channel_info_header_title')
    messages = soup.select('.tgme_widget_message[data-post]')
    if not heading or not messages:
        raise FeedError('Публичные публикации недоступны: канал закрыт, пуст или не поддерживает веб-просмотр Telegram.')
    name = heading.get_text(' ', strip=True) or '@' + username
    items = []
    seen = set()
    for message in messages:
        post = message.get('data-post', '')
        match = re.fullmatch(r'([A-Za-z0-9_]+)/(\d+)', post)
        if not match or match[1].lower() != username or post in seen:
            continue
        seen.add(post)
        body = message.select_one('.tgme_widget_message_text')
        # Media-only and inaccessible posts have no useful news text.
        if body is None:
            continue
        text = ' '.join(body.get_text(' ', strip=True).split())
        if not text:
            continue
        stamp = message.select_one('.tgme_widget_message_date time[datetime]')
        if stamp is None:
            continue
        try:
            created = datetime.fromisoformat(stamp['datetime'].replace('Z', '+00:00'))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        title = text[:180] + ('…' if len(text) > 180 else '')
        items.append(dict(title=title, url=f'https://t.me/{username}/{match[2]}',
                          description=text[:1500], created_at=created.astimezone(timezone.utc).isoformat(),
                          # Distinct posts may share their opening line; deduplicate by post ID.
                          title_key=f'telegram:{username}/{match[2]}'))
    if not items:
        raise FeedError('В публичном просмотре канала нет доступных текстовых публикаций. Посты только с медиа пропускаются.')
    return name, items

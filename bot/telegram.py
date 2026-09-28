import logging
from threading import Lock
import httpx
import config
from database import rows, connect

log = logging.getLogger(__name__)
lock = Lock()

def api(method, payload):
    try:
        response = httpx.post(f'https://api.telegram.org/bot{config.TOKEN}/{method}', json=payload, timeout=20)
        data = response.json()
        if not response.is_success or not data.get('ok'):
            raise RuntimeError('Telegram отклонил запрос. Проверьте токен и ID чата.')
        return data['result']
    except (httpx.HTTPError, ValueError):
        raise RuntimeError('Не удалось связаться с Telegram.') from None

def send_digest():
    if not config.TOKEN or not config.CHAT_ID:
        raise ValueError('Укажите TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env и перезапустите сервис.')
    with lock:
        items = rows('SELECT * FROM items WHERE sent_at IS NULL ORDER BY id LIMIT 30')
        if not items:
            return {'sent': 0}
        batches = []
        text, ids = '📰 Пульс · Новые материалы\n\n', []
        for number, item in enumerate(items, 1):
            part = f"{number}. {item['title'][:250]}\n{item['source'][:120]} · {item['description'][:200]}\n{item['url'][:1200]}\n\n"
            # Telegram measures its limit in UTF-16 code units.
            if len((text + part).encode('utf-16-le')) // 2 > 3900 and ids:
                batches.append((text, ids))
                text, ids = '📰 Пульс · Продолжение\n\n', []
            text += part
            ids.append(item['id'])
        if ids:
            batches.append((text, ids))
        sent = 0
        for text, ids in batches:
            api('sendMessage', {'chat_id': config.CHAT_ID, 'text': text, 'link_preview_options': {'is_disabled': True}})
            with connect() as db:
                db.executemany("UPDATE items SET sent_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", [(item_id,) for item_id in ids])
            sent += len(ids)
        return {'sent': sent}

def scheduled_digest():
    if config.TOKEN and config.CHAT_ID:
        try:
            send_digest()
        except Exception as exc:
            log.warning('Digest: %s', exc)

def poll():
    if not config.TOKEN or not config.CHAT_ID:
        return
    try:
        state = rows("SELECT value FROM settings WHERE key='telegram_offset'")
        updates = api('getUpdates', {'offset': int(state[0]['value']) if state else 0, 'timeout': 0, 'allowed_updates': ['message']})
        for update in updates:
            msg = update.get('message', {})
            if str(msg.get('chat', {}).get('id')) == config.CHAT_ID and msg.get('text', '').split('@')[0].strip() == '/digest':
                result = send_digest()
                if not result['sent']:
                    api('sendMessage', {'chat_id':config.CHAT_ID, 'text':'Новых материалов пока нет.'})
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('telegram_offset',?)", (str(update['update_id']+1),))
    except Exception as exc:
        log.warning('Telegram polling: %s', exc)

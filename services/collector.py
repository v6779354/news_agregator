import logging
from datetime import datetime, timezone
from threading import Lock
from collectors.rss import fetch, parse
from database import connect, rows
from collectors.telegram import channel_url, parse as parse_telegram

log = logging.getLogger(__name__)
lock = Lock()

def collect():
    if not lock.acquire(blocking=False):
        return {'added': 0, 'errors': 0, 'busy': True}
    added = errors = 0
    try:
        for source in rows('SELECT * FROM sources WHERE enabled=1'):
            now = datetime.now(timezone.utc).isoformat()
            try:
                data, url = fetch(source['url'])
                _, items = (parse_telegram(data, url) if channel_url(source["url"]) else parse(data, url))
                count = 0
                with connect() as db:
                    # A source can be removed while its request is in progress.
                    if not db.execute('SELECT 1 FROM sources WHERE id=? AND enabled=1', (source['id'],)).fetchone():
                        continue
                    for item in items:
                        cur = db.execute('''INSERT OR IGNORE INTO items
                            (title,url,source,source_id,description,created_at,title_key) VALUES (?,?,?,?,?,?,?)''',
                            (item['title'], item['url'], source['name'], source['id'], item['description'], item['created_at'], item['title_key']))
                        count += cur.rowcount
                    db.execute('UPDATE sources SET last_checked=?,last_success=?,error=NULL WHERE id=?', (now,now,source['id']))
                added += count
                log.info('source=%s received=%s added=%s', source['name'], len(items), count)
            except Exception as exc:
                errors += 1
                with connect() as db:
                    db.execute('UPDATE sources SET last_checked=?,error=? WHERE id=?', (now,str(exc)[:300],source['id']))
                log.warning('source=%s error=%s', source['name'], exc)
        log.info('Collection complete: added=%s errors=%s', added, errors)
        return {'added': added, 'errors': errors, 'busy': False}
    finally:
        lock.release()

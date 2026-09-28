import pytest
from fastapi.testclient import TestClient
import config
from database import init, rows, connect
from collectors.rss import parse, normalize_url, FeedError, public_url
from services import collector
from bot import telegram
from main import app

RSS=b'''<rss version="2.0"><channel><title>Test</title><item><title>Hello world</title><link>https://example.com/a?utm_source=x</link><description>&lt;p&gt;Some news&lt;/p&gt;</description></item></channel></rss>'''

@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'DATABASE_PATH',str(tmp_path/'test.sqlite'))
    init()
    class Scheduler:
        def shutdown(self, **kwargs): pass
    monkeypatch.setattr("main.start", lambda: Scheduler())


def test_dedup_and_failure_isolation(monkeypatch):
    def fetch(url):
        if 'habr' in url: raise FeedError('Offline')
        return RSS,url
    monkeypatch.setattr(collector,'fetch',fetch)
    assert collector.collect()=={'added':1,'errors':1,'busy':False}
    assert collector.collect()['added']==0
    assert len(rows('SELECT * FROM items'))==1
    assert rows('SELECT * FROM sources')[0]['error']=='Offline'


def test_url_and_title_dedup(monkeypatch):
    monkeypatch.setattr(collector,'fetch',lambda url:(RSS,url))
    collector.collect()
    changed=RSS.replace(b'utm_source=x',b'other=1')
    monkeypatch.setattr(collector,'fetch',lambda url:(changed,url))
    collector.collect()
    collector.collect()
    assert len(rows('SELECT * FROM items'))==2


def test_parse_and_invalid():
    _,items=parse(RSS,'https://example.com')
    assert items[0]['description']=='Some news'
    assert items[0]['url']=='https://example.com/a'
    with pytest.raises(FeedError): parse(b'<html>not rss</html>','https://example.com')
    with pytest.raises(FeedError): public_url('http://127.0.0.1/feed')


def test_source_api(monkeypatch):
    monkeypatch.setattr('main.discover',lambda url:('https://example.com/rss','Example',[]))
    with TestClient(app,raise_server_exceptions=True) as client:
        r=client.post('/api/sources',json={'url':'https://example.com/rss'})
        assert r.status_code==201
        source_id=r.json()['id']
        assert client.post('/api/sources',json={'url':'https://example.com/rss'}).status_code==409
        assert len(client.get('/api/sources?q=Example').json())==1
        assert client.patch(f'/api/sources/{source_id}',json={'enabled':False}).status_code==200
        assert client.delete(f'/api/sources/{source_id}').status_code==200
        assert client.get('/settings').status_code==200
        assert client.post('/api/collect',headers={'origin':'https://evil.example'}).status_code==403


def test_digest_checkpoints(monkeypatch):
    monkeypatch.setattr(collector,'fetch',lambda url:(RSS,url))
    collector.collect()
    monkeypatch.setattr(config,'TOKEN','test')
    monkeypatch.setattr(config,'CHAT_ID','123')
    monkeypatch.setattr(telegram,'api',lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    with pytest.raises(RuntimeError): telegram.send_digest()
    assert rows('SELECT * FROM items')[0]['sent_at'] is None
    monkeypatch.setattr(telegram,'api',lambda *args: {})
    assert telegram.send_digest()['sent']==1
    assert telegram.send_digest()['sent']==0


def test_russian_search():
    with TestClient(app) as client:
        assert len(client.get('/api/sources?q=хабр').json())==1


def test_discovery(monkeypatch):
    from collectors import rss
    calls=[]
    def fetch(url):
        calls.append(url)
        return (b'<html><link rel="alternate" type="application/rss+xml" href="/feed"></html>' if len(calls)==1 else RSS),url
    monkeypatch.setattr(rss,'fetch',fetch)
    url,name,items=rss.discover('https://example.com')
    assert url=='https://example.com/feed'
    assert len(items)==1


def test_schedule(monkeypatch):
    import scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    monkeypatch.setattr(BackgroundScheduler,'start',lambda self:None)
    scheduled=scheduler.start()
    assert {job.id for job in scheduled.get_jobs()}=={'collect','digest','telegram'}
    assert scheduled.get_job('collect').trigger.interval.total_seconds()==config.COLLECT_MINUTES*60


def test_digest_batches_and_partial_failure(monkeypatch):
    entries=''.join(f'<item><title>Material {i}</title><link>https://example.com/{i}</link><description>{"content "*100}</description></item>' for i in range(30))
    rss=f'<rss version="2.0"><channel><title>Test</title>{entries}</channel></rss>'.encode()
    monkeypatch.setattr(collector,'fetch',lambda url:(rss,url))
    collector.collect()
    monkeypatch.setattr(config,'TOKEN','test')
    monkeypatch.setattr(config,'CHAT_ID','123')
    calls=[]
    def api(method,payload):
        calls.append(payload)
        assert len(payload['text'].encode('utf-16-le'))//2 <= 4096
        if len(calls)==2: raise RuntimeError('offline')
        return {}
    monkeypatch.setattr(telegram,'api',api)
    with pytest.raises(RuntimeError): telegram.send_digest()
    sent=len(rows('SELECT id FROM items WHERE sent_at IS NOT NULL'))
    assert 0 < sent < 30
    assert len(calls)==2
    monkeypatch.setattr(telegram,'api',lambda *args:{})
    assert telegram.send_digest()['sent']==30-sent

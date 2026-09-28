import pytest
from collectors.telegram import channel_url, parse
from collectors.rss import FeedError

HTML='''<div class="tgme_channel_info_header_title">Новости</div>
<div class="tgme_widget_message" data-post="news_test/1">
<div class="tgme_widget_message_text"><b>Привет</b><br>Мир &amp; новости</div>
<a class="tgme_widget_message_date"><time datetime="2026-09-28T12:00:00+00:00"></time></a></div>
<div class="tgme_widget_message" data-post="news_test/2">
<div class="tgme_widget_message_text">Привет Мир &amp; новости</div>
<a class="tgme_widget_message_date"><time datetime="2026-09-28T12:01:00+00:00"></time></a></div>
<div class="tgme_widget_message" data-post="news_test/3"><div>Photo only</div></div>'''

@pytest.mark.parametrize('url',['https://t.me/News_Test','https://t.me/s/news_test','@news_test','t.me/news_test/12?single','https://telegram.me/news_test'])
def test_normalization(url):
    assert channel_url(url)=='https://t.me/s/news_test'

@pytest.mark.parametrize('url',['https://t.me/+secret','https://t.me/joinchat/secret','https://t.me/c/123/4','https://t.me/share/url'])
def test_private_and_service_links(url):
    with pytest.raises(FeedError): channel_url(url)


def test_parse():
    name,items=parse(HTML,'https://t.me/s/news_test')
    assert name=='Новости'
    assert len(items)==2
    assert items[0]['title']=='Привет Мир & новости'
    assert items[0]['url']=='https://t.me/news_test/1'
    assert items[0]['title_key']!=items[1]['title_key']
    with pytest.raises(FeedError): parse('<html>Join Telegram</html>','https://t.me/s/news_test')


def test_collection_and_discovery(tmp_path,monkeypatch):
    import config
    from collectors import rss
    from services import collector
    from database import init, connect, rows
    monkeypatch.setattr(config,'DATABASE_PATH',str(tmp_path/'db.sqlite'))
    init()
    monkeypatch.setattr(rss,'fetch',lambda url:(HTML,url))
    url,name,_=rss.discover('@news_test')
    with connect() as db:
        db.execute('UPDATE sources SET enabled=0')
        db.execute('INSERT INTO sources(name,url) VALUES (?,?)',(name,url))
    monkeypatch.setattr(collector,'fetch',lambda url:(HTML,url))
    assert collector.collect()['added']==2
    assert collector.collect()['added']==0
    assert len(rows('SELECT * FROM items'))==2

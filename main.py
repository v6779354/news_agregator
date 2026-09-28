import logging
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import config
from database import init, connect, rows
from collectors.rss import discover, FeedError
from services.collector import collect
from bot.telegram import send_digest
from scheduler import start

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app):
    init()
    app.state.scheduler = start()
    yield
    app.state.scheduler.shutdown(wait=True)

app = FastAPI(title='Пульс — агрегатор новостей', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=config.BASE / 'static'), name='static')

@app.middleware('http')
async def local_mutations(request: Request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail':'Запрос с другого сайта запрещён.'}, status_code=403)
    return await call_next(request)

@app.get('/')
@app.get('/settings')
def index():
    return FileResponse(config.BASE / 'static/index.html')

@app.get('/api/status')
def status():
    return {'items':rows('SELECT count(*) AS n FROM items')[0]['n'],
            'new':rows('SELECT count(*) AS n FROM items WHERE sent_at IS NULL')[0]['n'],
            'sources':rows('SELECT count(*) AS n FROM sources WHERE enabled=1')[0]['n'],
            'telegram':bool(config.TOKEN and config.CHAT_ID),
            'collect_minutes':config.COLLECT_MINUTES,
            'digest_time':f'{config.DIGEST_HOUR:02}:{config.DIGEST_MINUTE:02}', 'timezone':config.TIMEZONE}

@app.get('/api/sources')
def sources(q: str = ''):
    return rows('SELECT * FROM sources WHERE instr(casefold(name), ?) > 0 OR instr(casefold(url), ?) > 0 ORDER BY id', (q.casefold(), q.casefold()))

class SourceInput(BaseModel):
    url: str = Field(min_length=5, max_length=2048)

@app.post('/api/sources', status_code=201)
def add_source(data: SourceInput):
    try:
        url, name, _ = discover(data.url)
        with connect() as db:
            cur = db.execute('INSERT INTO sources(name,url) VALUES (?,?)', (name,url))
        return {'id':cur.lastrowid, 'name':name, 'url':url}
    except FeedError as exc:
        raise HTTPException(400, str(exc)) from exc
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Этот источник уже добавлен.') from None

class SourceUpdate(BaseModel):
    enabled: bool

@app.patch('/api/sources/{source_id}')
def toggle(source_id: int, data: SourceUpdate):
    with connect() as db:
        if not db.execute('UPDATE sources SET enabled=? WHERE id=?',(data.enabled,source_id)).rowcount:
            raise HTTPException(404,'Источник не найден.')
    return {'ok':True}

@app.delete('/api/sources/{source_id}')
def delete(source_id: int):
    with connect() as db:
        if not db.execute('DELETE FROM sources WHERE id=?',(source_id,)).rowcount:
            raise HTTPException(404,'Источник не найден.')
    return {'ok':True}

@app.get('/api/items')
def items(q: str = '', source: int = 0, new: bool = False, page: int = 1):
    where = 'WHERE (instr(casefold(title), ?) > 0 OR instr(casefold(description), ?) > 0)'
    args = [q.casefold(), q.casefold()]
    if source:
        where += ' AND source_id=?'; args.append(source)
    if new:
        where += ' AND sent_at IS NULL'
    total = rows('SELECT count(*) AS n FROM items '+where,args)[0]['n']
    return {'total':total, 'items':rows('SELECT * FROM items '+where+' ORDER BY collected_at DESC,id DESC LIMIT 20 OFFSET ?',args+[max(0,page-1)*20])}

@app.post('/api/collect')
def trigger_collect():
    return collect()

@app.post('/api/digest')
def digest():
    try:
        return send_digest()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400,str(exc)) from exc

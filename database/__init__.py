import sqlite3
from contextlib import contextmanager
from pathlib import Path
import config

@contextmanager
def connect():
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DATABASE_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.create_function("casefold", 1, lambda value: (value or "").casefold(), deterministic=True)
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init():
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sources (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
          enabled INTEGER NOT NULL DEFAULT 1, last_checked TEXT, last_success TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
          source TEXT NOT NULL, source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
          description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          collected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          title_key TEXT NOT NULL, sent_at TEXT, UNIQUE(title_key,source));
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        if not db.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            db.executemany('INSERT OR IGNORE INTO sources(name,url) VALUES (?,?)', [
                ('Хабр', 'https://habr.com/ru/rss/articles/?fl=ru'),
                ('Hacker News', 'https://news.ycombinator.com/rss')])
            db.execute("INSERT INTO settings VALUES ('seeded','1')")

def rows(sql, params=()):
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]

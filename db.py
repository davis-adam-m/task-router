"""SQLite persistence. Each service operation owns one atomic transaction."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def transaction(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with transaction(path) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS contributors(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS expertise(contributor_id INTEGER REFERENCES contributors(id), area TEXT NOT NULL, PRIMARY KEY(contributor_id,area));
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, area TEXT NOT NULL, priority TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'ready', current_request INTEGER);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), created REAL NOT NULL, due REAL, candidate INTEGER REFERENCES contributors(id), processed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), contributor_id INTEGER NOT NULL REFERENCES contributors(id), state TEXT NOT NULL CHECK(state IN ('offered','accepted','declined','failed','replaced','reopened')));
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_assignment ON assignments(task_id) WHERE state IN ('offered','accepted');
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), created REAL NOT NULL, message TEXT NOT NULL);
        ''')


def seed(path, now):
    with transaction(path) as c:
        if c.execute('SELECT count(*) FROM contributors').fetchone()[0]:
            return
        for name, areas in [('Alex Morgan', ['finance','data analysis']), ('Sam Rivera',['healthcare','operations']), ('Jamie Chen',['data analysis','operations'])]:
            cid = c.execute('INSERT INTO contributors(name) VALUES (?)',(name,)).lastrowid
            c.executemany('INSERT INTO expertise VALUES (?,?)',[(cid,a) for a in areas])
        for title, area, priority in [('Review market research','finance','High'),('Analyze clinic survey','healthcare','Normal'),('Improve intake workflow','operations','Normal')]:
            tid = c.execute('INSERT INTO tasks(title,area,priority,created) VALUES (?,?,?,?)',(title,area,priority,now)).lastrowid
            c.execute('INSERT INTO events(task_id,created,message) VALUES (?,?,?)',(tid,now,'Seed task created; ready to route.'))

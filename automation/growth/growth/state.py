import contextlib
import fcntl
import json
import sqlite3
from pathlib import Path


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS snapshots(day TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, etag TEXT, value TEXT, link TEXT);
        ''')

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value)))

    def history(self):
        return [(day, json.loads(value)) for day, value in self.db.execute(
            'SELECT day,value FROM snapshots ORDER BY day')]

    def snapshot(self, day, value):
        # One complete baseline per UTC day. A failed collection never replaces it.
        with self.db:
            self.db.execute('INSERT INTO snapshots VALUES (?,?)', (day, json.dumps(value)))
            self.db.execute('DELETE FROM snapshots WHERE day < date(?, "-90 days")', (day,))

    def cached(self, key):
        return self.db.execute('SELECT etag,value,link FROM cache WHERE key=?', (key,)).fetchone()

    def cache(self, key, etag, value, link):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?,?)',
                            (key, etag, json.dumps(value), link))

    @contextlib.contextmanager
    def lock(self):
        with open(str(self.path) + '.lock', 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another collector holds the execution lock') from None
            yield

    def close(self):
        self.db.close()

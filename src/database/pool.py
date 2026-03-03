import os
import time
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg2
from psycopg2 import pool


class DatabasePool:
    _instance: Optional["DatabasePool"] = None
    _pool: Optional[pool.SimpleConnectionPool] = None

    def __new__(cls) -> "DatabasePool":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def init(self, min_conn: int = 1, max_conn: int = 20) -> None:
        if self._pool is None:
            dsn = os.getenv("POSTGRES_URI")
            if not dsn:
                raise RuntimeError("Missing POSTGRES_URI environment variable")
            self._pool = psycopg2.pool.SimpleConnectionPool(min_conn, max_conn, dsn=dsn)

    def getconn(self):
        """Return a connection from the pool (caller must call putconn when done)."""
        if self._pool is None:
            self.init()
        return self._pool.getconn()

    def putconn(self, conn) -> None:
        """Return a connection to the pool."""
        if self._pool is not None and conn is not None:
            self._pool.putconn(conn)

    @contextmanager
    def get_conn(self, retries: int = 3) -> Generator["psycopg2.extensions.connection", None, None]:
        if self._pool is None:
            self.init()

        conn = None
        for attempt in range(retries):
            try:
                conn = self._pool.getconn()
                yield conn
                return
            except Exception:
                if attempt == retries - 1:
                    raise
                # Exponential backoff between attempts
                time.sleep(0.5 * (2 ** attempt))
            finally:
                if conn:
                    self._pool.putconn(conn)

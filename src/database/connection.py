"""
Database connection pool and helper functions.

Uses DatabasePool (with retry logic) for get_connection(); get_pool() returns
the same pool instance for callers that use getconn/putconn directly.
"""
import logging
from typing import Optional, List, Dict, Any, Generator
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

import os
from dotenv import load_dotenv

from src.database.pool import DatabasePool

load_dotenv()
POSTGRES_URI = os.getenv("POSTGRES_URI")
if not POSTGRES_URI:
    raise RuntimeError("Missing POSTGRES_URI environment variable")

logger = logging.getLogger(__name__)


def initialize_pool(min_conn: int = 1, max_conn: int = 20) -> None:
    """Initialize the database connection pool (DatabasePool singleton)."""
    db_pool = DatabasePool()
    db_pool.init(min_conn=min_conn, max_conn=max_conn)
    logger.info("Database connection pool initialized (%s-%s connections)", min_conn, max_conn)


def get_pool() -> DatabasePool:
    """Get the database connection pool (DatabasePool with getconn/putconn)."""
    db_pool = DatabasePool()
    if db_pool._pool is None:
        initialize_pool()
    return db_pool


@contextmanager
def get_connection():
    """Context manager for database connections (uses pool with retries)."""
    db_pool = get_pool()
    with db_pool.get_conn() as conn:
        try:
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error("Database error: %s", e)
            raise


def pg_fetchone(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Execute query and return first row"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET statement_timeout = '3s'")
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        logger.error(f"Database query error: {e}")
        raise


def pg_fetchall(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Execute query and return all rows"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET statement_timeout = '3s'")
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Database query error: {e}")
        raise


def pg_execute(sql: str, params: tuple = ()) -> None:
    """Execute query without returning results"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '3s'")
                cur.execute(sql, params)
                conn.commit()
    except Exception as e:
        logger.error(f"Database execute error: {e}")
        raise


@contextmanager
def transaction() -> Generator[Any, None, None]:
    """
    Context manager for database transactions.
    Commits on success, rolls back on exception.
    """
    with get_connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def pg_execute_in_transaction(conn, query: str, params: tuple = ()) -> Optional[List[Dict[str, Any]]]:
    """
    Execute query within an existing transaction.
    Returns fetched rows if the statement has a result set, otherwise None.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET statement_timeout = '3s'")
        cur.execute(query, params)
        if cur.description:
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        return None

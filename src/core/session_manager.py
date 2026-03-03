"""
Session management for the CSD Chatbot.

This module is responsible for loading, saving, and creating chat
sessions backed by the `ec1_chat_history` table.

It provides both a `SessionManager` class and convenience functions
that mirror the historical helpers from `app.py`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import HTTPException
from psycopg2.extras import Json

from src.database.connection import pg_fetchone, pg_execute


MAX_MEMORY = 15


def _compose_sid(chat_id: Optional[str], session_id: Optional[str]) -> str:
    """
    Generate a unique session ID for each conversation.

    This follows the same contract as the original implementation
    in `app.py` to remain backwards compatible with existing data.
    """
    # Handle string "null" or "None" as None
    if session_id and isinstance(session_id, str):
        session_id_lower = session_id.lower().strip()
        if session_id_lower in ["null", "none", ""]:
            session_id = None

    # If session_id already contains colons, it's a full composite ID - return as-is
    if session_id and session_id.count(":") >= 2:
        return session_id

    # Generate new unique session ID
    chat = chat_id or _random_hex(4)
    timestamp = str(int(time.time() * 1000))  # Milliseconds since epoch
    random_suffix = _random_hex(4)  # 8 hex characters

    return f"{chat}:{timestamp}:{random_suffix}"


def _random_hex(num_bytes: int) -> str:
    import os

    return os.urandom(num_bytes).hex()


def _row_to_session(row: dict) -> Dict[str, Any]:
    messages = row.get("messages") or []
    pending = row.get("pending") or {}
    return {
        "_id": row["session_id"],
        "chat_id": row["chat_id"],
        "session_id": row["session_id"].split(":", 1)[1] if ":" in row["session_id"] else "",
        "title": row.get("title") or "New conversation",
        "messages": messages,
        "state": row.get("state") or "none",
        "pending": pending,
    }


def _get_messages(session_id: str) -> List[dict]:
    row = pg_fetchone("SELECT messages FROM ec1_chat_history WHERE session_id = %s", (session_id,))
    msgs = row.get("messages") if row else []
    if isinstance(msgs, str):
        import json

        try:
            msgs = json.loads(msgs)
        except Exception:
            msgs = []
    return msgs or []


@dataclass
class SessionManager:
    """
    High-level session management API.

    The underlying storage and schema matches the legacy implementation
    from `app.py`, but the behavior is encapsulated behind this class.
    """

    def load(self, chat_id: Optional[str], session_id: Optional[str]) -> Dict[str, Any]:
        sid = _compose_sid(chat_id, session_id)
        # Insert-if-not-exists semantics (same as original)
        pg_execute(
            """
            INSERT INTO ec1_chat_history (session_id, chat_id, title, messages, state, pending, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (session_id) DO NOTHING;
            """,
            (sid, (chat_id or sid.split(":", 1)[0]), "New conversation", Json([]), "none", Json({})),
        )
        row = pg_fetchone("SELECT * FROM ec1_chat_history WHERE session_id = %s", (sid,))
        return _row_to_session(row)

    def save(self, session: Dict[str, Any]) -> None:
        """
        Persist the current session payload.

        This is a thin wrapper that updates messages/state/pending; callers
        are responsible for mutating the in-memory `session` dict first.
        """
        pg_execute(
            """
            UPDATE ec1_chat_history
            SET messages = %s, state = %s, pending = %s, updated_at = NOW()
            WHERE session_id = %s
            """,
            (
                Json(session.get("messages") or []),
                session.get("state") or "none",
                Json(session.get("pending") or {}),
                session["_id"],
            ),
        )

    def create(self, chat_id: Optional[str]) -> Dict[str, Any]:
        """Explicitly create a new session for a chat_id."""
        sid = _compose_sid(chat_id, None)
        pg_execute(
            """
            INSERT INTO ec1_chat_history (session_id, chat_id, title, messages, state, pending, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (sid, (chat_id or sid.split(":", 1)[0]), "New conversation", Json([]), "none", Json({})),
        )
        row = pg_fetchone("SELECT * FROM ec1_chat_history WHERE session_id = %s", (sid,))
        return _row_to_session(row)

    def get_or_create(self, chat_id: Optional[str], session_id: Optional[str]) -> Dict[str, Any]:
        if session_id:
            row = pg_fetchone("SELECT * FROM ec1_chat_history WHERE session_id = %s", (_compose_sid(chat_id, session_id),))
            if row:
                return _row_to_session(row)
        return self.create(chat_id)

    def save_message(self, session: Dict[str, Any], role: str, content: Any) -> str:
        msgs = _get_messages(session["_id"])
        entry = {"role": role, "content": content, "ts": time.time()}
        msgs.append(entry)
        msgs = msgs[-MAX_MEMORY:]
        pg_execute(
            "UPDATE ec1_chat_history SET messages = %s, updated_at = NOW() WHERE session_id = %s",
            (Json(msgs), session["_id"]),
        )
        session["messages"] = msgs
        return str(entry["ts"])

    def clear_state(self, session: Dict[str, Any]) -> None:
        pg_execute(
            "UPDATE ec1_chat_history SET state = %s, pending = %s, updated_at = NOW() WHERE session_id = %s",
            ("none", Json({}), session["_id"]),
        )
        session["state"] = "none"
        session["pending"] = {}


# Global singleton for convenience (mirrors legacy function API)
session_manager = SessionManager()


def load_session(chat_id: Optional[str], session_id: Optional[str]) -> Dict[str, Any]:
    """
    Load a session with defensive error handling.
    Returns an in-memory fallback session if the database is unavailable.
    """
    sid = _compose_sid(chat_id, session_id)
    try:
        return session_manager.load(chat_id, session_id)
    except psycopg2.Error:
        # Return emergency fallback session when the database is unavailable
        base_chat_id = (chat_id or sid.split(":", 1)[0])
        short_session_id = sid.split(":", 1)[1] if ":" in sid else ""
        return {
            "_id": sid,
            "chat_id": base_chat_id,
            "session_id": short_session_id,
            "title": "New conversation",
            "messages": [],
            "pending": {},
            "state": "OPEN",
        }
    except Exception:
        # Log at a higher level and surface a controlled API error
        raise HTTPException(status_code=500, detail="Session system unavailable")


def save_session(session: Dict[str, Any]) -> None:
    session_manager.save(session)


def create_new_session(chat_id: Optional[str]) -> Dict[str, Any]:
    return session_manager.create(chat_id)


def get_or_create_session(chat_id: Optional[str], session_id: Optional[str]) -> Dict[str, Any]:
    return session_manager.get_or_create(chat_id, session_id)


def save_message(session: Dict[str, Any], role: str, content: Any) -> str:
    return session_manager.save_message(session, role, content)


def clear_state(session: Dict[str, Any]) -> None:
    session_manager.clear_state(session)


def get_messages(session_id: str) -> List[dict]:
    """
    Public helper to fetch all raw messages for a session.

    This mirrors the legacy `_get_messages` helper from `app.py` and
    is primarily used by streaming endpoints.
    """
    return _get_messages(session_id)


__all__ = [
    "SessionManager",
    "session_manager",
    "load_session",
    "save_session",
    "create_new_session",
    "get_or_create_session",
    "save_message",
    "clear_state",
    "get_messages",
]


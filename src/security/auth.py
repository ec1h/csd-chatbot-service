"""
API key authentication and verification
"""
import base64
import hashlib
import hmac
from typing import Optional
from datetime import datetime, timezone
from fastapi import HTTPException, Header, Request
import logging

from src.database.connection import pg_fetchone

logger = logging.getLogger(__name__)


def _safe_bytes(value):
    """Safely convert value to bytes"""
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return base64.b64decode(value)
    raise ValueError(f"Unsupported type for salt/key_hash: {type(value)}")


def verify_api_key_header(request: Request, x_api_key: Optional[str] = Header(default=None)) -> dict:
    """
    Verify API key from header
    
    Supports:
    - X-API-Key header
    - Authorization: Bearer <key> header
    
    Returns:
        API key document from database
    """
    header = x_api_key
    bearer = request.headers.get("Authorization", "")
    if not header and bearer.lower().startswith("bearer "):
        header = bearer.split(" ", 1)[1].strip()

    if not header:
        raise HTTPException(status_code=401, detail="Missing API key")

    try:
        key_id, secret = header.split(".", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed API key")

    try:
        doc = pg_fetchone("""
            SELECT key_id, salt, key_hash, status, expires_at
            FROM ec1_api_keys
            WHERE key_id = %s
        """, (key_id,))
    except Exception as e:
        logger.error(f"Database error during API key verification: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    if not doc:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if doc["status"] != "active":
        raise HTTPException(status_code=403, detail="API key not active")

    expires_at = doc.get("expires_at")
    if expires_at:
        if getattr(expires_at, "tzinfo", None) is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            raise HTTPException(status_code=403, detail="API key expired")

    try:
        salt = _safe_bytes(doc["salt"])
        expected = _safe_bytes(doc["key_hash"])
    except Exception as e:
        logger.error(f"API key record corrupted: {e}")
        raise HTTPException(status_code=500, detail=f"API key record corrupted: {e}")

    computed = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 100_000)
    if not hmac.compare_digest(computed, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return doc

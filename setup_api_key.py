import hashlib
import os
import psycopg2
from datetime import datetime, timezone, timedelta
import base64

# Database connection
conn = psycopg2.connect(
    host="test-csd-chatbot-db.cx6kcuiu8rwl.af-south-1.rds.amazonaws.com",
    database="csd_chatbot",
    user="postgres",
    password="YourSecurePassword123"
)

# Your API key components
key_id = "test-key"
secret = "test-secret-123"

# Generate a random salt (16 bytes)
salt = os.urandom(16)

# Hash the secret with PBKDF2 (100,000 iterations as in dependencies.py)
key_hash = hashlib.pbkdf2_hmac('sha256', secret.encode('utf-8'), salt, 100000)

# Insert into database
with conn.cursor() as cur:
    cur.execute("""
        INSERT INTO ec1_api_keys (key_id, salt, key_hash, status, created_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (key_id) DO UPDATE SET
            salt = EXCLUDED.salt,
            key_hash = EXCLUDED.key_hash,
            status = EXCLUDED.status
    """, (
        key_id,
        psycopg2.Binary(salt),
        psycopg2.Binary(key_hash),
        'active',
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=365)
    ))
    conn.commit()

print(f"✅ API key '{key_id}.{secret}' has been inserted/updated in the database")
print(f"Salt (base64): {base64.b64encode(salt).decode()}")
print(f"Hash (base64): {base64.b64encode(key_hash).decode()}")
conn.close()

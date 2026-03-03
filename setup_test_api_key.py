#!/usr/bin/env python3
"""
Setup Test API Key for CSD Chatbot
This script properly generates and inserts the test API key into the database.
Run this after starting Docker containers.
"""
import hashlib
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

# Test API Key Configuration
KEY_ID = "test-key"
SECRET = "test-secret-123"

# Database connection (default from docker-compose)
POSTGRES_URI = os.getenv(
    "POSTGRES_URI",
    "postgresql://postgres:YourSecurePassword123@localhost:5434/ec1"
)

def generate_api_key():
    """Generate salt and hash for the test API key"""
    # Use a fixed salt for the test key (so it's reproducible)
    # Salt must be 32 bytes = 64 hex characters exactly
    # In production, use random salt: os.urandom(32)
    salt_hex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    salt = bytes.fromhex(salt_hex)
    
    # Generate hash using PBKDF2-HMAC-SHA256 (must match API key verification in dependencies.py)
    key_hash = hashlib.pbkdf2_hmac('sha256', SECRET.encode('utf-8'), salt, 100_000)
    
    return salt, key_hash

def setup_api_key():
    """Insert or update the test API key in the database"""
    print("=" * 60)
    print("CSD Chatbot - Test API Key Setup")
    print("=" * 60)
    print()
    
    salt, key_hash = generate_api_key()
    
    print(f"Key ID: {KEY_ID}")
    print(f"Secret: {SECRET}")
    print(f"Full Key: {KEY_ID}.{SECRET}")
    print()
    
    try:
        print("Connecting to database...")
        conn = psycopg2.connect(POSTGRES_URI)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if key exists
        cur.execute("SELECT key_id FROM ec1_api_keys WHERE key_id = %s", (KEY_ID,))
        exists = cur.fetchone()
        
        if exists:
            print("Updating existing test key...")
            cur.execute("""
                UPDATE ec1_api_keys
                SET salt = %s, key_hash = %s, status = 'active',
                    expires_at = NOW() + INTERVAL '1 year'
                WHERE key_id = %s
            """, (salt, key_hash, KEY_ID))
        else:
            print("Inserting new test key...")
            cur.execute("""
                INSERT INTO ec1_api_keys (key_id, salt, key_hash, status, expires_at)
                VALUES (%s, %s, %s, 'active', NOW() + INTERVAL '1 year')
            """, (KEY_ID, salt, key_hash))
        
        conn.commit()
        
        # Verify
        cur.execute("""
            SELECT key_id, status, expires_at 
            FROM ec1_api_keys 
            WHERE key_id = %s
        """, (KEY_ID,))
        result = cur.fetchone()
        
        print()
        print("=" * 60)
        print("✅ API Key Setup Successful!")
        print("=" * 60)
        print()
        print("Use this in Postman:")
        print(f"  Authorization: Bearer {KEY_ID}.{SECRET}")
        print()
        print("Or in curl:")
        print(f'  curl -H "Authorization: Bearer {KEY_ID}.{SECRET}" \\')
        print('       -H "Content-Type: application/json" \\')
        print('       -X POST http://localhost:8001/chat \\')
        print('       -d \'{"chat_id":"test","message":"water leak"}\'')
        print()
        print(f"Key Status: {result['status']}")
        print(f"Expires: {result['expires_at']}")
        print()
        
        cur.close()
        conn.close()
        
        return True
        
    except psycopg2.OperationalError as e:
        print()
        print("=" * 60)
        print("❌ Database Connection Failed")
        print("=" * 60)
        print()
        print("Make sure:")
        print("  1. Docker containers are running: docker-compose ps")
        print("  2. PostgreSQL is accessible on port 5434")
        print("  3. POSTGRES_PASSWORD matches your .env file")
        print()
        print(f"Error: {e}")
        print()
        print("Current POSTGRES_URI:", POSTGRES_URI)
        print()
        return False
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ Error Setting Up API Key")
        print("=" * 60)
        print()
        print(f"Error: {e}")
        print()
        return False

if __name__ == "__main__":
    success = setup_api_key()
    sys.exit(0 if success else 1)

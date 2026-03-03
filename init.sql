-- CSD Chatbot Database Initialization Script
-- This script creates all necessary tables for the chatbot

-- Create API Keys table
CREATE TABLE IF NOT EXISTS ec1_api_keys (
  key_id       TEXT PRIMARY KEY,
  salt         BYTEA NOT NULL,
  key_hash     BYTEA NOT NULL,
  status       TEXT NOT NULL DEFAULT 'active', -- 'active' | 'revoked'
  expires_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ec1_api_keys_status ON ec1_api_keys (status);
CREATE INDEX IF NOT EXISTS idx_ec1_api_keys_expires ON ec1_api_keys (expires_at);

-- Create Chat History table
CREATE TABLE IF NOT EXISTS ec1_chat_history (
  session_id   TEXT PRIMARY KEY,              -- format: {chat_id}:{session_hex}
  chat_id      TEXT NOT NULL,
  title        TEXT NOT NULL DEFAULT 'New conversation',
  messages     JSONB NOT NULL DEFAULT '[]',   -- [{role, content, ts}]
  state        TEXT NOT NULL DEFAULT 'none',  -- 'none' | 'awaiting_category' | 'awaiting_code'
  pending      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ec1_chat_history_chatid ON ec1_chat_history (chat_id);
CREATE INDEX IF NOT EXISTS idx_ec1_chat_history_updated ON ec1_chat_history (updated_at DESC);

-- Create Tickets table
CREATE TABLE IF NOT EXISTS ec1_tickets (
  id          BIGSERIAL PRIMARY KEY,
  session_id  TEXT NOT NULL,
  code        TEXT NOT NULL,
  description TEXT NOT NULL,
  query       TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ec1_tickets_session ON ec1_tickets (session_id);
CREATE INDEX IF NOT EXISTS idx_ec1_tickets_code ON ec1_tickets (code);

-- Create Merged Call Types table
CREATE TABLE IF NOT EXISTS merged_call_types (
  "Category"                   TEXT NOT NULL,     -- 'water' | 'electricity'
  "Call Type Code_NEW"         TEXT NOT NULL,
  "Short Description-Call Type" TEXT NOT NULL,
  "Dept/MOE & Call Type"       TEXT,
  PRIMARY KEY ("Category", "Call Type Code_NEW")
);

CREATE INDEX IF NOT EXISTS idx_calltypes_cat ON merged_call_types (LOWER("Category"));
CREATE INDEX IF NOT EXISTS idx_calltypes_short ON merged_call_types (LOWER("Short Description-Call Type"));

-- Insert sample call types for testing
INSERT INTO merged_call_types ("Category", "Call Type Code_NEW", "Short Description-Call Type", "Dept/MOE & Call Type")
VALUES
  ('electricity', 'E123', 'Power outage', 'City Power - Outage'),
  ('electricity', 'E456', 'Street light issue', 'City Power - Street Lights'),
  ('electricity', 'E789', 'Cable fault', 'City Power - Cable Fault'),
  ('water', 'W123', 'Water leak', 'Joburg Water - Leak'),
  ('water', 'W456', 'No water supply', 'Joburg Water - No Supply'),
  ('water', 'W789', 'Burst pipe', 'Joburg Water - Burst Pipe')
ON CONFLICT DO NOTHING;

-- NOTE: The test API key is NOT created here because it requires proper PBKDF2-HMAC-SHA256 hashing
-- Run setup_test_api_key.py or setup_test_api_key.bat after starting Docker containers
-- This will properly generate and insert: test-key.test-secret-123

-- Success message
DO $$
BEGIN
  RAISE NOTICE 'Database initialization complete!';
  RAISE NOTICE 'Tables created: ec1_api_keys, ec1_chat_history, ec1_tickets, merged_call_types';
  RAISE NOTICE 'Sample data inserted for testing';
END $$;

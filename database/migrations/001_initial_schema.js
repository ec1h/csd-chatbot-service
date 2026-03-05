exports.up = async (pool) => {
    // Create API Keys table
    await pool.query(`
      CREATE TABLE IF NOT EXISTS ec1_api_keys (
        key_id       TEXT PRIMARY KEY,
        salt         BYTEA NOT NULL,
        key_hash     BYTEA NOT NULL,
        status       TEXT NOT NULL DEFAULT 'active',
        expires_at   TIMESTAMPTZ,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
  
      CREATE INDEX IF NOT EXISTS idx_ec1_api_keys_status ON ec1_api_keys (status);
      CREATE INDEX IF NOT EXISTS idx_ec1_api_keys_expires ON ec1_api_keys (expires_at);
    `);
  
    // Create Chat History table
    await pool.query(`
      CREATE TABLE IF NOT EXISTS ec1_chat_history (
        session_id   TEXT PRIMARY KEY,
        chat_id      TEXT NOT NULL,
        title        TEXT NOT NULL DEFAULT 'New conversation',
        messages     JSONB NOT NULL DEFAULT '[]',
        state        TEXT NOT NULL DEFAULT 'none',
        pending      JSONB NOT NULL DEFAULT '{}',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
  
      CREATE INDEX IF NOT EXISTS idx_ec1_chat_history_chatid ON ec1_chat_history (chat_id);
      CREATE INDEX IF NOT EXISTS idx_ec1_chat_history_updated ON ec1_chat_history (updated_at DESC);
    `);
  
    // Create Tickets table
    await pool.query(`
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
    `);
  };
  
  exports.down = async (pool) => {
    await pool.query(`DROP TABLE IF EXISTS ec1_tickets CASCADE`);
    await pool.query(`DROP TABLE IF EXISTS ec1_chat_history CASCADE`);
    await pool.query(`DROP TABLE IF EXISTS ec1_api_keys CASCADE`);
  };
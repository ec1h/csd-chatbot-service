const { SecretsManager } = require('@aws-sdk/client-secrets-manager');
const crypto = require('crypto');

exports.up = async (pool) => {
  console.log('Setting up API keys from Secrets Manager (pipeline secret)...');

  const secretsManager = new SecretsManager({ region: 'af-south-1' });
  const environment = process.env.ENVIRONMENT || 'test';
  const secretName = `csd-chatbot/api-key-${environment}`;

  try {
    console.log(`Fetching secret: ${secretName}`);
    const secret = await secretsManager.getSecretValue({ SecretId: secretName });
    const apiKey = secret.SecretString; // Format: "key_id.secret_value"
    const [keyId, secretValue] = apiKey.split('.');
    if (!keyId || !secretValue) {
      console.warn(`Skipping API key sync: secret ${secretName} has invalid format (expected key_id.secret_value)`);
      return;
    }
    console.log(`Key ID: ${keyId}`);

    const salt = crypto.randomBytes(16);
    const keyHash = crypto.pbkdf2Sync(secretValue, salt, 100000, 32, 'sha256');

    await pool.query(`
      INSERT INTO ec1_api_keys (key_id, salt, key_hash, status, created_at, expires_at)
      VALUES ($1, $2, $3, 'active', NOW(), NOW() + INTERVAL '365 days')
      ON CONFLICT (key_id) DO UPDATE SET
        salt = EXCLUDED.salt,
        key_hash = EXCLUDED.key_hash,
        status = EXCLUDED.status,
        expires_at = EXCLUDED.expires_at
    `, [keyId, salt, keyHash]);

    console.log(`API key for ${keyId} synced to database`);
    const verify = await pool.query(`SELECT key_id, status FROM ec1_api_keys WHERE key_id = $1`, [keyId]);
    if (verify.rows[0]) {
      console.log(`Verified: ${verify.rows[0].key_id} - ${verify.rows[0].status}`);
    }
  } catch (error) {
    if (error.name === 'ResourceNotFoundException' || error.code === 'ResourceNotFoundException') {
      console.log(`Secret ${secretName} not found; skipping API key sync (run setup-api-key job first or create secret).`);
      return;
    }
    console.error('Error syncing API key to database:', error);
    throw error;
  }
};

exports.down = async (pool) => {
  console.log('Skipping API key removal on rollback');
};

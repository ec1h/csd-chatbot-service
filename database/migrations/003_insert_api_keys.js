const { SecretsManager } = require('@aws-sdk/client-secrets-manager');
const crypto = require('crypto');

exports.up = async (pool) => {
  console.log('Setting up API keys from Secrets Manager...');
  
  const secretsManager = new SecretsManager({ region: 'af-south-1' });
  const environment = process.env.ENVIRONMENT || 'test';
  
  try {
    // Get API key from Secrets Manager
    const secretName = `${environment}/csd-chatbot/api-key`;
    console.log(`Fetching secret: ${secretName}`);
    
    const secret = await secretsManager.getSecretValue({ SecretId: secretName });
    const apiKey = secret.SecretString; // Format: "key_id.secret_value"
    
    const [keyId, secretValue] = apiKey.split('.');
    console.log(`Key ID: ${keyId}`);
    
    // Generate salt and hash (same method as verify_api_key_header)
    const salt = crypto.randomBytes(16);
    const keyHash = crypto.pbkdf2Sync(secretValue, salt, 100000, 32, 'sha256');
    
    // Insert into database
    await pool.query(`
      INSERT INTO ec1_api_keys (key_id, salt, key_hash, status, created_at, expires_at)
      VALUES ($1, $2, $3, 'active', NOW(), NOW() + INTERVAL '365 days')
      ON CONFLICT (key_id) DO UPDATE SET
        salt = EXCLUDED.salt,
        key_hash = EXCLUDED.key_hash,
        status = EXCLUDED.status,
        expires_at = EXCLUDED.expires_at
    `, [
      keyId,
      salt,
      keyHash
    ]);
    
    console.log(`API key '${apiKey}' synced to database`);
    
    // Verify it was inserted
    const verify = await pool.query(`SELECT key_id, status FROM ec1_api_keys WHERE key_id = $1`, [keyId]);
    console.log(`Verified: ${verify.rows[0].key_id} - ${verify.rows[0].status}`);
    
  } catch (error) {
    console.error('Error syncing API key to database:', error);
    throw error;
  }
};

exports.down = async (pool) => {
  console.log('Skipping API key removal on rollback');
};

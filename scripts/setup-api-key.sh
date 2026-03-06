#!/bin/bash
set -e

ENVIRONMENT=$1
export ENVIRONMENT
echo "Setting up API key for $ENVIRONMENT environment"

# Generate API key using Node (reads ENVIRONMENT from env)
node << 'EOF'
const crypto = require('crypto');
const { Client } = require('pg');
const { SecretsManager } = require('@aws-sdk/client-secrets-manager');

const environment = process.env.ENVIRONMENT || 'test';
const secretsManager = new SecretsManager({ region: 'af-south-1' });

async function setup() {
  // Load environment variables
  const envVars = {
    DB_HOST: process.env.DB_HOST,
    DB_PORT: process.env.DB_PORT,
    DB_NAME: process.env.DB_NAME,
    DB_USERNAME: process.env.DB_USERNAME,
    DB_PASSWORD: process.env.DB_PASSWORD
  };

  // Generate API key
  const keyId = `csd-${environment}`;
  const secret = crypto.randomBytes(24).toString('base64url');
  const salt = crypto.randomBytes(16);
  const keyHash = crypto.pbkdf2Sync(secret, salt, 100000, 32, 'sha256');

  console.log(`Generated API key: ${keyId}.${secret}`);

  // Connect to database
  const client = new Client({
    host: envVars.DB_HOST,
    port: envVars.DB_PORT,
    database: envVars.DB_NAME,
    user: envVars.DB_USERNAME,
    password: envVars.DB_PASSWORD,
  });

  await client.connect();

  // Insert into database
  await client.query(`
    INSERT INTO ec1_api_keys (key_id, salt, key_hash, status, created_at, expires_at)
    VALUES ($1, $2, $3, 'active', NOW(), NOW() + INTERVAL '365 days')
    ON CONFLICT (key_id) DO UPDATE SET
      salt = EXCLUDED.salt,
      key_hash = EXCLUDED.key_hash,
      status = EXCLUDED.status,
      expires_at = EXCLUDED.expires_at
  `, [keyId, salt, keyHash]);

  console.log('API key stored in database');

  // Store in Secrets Manager
  const secretName = `csd-chatbot/api-key-${environment}`;
  
  try {
    await secretsManager.createSecret({
      Name: secretName,
      SecretString: `${keyId}.${secret}`,
      Tags: [{ Key: 'Environment', Value: environment }]
    });
    console.log(`API key stored in Secrets Manager: ${secretName}`);
  } catch (error) {
    if (error.name === 'ResourceExistsException') {
      await secretsManager.updateSecret({
        SecretId: secretName,
        SecretString: `${keyId}.${secret}`
      });
      console.log(`API key updated in Secrets Manager: ${secretName}`);
    } else {
      throw error;
    }
  }

  await client.end();
}

setup().catch(console.error);
EOF
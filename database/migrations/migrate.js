#!/usr/bin/env node

const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const pool = new Pool({
  host: process.env.DB_HOST,
  port: process.env.DB_PORT || 5432,
  database: process.env.DB_NAME,
  user: process.env.DB_USERNAME,
  password: process.env.DB_PASSWORD,
});

const migrationsTable = `
  CREATE TABLE IF NOT EXISTS migrations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
`;

async function runMigrations() {
  const direction = process.argv[2] || 'up';
  
  await pool.query(migrationsTable);
  
  const executedMigrations = await pool.query(
    'SELECT name FROM migrations ORDER BY id'
  );
  const executedNames = executedMigrations.rows.map(r => r.name);
  
  const migrationFiles = fs.readdirSync(__dirname + '/migrations')
    .filter(f => f.endsWith('.js'))
    .sort();
  
  for (const file of migrationFiles) {
    const migration = require(`./migrations/${file}`);
    const name = file.replace('.js', '');
    
    if (direction === 'up' && !executedNames.includes(name)) {
      console.log(`Running migration: ${name}`);
      await migration.up(pool);
      await pool.query('INSERT INTO migrations (name) VALUES ($1)', [name]);
      console.log(`Completed migration: ${name}`);
    } else if (direction === 'down' && executedNames.includes(name)) {
      console.log(`Reverting migration: ${name}`);
      await migration.down(pool);
      await pool.query('DELETE FROM migrations WHERE name = $1', [name]);
      console.log(`Reverted migration: ${name}`);
      break; // Only revert one at a time for safety
    }
  }
  
  console.log('Migrations completed');
  await pool.end();
}

runMigrations().catch(console.error);
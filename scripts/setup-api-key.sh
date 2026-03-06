#!/bin/bash
set -e

ENVIRONMENT=$1
SECRET_NAME="csd-chatbot/api-key-${ENVIRONMENT}"

echo "Setting up API key for $ENVIRONMENT environment (Secrets Manager only)"

# Check if secret already exists
if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region af-south-1 2>/dev/null; then
  echo "API key already exists in Secrets Manager ($SECRET_NAME), skipping"
  exit 0
fi

# Generate new API key (format: csd-<env>.<random>)
RANDOM_PART=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
API_KEY="csd-${ENVIRONMENT}.${RANDOM_PART}"

aws secretsmanager create-secret \
  --name "$SECRET_NAME" \
  --secret-string "$API_KEY" \
  --region af-south-1 \
  --tags Key=Environment,Value="$ENVIRONMENT"

echo "API key created and stored in Secrets Manager: $SECRET_NAME"

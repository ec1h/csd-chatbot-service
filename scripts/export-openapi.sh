#!/bin/bash
set -e

ENVIRONMENT=$1
SERVICE="csd-chatbot"
AWS_REGION="af-south-1"

echo "Exporting OpenAPI spec for $SERVICE in $ENVIRONMENT"

# Get ALB DNS name
ALB_DNS=$(aws elbv2 describe-load-balancers \
  --names "csd-chatbot-alb-${ENVIRONMENT}" \
  --query 'LoadBalancers[0].DNSName' \
  --output text \
  --region ${AWS_REGION})

# Download OpenAPI spec from the service
curl -s "http://${ALB_DNS}/openapi.json" -o openapi.json

# Upload to S3
S3_BUCKET="csd-openapi-definitions-${ENVIRONMENT}"
aws s3 cp openapi.json "s3://${S3_BUCKET}/${SERVICE}/openapi.json" --region ${AWS_REGION}

# Also upload versioned copy with timestamp
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
aws s3 cp openapi.json "s3://${S3_BUCKET}/${SERVICE}/openapi-${TIMESTAMP}.json" --region ${AWS_REGION}

echo " OpenAPI spec uploaded to s3://${S3_BUCKET}/${SERVICE}/"
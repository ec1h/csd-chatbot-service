# Environment-level configuration for uat
environment = "uat"
vpc_id      = "vpc-0c70f9c141381565b"
private_subnet_ids = [
  "subnet-04f62cb7b8d2a6f24",
  "subnet-05869d1467326e2d0"
]
public_subnet_ids = [
  "subnet-0b05513511446451a",
  "subnet-00ebff1d7e7e64c05"
]
database_secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:uat/csd-chatbot/database-xxxxx"
azure_openai_api_key_secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:csd-chatbot/uat-xxxxx:AZURE_OPENAI_API_KEY::"
api_key_secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:csd-chatbot/api-key-uat-xxxxx"
azure_openai_endpoint = "https://ec1-azureopenai-askjo.openai.azure.com/"
azure_openai_deployment = "gpt-4.1"
allowed_origins = ["http://localhost:3000", "https://uat.chatbot.ec1.co.za"]
enable_https = true
ssl_certificate_arn = "arn:aws:acm:af-south-1:905418043725:certificate/uat-chatbot-xxxxx"
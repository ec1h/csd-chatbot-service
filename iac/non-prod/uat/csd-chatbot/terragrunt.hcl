include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//csd-chatbot-service"
}

inputs = {
  environment          = "uat"
  service_version      = get_env("TF_VAR_service_version", "latest")
  vpc_id               = dependency.vpc.outputs.vpc_id
  private_subnet_ids   = dependency.vpc.outputs.private_subnet_ids
  public_subnet_ids    = dependency.vpc.outputs.public_subnet_ids
  database_secret_arn  = dependency.database.outputs.secret_arn
  azure_openai_api_key_secret_arn = dependency.secrets.outputs.azure_openai_api_key_arn
  api_key_secret_arn   = dependency.secrets.outputs.api_key_arn
  azure_openai_endpoint = "https://ec1-azureopenai-askjo.openai.azure.com/"
  azure_openai_deployment = "gpt-4.1"
  log_level            = "INFO"
  desired_count        = 2
  allowed_origins      = ["https://uat.chatbot.ec1.co.za"]
  enable_https         = true
  ssl_certificate_arn  = "arn:aws:acm:af-south-1:905418043725:certificate/uat-chatbot-xxxxx"
  
  tags = {
    Environment = "uat"
    Service     = "csd-chatbot"
  }
}

dependency "vpc" {
  config_path = "../../vpc"
}

dependency "database" {
  config_path = "../../database"
}

dependency "secrets" {
  config_path = "../../secrets"
}
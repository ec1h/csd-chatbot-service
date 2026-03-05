include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//csd-chatbot-service"
}

dependency "vpc" {
  config_path = "../vpc"
}

dependency "database" {
  config_path = "../database"
}

inputs = {
  environment          = "qa"
  service_version      = get_env("TF_VAR_service_version", "latest")
  vpc_id               = dependency.vpc.outputs.vpc_id
  private_subnet_ids   = dependency.vpc.outputs.private_subnet_ids
  public_subnet_ids    = dependency.vpc.outputs.public_subnet_ids
  database_secret_arn  = dependency.database.outputs.secret_arn
  
  # Azure OpenAI (QA secrets - these need to be created!)
  azure_openai_api_key_secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:qa/csd-chatbot/azure-openai-NlSsQx"
  api_key_secret_arn   = "arn:aws:secretsmanager:af-south-1:905418043725:secret:qa/csd-chatbot/api-key-wKxYZu"  # This exists!
  
  azure_openai_endpoint = "https://ec1-azureopenai-askjo.openai.azure.com/"
  azure_openai_deployment = "gpt-4.1"
  call_types_data_path = get_env("TF_VAR_call_types_data_path", "/app/data/refined data/files/all_call_types_combined.json")
  log_level            = "INFO"
  desired_count        = 2
  allowed_origins      = ["https://qa.chatbot.ec1.co.za"]
  enable_https         = true
  ssl_certificate_arn  = "arn:aws:acm:af-south-1:905418043725:certificate/qa-chatbot-PLACEHOLDER"
  
  tags = {
    Environment = "qa"
    Service     = "csd-chatbot"
  }
}

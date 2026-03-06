include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//csd-chatbot-service"
}

locals {
  is_plan = get_terraform_command() == "plan"
}

dependency "vpc" {
  config_path = "../vpc"
  
  mock_outputs = {
    vpc_id = "vpc-0c70f9c141381565b"
    private_subnet_ids = ["subnet-04f62cb7b8d2a6f24", "subnet-05869d1467326e2d0"]
    public_subnet_ids = ["subnet-0b05513511446451a", "subnet-00ebff1d7e7e64c05"]
  }
  mock_outputs_allowed_terraform_commands = ["plan", "validate"]
}

dependency "database" {
  config_path = "../database"
  
  mock_outputs = {
    secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:uat/csd-chatbot/database-PLACEHOLDER"
  }
  mock_outputs_allowed_terraform_commands = ["plan", "validate"]
}

inputs = {
  environment          = "uat"
  service_version      = get_env("TF_VAR_service_version", "latest")
  vpc_id               = dependency.vpc.outputs.vpc_id
  private_subnet_ids   = dependency.vpc.outputs.private_subnet_ids
  public_subnet_ids    = dependency.vpc.outputs.public_subnet_ids
  database_secret_arn  = dependency.database.outputs.secret_arn
  
  # Azure OpenAI
  azure_openai_api_key_secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:uat/csd-chatbot/azure-openai-quKKzB"
  api_key_secret_name  = local.is_plan ? "" : "csd-chatbot/api-key-uat"
  api_key_secret_arn   = local.is_plan ? "arn:aws:secretsmanager:af-south-1:905418043725:secret:placeholder" : ""
  
  azure_openai_endpoint = "https://ec1-azureopenai-askjo.openai.azure.com/"
  azure_openai_deployment = "gpt-4.1"
  call_types_data_path = get_env("TF_VAR_call_types_data_path", "/app/data/refined data/files/all_call_types_combined.json")
  log_level            = "INFO"
  desired_count        = 2
  allowed_origins      = ["https://uat.chatbot.ec1.co.za"]
  enable_https         = true
  ssl_certificate_arn  = "arn:aws:acm:af-south-1:905418043725:certificate/uat-chatbot-PLACEHOLDER"
  
  tags = {
    Environment = "uat"
    Service     = "csd-chatbot"
  }
}

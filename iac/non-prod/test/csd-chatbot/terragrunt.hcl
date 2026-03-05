include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//csd-chatbot-service"
}

inputs = {
  environment          = "test"
  service_version      = get_env("TF_VAR_service_version", "latest")
  
  # Use data sources for existing resources
  existing_cluster_name = "csd-test-cluster"
  existing_alb_name     = "csd-chatbot-alb"
  existing_target_group_arn = "arn:aws:elasticloadbalancing:af-south-1:905418043725:targetgroup/csd-chatbot-tg/33bb305ee645e8d4"
  
  # Database (TEST instance exists)
  database_secret_arn  = "arn:aws:secretsmanager:af-south-1:905418043725:secret:test/csd-chatbot/database-W1NSjd"
  
  # Azure OpenAI (TEST exists)
  azure_openai_api_key_secret_arn = "arn:aws:secretsmanager:af-south-1:905418043725:secret:test/csd-chatbot/azure-openai-xC9TFZ"
  
  # API Key (TEST we created)
  api_key_secret_arn   = "arn:aws:secretsmanager:af-south-1:905418043725:secret:test/csd-chatbot/api-key-JoqAwN"
  
  azure_openai_endpoint = "https://ec1-azureopenai-askjo.openai.azure.com/"
  azure_openai_deployment = "gpt-4.1"
  call_types_data_path = get_env("TF_VAR_call_types_data_path", "/app/data/refined data/files/all_call_types_combined.json")
  log_level            = "DEBUG"
  desired_count        = 1
  allowed_origins      = ["http://localhost:3000", "https://test.chatbot.ec1.co.za"]
  enable_https         = false
  
  tags = {
    Environment = "test"
    Service     = "csd-chatbot"
  }
}

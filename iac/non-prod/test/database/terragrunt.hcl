include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//database"
}

inputs = {
  environment = "test"
  db_instance_identifier = "test-csd-chatbot-db"
}

dependency "secrets" {
  config_path = "../secrets"
}

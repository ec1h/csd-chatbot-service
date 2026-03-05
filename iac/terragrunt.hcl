# Root terragrunt.hcl
terraform {
  extra_arguments "common_vars" {
    commands = get_terraform_commands_that_need_vars()
    arguments = [
      "-var-file=${find_in_parent_folders("account.hcl")}",
      "-var-file=${find_in_parent_folders("env.hcl")}",
    ]
  }
}

remote_state {
  backend = "s3"
  config = {
    bucket         = "csd-terraform-state-${get_env("CSD_AWS_ACCOUNT_ID", "905418043725")}"
    key            = "${path_relative_to_include()}/terraform.tfstate"
    region         = "af-south-1"
    encrypt        = true
    dynamodb_table = "csd-terraform-locks"
  }
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
provider "aws" {
  region = "af-south-1"
  default_tags {
    tags = {
      Environment = "${get_env("ENVIRONMENT", "test")}"
      ManagedBy   = "Terragrunt"
      Project     = "csd-chatbot"
    }
  }
}
EOF
}
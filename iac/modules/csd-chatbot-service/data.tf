# Data sources for existing resources (TEST environment only)

data "aws_caller_identity" "current" {}

# Resolve API key secret ARN by name when using pipeline-generated secret (csd-chatbot/api-key-<env>)
data "aws_secretsmanager_secret" "api_key_by_name" {
  count  = var.api_key_secret_name != "" ? 1 : 0
  name   = var.api_key_secret_name
}

locals {
  api_key_secret_arn = var.api_key_secret_name != "" ? data.aws_secretsmanager_secret.api_key_by_name[0].arn : var.api_key_secret_arn
}

data "aws_ecs_cluster" "existing" {
  count = var.existing_cluster_name != "" ? 1 : 0
  cluster_name = var.existing_cluster_name
}

data "aws_lb" "existing" {
  count = var.existing_alb_name != "" ? 1 : 0
  name = var.existing_alb_name
}

data "aws_lb_target_group" "existing" {
  count = var.existing_target_group_arn != "" ? 1 : 0
  arn = var.existing_target_group_arn
}


data "aws_secretsmanager_secret" "database" {
  name = "${var.environment}/csd-chatbot/database"
}

data "aws_secretsmanager_secret_version" "database" {
  secret_id = data.aws_secretsmanager_secret.database.id
}

locals {
  db_credentials = jsondecode(data.aws_secretsmanager_secret_version.database.secret_string)
}

output "secret_arn" {
  description = "ARN of the database secret"
  value = data.aws_secretsmanager_secret.database.arn
}

output "db_username" {
  description = "Database username from secret"
  value = local.db_credentials.username
}

output "db_password" {
  description = "Database password from secret"
  value = local.db_credentials.password
  sensitive = true
}

output "connection_string" {
  description = "Full PostgreSQL connection string"
  value = "postgresql://${local.db_credentials.username}:${local.db_credentials.password}@${data.aws_rds_cluster.existing[0].endpoint}:5432/${local.db_credentials.dbname}"
  sensitive = true
}

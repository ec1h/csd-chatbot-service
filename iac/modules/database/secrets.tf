data "aws_secretsmanager_secret" "database" {
  name = "${var.environment}/csd-chatbot/database"
}

data "aws_secretsmanager_secret_version" "database" {
  secret_id = data.aws_secretsmanager_secret.database.id
}

locals {
  raw_secret   = data.aws_secretsmanager_secret_version.database.secret_string
  is_json      = length(regexall("^\\s*\\{", local.raw_secret)) > 0
  parsed       = local.is_json ? jsondecode(local.raw_secret) : null
  # When JSON: use parsed keys (AWS RDS secret uses username/password/dbname or similar). When plain: use RDS instance/cluster for user/dbname and raw as password.
  db_username  = local.is_json ? try(local.parsed.username, local.parsed.master_username, "") : (var.db_instance_identifier != "" ? data.aws_db_instance.existing[0].master_username : data.aws_rds_cluster.existing[0].master_username)
  db_password  = local.is_json ? try(local.parsed.password, "") : local.raw_secret
  db_dbname    = local.is_json ? try(local.parsed.dbname, local.parsed.database, "") : (var.db_instance_identifier != "" ? data.aws_db_instance.existing[0].db_name : "")
  db_host      = var.db_instance_identifier != "" ? data.aws_db_instance.existing[0].address : data.aws_rds_cluster.existing[0].endpoint
  db_port      = var.db_instance_identifier != "" ? tostring(data.aws_db_instance.existing[0].port) : "5432"
}

output "secret_arn" {
  description = "ARN of the database secret"
  value       = data.aws_secretsmanager_secret.database.arn
}

output "db_username" {
  description = "Database username from secret or RDS"
  value       = local.db_username
}

output "db_password" {
  description = "Database password from secret"
  value       = local.db_password
  sensitive   = true
}

output "connection_string" {
  description = "Full PostgreSQL connection string"
  value       = "postgresql://${local.db_username}:${local.db_password}@${local.db_host}:${local.db_port}/${local.db_dbname}"
  sensitive   = true
}

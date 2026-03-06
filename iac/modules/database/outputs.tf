data "aws_rds_cluster" "existing" {
  count = var.db_cluster_identifier != "" ? 1 : 0
  cluster_identifier = var.db_cluster_identifier
}

data "aws_db_instance" "existing" {
  count = var.db_instance_identifier != "" ? 1 : 0
  db_instance_identifier = var.db_instance_identifier
}

locals {
  # For clusters
  cluster_endpoint = try(data.aws_rds_cluster.existing[0].endpoint, "")
  cluster_reader_endpoint = try(data.aws_rds_cluster.existing[0].reader_endpoint, "")
  cluster_arn = try(data.aws_rds_cluster.existing[0].arn, "")
  
  # For instances
  instance_endpoint = try(data.aws_db_instance.existing[0].endpoint, "")
  instance_arn = try(data.aws_db_instance.existing[0].db_instance_arn, "")
  instance_db_name = try(data.aws_db_instance.existing[0].db_name, "")
  instance_username = try(data.aws_db_instance.existing[0].master_username, "")
}

output "endpoint" {
  description = "Database endpoint"
  value = var.db_cluster_identifier != "" ? local.cluster_endpoint : local.instance_endpoint
}

output "arn" {
  description = "Database ARN"
  value = var.db_cluster_identifier != "" ? local.cluster_arn : local.instance_arn
}

output "db_name" {
  description = "Database name"
  value = var.db_cluster_identifier != "" ? "" : local.instance_db_name
}

output "username" {
  description = "Master username"
  value = var.db_cluster_identifier != "" ? "" : local.instance_username
}

output "is_cluster" {
  description = "Whether this is a cluster"
  value = var.db_cluster_identifier != ""
}

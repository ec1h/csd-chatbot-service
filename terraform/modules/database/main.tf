terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

resource "random_password" "db_password" {
  length  = 16
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.environment}-csd-chatbot-db-subnet-group"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.environment}-csd-chatbot-db-subnet-group"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.environment}-csd-chatbot-rds-sg"
  description = "Security group for CSD Chatbot RDS — inbound PostgreSQL from VPC only"
  vpc_id      = var.vpc_id

  ingress {
    description = "PostgreSQL from ECS tasks"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.environment}-csd-chatbot-rds-sg"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}

resource "aws_db_instance" "main" {
  identifier = "${var.environment}-csd-chatbot-db"

  engine         = "postgres"
  engine_version = "15.4"
  instance_class = var.instance_class

  db_name  = "csd_chatbot"
  username = "csd_chatbot"
  password = random_password.db_password.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_encrypted     = true
  storage_type          = "gp3"

  backup_retention_period = var.backup_retention_period
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  skip_final_snapshot = true
  deletion_protection = false

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = {
    Name        = "${var.environment}-csd-chatbot-db"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name = "${var.environment}/csd-chatbot/database"

  tags = {
    Name        = "${var.environment}-csd-chatbot-db-credentials"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id

  secret_string = jsonencode({
    username          = aws_db_instance.main.username
    password          = random_password.db_password.result
    host              = aws_db_instance.main.address
    port              = aws_db_instance.main.port
    database          = aws_db_instance.main.db_name
    connection_string = "postgresql://${aws_db_instance.main.username}:${random_password.db_password.result}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${aws_db_instance.main.db_name}"
  })
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "database_port" {
  value = aws_db_instance.main.port
}

output "database_name" {
  value = aws_db_instance.main.db_name
}

output "secrets_manager_arn" {
  value = aws_secretsmanager_secret.db_credentials.arn
}

output "security_group_id" {
  value = aws_security_group.rds.id
}

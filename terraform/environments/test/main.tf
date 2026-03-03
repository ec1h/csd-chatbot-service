terraform {
  backend "s3" {
    bucket         = "csd-terraform-state-905418043725"
    key            = "csd-chatbot/test/terraform.tfstate"
    region         = "af-south-1"
    dynamodb_table = "terraform-state-locks"
    encrypt        = true
  }

  required_version = ">= 1.0"
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

provider "aws" {
  region = "af-south-1"
}

provider "random" {}

data "aws_caller_identity" "current" {}


data "aws_vpc" "test" {
  id = "vpc-0c70f9c141381565b"
}

data "aws_subnets" "test_private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.test.id]
  }
  filter {
    name   = "tag:Name"
    values = ["*private*"]
  }
}

data "aws_ecs_cluster" "test" {
  cluster_name = "csd-test-cluster"
}

data "aws_iam_role" "ecs_execution" {
  name = "ecsTaskExecutionRole"
}

data "aws_iam_role" "ecs_task" {
  name = "ecsTaskRole"
}

data "aws_secretsmanager_secret" "azure_openai" {
  name = "test/csd-chatbot/azure-openai"
}


module "database" {
  source = "../../modules/database"

  environment    = "test"
  vpc_id         = data.aws_vpc.test.id
  vpc_cidr       = data.aws_vpc.test.cidr_block
  subnet_ids     = data.aws_subnets.test_private.ids
  instance_class = "db.t3.small"
}


resource "aws_ecr_repository" "chatbot" {
  name                 = "csd-chatbot-test"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "csd-chatbot-test"
    Environment = "test"
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}

resource "aws_ecr_lifecycle_policy" "chatbot" {
  repository = aws_ecr_repository.chatbot.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}


resource "aws_cloudwatch_log_group" "chatbot" {
  name              = "/ecs/csd-chatbot-test"
  retention_in_days = 30

  tags = {
    Name        = "csd-chatbot-test-logs"
    Environment = "test"
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}


resource "aws_ecs_task_definition" "chatbot" {
  family                   = "csd-chatbot-test"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = data.aws_iam_role.ecs_execution.arn
  task_role_arn            = data.aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "chatbot"
      image     = "${aws_ecr_repository.chatbot.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = 8001
          hostPort      = 8001
          protocol      = "tcp"
          name          = "chatbot-8001"
        }
      ]

      environment = [
        { name = "ENV",                       value = "test" },
        { name = "LOG_LEVEL",                 value = "DEBUG" },
        { name = "USE_OPTIMIZED_PIPELINE",    value = "true" },
        { name = "MAX_CLARIFICATION_TURNS",   value = "3" }
      ]

      secrets = [
        {
          name      = "POSTGRES_URI"
          valueFrom = "${module.database.secrets_manager_arn}:connection_string::"
        },
        {
          name      = "AZURE_OPENAI_API_KEY"
          valueFrom = "${data.aws_secretsmanager_secret.azure_openai.arn}:api_key::"
        },
        {
          name      = "AZURE_OPENAI_ENDPOINT"
          valueFrom = "${data.aws_secretsmanager_secret.azure_openai.arn}:endpoint::"
        },
        {
          name      = "AZURE_OPENAI_DEPLOYMENT"
          valueFrom = "${data.aws_secretsmanager_secret.azure_openai.arn}:deployment::"
        },
        {
          name      = "AZURE_OPENAI_API_VERSION"
          valueFrom = "${data.aws_secretsmanager_secret.azure_openai.arn}:api_version::"
        },
        {
          name      = "AZURE_OPENAI_MODEL_NAME"
          valueFrom = "${data.aws_secretsmanager_secret.azure_openai.arn}:deployment::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.chatbot.name
          "awslogs-region"        = "af-south-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name        = "csd-chatbot-test"
    Environment = "test"
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}


resource "aws_ecs_service" "chatbot" {
  name            = "csd-chatbot-test"
  cluster         = data.aws_ecs_cluster.test.id
  task_definition = aws_ecs_task_definition.chatbot.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    security_groups  = [module.database.security_group_id]
    subnets          = data.aws_subnets.test_private.ids
    assign_public_ip = false
  }

  force_new_deployment = true

  tags = {
    Name        = "csd-chatbot-test"
    Environment = "test"
    ManagedBy   = "Terraform"
    Service     = "csd-chatbot"
  }
}


output "ecr_repository_url" {
  value       = aws_ecr_repository.chatbot.repository_url
  description = "ECR repository URL — use this to tag and push the Docker image"
}

output "database_endpoint" {
  value       = module.database.database_endpoint
  description = "RDS endpoint for the test database"
}

output "database_secret_arn" {
  value       = module.database.secrets_manager_arn
  description = "Secrets Manager ARN for the database credentials"
}

output "azure_openai_secret_arn" {
  value       = data.aws_secretsmanager_secret.azure_openai.arn
  description = "Secrets Manager ARN for the Azure OpenAI credentials"
}

output "ecs_service_name" {
  value       = aws_ecs_service.chatbot.name
  description = "ECS service name"
}

output "ecs_cluster_name" {
  value       = data.aws_ecs_cluster.test.cluster_name
  description = "ECS cluster name"
}

output "cloudwatch_log_group" {
  value       = aws_cloudwatch_log_group.chatbot.name
  description = "CloudWatch log group for ECS container logs"
}

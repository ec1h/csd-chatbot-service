# ECS Cluster - Use existing if provided, otherwise create new
locals {
  cluster_id = var.existing_cluster_name != "" ? data.aws_ecs_cluster.existing[0].id : aws_ecs_cluster.main[0].id
}

# Create new cluster only if not using existing
resource "aws_ecs_cluster" "main" {
  count = var.existing_cluster_name != "" ? 0 : 1
  name = "csd-chatbot-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs.name
      }
    }
  }

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

# Task Definition (always create new)
resource "aws_ecs_task_definition" "app" {
  family                   = "csd-chatbot-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "chatbot"
      image     = "${data.aws_caller_identity.current.account_id}.dkr.ecr.af-south-1.amazonaws.com/csd-chatbot-${var.environment}:${var.service_version}"
      essential = true

      portMappings = [
        {
          containerPort = 8001
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "LOG_LEVEL"
          value = var.log_level
        },
        {
          name  = "USE_OPTIMIZED_PIPELINE"
          value = "true"
        },
        {
          name  = "MAX_CLARIFICATION_TURNS"
          value = "3"
        },
        {
          name  = "AZURE_OPENAI_ENDPOINT"
          value = var.azure_openai_endpoint
        },
        {
          name  = "AZURE_OPENAI_DEPLOYMENT"
          value = var.azure_openai_deployment
        },
        {
          name  = "AZURE_OPENAI_API_VERSION"
          value = var.azure_openai_api_version
        },
        {
          name  = "ALLOWED_ORIGINS"
          value = join(",", var.allowed_origins)
        },
        {
          name  = "CALL_TYPES_DATA_PATH"
          value = var.call_types_data_path
        }
      ]

      secrets = [
        {
          name      = "POSTGRES_URI"
          valueFrom = "${var.database_secret_arn}:postgresql_uri::"
        },
        {
          name      = "AZURE_OPENAI_API_KEY"
          valueFrom = var.azure_openai_api_key_secret_arn
        },
        {
          name      = "API_KEY"
          valueFrom = var.api_key_secret_arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
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

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

# ECS Service
resource "aws_ecs_service" "app" {
  name            = "csd-chatbot-${var.environment}"
  cluster         = local.cluster_id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.existing_target_group_arn != "" ? var.existing_target_group_arn : aws_lb_target_group.main.arn
    container_name   = "chatbot"
    container_port   = 8001
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  health_check_grace_period_seconds = 60

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

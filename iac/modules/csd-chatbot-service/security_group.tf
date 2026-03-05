# ALB Security Group
resource "aws_security_group" "alb" {
  name        = "csd-chatbot-alb-${var.environment}"
  description = "Security group for CSD Chatbot ALB"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from internet"
  }

  dynamic "ingress" {
    for_each = var.enable_https ? [1] : []
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "HTTPS from internet"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Outbound to anywhere"
  }

  tags = merge(var.tags, {
    Name        = "csd-chatbot-alb-${var.environment}"
    Environment = var.environment
  })
}

# ECS Tasks Security Group
resource "aws_security_group" "ecs_tasks" {
  name        = "csd-chatbot-ecs-${var.environment}"
  description = "Security group for CSD Chatbot ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 8001
    to_port         = 8001
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Traffic from ALB"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Outbound internet access"
  }

  tags = merge(var.tags, {
    Name        = "csd-chatbot-ecs-${var.environment}"
    Environment = var.environment
  })
}
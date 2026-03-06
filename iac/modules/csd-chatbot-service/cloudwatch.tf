# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/csd-chatbot-${var.environment}"
  retention_in_days = 30

  tags = merge(var.tags, {
    Environment = var.environment
  })

  lifecycle {
    prevent_destroy = true
  }
}

# CloudWatch Dashboard
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "csd-chatbot-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", { stat = "Average" }],
            ["AWS/ECS", "MemoryUtilization", { stat = "Average" }]
          ]
          period = 300
          stat   = "Average"
          region = "af-south-1"
          title  = "ECS Task Resource Utilization"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", { stat = "Average" }],
            ["AWS/ApplicationELB", "RequestCount", { stat = "Sum" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", { stat = "Sum" }]
          ]
          period = 300
          stat   = "Average"
          region = "af-south-1"
          title  = "ALB Metrics"
        }
      },
      {
        type = "log"
        properties = {
          query  = "SOURCE '/ecs/csd-chatbot-${var.environment}' | fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20"
          region = "af-south-1"
          title  = "Recent Errors"
        }
      }
    ]
  })
}

# CloudWatch Alarms
resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "csd-chatbot-high-cpu-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "This alarm monitors ECS task CPU utilization"
  alarm_actions       = []  # Add SNS topic ARN here
  
  dimensions = {
    ClusterName = var.existing_cluster_name != "" ? var.existing_cluster_name : (
      length(aws_ecs_cluster.main) > 0 ? aws_ecs_cluster.main[0].name : null
    )
    ServiceName = aws_ecs_service.app.name
  }

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

resource "aws_cloudwatch_metric_alarm" "high_5xx" {
  alarm_name          = "csd-chatbot-5xx-errors-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "This alarm monitors ALB 5xx errors"
  alarm_actions       = []  # Add SNS topic ARN here
  
  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.main.arn_suffix
  }

  tags = merge(var.tags, {
    Environment = var.environment
  })
}
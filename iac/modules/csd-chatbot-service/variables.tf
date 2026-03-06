variable "environment" {
  description = "Environment name (test, qa, uat, prod)"
  type        = string
}

variable "service_version" {
  description = "Version of the service to deploy (commit hash or tag)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs"
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs"
  type        = list(string)
}

variable "database_secret_arn" {
  description = "ARN of the database secret"
  type        = string
}

variable "task_cpu" {
  description = "CPU units for the task"
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Memory for the task"
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Desired number of tasks"
  type        = number
  default     = 1
}

variable "log_level" {
  description = "Log level"
  type        = string
  default     = "INFO"
}

variable "call_types_data_path" {
  description = "Path to call types data file"
  type        = string
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint"
  type        = string
}

variable "azure_openai_deployment" {
  description = "Azure OpenAI deployment name"
  type        = string
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version"
  type        = string
  default     = "2024-12-01-preview"
}

variable "azure_openai_api_key_secret_arn" {
  description = "ARN of the Azure OpenAI API key secret"
  type        = string
}

variable "api_key_secret_arn" {
  description = "ARN of the API key secret (used when api_key_secret_name is not set)"
  type        = string
  default     = ""
}

variable "api_key_secret_name" {
  description = "Name of the API key secret in Secrets Manager (e.g. csd-chatbot/api-key-test). When set, ARN is looked up and used instead of api_key_secret_arn."
  type        = string
  default     = ""
}

variable "allowed_origins" {
  description = "List of allowed CORS origins"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "enable_https" {
  description = "Enable HTTPS listener"
  type        = bool
  default     = false
}

variable "ssl_certificate_arn" {
  description = "ARN of SSL certificate"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
# Variables for referencing existing resources (TEST mode)
variable "existing_cluster_name" {
  description = "Name of existing ECS cluster (for TEST)"
  type        = string
  default     = ""
}

variable "existing_alb_name" {
  description = "Name of existing ALB (for TEST)"
  type        = string
  default     = ""
}

variable "existing_target_group_arn" {
  description = "ARN of existing target group (for TEST)"
  type        = string
  default     = ""
}

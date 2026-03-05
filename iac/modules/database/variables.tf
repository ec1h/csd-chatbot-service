variable "environment" {
  description = "Environment name"
  type        = string
}

variable "db_cluster_identifier" {
  description = "Existing database cluster identifier"
  type        = string
  default     = ""
}

variable "db_instance_identifier" {
  description = "Existing database instance identifier (for non-cluster)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply"
  type        = map(string)
  default     = {}
}

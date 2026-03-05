terraform {
  required_version = ">= 1.0"
  backend "s3" {}  # Empty backend - Terragrunt will configure this
}

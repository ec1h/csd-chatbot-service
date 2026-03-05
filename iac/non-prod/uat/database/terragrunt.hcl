include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//database"
}

inputs = {
  environment = "uat"
  db_cluster_identifier = "csd-database-cluster-uat"
}

dependency "secrets" {
  config_path = "../secrets"
}

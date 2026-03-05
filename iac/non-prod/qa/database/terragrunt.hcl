include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//database"
}

inputs = {
  environment = "qa"
  db_cluster_identifier = "csd-database-cluster-qa"
}

dependency "secrets" {
  config_path = "../secrets"
}

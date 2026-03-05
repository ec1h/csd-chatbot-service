include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//database"
}

inputs = {
  environment = "prod"
  db_cluster_identifier = "csd-database-cluster-prod"
}

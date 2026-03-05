include {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules//vpc-data"
}

inputs = {
  vpc_id      = "vpc-0c70f9c141381565b"
  environment = "test"
}

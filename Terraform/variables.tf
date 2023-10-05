variable "aws_region" {
  default = "us-east-1"
}

variable "items_dynamodb_table" {
  default = "Get table Name from the SAM deployment, AccountExceptions table"
}

variable "regions_dynamodb_table" {
  default = "Get table Name from the SAM deployment, RegionsDynamoDBTable table"
}

variable "lambda_function_name" {
  default = "process_ddb_lambda"
}

variable "bucket_name" {
  default = "set a valid name"
}
variable "SecurityHubAdminAccountId" {
  default = 12345678901
}
variable "state_machine_arn" {
  default = "arn:aws:states:XXXXXXX"
}
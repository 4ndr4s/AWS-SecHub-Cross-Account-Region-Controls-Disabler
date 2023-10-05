provider "archive" {}
data "archive_file" "process_ddb_lambda_zip_file" {
	type        = "zip"
	source_file = "lambda/lambda_handlers.py"
	output_path = "lambda/ddb_lambda.zip"
}

resource "aws_lambda_function" "process_ddb_lambda" {
	function_name    = var.lambda_function_name
	filename          = data.archive_file.process_ddb_lambda_zip_file.output_path
	role             = aws_iam_role.ddb_lambda_process.arn
	handler          = "lambda_handlers.lambda_handler"
	runtime          = "python3.10"
  source_code_hash = data.archive_file.process_ddb_lambda_zip_file.output_base64sha256
  timeout                        = 900
  environment {
        variables = {
            "ItemsDynamoDB"  = var.items_dynamodb_table
            "RegionsDynamoDB" = var.regions_dynamodb_table
            "items_json_file" = "items.json"
            "accounts_json_file" = "accounts.json"
            "StateMachineArn" = var.state_machine_arn
        }
    }
}

resource "aws_s3_bucket" "items_bucket" {
  bucket = "${var.bucket_name}-${substr(uuid(), 0, 6)}"
  lifecycle {
    ignore_changes        = [bucket]
    create_before_destroy = true
  }
}


resource "aws_s3_bucket_notification" "aws_lambda_trigger" {
  bucket = aws_s3_bucket.items_bucket.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.process_ddb_lambda.arn
    events              = ["s3:ObjectCreated:*"]

  }
  depends_on = [aws_lambda_permission.ddb_lambda_invoke]
}

resource "aws_lambda_permission" "ddb_lambda_invoke" {
    action        = "lambda:InvokeFunction"
    function_name = aws_lambda_function.process_ddb_lambda.function_name
    principal     = "s3.amazonaws.com"
    source_arn    = aws_s3_bucket.items_bucket.arn
    statement_id  = "AllowS3Invoke"
}

resource "aws_s3_object" "object_upload" {
    bucket                 = aws_s3_bucket.items_bucket.id
    key                    = "items.json"
    source                 = "lambda/items.json"
    # The filemd5() function is available in Terraform 0.11.12 and later
    # For Terraform 0.11.11 and earlier, use the md5() function and the file() function:
    # etag = "${md5(file("path/to/file"))}"
    etag = filemd5("lambda/items.json")
    depends_on = [aws_s3_bucket.items_bucket]
}

resource "aws_s3_object" "accounts_object_upload" {
  bucket = aws_s3_bucket.items_bucket.id
  key    = "accounts.json"
  source = "lambda/accounts.json"
  # The filemd5() function is available in Terraform 0.11.12 and later
  # For Terraform 0.11.11 and earlier, use the md5() function and the file() function:
  # etag = "${md5(file("path/to/file"))}"
  etag       = filemd5("lambda/accounts.json")
  depends_on = [aws_s3_bucket.items_bucket]
}


resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 30
}
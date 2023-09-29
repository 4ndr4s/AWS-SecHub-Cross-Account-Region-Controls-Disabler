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
            "DynamoDB"  = var.dynamodb_table
            "json_file" = "items.json"

        }
    }
}

resource "aws_s3_bucket_notification" "aws-lambda-trigger" {
  bucket = var.s3_bucket
  lambda_function {
    lambda_function_arn = aws_lambda_function.process_ddb_lambda.arn
    events              = ["s3:ObjectCreated:*"]

  }
}

resource "aws_lambda_permission" "ddb_lambda_invoke" {
    action        = "lambda:InvokeFunction"
    function_name = aws_lambda_function.process_ddb_lambda.function_name
    principal     = "s3.amazonaws.com"
    source_arn    = "arn:aws:s3:::${var.s3_bucket}"
    statement_id  = "AllowS3Invoke"
}

resource "aws_s3_object" "object_upload" {
    bucket                 = var.s3_bucket
    key                    = "items.json"
    source                 = "lambda/items.json"
    # The filemd5() function is available in Terraform 0.11.12 and later
    # For Terraform 0.11.11 and earlier, use the md5() function and the file() function:
    # etag = "${md5(file("path/to/file"))}"
    etag = filemd5("lambda/items.json")
}

resource "aws_cloudwatch_log_group" "ddb_lambda_chatbot" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 30
}
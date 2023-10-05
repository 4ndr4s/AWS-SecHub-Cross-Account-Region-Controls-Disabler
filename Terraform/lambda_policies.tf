data "aws_iam_policy_document" "ddb_lambda_policy" {
	statement {
		sid    = "DDBLambdaPolicyId"
		effect = "Allow"
		principals {
			identifiers = ["lambda.amazonaws.com"]
			type        = "Service"
		}
		actions = ["sts:AssumeRole"]
	}
}

data "aws_iam_policy_document" "ddb_lambda_policy_doc" {
  statement {
    effect = "Allow"
    actions = [
        "dynamodb:DescribeTable",
         "dynamodb:Scan",
         "dynamodb:Query",
         "dynamodb:PutItem",
         "dynamodb:GetItem",
         "dynamodb:UpdateItem"
    ]
    resources = ["arn:aws:dynamodb:us-east-1:${var.SecurityHubAdminAccountId}:table/${var.items_dynamodb_table}",
                "arn:aws:dynamodb:us-east-1:${var.SecurityHubAdminAccountId}:table/${var.regions_dynamodb_table}"]
  }
  statement {
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["*"]
  }
  statement {
    effect = "Allow"

    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket"
    ]

    resources = ["${aws_s3_bucket.items_bucket.arn}", "${aws_s3_bucket.items_bucket.arn}/*"]
  }
  statement {
    effect = "Allow"

    actions = [
      "states:StartExecution",
      "states:ListExecutions"
    ]

    resources = [var.state_machine_arn]
  }
}

resource "aws_iam_policy" "ddb_execution_policy" {
  name   = "ddb_lambda_policy"
  policy = data.aws_iam_policy_document.ddb_lambda_policy_doc.json
}

resource "aws_iam_role" "ddb_lambda_process" {
	name               = "ddb_lambda_process"
	assume_role_policy = data.aws_iam_policy_document.ddb_lambda_policy.json
}

resource "aws_iam_role_policy_attachment" "ec2_policy_attachment" {
  role       = aws_iam_role.ddb_lambda_process.name
  policy_arn = aws_iam_policy.ddb_execution_policy.arn
}
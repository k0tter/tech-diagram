provider "aws" {
  region = var.region
}

# --- ネットワーク ---
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
}

resource "aws_subnet" "private" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.2.0/24"
}

# --- データストア ---
resource "aws_dynamodb_table" "orders" {
  name         = "orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "order_id"
  attribute {
    name = "order_id"
    type = "S"
  }
}

resource "aws_s3_bucket" "assets" {
  bucket = "orders-api-assets"
}

# --- 非同期処理 ---
resource "aws_sqs_queue" "jobs" {
  name = "orders-jobs"
}

# --- Lambda(2本)---
resource "aws_lambda_function" "api_handler" {
  function_name = "orders-api-handler"
  runtime       = "nodejs20.x"
  handler       = "index.handler"
  filename      = "src/api_handler"
  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.orders.name
      QUEUE_URL  = aws_sqs_queue.jobs.url
    }
  }
}

resource "aws_lambda_function" "queue_worker" {
  function_name = "orders-queue-worker"
  runtime       = "nodejs20.x"
  handler       = "index.handler"
  filename      = "src/queue_worker"
  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.orders.name
    }
  }
}

# --- トリガー配線 ---
resource "aws_lambda_event_source_mapping" "jobs_to_worker" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.queue_worker.arn
}

resource "aws_api_gateway_rest_api" "api" {
  name = "orders-api"
}

# --- 条件付き(既定 false=このリポジトリでは未適用のデッドコード)---
resource "aws_wafv2_web_acl" "front" {
  count = var.enable_waf ? 1 : 0
  name  = "orders-waf"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "orders-waf"
    sampled_requests_enabled   = true
  }
}

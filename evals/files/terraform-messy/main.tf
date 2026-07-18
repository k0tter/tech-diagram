provider "aws" {
  region = var.region
}

locals {
  lambda_fns = {
    ingest    = { handler = "index.handler", dir = "src/ingest" }
    transform = { handler = "index.handler", dir = "src/transform" }
  }
}

resource "aws_vpc" "main" {
  cidr_block = "10.1.0.0/16"
}

resource "aws_subnet" "app" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.1.1.0/24"
}

# dynamic ブロック(パーサのサブセット外になりがちなノイズ)
resource "aws_security_group" "app" {
  vpc_id = aws_vpc.main.id
  dynamic "ingress" {
    for_each = [443, 8080]
    content {
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/8"]
    }
  }
}

resource "aws_dynamodb_table" "events" {
  name         = "events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"
  attribute {
    name = "event_id"
    type = "S"
  }
}

# for_each 展開(2インスタンス)。env は両方 events テーブル参照
resource "aws_lambda_function" "fn" {
  for_each      = local.lambda_fns
  function_name = "evt-${each.key}"
  runtime       = "nodejs20.x"
  handler       = each.value.handler
  filename      = each.value.dir
  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.events.name
      QUEUE_URL  = module.queue.url
    }
  }
}

# ローカルモジュール(SQS 本体+DLQ を内包)
module "queue" {
  source = "./modules/queue"
  name   = "evt-jobs"
}

resource "aws_lambda_event_source_mapping" "q_to_transform" {
  event_source_arn = module.queue.arn
  function_name    = aws_lambda_function.fn["transform"].arn
}

resource "aws_api_gateway_rest_api" "api" {
  name = "events-api"
}

# 条件付きだが既定 true = このリポジトリでは稼働している
resource "aws_wafv2_web_acl" "front" {
  count = var.enable_waf ? 1 : 0
  name  = "events-waf"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "events-waf"
    sampled_requests_enabled   = true
  }
}

# どこからも参照されない孤児モジュール(レガシー残骸)
module "legacy" {
  source = "./modules/legacy"
}

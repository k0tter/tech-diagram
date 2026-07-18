variable "name" {
  type = string
}

resource "aws_sqs_queue" "dlq" {
  name = "${var.name}-dlq"
}

resource "aws_sqs_queue" "main" {
  name = var.name
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

output "url" {
  value = aws_sqs_queue.main.url
}

output "arn" {
  value = aws_sqs_queue.main.arn
}

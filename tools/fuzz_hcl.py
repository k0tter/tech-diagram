#!/usr/bin/env python3
"""tf_to_spec の頑健性ファザー(CI スモーク用)。

変異 HCL・完全なゴミ入力を投げ、クラッシュ / ハング / 不正 JSON 出力が
ゼロであることを確認する。シード固定で再現可能。

使い方: python3 tools/fuzz_hcl.py [ケース数=100]
終了コード: 問題ゼロなら 0、あれば 1(再現シードを表示)
"""

from __future__ import annotations

import json
import random
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "scripts" / "tf_to_spec.py"

BASE = '''
variable "enable_dr" { default = false }

resource "aws_apigatewayv2_api" "api" {
  name          = "orders-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "i" {
  api_id          = aws_apigatewayv2_api.api.id
  integration_uri = aws_lambda_function.fn.invoke_arn
}

data "archive_file" "zip" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/dist/fn.zip"
}

resource "aws_lambda_function" "fn" {
  function_name = "fn"
  filename      = data.archive_file.zip.output_path
  handler       = "h.main"
  policy        = <<EOT
{"Statement": [{"Action": "dynamodb:*"}]}
EOT
  environment {
    variables = {
      TABLE = aws_dynamodb_table.t.name
      QUEUE = aws_sqs_queue.q.url
    }
  }
}

resource "aws_dynamodb_table" "t" {
  name     = "t"
  hash_key = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_sqs_queue" "q" { name = "q" }

resource "aws_lambda_event_source_mapping" "m" {
  event_source_arn = aws_sqs_queue.q.arn
  function_name    = aws_lambda_function.fn.arn
}

resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }
resource "aws_subnet" "s" {
  vpc_id                  = aws_vpc.v.id
  map_public_ip_on_launch = true
}
resource "aws_instance" "web" { subnet_id = aws_subnet.s.id }

module "app" { source = "./modules/app" }

resource "aws_dynamodb_table" "dr" {
  count    = var.enable_dr ? 1 : 0
  name     = "dr"
  hash_key = "id"
}
'''

MODULE = '''
resource "aws_sns_topic" "t" { name = "t" }
output "topic_arn" { value = aws_sns_topic.t.arn }
'''


def mutate(rnd: random.Random, text: str) -> str:
    for _ in range(rnd.randint(1, 6)):
        if not text:
            break
        i = rnd.randrange(len(text))
        op = rnd.randrange(7)
        if op == 0:
            text = text[:i] + text[i + 1:]
        elif op == 1:
            text = text[:i] + rnd.choice('{}"()[]=$#<\n\\') + text[i:]
        elif op == 2:
            j = min(len(text), i + rnd.randrange(200))
            text = text[:j] + text[i:j] + text[j:]
        elif op == 3:
            text = text[:i]
        elif op == 4:
            text = text[:i] + '\npolicy = <<EOT\n{"x": 1}\n' + text[i:]
        elif op == 5:
            text = text[:i] + "x" * rnd.randrange(1, 3000) + text[i:]
        else:
            text = text[:i] + "".join(
                rnd.choices(string.printable, k=80)) + text[i:]
    return text


def run_case(seed: int) -> str | None:
    rnd = random.Random(seed)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "modules" / "app").mkdir(parents=True)
        (root / "modules" / "app" / "main.tf").write_text(
            MODULE if seed % 3 else mutate(rnd, MODULE), encoding="utf-8")
        if seed % 5 == 4:   # 完全なゴミ
            body = "".join(rnd.choices(string.printable,
                                       k=rnd.randrange(3000)))
        else:
            body = mutate(rnd, BASE)
        (root / "main.tf").write_text(body, encoding="utf-8")
        t0 = time.perf_counter()
        try:
            r = subprocess.run(
                [sys.executable, str(TOOL), td, "-o", f"{td}/o.spec.json",
                 "--review", f"{td}/o.review.json"],
                capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return f"HANG seed={seed}"
        if "Traceback" in r.stderr:
            return (f"CRASH seed={seed}: "
                    f"{r.stderr.strip().splitlines()[-1][:100]}")
        if time.perf_counter() - t0 > 20:
            return f"SLOW seed={seed}"
        if r.returncode == 0:
            for f in ("o.spec.json", "o.review.json"):
                try:
                    json.loads(Path(f"{td}/{f}").read_text(encoding="utf-8"))
                except Exception as e:
                    return f"BADJSON seed={seed} {f}: {e}"
    return None


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    problems = [p for p in (run_case(s) for s in range(n)) if p]
    print(f"fuzz_hcl: {n} cases, problems: {len(problems)}")
    for p in problems[:10]:
        print(" ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

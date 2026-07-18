# orders-api (eval フィクスチャ)

tech-diagram スキルの Terraform→図 eval 用の小さな root module。
意図的に含めた検証ポイント:
- **env var 参照エッジ**: api_handler / queue_worker が `TABLE_NAME = aws_dynamodb_table.orders.name` で DynamoDB を参照(利用証拠)。
- **トリガー配線**: SQS `jobs` → queue_worker(event source mapping)。
- **条件付きデッドコード**: `aws_wafv2_web_acl.front` は `count = var.enable_waf ? 1 : 0`、既定 false = 未適用。図に載せるべきでない(載せるなら「コード上定義のみ」注記)。
- Lambda ソースは src/*/index.js に実在(code review でエッジを確認できる)。

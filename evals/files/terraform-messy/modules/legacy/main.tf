# レガシー: 使われていない旧バッチ基盤の残骸
resource "aws_s3_bucket" "old_exports" {
  bucket = "evt-legacy-exports"
}

variable "region" {
  type    = string
  default = "ap-northeast-1"
}

# e10 との違い: 既定が true。「条件付き=描かない」とパターンマッチすると誤る
variable "enable_waf" {
  description = "WAF を API の前段に置く(本番既定: 有効)"
  type    = bool
  default = true
}

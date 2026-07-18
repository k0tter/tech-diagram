variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "enable_waf" {
  description = "WAF を前段に置くか。既定は無効(このリポジトリでは未適用)。"
  type        = bool
  default     = false
}

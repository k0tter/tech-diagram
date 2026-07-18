# Security Policy

[English](SECURITY.md) | [日本語](SECURITY.ja.md) | [Bahasa Indonesia](SECURITY.id.md)

## 脆弱性の報告

脆弱性は**公開 Issue に書かず**、GitHub の Private vulnerability reporting で報告してください:

1. [Security タブ → Report a vulnerability](https://github.com/k0tter/tech-diagram/security/advisories/new) を開く
2. 再現手順(可能なら再現スペック / 入力ファイル)と影響を記載して送信

報告は非公開の Security Advisory として届き、修正がリリースされるまで公開されません。
受領後 7 日以内に一次返信します。

## サポート範囲

| バージョン | サポート |
|---|---|
| 最新リリース([Releases](https://github.com/k0tter/tech-diagram/releases) の最新) | 対応する |
| それ以前 | 対応しない(最新へ更新してください) |

## 前提(攻撃面について)

- 実行時依存は Python 標準ライブラリのみで、スクリプトは**ネットワークアクセスを行いません**。
- 主な攻撃面は入力ファイル(`.spec.json` / `.tf` / `.drawio`)のパースです。
  ゴミ入力・敵対的入力への頑健性は CI のファザースモーク(`tools/fuzz_hcl.py` /
  `tools/fuzz_layout.py`)で継続検証しています。
- 配布 zip の完全性は、リリース資産の `SHA256SUMS` とビルド来歴の attestation で検証できます:

  ```bash
  sha256sum -c SHA256SUMS   # macOS は shasum -a 256 -c SHA256SUMS
  gh attestation verify tech-diagram-vX.Y.Z.zip --repo k0tter/tech-diagram
  ```

# reference-architectures — 検証済み起点スペック

作図依頼が定番パターン(`../patterns.md`)に合致したら、ここのスペックをコピーして
差分編集する(全て 0 エラー・0 警告・交差目安内でビルド確認済み)。各スペックの
正解ポイントは meta.assumptions に記載(図の冒頭パネルにも描画される — 納品物では
meta を依頼内容に合わせて書き換えること)。
ビルド: `python3 {SKILL}/scripts/build_drawio.py <spec> -o <out>.drawio`

| ファイル | パターン | 要点 | patterns.md |
|---|---|---|---|
| multiregion-dr.spec.json | マルチリージョン DR(active-passive 方式A) | オリジンのみ切替・CloudFront/WAF 共通の対称 failover。Aurora 一方向/DynamoDB 双方向/S3 CRR | P3 |
| three-tier-web.spec.json | 3層 Web(Multi-AZ) | アプリ/DB=private・スタンバイ読取不可・NAT egress・ALB=internet-facing(Public 列・AZ 間) | P1 |
| serverless-api.spec.json | サーバーレス API | Cognito 非直列・API GW regional・S3 OAC | P2 |
| static-site.spec.json | 静的サイト | CloudFront+S3 OAC(REST エンドポイント・非公開) | P6 |
| container-ecs.spec.json | コンテナ(ECS/Fargate) | タスク private・pull=NAT/VPC エンドポイントの 2 択・ALB=internet-facing(Public 列・AZ 間) | P7 |

- LB は複製せず、AZ 省略図=所属 subnet 内/AZ 明示図=所属 subnet と同列・AZ 間の 2 形態(SKILL.md)。scheme(internet-facing/internal)を明示する。
- P4(マルチアカウント)は `templates/example-multiaccount.spec.json` を起点にする。
- P5(イベント駆動)・P8(ハイブリッド)は patterns.md の要点に従い自由構成(境界は W8/W14 が機械検査)。

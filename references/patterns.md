# AWS 定番パターン正解カタログ(意味的正しさの作図基準)

依頼が下記パターンに合致したら自由作文せず、`reference-architectures/` の検証済み
スペック(全て 0 エラー・0 警告でビルド確認済み)をコピーして差分編集する。
合致しない構成は自由に組んでよいが、納品前に末尾のアンチパターン早見表で自己検査する。
URL は AWS 一次情報(2026-07-18 実在確認済み)。

## P1. 3層 Web(Multi-AZ)— `reference-architectures/three-tier-web.spec.json`

ユーザー→(Route 53)→[任意: CloudFront+WAF]→ALB(public)→EC2/ECS(private)→RDS(private・Multi-AZ)。
- 境界: アプリ・DB は private subnet。NAT は public subnet。外向き egress は NAT→IGW
- 冗長: 本番は 2AZ 以上。RDS Multi-AZ は別 AZ に同期スタンバイ(**読取不可** — 読取分散はリードレプリカ/Multi-AZ DB クラスター)
- よくある誤り: DB を public subnet に置く(AP6)/スタンバイへ読取線(AP10)
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html / https://docs.aws.amazon.com/vpc/latest/userguide/configure-subnets.html

## P2. サーバーレス API — `reference-architectures/serverless-api.spec.json`

静的: ユーザー→CloudFront→S3(OAC)。API: ①Cognito でトークン取得→②API Gateway(トークン検証)→Lambda→DynamoDB。
- Cognito はメイン経路に**直列に入れない**(トークン取得・検証の補助線で描く)
- 自前 CloudFront の背後に置く API Gateway は **regional**(edge-optimized は CDN 二重=AP7)
- AZ コンテナ不要(リージョン内冗長はサービス側が担う)。全ノード VPC 外(W8)
- よくある誤り: ユーザー→Cognito→API GW の直列(AP8)
- https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-integrate-with-cognito.html / https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-endpoint-types.html

## P3. マルチリージョン DR — `reference-architectures/multiregion-dr.spec.json`(最重要)

active-passive 方式A: ユーザー→CloudFront(+WAF global)→[オリジン=Route 53 failover レコード]→Primary/DR の ALB。
- **切り替えるのはオリジンだけ。CloudFront/WAF は平常時・障害時とも共通に通す(対称経路)**。
  Route 53→DR ALB 直行は WAF バイパスであり、ALB を CloudFront 限定に保護する推奨構成では
  フェイルオーバー時に全リクエスト 403 で DR が機能しない(REL13-BP04 構成ドリフト)
- 方式B(CloudFront origin group)は GET/HEAD/OPTIONS のみ・リクエスト単位 — 書込を含む DR の単独手段にしない
- データ層: Aurora Global=**一方向**複製(secondary は読取専用・昇格で書込可)/
  DynamoDB Global Tables=**双方向**(マルチアクティブ)/S3 CRR(RTC で 15 分 SLA)
- active/active では failover 線を描かず両経路とも実線(Route 53 latency/weighted 等+ヘルスチェック)
- 切替の自動/手動を説明文で明示(自動は誤検知コスト。手動起動+手順自動化が定番=AP13)
- https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_planning_for_recovery_config_drift.html / https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html
- https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-options-in-the-cloud.html / https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-global-database.html

## P4. マルチアカウント — `templates/example-multiaccount.spec.json`(既存テンプレを起点)

Organizations(OU 階層+SCP)+Network アカウントの Transit Gateway+集中 Egress VPC(NAT→IGW)。
- TGW は VPC 外・リージョナル(W14 検査)。集中 egress ではワークロード VPC に NAT/IGW を残さない(AP12)
- https://docs.aws.amazon.com/organizations/latest/userguide/orgs_introduction.html / https://docs.aws.amazon.com/whitepapers/latest/building-scalable-secure-multi-vpc-network-infrastructure/centralized-egress-to-internet.html

## P5. イベント駆動(EventBridge / SQS / Step Functions)

API GW→Lambda(薄い受付)→EventBridge(ルールで多対多配送)→SQS→Lambda(イベントソースマッピングが**ポーリング**・at-least-once)/Step Functions(オーケストレーション)。
- SQS→コンシューマは push ではない(線種は非同期に)。全て VPC 外(W8 検査)。ポイントツーポイントは Pipes
- https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html / https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html

## P6. 静的サイト — `reference-architectures/static-site.spec.json`

ユーザー→CloudFront→S3(**REST エンドポイント+OAC** でバケット非公開)。
- ユーザー→S3 の直行線を引かない。OAI はレガシー。website endpoint は OAC/OAI 不可(AP11)
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html

## P7. コンテナ(ECS/Fargate)— `reference-architectures/container-ecs.spec.json`

ユーザー→ALB(public)→タスク(private・複数 AZ)。外向き(image pull・外部 API)は NAT(public)→IGW。
- 代替: ECR/S3/CloudWatch へは VPC エンドポイント(endpoints アイコンを subnet 内に)で NAT 回避
- https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_fault_isolation_multiaz_region_system.html / https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/networking-best-practices.html

## P8. ハイブリッド(Direct Connect / Site-to-Site VPN)

DX: private VIF→VGW(単一 VPC)/ transit VIF→DX gateway→TGW(複数 VPC)。VPN は IPsec 2 トンネル(図では 1 本に集約可)。
- 配置は W14 検査(VGW=VPC 直下、DX/TGW=VPC 外)。DX 冗長は Resiliency Toolkit(Maximum/High/Dev&Test)
- 「DX のバックアップに VPN」は定番だが一次情報の明文は未確認 — 断定表現を避ける
- https://docs.aws.amazon.com/directconnect/latest/UserGuide/Welcome.html / https://docs.aws.amazon.com/vpn/latest/s2svpn/VPC_VPN.html

## アンチパターン早見表(納品前セルフチェック)

W コード付きの行はビルド段+バリデータが機械検査する(W17/W18/W19 は error =
ビルド拒否、W16/W20/W21 は warning)。コード無しの行は機械判定できない
(エンドポイントタイプ等が図に現れない)ため、このレビューゲートだけが網。

| ID | 誤り | 正しい形 |
|---|---|---|
| AP1 (W16) | failover 線が CloudFront/WAF をバイパスして DR の LB へ直行 | オリジンだけ切替。エッジスタックは共通・対称(P3) |
| AP2 (W17) | CloudFront/Route 53/WAF(CF 用)を region 内に描く | グローバル=aws_cloud 直下。切替対象はオリジン |
| AP3 (W20) | 「HA/Multi-AZ」の依頼なのに AZ コンテナが 1 つ | 2AZ 以上+Multi-AZ DB(P1) |
| AP4 | S3/DynamoDB/SQS 等を VPC/subnet 内に描く | VPC 外。私設アクセスは endpoints アイコン(W8 検査済み) |
| AP5 (W21) | private subnet から外部へ NAT 無しの直行線 | private→NAT(public)→IGW。AWS 宛は VPC エンドポイント |
| AP6 (W18/W19) | DB が public subnet/外部から DB へ直接線 | DB は private subnet。アクセスはアプリ層からのみ |
| AP7 | 自前 CloudFront→edge-optimized API GW の直列 | API Gateway を regional に(P2) |
| AP8 | ユーザー→Cognito→API GW とメイン経路に直列 | 認証は補助線。メインはユーザー→API GW(P2) |
| AP9 | Aurora Global の複製が双方向/secondary へ書込線 | 一方向複製・書込は primary のみ。多リージョン書込は DynamoDB GT |
| AP10 | RDS Multi-AZ スタンバイへ読取線 | スタンバイは読めない。読取分散はリードレプリカ等(P1) |
| AP11 | S3 website endpoint+OAC/OAI の組合せ | 非公開化は REST エンドポイント+OAC(P6) |
| AP12 | 集中 egress なのに各 VPC に NAT/IGW が残る | 出口は egress VPC のみ(P4) |
| AP13 | 「ヘルスチェックで自動切替」とだけ注記 | 切替の自動/手動と手順自動化を説明文で明示(P3) |

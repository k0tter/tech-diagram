# AWS アイコン名カタログ(頻出のみ・コンパクト版)

スペックの `nodes.icon` にはここにある **name** を書くだけでよい。
色・シェイプ・サイズはジェネレータが icons-data.tsv から自動解決する。
ここにない分だけ検索する(icons-data.tsv 全 960 種を Read で全読みしない):

```bash
# {SKILL} = 本スキルの base directory(SKILL.md §2 の記法)
python3 {SKILL}/scripts/find_icon.py <英語キーワード>
# 例: find_icon.py kafka / find_icon.py open search / find_icon.py --exact eks
```

XML を直接手編集するときだけスタイル文字列が要る → `find_icon.py --style <name>`
とコンテナ枠スタイル(references/layout-rules.md)を使う。

## サービスアイコン(name → 正式名)

**Compute/Containers**: `ec2`, `lambda`, `fargate`, `ecs`, `eks`, `ecr`,
`elastic_beanstalk`, `app_runner`, `batch`, `elastic_load_balancing`

**Storage**: `s3`(S3), `glacier`, `elastic_file_system`(EFS), `fsx`, `backup`, `storage_gateway`

**Database**: `rds`, `aurora`, `dynamodb`, `elasticache`,
`documentdb_with_mongodb_compatibility`, `neptune`, `memorydb_for_redis`,
`database_migration_service`(DMS)

**Networking/Edge**: `cloudfront`, `route_53`, `route_53_resolver`, `vpc`,
`vpc_privatelink`, `transit_gateway`, `direct_connect`, `global_accelerator`, `client_vpn`

**App Integration**: `api_gateway`, `sqs`, `sns`, `eventbridge`, `step_functions`,
`appsync`, `mq`

**Security/Identity**: `cognito`, `waf`, `shield`, `secrets_manager`,
`identity_and_access_management`(IAM), `key_management_service`(KMS),
`certificate_manager_3`(ACM), `guardduty`, `security_hub`, `inspector`,
`network_firewall`, `single_sign_on`(Identity Center), `macie`

**Management/Monitoring**: `cloudwatch_2`, `cloudtrail`, `cloudformation`,
`systems_manager`, `config`, `organizations`, `control_tower`, `chatbot`,
`managed_service_for_grafana`, `managed_service_for_prometheus`

**Analytics**: `athena`, `glue`, `kinesis`, `kinesis_data_streams`,
`kinesis_data_firehose`, `emr`, `redshift`, `quicksight`, `lake_formation`,
`managed_streaming_for_kafka`(MSK), `elasticsearch_service`(OpenSearch Service),
`managed_workflows_for_apache_airflow`(MWAA)

**AI/ML**: `bedrock`, `sagemaker`, `rekognition_2`, `textract`, `comprehend`,
`translate`, `lex`, `kendra`, `q`

**DevTools/CI-CD**: `codepipeline`, `codebuild`, `codedeploy`, `codecommit`,
`xray`, `cloud_development_kit`(CDK)

**その他**: `amplify`, `simple_email_service`(SES), `iot_core`, `connect`,
`pinpoint`, `cost_explorer`, `budgets_2`, `datasync`, `transfer_family`, `workspaces`

よく使う略称はビルダーが自動解決する: `cloudwatch`→cloudwatch_2 / `ses` / `kms` /
`alb` / `nlb` / `msk` / `opensearch` / `documentdb`

## ネットワーク系リソースシェイプ(VPC 内の部品)

`internet_gateway`, `nat_gateway`, `application_load_balancer`,
`network_load_balancer`, `gateway_load_balancer`, `classic_load_balancer`,
`endpoints`(VPC Endpoints), `vpn_gateway`, `vpn_connection`, `customer_gateway`,
`elastic_network_interface`, `flow_logs`, `route_table`, `router`

## 汎用シェイプ(図の起点・外部要素)

`users`, `user`, `client`, `mobile_client`, `internet_alt1`(Internet),
`traditional_server`, `office_building`, `generic_database`, `documents`,
`email`, `ssl_padlock`, `logs`, `metrics`, `alarm`, `globe`, `gear`

(コンテナ type の一覧は SKILL.md §3 が正)

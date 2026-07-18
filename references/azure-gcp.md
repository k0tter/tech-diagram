# Azure / GCP / マルチクラウド構成図の描き方

Azure・GCP を含む図を描くときに 1 回 Read する。ワークフロー・配置原則・
meta/legend/kinds・--optimize は SKILL.md と同一。ここには差分だけ書く。

## アイコン(name にプレフィックスを付ける)

```json
{"id": "vm1", "label": "Web VM", "icon": "azure:virtual_machine", "col": 2, "row": 1},
{"id": "gke1", "label": "アプリ", "icon": "gcp:gke", "col": 5, "row": 1}
```

- Azure: `azure:<name>`(641 種・現行 Azure アイコン)。検索:
  `find_icon.py --provider azure <英語キーワード>`
- GCP: `gcp:<name>`(主要製品 19 種+カテゴリ 26 種=計 45。**Pub/Sub・Dataflow・
  Cloud Functions・Firestore・Cloud Load Balancing 等の製品アイコンは無い** →
  カテゴリアイコン(`gcp:dataanalytics` `gcp:networking` 等)+正式名ラベルで表す)
- AWS はプレフィックスなしのまま。1 つの図に 3 社混在してよい(マルチクラウド)

### Azure 頻出 name

`virtual_machine` `vm_scale_sets` `kubernetes_services`(AKS)
`container_instances` `container_registries` `app_services` `function_apps`
`sql_database` `azure_cosmos_db` `storage_accounts` `blob_block` `cache_redis`
`virtual_networks` `subnet` `network_security_groups` `application_gateways`
`load_balancers` `front_doors` `firewalls` `dns_zones` `expressroute_circuits`
`virtual_network_gateways` `key_vaults` `azure_active_directory`(Entra ID)
`monitor` `log_analytics_workspaces` `application_insights` `service_bus`
`event_hubs` `event_grid_topics` `logic_apps` `api_management_services`
`azure_devops` `azure_defender` `azure_sentinel` `bastions`

### GCP name(主要製品)

`computeengine` `gke` `cloudrun` `cloudsql` `alloydb` `cloudspanner` `bigquery`
`cloud_storage` `hyperdisk` `apigee` `anthos` `vertexai` `looker`
`securitycommandcenter` `mandiant` `secops` — ほか `find_icon.py --provider gcp` で

## コンテナ(containers.type)

| provider | type | 階層(W9 で検証) |
|---|---|---|
| Azure | `mgmt_group` → `subscription` → `resource_group` → `vnet` → `az_subnet` | Management Group > Subscription > RG > VNet > Subnet |
| GCP | `folder` → `project` → `gcp_vpc` → `gcp_subnet`、`gcp_zone` | Org/Folder > Project > VPC Network > Subnet(リージョナル) |

- **GCP のサブネットはリージョナル**(AWS のように AZ 単位ではない)。ゾーンを
  描くなら `gcp_zone` をサブネットや VPC の中に
- Azure の PaaS(Storage/Cosmos DB/Service Bus 等)・GCP のマネージド
  (GCS/BigQuery/Spanner 等)は **VNet/VPC の外**に置く(W8 が警告)。
  私設アクセスは Private Endpoint / Private Service Connect のアイコンで表す

## マルチクラウドの定石

- プロバイダごとに最上位コンテナ(aws_cloud / subscription / project)を
  **左右に並べる**(内周ガターが各社の枠内配線を保証する)
- クラウド間接続は専用線・VPN を明示: AWS `direct_connect`・
  Azure `expressroute_circuits`・GCP は `gcp:networking` カテゴリ+ラベル
  「Cloud Interconnect」。接続線はコンテナ端点(cloud→cloud)でよい
- 図全体の凡例に「どの色がどのクラウドか」は不要(公式アイコンで自明)。
  線種の意味だけ legend に載せる

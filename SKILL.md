---
name: tech-diagram
description: クラウド構成図(AWS/Azure/GCP・マルチクラウド)とER図・UMLクラス図・フローチャート、AWS公式風リファレンスアーキテクチャ図(番号バッジ+ステップ説明)をdraw.io(.drawio)形式で作成・修正するスキル。ノードにマス目(col/row)を割り当てたJSONを書くだけで、ピクセル座標・コンテナサイズ・直交配線・ラベル位置は自作レイアウトエンジン(Python標準ライブラリのみ)が計算し、各クラウドの公式アイコンで描画、バリデータで重なり・交差・境界の正確さを機械検証する。「AWS/Azure/GCPの構成図・アーキテクチャ図」「システム構成図/インフラ構成図/ネットワーク図」「マルチアカウント/マルチクラウド構成図」「リファレンスアーキテクチャ図」「番号付きで手順を図解」「ダイアグラム/図解を作って」「ER図/ERD/テーブル設計図/スキーマ図」「UMLクラス図/コンポーネント図」「フローチャート/業務フロー/承認フロー」「draw.ioで図を」などで起動。対象外: シーケンス図・ユースケース図、Mermaid/PlantUMLなどdraw.io以外の形式が明示指定された図。
---

# 技術図 (draw.io) 作成スキル — クラウド構成図・ER/UML・フローチャート

**ピクセル座標・サイズ・配線は書かない。** ノードにマス目(col/row の整数 2 つ)を
割り当てた論理スペックを書き、あとはエンジン(回廊格子の最短路探索で交差最少の
直交配線を選ぶ)に任せる。座標を推論し始めたら設計ミス。

**ドメイン分岐**(ワークフローは全ドメイン共通。該当リファレンスを先に 1 回 Read):
- **AWS 定番構成**(3層 Web / サーバーレス API / 静的サイト / コンテナ /
  マルチリージョン DR / マルチアカウント等)→ `references/patterns.md`
  (正解トポロジ+アンチパターン早見表。合致したら自由作文せず
  `references/reference-architectures/` の検証済みスペックから差分編集)
- **Azure / GCP / マルチクラウド** → `references/azure-gcp.md`
  (`azure:` / `gcp:` プレフィックス、コンテナ型、境界ルール)
- **ER 図・UML クラス図/コンポーネント図** → `references/er-uml.md`
- **フローチャート・業務フロー** → `references/flowchart.md`
- **リファレンスアーキテクチャ図・番号付き解説** → `references/reference-arch.md`
  (step バッジ+steps 説明パネル・無地矢印の規約)
- **Terraform リポジトリから起こす** → `references/terraform.md`
  (tf_to_spec.py で骨格を自動生成 → review を潰して仕上げる。手で全読みしない)
- シーケンス図・ユースケース図は対象外 — 時系列レイアウトはこのエンジンの
  前提(グリッド+機械検証)と合わず 0e0w 保証が崩れるため。理由を一言添えて
  Mermaid の `sequenceDiagram` を提案する(黙って断らない・生 XML を書かない)

**着手前に確認(手戻りの最大要因)**: ①1 ページか複数タブか ②完全表現か縮約か
③生成物(.drawio / .spec.json)の格納ディレクトリ。指定済みなら聞かない。

**IaC・実コードから起こす図**: **コードに在る=稼働中ではない。デッドコードを
図に載せない。** 疑うもの — 未参照モジュール、`count`/`for_each` が 0 になり得る
条件付きリソース、コメントアウト、feature flag 無効、廃止済みの残骸。
`terraform state list` / plan があれば実在照合が最優先。判別できないものは省くか
「コード上定義のみ(未適用の可能性)」注記で載せ、どちらにしたか報告に明記する。

## 1. スコープと抽象度

- **縮約(デフォルト)**: 載せるのは「その図の話に必要な代表ノード」だけ
  (1 図 1〜2 フロー)。定番: EventBridge/SQS/SNS/MSK→Event Backbone、
  Glue/Athena/SageMaker/QuickSight→Data Lake & AI、CloudFront+WAF+Shield→
  Edge Protection、DX+VPN→接続 1 ノード。横断的関心事(監視・CI/CD・統制)は
  全結線せず代表エッジ 1 本か位置関係で語る
- **完全表現モード**: 「省略しない」と言われたら縮約禁止・全要素 1:1。密度は
  タブ分割で処理し、1 ページ指定と両立しない規模なら先に優先を確認
- **分割**: まず 1 ページ(縮約+コンテナ端点化で 45 ノード程度まで可 —
  dense テンプレが実例)。タブ分割(`diagrams` 配列、共有ノードは `"ref": true`)は
  --optimize でも交差が目安に収まらないか、関心事が本当に別の話のときだけ。
  **1 ページ指定なら分割しない**
- **ユーザーが個別に列挙した要素は縮約しない**(密度が問題なら縮約を提案)
- 入口系(GA/WAF/Shield/Route 53)が入力にあるのに省くときは理由を必ず書く

## 2. アイコン名

AWS アイコンを使う図なら `references/icon-catalog.md` を 1 回 Read。ない分だけ:
```bash
python3 {SKILL}/scripts/find_icon.py <英語キーワード>
```
**`{SKILL}` = 本スキルの base directory**(起動時ヘッダーの実パス。配置は
エージェントごとに異なる)。コマンドは全て絶対パスに置換して使う。
スペックに書くのは name だけ(色・スタイル・サイズは自動解決)。

## 3. スペックを書く

```json
{"diagrams": [{
  "name": "タブ名",
  "meta": {"purpose": "何を伝える図か", "audience": "読者", "scope": "対象範囲",
           "abstraction": "概要|詳細|完全(省略なし)", "assumptions": "前提・情報源"},
  "kinds": {"repl": {"base": "sub", "color": "#2E8B57"}},
  "legend": {"main": "同期呼び出し", "repl": "レプリケーション", "ops": "運用・監視"},
  "containers": [
    {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
    {"id": "vpc", "label": "VPC", "type": "vpc", "parent": "cloud"}
  ],
  "nodes": [
    {"id": "users", "label": "ユーザー", "icon": "users", "col": 0, "row": 1},
    {"id": "ec2", "label": "EC2 アプリ", "icon": "ec2", "parent": "vpc", "col": 2, "row": 1},
    {"id": "db", "label": "Aurora", "icon": "aurora", "parent": "vpc", "col": 3, "row": 1},
    {"id": "db_dr", "label": "Aurora (DR)", "icon": "aurora", "parent": "cloud", "col": 5, "row": 1},
    {"id": "cw", "label": "CloudWatch", "icon": "cloudwatch_2", "parent": "cloud", "col": 3, "row": 3}
  ],
  "edges": [
    {"id": "e1", "src": "users", "dst": "ec2", "kind": "main", "label": "HTTPS"},
    {"id": "e2", "src": "ec2", "dst": "db", "kind": "main"},
    {"id": "e3", "src": "db", "dst": "db_dr", "kind": "repl"},
    {"id": "e4", "src": "vpc", "dst": "cw", "kind": "ops", "label": "メトリクス"}
  ]
}]}
```
この例はそのままビルドが通る。単一タブは `diagrams` ラッパー省略可。

- **meta は必須**(冒頭にパネル描画。updated は自動。欠落は WARN)
- **col/row は図全体で共有のグローバル座標**。col=左→右の流れ(1 ホップ +1)、
  row=段。主フローは同一 row に一直線(左→右で読めることが QA 項目)。
  空き行/列は自動で潰れる(帯の分離は 1 行空け・番号は疎でよい)
- `containers.type`: aws_cloud / region / vpc / az / public_subnet / private_subnet /
  ou / account / security_group / auto_scaling / ec2_contents / corporate_dc / generic。
  親を先に。**コンテナ範囲=子の外接矩形(列×行)**。非所属ノードは矩形内に
  置けないが、**行(または列)が範囲外なら同じ列(行)は使える** — 例:
  2 リージョンの真上の行に Route 53。aws_cloud は全子孫を覆う → 外部ノード
  (users 等)はその範囲外に
- **グローバル/リージョナル**: CloudFront・Route 53・IAM・Organizations・GA・
  Shield は**グローバル** — region の外(aws_cloud 直下)。region 内は W11。
  EC2/RDS/Lambda/S3 等は region を描く図では region 内。WAF は文脈依存
  (CloudFront 用=グローバル側、ALB/API GW 用=リージョン側)。**監視・統制系**
  (CloudWatch・X-Ray・CloudTrail・Config 等)はリージョナル — region 内かつ
  VPC の外(region を描かない図では aws_cloud 直下)
- **ハイブリッド**(オンプレ+AWS): `corporate_dc` を aws_cloud と**トップレベルに
  並置**。DX/VPN 系ノードは 2 コンテナの間の列に
- 線種の内規(図内は legend で自己完結): **main**(実線)=同期 / **sub**(破線)
  =非同期・複製・戻り / **ops**(点線)=監視・CI/CD・統制。足りなければ `kinds`
  で追加(base+color)。**4 種目以降は色に加えて style_extra の dashPattern も
  変える**(白黒・色覚多様性対応。色だけの区別は不可)。例: `dashPattern=10 5;`
  (長破線)/ `12 3 3 3`(一点鎖線)/ `1 6`(疎な点線)。見本: dense-1page の kinds
- 複数線種の図は `legend` 必須(未掲載 kind は WARN)
- ラベル折り返しは `\n` か `<br>`。**全角 10 文字超の 1 行ラベル**はセルを圧迫し
  E1 の元 — 座標をいじる前に改行・短縮を疑う。隣接セル間の短いエッジは
  短ラベル(半角推奨)か無ラベルに(長ラベルは E5 の元)
- コンテナタイトルは短く。サブネット等の定型は英語単独表記(Public subnet / Private
  subnet / Isolated subnet)推奨 — 和英併記は 2 行折返しで上辺を占有し配線の余裕が減る
- **ノードの下辺**: 下向きに出るのは可(キャプション真下から垂直 = AWS 公式の
  流儀)。上向き矢印を下辺に入れるのは不可 — 左右辺から入る配線が正常な処方
- **ゲートウェイ系**(IGW/VGW 等)は `"on_boundary": "left|right|top|bottom"` で親コンテナ
  の枠線上センターまたぎに描ける(公式図の慣例)。col/row は親の内側・指定辺に隣接するセルに。
  配置規約(IGW/VGW=VPC 直下・NAT=public subnet 内・TGW/DX=VPC 外)は W14 が機械検査する
- 線は必ず方向を持つ(`bidir: true` で両矢印)。自明でない線にはラベル(HTTPS /
  DNS alias / async event / replication / logs 等・**2 行以内**)。自明な線は無ラベル
- **CI/CD は意味を混ぜない**(artifact / registry / GitOps deploy / secret / KMS を
  分け、束ねたら注釈)。**DR**: 概要図は Region 端点+"DNS failover"、実装図は
  DR ALB・複製データストアへ直接

**配置原則(初回の交差数を決める)**:
1. 流入元は流入先の**隣接列**に(TGW/DX は VPC の隣に縦バンド)。VPC 相互は
   **コンテナ端点エッジ+bidir+ラベル**でよい(アイコン不要)
2. 連結された 2 グループの間の列に主フロー行のノードを置かない(水平線を塞ぐ)。
   主フロー行を縦断する長エッジも大回りになる(HINT で報告)
3. 横断的関心事は個別ノードでなく**コンテナを端点に**(`vpc→cw`)。交差が桁で
   減る。境界が全部埋まったコンテナは矢印が端のノードを指して見える → ノード
   直指定へ。**1 セルの小コンテナへの端点集約は 1〜2 本まで**(3 本以上は
   境界セル不足で斜め E4 → 実ノードの直指定)
4. Ops・補助の帯は使うノード群の**直下の row**。随伴サービス(WAF/ACM 等)は
   相手の**真上か横隣り**
5. Primary/DR は上下でなく**左右対称**。多対1ハブは接続先の隣の列
6. 次数7以上のハブは相手を**8近傍リング**(周囲8セル)に。9本目以降はエッジを
   引かず所属や端点集約で表現。ハブ2つなら行を分ける。**次数10級を1ページに
   畳む前に選択肢を提示**: ①タブ分割 ②中間ノードでハブ分解(意味のある中間
   ノードは gear 可) ③コンテナ端点集約。コンテナ内外に分かれるときはリングの
   **部分適用でよい**
7. 小中規模の Multi-AZ 図は各 AZ 内のサブネットを**同一行に横並び**(Public→
   Private→Isolated)にして AZ を 1 行に潰す(縦長化の防止)。入口系(users/
   IGW/LB)は **AZ の間の 1 行**に集約し、貫通行を入口フローの帯として使う。
   AZ 行はハブ行を挟んで**鏡映対称**に組む — コンテナの上下パディングは
   非対称なので、行構成が対称でないとペア経路の脚長・折れ構造が揃わない
8. 同種・同役割のコンテナは**同一寸法**で並べる(エンジンが既定で等化。
   `equalize_containers: false` で固定)。中身のバランスもスペック側で取る —
   片方だけ詰め込んで膨らませない(実務例: DB と Cache はサブネットを分ける)

**グリッドの完全解を頭で探さない**(手作業の組合せ探索が最大コスト)。3 通り:
①原則 1〜5 で自分で書く(小中規模は最速) ②ラフに置いて `--optimize` に磨かせる
(スペックへ書き戻し・OPT: 行で報告) ③col/row 全省略で自動配置+`--optimize 30`
(叩き台)。**--optimize が効くのは〜50 ノードまで**(実測: 50 で交差 206→43。
120 超では予算内に 0〜2 手=清書にならない)。それ以上はタブ分割・縮約だけ。
固定したいノードは `"pin": true`(col/row 必須。③は確定値を書き戻すので、
その後 pin を付けて②へ)。**和文 2 行ラベルの大型図では --optimize が E1/E5 を
生みやすい** — pin で守るか、隣接ノードを 2 列ピッチにして手配置。

## 4. 生成 → 5. 修正ループ

```bash
python3 {SKILL}/scripts/build_drawio.py <name>.spec.json -o <name>.drawio
```
パスは絶対パスで(cwd が変わり得る)。40 ノード級 0.1〜0.4 秒・150 ノード級
15〜20 秒。検証も自動で走る。`--optimize [秒]`(既定 30)=配置ローカルサーチ。

- ERROR →**スペック側**を直して再生成(メッセージに空きセル候補等のヒント入り)
- `HINT:` は配置改善の手掛かり。`WARN: 代替配線` は貫通の可能性 — 必ず対処
  (隣接列へ / コンテナ端点化 / ノード直指定)
- **止め時: 0 エラー・WARN 対処済み・交差が目安以内(I1 が INFO)**。
  代替配線 / meta 欠落 / legend 未掲載は納品ブロッカー。meta/legend の WARN は
  **ビルド段**で出てサマリの warning 数に入らない(「注意:」行で再通知)—
  サマリ 0/0 でも WARN 行が残っていれば納品不可。目安=基本(ノード数連動)+
  ハブ補正(内訳表示あり)。目安内の微調整は過剰投資。構造要因(次数 10 級・
  完全表現×1 ページ)で超過が残るときは目視で可読性を確認し理由を報告して納品可
- 交差・E7・E3 の多発は密度・配置の症状。効く順: `--optimize` → 配置原則の違反を
  直す → エッジを削る → タブ分割。個別エッジをいじる発想は捨てる
- 1 本だけ手で引くなら `exit / entry / points` の **3 点セット**で直書き
  (exit+entry だけの両側ピンは斜め E4 の元)。points は**描画後の最終座標**。
  暴れる長距離エッジは points で凍結。手動配線・`--emit-abs` のときは
  `references/layout-rules.md` を Read
- **W5(題字貫通)を手動 points の大迂回で隠さない**(帯回避・上辺 entry の
  オフセットは自動)。残る W5 は配置の症状 — 帯を塞ぐノードを動かして
  自動配線に戻す(実例: 交差 2→0)
- 生成 XML は Read しない。判断はバリデータ出力で。全件・機械可読が要るときだけ
  `validate_drawio.py <file> --json`

## 6. 納品(レポート必須項目)

1. 構成要約・バリデータ結果(0 errors・交差数と目安)・開き方(draw.io アプリ /
   VS Code 拡張 / app.diagrams.net)
2. **Abstraction Notes**: 入力の各要素を kept as-is / grouped / omitted / replaced /
   meaning changed(可能性含む)に分類。入口系の省略は理由付き
3. **Coverage audit**(3 層): critical path(入口・実行系・データ・DR・セキュリティ)
   =原則全部 / supporting(可観測性・CI/CD・分析・統制)=代表化可 / optional=
   省略可。完全表現モードでは全件 kept as-is を確認
4. **QA**: ①主要経路が規定方向で読めるか(構成図=左→右、フロー図=上→下)
   ②交差が目安内 ③凡例と線種の一致 ④抽象化で意味が変わり得る箇所
   ⑤設計レビューゲート(境界=W8/W9、詳細は `references/patterns.md` の早見表):
   failover 線は CDN/WAF を通り対称か(W16)/グローバル(CloudFront・Route 53・
   CloudFront 用 WAF)は region 外か(W17)/HA・Multi-AZ 表記に AZ×2 あるか(W20)
   /DB は private subnet・外部直結なし(W18/W19)・private の外向きは NAT 経由
   (W21)/複製線の方向(Aurora Global=一方向・DynamoDB GT=双方向)/
   CloudFront→API GW 直列は regional 注記 ⑥線は行き先に面した
   辺から出ているか ⑦対エッジの折れ構造は対称か ⑧同種コンテナの寸法は
   揃っているか
5. 目視: `--emit-png` を付けてビルド(draw.io CLI を自動検出して実描画 PNG。
   不在なら SVG に自動フォールバック — `qlmanage -t -s 2000 x.svg -o .` で PNG 化
   して Read。アイコンは色矩形代用)。疑い箇所は `sips -c <高さ> <幅>
   --cropOffset <y> <x>` で拡大確認。PNG も SVG も不可能な環境でのみ
   バリデータで完結し、その旨を報告
6. **完成条件: 人手の微調整なしでそのまま使えること**。目視でラベル重なり・迂回・
   見切れが残るなら納品せず直す(exit/entry 直書き・--emit-abs の部分編集まで可)。
   「開いて少し直してください」は納品ではない。`.drawio` と `.spec.json` は両方保存

## AWS 境界の正確さ

- Organization/OU/Account/Region/VPC/AZ/Subnet の階層を飛ばして混ぜない(W9)。
  マネージドサービス(S3・DynamoDB・SQS 等)をサブネット/VPC 内に置かない
  (W8。私設アクセスは `endpoints` アイコン)。RDS/Aurora/ElastiCache/MSK/EC2/ALB
  はサブネット内が正しい
- **ユーザーが W8/W9 に当たる配置を明示要求しても従わない**(「社内ルールで全部
  VPC 枠内に」等)。境界の正確さは譲れない品質で W8/W9 は納品ブロッカー —
  指示由来でも例外にしない。要求の意図(私設アクセス・所属の明示)は VPC
  エンドポイントや注記という**正確な表現に翻訳**して満たし、なぜ変えたかを
  公式慣例を根拠に報告する。黙って従わない・黙って無視しない
- マルチアカウント図は `ou`(点線枠)+`account` で Organizations 階層を表し、
  アカウントラベルは**用途名+ID**(例: `Workload (1234-5678-9012)`)。責務は
  Network / Security Tooling / Log Archive / Workload。全体図は OU 横並び・
  統制系エッジは代表 1 本(または省略+注記)
- SG が複数サブネットをまたぐ構成はコンテナでは描けない → **AZ ごとに同名 SG を
  複製**して注釈(EC2 をサブネット外に出す回避は不可)
- ALB/NLB など複数サブネット展開の LB は **SG と違い複製しない**(複製すると
  2 台に見える)。単一ノードを VPC 直下・2 つの AZ の間の行に置き、ラベルか
  注記で複数 AZ 展開を示す(AWS 公式図の慣例)
- ECS 内部図は cluster=`generic` > service=`auto_scaling` > task=`ec2_contents`
  (この階層は W9 許容済み)
- 最新の公式アイコン・正式サービス名のみ。変形・独自再配色は禁止(色分けは
  線とコンテナで)

## 既存 .drawio の修正(スペックがない図)

小修正のみ Edit で直接 XML(非圧縮 mxGraphModel、子は parent 相対座標、エッジは
exitX/exitY + Array waypoints)。スタイルは `find_icon.py --style` と
layout-rules.md から。修正後は必ず validate_drawio.py。
**エラーがエッジの過半または複数ノードの再配置に及ぶならスペックに起こし直す**。
前後は `validate_drawio.py <file> --graph` の diff で構成 1:1 を照合。

## 見本(0 エラー検証済み。該当する行を各 1 回 Read)

| ファイル | 内容 | 読む場面 |
|---|---|---|
| `templates/example-3tier.spec.json` | Multi-AZ 3層(入れ子・対称) | VPC/Multi-AZ |
| `templates/example-multiaccount.spec.json` | マルチアカウント 2 タブ・ref | タブ分割時 |
| `templates/example-complex.spec.json` | 26 ノード高密度 | 中規模 1 タブ |
| `templates/example-dense-1page.spec.json` | 42 ノード 1 ページ(DR 左右・帯・端点・kinds・legend) | **1 ページ大型図はまず Read** |
| `templates/example-hub-star.spec.json` | 次数10級ハブの畳み方 | 高次数ハブ |
| `templates/example-er-uml.spec.json` | ER+UML 2 タブ(関係線 6 種) | ER/UML |
| `templates/example-multiregion.spec.json` | マルチリージョン DR(kinds 5 種) | マルチリージョン/DR |
| `templates/example-multicloud.spec.json` | AWS+Azure+GCP 接続図 | マルチクラウド |
| `templates/example-flowchart.spec.json` | 承認フロー(レーン 3・分岐・差し戻し) | フロー図 |
| `templates/example-reference.spec.json` | step バッジ+説明パネル | リファレンス図 |

## コンテキスト運用

| ファイル | 読み方 |
|---|---|
| `references/icon-catalog.md` | AWS アイコンを使う図で 1 回 |
| `templates/example-*.spec.json` | 上表の場面だけ |
| `references/azure-gcp.md` / `er-uml.md` / `flowchart.md` / `reference-arch.md` / `terraform.md` | 該当ドメインで 1 回 |
| `references/layout-rules.md` | XML 手編集・絶対座標・points 手動配線のときだけ |
| `references/icons-*.tsv`(1,600 種超) | Read 禁止。find_icon.py で引く |
| `scripts/*.py` / 生成 .drawio / .abs.json | Read しない(スキーマは本ファイルに完備) |

## サードパーティ / 禁止事項

- 公式アイコンが無いもの(Terraform/Argo CD/GitHub 等)は最も近い AWS アイコン
  (`cloud_development_kit`・`git_repository`)か汎用シェイプ(`gear`)+**正式名
  ラベル**。画像・絵文字は不可
- K8s 内部図は専用アイコンが無い → Namespace/クラスタ=`generic` コンテナ、
  Pod/Service 等=フローチャートの `process`/`subprocess` 箱+正式名
- スペックを介さない生 XML の新規手書き/ピクセル座標の手動設計から始めない
- icons-data.tsv・生成 XML の全読みをしない
- バリデータを通さずに「完成」と報告しない

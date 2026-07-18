# tech-diagram

[English](README.md) | [日本語](README.ja.md) | [Bahasa Indonesia](README.id.md)

> シンプルな JSON グリッドスペックから、仕上がりの良い draw.io 図
> (AWS / Azure / GCP 構成図・ER 図・UML クラス図・フローチャート)を生成する
> Agent Skill。Python 標準ライブラリのみ・外部依存ゼロ。

エージェントに図を頼むと、スキルがノードにマス目(`col`/`row`)を割り当てた
JSON スペックを書き、レイアウトエンジンがピクセル座標・コンテナの入れ子とサイズ・
直交配線・ラベル配置を計算して、各クラウドの公式アイコンで描画します。
生成された図は、重なり・貫通・交差・境界の正確さ・アーキテクチャの
アンチパターンまで機械検証されてから手元に届きます。

[![ECS Web アプリの Multi-AZ 冗長構成(作例)](docs/images/samples/03-ecs-multiaz.png)](docs/images/samples/03-ecs-multiaz.png)

## ギャラリー

すべて同梱テンプレート([templates/](templates/))と実案件スペックからの
**無修正の生成結果**です(クリックで原寸)。

### 作例

| | | |
|---|---|---|
| [![ECS Multi-AZ](docs/images/samples/03-ecs-multiaz.png)](docs/images/samples/03-ecs-multiaz.png) | [![マルチアカウント+TGW](docs/images/samples/04-multiaccount-tgw.png)](docs/images/samples/04-multiaccount-tgw.png) | [![イベント駆動リファレンス](docs/images/samples/06-reference-event-driven.png)](docs/images/samples/06-reference-event-driven.png) |
| ECS Web アプリの Multi-AZ 冗長構成 | マルチアカウント+Transit Gateway | イベント駆動リファレンス(番号バッジ) |

### テンプレート 10 種

| | | |
|---|---|---|
| [![3層 Web](docs/images/templates/example-3tier.png)](docs/images/templates/example-3tier.png) | [![複雑系](docs/images/templates/example-complex.png)](docs/images/templates/example-complex.png) | [![高密度 42 ノード](docs/images/templates/example-dense-1page.png)](docs/images/templates/example-dense-1page.png) |
| 3層 Web(`example-3tier`) | 複雑系(`example-complex`) | 高密度 42 ノード 1 ページ(`example-dense-1page`) |
| [![マルチアカウント](docs/images/templates/example-multiaccount-main.png)](docs/images/templates/example-multiaccount-main.png) | [![マルチクラウド](docs/images/templates/example-multicloud.png)](docs/images/templates/example-multicloud.png) | [![マルチリージョン DR](docs/images/templates/example-multiregion.png)](docs/images/templates/example-multiregion.png) |
| マルチアカウント(`example-multiaccount`、[CI/CD タブ](docs/images/templates/example-multiaccount-cicd.png)) | マルチクラウド AWS/Azure/GCP(`example-multicloud`) | マルチリージョン DR(`example-multiregion`) |
| [![ハブ&スター](docs/images/templates/example-hub-star.png)](docs/images/templates/example-hub-star.png) | [![リファレンスアーキテクチャ](docs/images/templates/example-reference.png)](docs/images/templates/example-reference.png) | [![フローチャート](docs/images/templates/example-flowchart.png)](docs/images/templates/example-flowchart.png) |
| 高次数ハブ&スター(`example-hub-star`) | リファレンスアーキテクチャ(`example-reference`) | 承認フロー・スイムレーン(`example-flowchart`) |
| [![ER 図](docs/images/templates/example-er-uml-er.png)](docs/images/templates/example-er-uml-er.png) | [![UML クラス図](docs/images/templates/example-er-uml-uml.png)](docs/images/templates/example-er-uml-uml.png) | |
| ER 図(`example-er-uml` タブ1) | UML クラス図(`example-er-uml` タブ2) | |

## 特徴

- **対応図種**: AWS / Azure / GCP・マルチクラウド構成図、ER 図、UML クラス図、リファレンスアーキテクチャ図(番号バッジ+ステップ説明)、
  フローチャート(スイムレーン対応)。シーケンス図は対象外
- **配線品質**: 回廊格子上の最短路探索で、交差・混雑・曲がりをコストに複数の
  配線順序を試し交差最少を採用。クラウド内で完結する通信は境界の内側に収め、
  無関係なクラウド・アカウントの箱を貫通しない
- **機械検証**: ラベル重なり・ノード貫通・エッジ交差(ハブ次数補正付きの目安)・
  クラウド境界の慣例(マネージドサービスのサブネット内配置検出、コンテナ階層
  チェック)・アーキテクチャのアンチパターン(後述の
  [意味的正しさ](#意味的正しさ--アーキテクチャとして正しい図)参照)など約 20 種を検証
- **自動配置**: `col`/`row` 全省略で自動レイアウト、`--optimize` で配置ローカル
  サーチ(決定的・`pin` で固定可)
- **プレビュー**: `--emit-png` で実描画 PNG(draw.io CLI 自動検出)、`--emit-svg` で
  自己完結 SVG を出力(CLI がない環境での目視確認用。アイコンは公式カラーの矩形で代用)
- **Terraform からの自動起こし**: `tf_to_spec.py` が .tf を直接パースしてスペック骨格+レビュー情報を生成(認証・terraform CLI・state 不要)
- **依存ゼロ**: Python 標準ライブラリのみ(3.10+)

## 意味的正しさ — アーキテクチャとして正しい図

線がきれいなだけでなく、「きれいに描けているがアーキテクチャとして間違っている図」を
出さないための基盤を備えています:

- **パターンカタログ**([references/patterns.md](references/patterns.md)):
  AWS 定番パターン — 3層 Web(Multi-AZ)・サーバーレス API・マルチリージョン DR・
  マルチアカウント・イベント駆動・静的サイト・コンテナ(ECS/Fargate)・
  ハイブリッド — の正解ポイントを AWS 一次情報の URL(2026-07-18 実在確認済み)
  つきで整理。アンチパターン早見表も同梱
- **検証済み起点スペック**
  ([references/reference-architectures/](references/reference-architectures/)):
  3層 Web・サーバーレス API・マルチリージョン DR・静的サイト・ECS コンテナの
  5 スペック(全て 0 エラー・0 警告でビルド確認済み)。依頼が定番パターンに
  合致したら自由作文せず、検証済みスペックを起点に差分編集する
- **アンチパターン検査(W16〜W21)**: グローバルエッジサービス
  (CloudFront / Route 53 / WAF)のリージョン・VPC・サブネット内配置、
  DB・キャッシュのパブリックサブネット配置、外部クライアントから DB への
  直接エッジは**ビルド拒否のエラー**。CloudFront/WAF をバイパスして DR の
  ロードバランサへ直行するフェイルオーバー線、「Multi-AZ / HA」表記なのに
  AZ コンテナが 1 つ以下、プライベートサブネット内ノードから NAT / IGW /
  エンドポイント非経由で外部へ出るエッジは警告
- **誤検知ゼロの校正**: テンプレート・実案件相当スペック・フロー図・
  リファレンススペックの計 26 ファイルの掃引で、これらの検査の検出 0 件

## 使い方

お使いのエージェントが Agent Skills を探索するディレクトリに、フォルダ名
`tech-diagram` で配置するだけです(スキル名として認識されます)。配置場所は
自由で、スキル内部にパスのハードコードはありません。

あとはエージェントにこう頼むだけです:

- 「〜の AWS 構成図を描いて」
- 「このテーブル群の ER 図を描いて」
- 「この承認フローを図にして」

スキルが起動し、作図・検証・結果報告まで行います。作図手順の本体は
[SKILL.md](SKILL.md) です。出力された `.drawio` は draw.io デスクトップアプリ、
VS Code 拡張(hediet.vscode-drawio)、[app.diagrams.net](https://app.diagrams.net)
のいずれでも開けます。

### スペックを直接書く

エージェントを介さず、スペックから直接ビルドすることもできます:

```bash
python3 scripts/build_drawio.py templates/example-3tier.spec.json -o out.drawio
python3 scripts/find_icon.py --provider azure kubernetes   # アイコン名の検索
```

最小スペックの例:

```json
{
  "name": "3層構成",
  "meta": {"purpose": "Web アプリの全体像", "audience": "開発チーム",
           "scope": "本番環境", "abstraction": "サービス単位"},
  "containers": [
    {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
    {"id": "vpc", "label": "VPC", "type": "vpc", "parent": "cloud"}
  ],
  "nodes": [
    {"id": "users", "label": "ユーザー", "icon": "users", "col": 0, "row": 0},
    {"id": "alb", "label": "ALB", "icon": "application_load_balancer",
     "col": 1, "row": 0, "parent": "vpc"},
    {"id": "app", "label": "アプリ", "icon": "ec2", "col": 2, "row": 0, "parent": "vpc"}
  ],
  "edges": [
    {"id": "e1", "src": "users", "dst": "alb", "kind": "main", "label": "HTTPS"},
    {"id": "e2", "src": "alb", "dst": "app", "kind": "main"}
  ]
}
```

## 配線品質 Before / After

配線エンジンは「接続して見える(辺中央付近から出入り)> 直線 > 折れ点最少」の
優先原則で配線します。同一スペックでの旧世代エンジンと v1.0.0 の比較:

| Before(開発初期エンジン) | After(v1.0.0) |
|---|---|
| [![端点が中心からずれた縦線](docs/images/before-after/pairs-anchor-before.png)](docs/images/before-after/pairs-anchor-before.png) | [![辺中央から出入りする縦線](docs/images/before-after/pairs-anchor-after.png)](docs/images/before-after/pairs-anchor-after.png) |
| 垂直複製ペアの縦線が中心からずれた位置(frac 0.65)から出入り | 列幅拡張で辺中央(frac 0.5)を確保し、アイコン中心を貫く直線に |
| [![出射辺・入射辺が混在するファン](docs/images/before-after/fan-mixed-before.png)](docs/images/before-after/fan-mixed-before.png) | [![対称スロット+鏡映入射に統一されたファン](docs/images/before-after/fan-mixed-after.png)](docs/images/before-after/fan-mixed-after.png) |
| 同一 ALB からの対エッジが右辺と下辺に割れ、入射辺も混在 | 右辺の対称スロット(0.35/0.65)から出て上下対面辺へ鏡映入射に統一 |

## スキルの効果(実測)

自然言語の作図依頼から人手修正なしで 0 エラー・0 警告の .drawio を出せるかを、
[evals/](evals/) の評価スイートで測定しています(実測 2026-07-15、各構成 n=2):

| 構成 | expectations 充足 | 0 エラー・0 警告の図 |
|---|---|---|
| **スキル有**(当時の全 16 eval) | **83/83** | **16/16** |
| スキル無(基本 12 eval) | 34/61 | 3/12 |

採点は eval 設計者でも実行エージェントでもない新品コンテキストのエージェントが
行い(独立採点)、機械照合できる部分は自動判定します。詳細は
[evals/README.md](evals/README.md) を参照。

## ライセンスと商標

- 本リポジトリは [MIT License](LICENSE)。draw.io 由来のアイコンメタデータの帰属は [NOTICE](NOTICE) 参照。
- `references/icons-*.tsv` のアイコンメタデータ(名前・スタイル文字列・寸法)は
  [draw.io](https://github.com/jgraph/drawio)(Apache-2.0)のシェイプライブラリから
  抽出したものです。**アイコン画像そのものは同梱していません**(描画は draw.io 側の
  シェイプ・画像ライブラリを参照します)。
- AWS / Amazon Web Services、Microsoft Azure、Google Cloud の名称・アイコンは
  各社の商標です。図中での利用は各社のアイコン利用ガイドラインに従ってください。

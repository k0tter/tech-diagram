# Terraform → 図の自動起こし(tf_to_spec)

読むのは「Terraform リポジトリから図を作る」とき。手で .tf を全読みしない —
機械で骨格を作り、エージェントは判断が要る部分だけを読む。

## 推奨フロー

```bash
# 1. 骨格生成(認証・terraform CLI・state 不要。.tf を直接パース)
python3 {SKILL}/scripts/tf_to_spec.py <root module ディレクトリ> \
  -o <name>.spec.json --review <name>.review.json

# 2. review を潰す(下記)→ スペックを仕上げる

# 3. 叩き台を生成して磨く
python3 {SKILL}/scripts/build_drawio.py <name>.spec.json -o <name>.drawio --optimize 30
```

着手前の確認: 複数環境リポジトリ(envs/prod と envs/dev 等)は**どの root を
描くか**をユーザーに確認してから 1 を実行する。

## ツールが自動で出すもの(信じてよい)

- ノード: 図に載せる価値のある型だけ(IAM・ルートテーブル・SG ルール等の
  配線材料はノードにしない)。未対応の型は review の `unmapped_resources` へ
- コンテナ: VPC / サブネット(public/private は `map_public_ip_on_launch` と
  名前で判定)、所属はサブネットグループの間接参照まで解決
- **確定エッジ**(根拠は review の `confirmed_edges`):
  トリガー配線(event source mapping / SNS 購読 / EventBridge ターゲット /
  S3 通知 / API GW 統合)と **env var の他リソース参照**(TABLE_NAME =
  aws_dynamodb_table.x.name の類 — ほぼ確実な利用証拠)
- 注記: `count`/`for_each` が 0 になり得る条件付きリソース(図では半透明+
  [条件付き] 表示)、未参照モジュール、展開できない外部モジュール

## エージェントが潰すもの(review.json)

1. **`lambda_code_review`**: 各 Lambda のソース所在(`source=<実パス>`)。
   そのディレクトリを Read して SDK 呼び出し・Lambda 間 invoke・外部 API を
   確認し、エッジを追加する。`code=リポジトリ内にソースなし` の関数は
   env var / トリガー / IAM 候補だけで判断し、その旨を meta.assumptions に書く
2. **`edge_candidates`**: IAM ポリシー由来(`iam:` 接頭辞)と属性参照由来
   (`attr_ref`)の候補。コード確認・構成理解に基づいて採用/棄却する。
   IAM は付けすぎ権限による偽陽性があるので単独では確定にしない
3. **`unmapped_resources`**: 図に載せるべきか判断し、載せるなら
   find_icon.py でアイコンを探して手でノード追加
4. meta の `purpose`/`audience` を埋め、判断(省略・注記・候補の採否)を
   `assumptions` に記録する

## state による実在照合(オプション・普段は不要)

「書いてある=使う」が前提。ドリフトや destroy 済みを疑うときだけ:

```bash
terraform state pull > /tmp/state.json     # ユーザー側で実行(S3 バックエンド透過)
python3 {SKILL}/scripts/tf_to_spec.py <dir> --state /tmp/state.json
```

state に無いリソースは注記に出る。**state ファイルを Read で直接開かない**
(DB パスワード等の秘密情報が平文で入っている)。ツールは type/name の
位相情報だけを読み、値は一切出力しない。使用後は /tmp の state を消す。

## 対応している間接参照(黙って消えない)

- `local` 代入・`module` 出力・モジュール入力 `var` を **4 ホップまで解決**
  して env var エッジ等に反映する
- 同一ローカルモジュールの複数インスタンス化(使い回し)はインスタンス
  ごとに展開される(id は `モジュール名__リソース名`)
- multi-AZ で余った空サブネットは自動で省略し注記に残す(代表化)

## 限界(知っておく)

- HCL のサブセットパーサ: `dynamic` ブロック・関数評価・`for` 式の中身は
  展開しない(参照の抽出はされる)。凝った書き方は取りこぼしがあり得る —
  生成後に「載っているべきものが欠けていないか」を .tf の resource 一覧
  (`grep -rn '^resource' *.tf`)と突き合わせるのが安全
- 複数サブネットに跨るリソース(ALB・multi-AZ RDS)は先頭サブネットに
  代表配置される(またぎ表現にしたければ手で VPC 直下へ)
- エッジの意味付け(通信経路)はツールの守備範囲外。確定エッジも「設定上の
  結線」であって、実際のデータフローの向きはエージェントが判断する

# 独立採点エージェントのプロトコル(grader)

eval の採点を、実行エージェントとも eval 設計者とも別の**新品コンテキストの
エージェント**が行うための手順。設計者が自分で採点すると、期待挙動を知っている
ぶん甘くなる(自己採点バイアス)— それを排除する。

## 入力(run ディレクトリに揃っていること)

- `eval_metadata.json` — prompt と assertions(= evals.json の expectations)
- `outputs/` — 実行エージェントの生成物(.spec.json / .drawio / review.json 等)
- `report.md` — 実行エージェントの最終報告(オーケストレータが保存する)

## 手順

1. **機械照合を先に走らせる**(自己申告を読む前に判定を固定する):
   ```bash
   python3 {SKILL}/evals/check_diagram.py --spec <outputs/*.spec.json> [--absent コード...] --json
   # スペックが無い修正系 eval は .drawio 直で。1:1 保持は --graph-superset <元ファイル>
   ```
   eval ごとの推奨フラグは `evals/README.md` の対応表を使う。
2. **構造照合**: assertions が構造で判定できるもの(step バッジの有無・
   entity/er_ 記法・lane コンテナ・for_each 展開ノード・エッジの有無など)は、
   .spec.json / .drawio / `validate_drawio.py --graph` を自分でパースして確認する。
3. **報告照合**: Abstraction Notes・Coverage audit・判断の明記などレポート系の
   assertions は `report.md` の実文で確認する。**「やった」と書いてあるだけで
   生成物に痕跡が無いものは fail**(例: 「バリデータ 0/0」と書いてあるのに
   check_diagram が warning を出す → fail、evidence に両方を書く)。
4. **grading.json を書く**(スキーマは skill-creator の grading.json に準拠):
   ```json
   {"expectations": [{"text": "...", "passed": true, "evidence": "機械照合/構造/報告のどれでどう確認したか"}],
    "summary": {"passed": N, "failed": M, "total": T, "pass_rate": 0.0}}
   ```
5. 判定に迷ったら**厳しい側に倒し**、evidence に迷った理由を書く。
   assertions の文言が実装と食い違う場合は fail にせず evidence に
   「assertion の文言問題」と明記する(eval 側の改善材料)。

## アーキ正しさ採点ルーブリック(レビューゲート AP7〜AP13)

機械検査(W16〜W21 = check_diagram の `--absent W16 W17 W18 W19 W20 W21` で照合)に
**乗らない**7項目の判定基準。各項目を **Yes(違反あり)/ No(違反なし)/ N/A
(対象構成が図に無い)** で判定する。判定材料は .spec.json のグラフ(nodes/edges の
icon・kind・label)と report.md — 「兆候」に挙げた条件が揃えば Yes、対象自体が
図に無ければ N/A(N/A は fail にしない)。根拠はすべて
`references/patterns.md` / SEM-1 カタログの AWS 一次情報に接地している。

| # | 判定すること | Yes(違反)の具体的兆候 | N/A の条件 |
|---|---|---|---|
| AP7 | 自前 CloudFront の背後の API Gateway が edge-optimized になっていないか | cloudfront → api_gateway の main エッジがあり、かつ spec の label/meta にも report にも「regional」エンドポイントの明示が無い(edge-optimized はそれ自体が CloudFront 経由のため CDN 二重) | cloudfront→api_gateway の直列が図に無い |
| AP8 | Cognito がリクエスト経路に直列に描かれていないか | user/client 系 → cognito → api_gateway の **main(実線)エッジ直列**がある(正: クライアント⇄Cognito は認証の補助線 sub/点線、メイン線はクライアント→API Gateway 直行) | cognito ノードが図に無い |
| AP9 | Aurora Global / DynamoDB GT の複製・書き込み方向が正しいか | (a) label に Secondary/Replica/セカンダリ等を含む Aurora ノードへアプリからの main(書き込み)エッジがある (b) Aurora 対の repl エッジが bidir(双方向)になっている (c) 逆に DynamoDB Global Tables の複製線が一方向のまま(正: Aurora=primary→secondary 一方向・DynamoDB GT=双方向) | リージョン間のデータ複製が図に無い |
| AP10 | RDS Multi-AZ スタンバイへ読み取り線を引いていないか | label に standby/スタンバイを含む RDS/Aurora ノードへ、アプリ層からの main エッジがある(正: スタンバイは読めない。読み取り分散はリードレプリカ/Multi-AZ DB クラスターとして明示的に描く) | standby 表記のノードが図に無い |
| AP11 | S3 website endpoint と OAC/OAI を併用していないか | label/meta/report に「静的ウェブサイトホスティング/website endpoint」とありながら、同じ S3 に OAC/OAI で非公開と主張している(website endpoint はカスタムオリジン扱いで OAC/OAI 不可) | S3 静的配信が図に無い、または endpoint 種別への言及が無い |
| AP12 | 「集中 egress」構成で各ワークロード VPC に出口が残っていないか | タイトル/依頼/label に集中 egress・centralized egress とあり、egress VPC 以外の VPC 内に nat_gateway / internet_gateway ノードがある | 集中 egress を掲げた図ではない |
| AP13 | DR の切替起動方式(自動/手動)が明示されているか | failover 線・DR 構成があるのに、meta.assumptions にも report にも自動/手動の別(自動なら誤検知コストへの言及、手動なら手順自動化)が無い(DR ホワイトペーパー: 自動切替は誤検知コストがあるため手動起動+手順自動化がよく使われる) | failover 線・DR 構成が図に無い |

- 判定した項目は grading.json の evidence に「AP9=No: repl エッジ r1 は
  aurora_p→aurora_s の一方向・bidir なし」のように **エッジ/ノード id を挙げて**書く。
- Yes(違反)は該当 expectation を fail にする。N/A は pass 扱いにし、evidence に
  「N/A: 対象構成なし」と書く。
- ラベル文字列に依存する判定(AP9/AP10)は、ラベルから役割が読み取れない場合
  「判定不能」とし、厳しい側(fail)ではなく evidence に判定不能の理由を書いて
  pass にする(誤検知ゼロ優先 — 機械検査 W16〜W21 と同じ方針)。

## 禁止事項

- 実行エージェントの report.md の主張だけを根拠に pass にしない(機械照合を優先)
- 生成物を修正しない(採点は読み取りのみ)
- expectations に無い観点で減点しない(発見は grading.json の外に note として書く)

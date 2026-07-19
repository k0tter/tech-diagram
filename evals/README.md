# tech-diagram evals — スキル有効性の end-to-end 評価

## 何を測るか

**「Claude/Codex 等のエージェントがこのスキルを起動して、自然言語の作図依頼から、人手修正なしでそのまま使える
0 エラー・0 警告の .drawio を作れるか」** を測る。アイコン選択・境界配置(グローバル/
リージョナル、サブネット内外)・縮約の判断・番号付け・バリデータ反復・納品レポートまでを
含む、エージェントの判断の質を評価する。

### `scripts/tests.py` との違い

| | `scripts/tests.py` | `evals/`(これ) |
|---|---|---|
| 対象 | スクリプト内部(ビルダー/バリデータ/レイアウトエンジン/tf_to_spec) | エージェントがスキルを使う end-to-end |
| 問い | 「サブネット内のマネージドサービスに W8 を出すか」 | 「"AWS 3層図を作って" から W8 の出ない正しい図を作れるか」 |
| 入力 | 固定 spec・敵対的 spec | 自然言語の作図依頼 |
| 実行 | `python3 scripts/tests.py`(CI) | 独立した実行エージェント/採点エージェント |

本 evals は、手動の実戦検証を再現可能な end-to-end 評価として定式化したもの。

## eval 一覧(全20件 = 基本12+高難度4+回帰2+アーキ正しさ2、118 expectations)

### 基本セット(id 1–12)

| id | 名前 | 狙う能力 | fixture |
|---|---|---|---|
| 1 | aws-web-3tier | VPC/サブネット境界・グローバル/リージョナル・左→右 | — |
| 2 | reference-architecture | step バッジ+steps 説明パネル・無地矢印(W12) | — |
| 3 | multi-account-org | Organizations 階層(ou/account)・ID 併記・W9 | — |
| 4 | multi-region-dr | 左右対称 DR・レプリケーション線種・凡例自己完結 | — |
| 5 | multicloud-aws-azure-gcp | azure:/gcp: プレフィックス・3社コンテナ型・貫通なし | — |
| 6 | er-diagram | entity 箱・er_ 系多重度線 | — |
| 7 | uml-class-diagram | クラス箱(属性/メソッド)・継承/コンポジション/関連 | — |
| 8 | flowchart-approval | 上→下・スイムレーン(lane)・ひし形分岐・差し戻し | — |
| 9 | high-degree-hub | 次数10級ハブの畳み方(リング/分解/端点集約)・交差目安 | — |
| 10 | terraform-to-diagram | tf_to_spec・確定エッジ反映・条件付きデッドコードの扱い | `files/terraform-orders-api/` |
| 11 | modify-existing-drawio | スペックなし図の修正・構成 1:1 保持(--graph) | `files/modify/webapp.drawio` |
| 12 | dense-abstraction-1page | 1ページ縮約・横断的関心事の代表化・Coverage audit | — |

網羅範囲: クラウド構成図(AWS/Azure/GCP・マルチ)・リファレンス図・ER・UML・
フローチャート・Terraform 起こし・既存図修正・高次数ハブ・縮約の全モード。

### 高難度セット(id 13–16、iteration-2 で追加)

iteration-1 の基本12本は with_skill が満点(61/61)で天井に張り付いたため、
スキルの**上限**を測る4本。iteration-2 実測: 18/22(e13/e15/e16 満点、e14 のみ 1/5)。

| id | 名前 | 突く限界 | fixture |
|---|---|---|---|
| 13 | scale-conflict-complete-1page | 48要素×完全表現×1ページ×ハブ2つ(--optimize 有効域の上限) | — |
| 14 | wrong-instruction-boundary | ユーザー指示 vs 公式境界慣例(W8 違反の明示要求) | — |
| 15 | terraform-messy-repo | tf_to_spec の実在の取りこぼし3罠: for_each 縮約・**既定 true** の条件付き WAF(e10 の逆)・孤児モジュール混入 | `files/terraform-messy/` |
| 16 | repair-broken-drawio | スペックなしの壊れ図(E1+E4+E6×6 を仕込み済み)の修復+機能追加 | `files/repair/legacy-webapp.drawio` |

e14 は当初スキルが落ちた割れ目(指示に従い W8 を残す・1/5)。SKILL.md「AWS 境界の
正確さ」に指針(明示要求でも従わず endpoints へ翻訳+根拠報告)を追記後の再実行で
5/5 に回復済み(iteration-2 の with_skill_v2)。以後この指針の**回帰テスト**として機能する。

### 回帰セット(id 17–18、第3R〜第7Rで拡張)

| id | 名前 | 固定する挙動 | fixture |
|---|---|---|---|
| 17 | router-regression-multi-az | ルータ優先原則「接続して見える(辺中央付近から出入り)> 直線 > 折れ点最少」の3挙動+第4R の3挙動(出射辺の方向・垂直ペア中心・兄弟コンテナ寸法)+第5R の4挙動(ファン辺流儀統一・折れ点上限・同一辺ポート分離・fork 形状) | `files/router-regression/`(fail-before 検証用) |
| 18 | r7-flow-er-uml-contracts | decision 4頂点+上方流入、safe id、両端ラベル、ER端別カーディナリティ、stereotype斜体、新flow shape/link、gateway fork/join | `files/router-regression/r7-*.spec.json` |

v1.5.0 直線優先化の3つの副作用(①端点 frac がほぼ角 0.9215 へ ②同一 src ファンの
±7px 階段割れ ③異 src 並走の分離漏れ)と、v1.6.0 に残った3つの不自然さ
(④行き先と逆の辺から回り込む出射 ⑤垂直複製ペアの中心ずらし直線 ⑥同種兄弟
コンテナの寸法ガタつき)、v1.7.0 に残った不統一(⑦同一 src 横ファン対の
出射/入射辺の混在 ⑧交差ゼロでも残る折れ多の大回り ⑨手動 pin と自動端点の
矢じり重なり ⑩中心二股が平行 2 レーンに割れる)の修正を、e14 方式で固定する。
`scripts/tests.py` の TestFeedbackRound3 / TestFeedbackRound4 /
TestEqualizeContainers / TestExternalPatchA / TestCenterFork / TestSublaneRepair が
エンジン内部を、本 eval が end-to-end(自然な依頼から3形状 — 縦並び複製ペア2組の
隣接・ALB 上下ファンアウト・題字が上辺を覆う狭サブネット — を含む図を17チェック
0 違反で出せるか)を担う。e18 は自然言語で安定して要求できる decision・両端ラベル・
ER端別・stereotype を3タブ課題として固定する。unsafe id・特定の新shape・fork/join・
subprocess link の**発動そのもの**は自然言語から安定誘発できないため、固定スペックの
`verify.py` に委ねる。

### アーキ正しさセット(id 19–20、SEM-4 で追加)

SEM-1〜3(接地カタログ → リファレンススペック → W16〜W21 実装)で潰した
**アーキテクチャの意味的な誤り**が、将来黙って再発したら eval が落ちて捕まえる
ための回帰セット。発端は出荷済みテンプレ example-multiregion / example-dense-1page
の実誤り = **DR フェイルオーバー非対称**(平常時ユーザー→CloudFront(+WAF)→ALB
なのにフェイルオーバーが Route 53→DR の ALB 直行で CDN/WAF をバイパス)。

| id | 名前 | 突く誤り | 機械照合 |
|---|---|---|---|
| 19 | architecture-correctness-dr | DR 非対称(W16)・グローバルのリージョン内配置(W17)・複製方向(AP9)・切替起動方式(AP13) | `--spec <spec> --absent W16 W17 W18 W19 W20 W21` +ルーブリック |
| 20 | architecture-correctness-ha-3tier | HA 詐称単一 AZ(W20)・DB public(W18)・外部→DB 直結の誤指示(W19、e14 と同じ規律)・standby 読取(AP10)・NAT 欠落(W21) | 同上 |

**機械検査(W16〜W21)とレビューゲート(AP7〜AP13)の棲み分け**:
アンチパターン13件のうち、曖昧さゼロで機械判定できる6件だけを
W コード(ビルド段 `build_drawio.validate_spec` +バリデータ
`validate_drawio` の両対応、語彙は `scripts/_common.py` に一本化)にした。
残り7件は図に現れない属性(エンドポイントタイプ)やラベル文字列に依存し、
規則化すると偽陽性がメンテ負荷を上回るため、機械化せず
**grader.md の「アーキ正しさ採点ルーブリック」**(AP7〜AP13 を Yes/No/N/A で
判定する採点者向け基準)に置いた。

| コード | 内容 | 段階 |
|---|---|---|
| W16 | フェイルオーバー線が CDN/WAF をバイパスして DR の LB/コンピュートへ直行(REL13-BP04 のサービス差異。バイパス経路は WAF 検査ゼロ+推奨保護構成では 403 で DR 不能) | WARN |
| W17 | CloudFront/Route 53/WAF(CloudFront 接続)が region/VPC/サブネット内(グローバルサービスはリージョン障害の切替対象ではない) | ERROR(ビルド拒否) |
| W18 | RDS/Aurora/ElastiCache 系が public subnet 内(DB は private subnet が公式推奨) | ERROR(ビルド拒否) |
| W19 | 外部クライアント → DB の直接エッジ(DB へのアクセスはアプリ層からのみ) | ERROR(ビルド拒否) |
| W20 | ラベルに Multi-AZ/HA/冗長とあるのに AZ コンテナ相当が 1 つ以下(REL10-BP01 のアンチパターン第1項) | WARN |
| W21 | private subnet 内ノードから外部への直行エッジ(NAT/IGW/エンドポイント非経由 — 到達不能な経路) | WARN |

era=sem(旧 = SEM-3 実装前 v1.9.0 スナップショット、実測 2026-07-18):
`files/sem-regression/` の誤りスペック7本(w16〜w21 の最小形+
**multiregion-prefix = example-multiregion の修正前形そのもの** = DR 非対称の
実誤り・最重要 fixture)を旧エンジンでビルドすると **7本全てが素通り**
(ビルド成功 rc=0・W16〜W21 のログ 0 行・旧バリデータの finding も 0 件)。
**同じ産物**へ現行バリデータを通すと各 fixture で狙いのコードが 1 件ずつ発火
(multiregion-prefix → W16)。現行エンジンは同じ誤りスペックを W17/W18/W19 で
ビルド拒否、W16/W20/W21 で WARN+validate 発火させ、正解形 6 本(`ok/`)は
0 error・0 warning・W16〜W21 = 0 件で通る(すべて `verify.py` が毎回実証)。

誤検知ゼロの固定: `verify.py --sweep-sem` が同梱テンプレ10(validate 直)+
リファレンススペック5(現行ビルド+validate)の**計15ファイルで
W16〜W21 = 0 件**を確認する。任意の手元図は
`--sweep-dir label=/absolute/path` で明示追加できる。

**fail-before の実証**(エージェント実走なしの判別力確認):
`files/router-regression/verify.py` が固定スペック(fixture 12本+
`templates/example-complex.spec.json`)を現行/旧エンジンの両方でビルドし、
17チェックの判別力を世代別(`--era r3|r4|r5|r7|sem` — sem はルータ幾何でなく
アーキ正しさ W16〜W21、後述のアーキ正しさセット節)に再現確認する。現行エンジンは
全13スペックで17チェック 0 違反+center-fork の fork 発動+二段ステップなし
(pass-after、実測 2026-07-18)。旧側の実測:

era=r3(旧 = R3 修正前 v1.5.0 スナップショット、2026-07-15):

- **接続アンカー**(pairs-anchor): 旧 = e6 の exit/entry frac **0.9215**(ほぼ右角)×2件
- **ファンアウト対称**(fan-symmetry): 旧 = 縦レーンが **x=223 / 209** の ±7px
  階段に分裂 → 現行 = x=216 を共有
- **レーン分離**(multi-az-ecs): 旧 = r_db の迂回が r_ca と**間隔 2.4px で 129px
  並走**(E7)→ 現行 = 中心出射+最小ジョグで 0/0

era=r4(旧 = R4 修正前 v1.6.0 スナップショット、2026-07-16):

- **出射辺の方向**(example-complex): 旧 = e10 exit / e23 entry が行き先と逆の辺から
  回り込み(余弦 **-0.698 / -0.513**)→ 現行 = 行き先に面した辺(負の余弦 0 件)
- **垂直ペア中心**(pairs-anchor): 旧 = e6 が中心からずらした垂直直線 frac
  **0.6484** → 現行 = 列幅拡張で中心 **0.5** を確保
- **兄弟コンテナ寸法**(multi-az-ecs): 旧 = 各 AZ 内のサブネット高 **154 / 318**
  のガタつき ×2組 → 現行 = 寸法等化で 318 / 318

era=r5(旧 = 外部パッチ A / R5-B/C 実装前 v1.7.0 スナップショット、2026-07-17):

- **ファン辺の流儀統一**(fan-mixed): 旧 = コンテナ宛の対の exit が
  **右辺 [1,0.35] / 下辺 [0.5,1]**、entry が **下辺(v流儀)/ 左辺 [0,0.474]
  (h流儀)** の混在 ×2件 → 現行 = exit 右辺 0.35/0.65 対称+entry 上下対面辺
  [0.5,1]/[0.5,0] の鏡映 v 流儀に統一
- **同一辺ポート分離**(pin-ladder): 旧 = 手動 pin(hub 左辺 frac 0.4)の
  **7.8px 隣(frac 0.5)**へ自動端点を割当(W6 矢じり重なり)→ 現行 = pin を
  固定スロットとして回避し frac 0.715 へ(24.6px 分離。この帯外 frac は
  A-3 の既知の副作用で、接続アンカー検査は同一辺 2 ポート以上のラダー免除が
  pin も数えるため衝突しない — pin 入りフィクスチャ現行ビルドで違反 0 を実測)
- **fork 形状**(center-fork): 旧 = **機能自体が無く**、exit [0.5,0]/[1,0.5] の
  不揃い 2 レーンで fork 署名(対称スロット 0.35/0.65 +対面辺入射)にならない
  ことを before として記録(verify.py の擬似チェック fork_absent)→ 現行 =
  fork 発動(レーン x=304.4 を 2 本が共有・entry frac 0.2505 = レーン正規化値・
  トランク間隔 23.4px)
- **二段ステップ**(sublane-step): 旧 = s4 の src 側に **横32px→縦36.3px→横**の
  終端二段ステップ(verify.py の擬似チェック two_step_ends — R5-C の検出形状を
  eval 側に凍結した再実装)→ 現行 = サブレーン修復で段差なし

era=r7(旧 = 第7R開始前 backup8、A/A2/B/C 実装前、2026-07-18):

- **decision/gateway頂点**(r7-decision): 旧 = 頂点外5件((0.715,1)、(1,0.65)、
  (1,0.35)、(0,0.35)、(0,0.65)) + 上方流入が上頂点でない2件 = **計7件**
- **safe id**(r7-id-labels-uml): 旧 = 危険id `join` がXMLに残る **1件**
- **両端ラベル**(同): 旧 = `src_label` / `dst_label` の子セル欠落 **2件**
- **stereotype**(同): 旧 = interface / abstract のstereotype行・italicビット欠落
  **2件**
- **ER端別**(r7-er-cardinality): 旧 = `er_01n` を未知kindとして明示拒否
  (**build-rejected 1件**)
- **新flow shape / gateway**(r7-flow-shapes): 旧 = `connector` を未知shapeとして
  明示拒否(flow_shapes_links / gateway_topology / diamond_vertices の各
  **build-rejected 1件**)
- **subprocess link**(r7-subprocess-link): 旧 = `UserObject link` 属性欠落 **1件**

build rejection を fail-before とするのは、旧エンジンが新kind/shapeを黙って欠落
させず入力境界で拒否する上記2 fixtureだけ(表示は「機能未実装」)。その他は
旧出力を新checkerへ渡して実際のXML違反数を測る。build-rejected の2 fixtureでは
検査関数が一度も走らないため、検査自体の判別力は `router-regression/broken/` の
破損フィクスチャ(現行ビルドの正しい出力を人工的に壊した固定 .drawio)で実証
する — `verify.py` の pass-after 実行が毎回、er_cardinality / flow_shapes_links /
gateway_topology / diamond_vertices の ≥1 違反検出を確認する(REV-3)。

折れ点上限(max_bends)のみ fail-before を持たない: 閾値は誤検知ゼロ校正で
実測最大 6(dense / multiregion の by-design 障害物迂回 — exit_direction が
大迂回として免除するのと同じ辺)+マージン 1 = **7** となり、A-2 磨きパスの
修復対象(6 折れ)は下回る。暴走経路(8 折れ以上)だけを検出するガードレール。

## 実行方法(2段)

以下の隔離 eval ループに従う。各 eval を **with_skill**(スキルを渡す)と
**without_skill**(ベースライン)の2構成で実行し比較する。

1. **executor**: 新品コンテキストのサブエージェントに、スキルへのパスと `prompt`
   (+ `files`)を渡して実行させ、生成物(`.spec.json` / `.drawio` とレポート)を保存。
2. **grader**: 生成物に対し `expectations` を採点。客観部分は `check_diagram.py`
   (下記)で自動照合し、判断・レポート系(Abstraction Notes の質・縮約の妥当性・
   references を読んだか)は成果物とトランスクリプトを見て採点する。

ベースライン(スキルなし)は Mermaid や生 draw.io XML を手書きし、バリデータを通さず
重なり・貫通の残る図を出しがち — `expectations` はその差が出るよう設計している。

## grading: `check_diagram.py`

`expectations` の**機械照合できる部分**を自動化する(残りは採点者が判断)。
`scripts/validate_drawio.py`(幾何/境界: E\*・W1–W8/W10–W14・I1 交差)に加え、
`--spec` を渡すと `build_drawio.py` でビルドし直してビルド段の警告(
legend 未掲載・meta 欠落)まで拾う。**完全な 0 警告判定には `--spec` を使う。**

```bash
# 生成 .drawio を検証(0/0・交差目安・finding コード)
python3 evals/check_diagram.py <out.drawio>

# 特定コードの不在を要求(AWS 図: 境界違反が無いこと)
python3 evals/check_diagram.py <out.drawio> --absent W8 W11

# スペックからビルドし直して W9/legend/meta まで含め完全判定
python3 evals/check_diagram.py --spec <out.spec.json>

# 既存図の 1:1 保持(modify eval): baseline の全頂点・辺が残っているか
python3 evals/check_diagram.py <out.drawio> --graph-superset evals/files/modify/webapp.drawio

# ルータ回帰チェック(eval 17)も判定
python3 evals/check_diagram.py --spec <out.spec.json> --router

# 採点エージェント向け JSON
python3 evals/check_diagram.py --spec <out.spec.json> --json
```

### `--router`: ルータ回帰の機械照合(eval 17–18)

生成 .drawio の XML 幾何(セグメント抽出・座標系は validate_drawio.py の
E7/W5 実装と同じ規約)を直接測る17チェックを追加する。コンテナ題字帯の貫通は
既存の W5 がビルド/validate 段で機械検出するため、--router では重複実装しない。
R5-D(経路の慣性)は `<out>.routes.json` キャッシュがあるときだけ働く機能で、
eval はキャッシュなしの新規ビルドしか扱わないため検査対象外。

FB第3R の3チェック:

- **check_anchor_fractions(接続アンカー)**: 全ノード端点の「辺に沿う方向」の
  exit/entry fraction が 0.35〜0.65(辺中央付近)。対象外 = コンテナ端点・
  同一辺の多重ポートラダー(指摘6の対称規約で 0.15〜0.85 が正当)・手動配線
  レシピの分割点 **0.25 / 0.75 ちょうど**(layout-rules の 3 点セット手動配線
  規約 — 実案件 03 で実測。自動端点は NEAR_FRAC クランプでこの値に落ちない)。
  旧 SLIDE_MAX(辺中心から 14.5px 以内の端点スライド)免除は R4-4
  (separate_terminals の NEAR_FRAC クランプ)で撤去済み — 単独ポートの
  帯外端点は常に実バグとして検出する
- **check_fan_symmetry(ファンアウト対称)**: 同一 src の対エッジで、同一回廊の
  中間レーン(区間が重ならない対 = エンジンの対称ユニット条件)が一致(±2px)
  or src 中心対称であること、対称ユニットの entry fraction が対で一致すること
- **check_corun_separation(レーン分離)**: 異 source のエッジ同士が 7px 未満の
  間隔で 20px 超、同軸並走していないこと(E7 の再実装でなく幾何の直接測定。
  同一 src の fork トランクは意図的な同走なので除外)

FB第4R の3チェック:

- **check_exit_direction(出射辺の方向)**: 両端ノードのエッジ端点で、端点辺の
  外向き法線と相手ノード方向の余弦が **-0.48 以上**(エンジン _dir_penalty と
  同じ測り方)。閾値は校正対象12種の実測で決定 — by-design の最悪値(交差最少が
  辞書式に勝った正当な辺選択: dense -0.455 / multiregion -0.379)は通し、
  R4-1 修正前の悪例(complex -0.698 / -0.513)は検出する。折れ線 6 点以上の
  大迂回(dense の -0.987 / -0.58)は正当として対象外。さらに免除2種(A3校正):
  ①戻りエッジ = 破線かつ dst 箱が src 箱より完全に上(フロー図の差し戻し。
  実測 01-approval f10 -0.843)②ER ハブ出射 = ER マーカー付きエッジで src
  次数 ≥3(実測 04-saas-er r1 -0.693/-0.721)。悪例 e10 は非破線・e23 は
  下向きでどちらの免除にも掛からず検出維持。悪例と by-design の
  マージンが ±0.03 前後と薄いため、閾値を動かすときは要再校正
- **check_pair_center(垂直ペア中心)**: 直行ノード間の垂直直線(2点折れ線・
  両端がノードの上下辺)の exit/entry fraction が **0.5±0.02**(R4-3 の中心
  優先を固定)。手動 points 凍結エッジは折れ点が入るため自然と対象外
- **check_sibling_dims(兄弟コンテナ寸法)**: 同一親・同種の兄弟コンテナの寸法が
  ±1px で一致(縦積み=幅・横並び=高さ — エンジンの等化が保証する軸のみ)。
  **対象は subnet 系と az に限定**。ou / account / generic 等を外すのは、
  ①等化のロールバック(等化で ERROR/WARN が増えるタブは等化なしで再ビルド —
  multiaccount テンプレの CI/CD タブで実際に発動)②等化実装前に検証済みの
  .drawio(実案件 04 等)の不一致が、XML からは「正当な見送り」と「バグ」を
  機械では区別できないため。subnet/az は全校正対象で不一致ゼロを実測確認済み

FB第5R の4チェック:

- **check_fan_side_consistency(ファン辺の流儀統一)**: 同一 src ノードから
  横方向(全 dst 中心が右または左)へ出る群のうち、**コンテナ宛メンバーが
  ちょうど 2 本の対**について、(a) 出射辺が同一 or 上下鏡映({上,下})で
  あること(軸をまたぐ混在 = 右辺+下辺は違反)(b) 入射辺が h 流儀(src を
  向く横辺)か v 流儀(src の行を向く上下対面辺)のどちらかに対で統一されて
  いること。**対(2本)限定なのは校正の実測による**: エンジンの fan_fixes は
  スコア第 4 キー+ゲート付き修復で、交差・題字・anti 端点を悪化させる統一は
  正当に見送られる(広い群定義では現行ビルド 9/15 に by-design 混在が残存
  → 対のコンテナ宛ファン = test_a1 の再現形状では常に統一される)
- **check_max_bends(折れ点上限)**: 全エッジの方向転換数が **7 以下**
  (斜め線は E4 の領分で対象外)。閾値校正は上記 era=r5 の節を参照
- **check_pin_slot_distance(同一辺ポート分離)**: 同一ノード同一辺の端点対の
  距離が **8px 以上**(自己ループは対象外)。pin は XML から自動端点と区別
  できないため全端点対で測る — A-3 修正前の実測 7.8px(W6)を検出し、正当な
  最小値(校正実測 13.0px・ラダー最密の理論値 ≈8.8px)は通す。pin の無い図
  では自動スロットが常にこの間隔を保つ(自動パス)
- **check_fork_shape(fork 形状)**: fork 署名(同一 src から 2 本が同一縦辺の
  対称スロット 0.35/0.65 で出てコンテナ宛・上行きは宛先下辺/下行きは上辺へ
  入射)に一致した対だけに、①折れ x の一致(±1px)②entry frac = レーン x の
  正規化値(±0.02)③平行トランク 2 本(出射 y 間隔 > 0)を要求する。
  署名が無い図は自動パス。fan_fixes が fork と同型(0.35/0.65 +鏡映入射)へ
  統一した対も署名に一致するが、その場合もレーン共有・entry 整合を実測で
  満たす(fan-mixed 現行ビルドで確認済み)

第7R の7チェック:

- **check_diamond_vertices(decision/gateway頂点)**: decision と parallel gateway の
  全端点が4頂点 `(0.5,0)/(1,0.5)/(0.5,1)/(0,0.5)` のいずれか
  (fraction許容 **±0.001**)。decisionの上方src流入は上頂点を要求するが、W15と
  同じく複数流入のうち1本が上頂点を取れば残りの側頂点を許す。自己ループ
  (retry 等)は builder/W15 と同じく対象外、端点未指定は E6 の領分として
  skip(REV-2/11)
- **check_safe_cell_ids(draw.io CLI安全id)**: Array/Object prototype由来49語が
  mxCell/UserObject/object idに残っていないこと(E10/E11 と同じ生タグ走査 —
  包みの内側 mxCell に残る id も拾う。REV-9)。builder定数をimportせずeval側へ凍結
- **check_end_labels(両端ラベル)**: `--spec` 時はsrc/dst双方のラベルセルの存在と
  値を要求し、出力XMLでは**端点→ラベル箱の最近接点が 90px以内**(中心距離だと
  長ラベルで恒常発火する — REV-1)・全ノード箱と非重複・
  `x=-1/1 relative=1 + offset` を照合
- **check_er_cardinality(ER端別)**: `er_01n` = 親側`ERzeroToOne`、`er_11n` =
  親側`ERmandOne`、子側はいずれも`ERmany`で、source/targetの向きも維持。
  spec なしの汎用則は「子側 ER マーカーの欠落」だけを見る(子側が別の ER
  マーカーのカスタム多重度 0..1:1 等は通す。REV-10)
- **check_stereotype_italic(UML stereotype)**: `--spec` の
  `stereotype: interface/abstract` に対し、stereotype行と`fontStyle` italicビット
  (bit 2)を要求。legacyのtitle直書き`«interface»`とはXMLだけで区別できないため
  presence検査はspec-aware
- **check_flow_shapes_links(new shape/link)**: gateway/delay/preparation/junction/
  connectorのnative styleと既定最小寸法(64x64 / 120x56 / 140x56 / 28x28 /
  42x42)をspecと照合し、subprocessは`UserObject link`属性と`shape=process`を照合
- **check_gateway_topology(fork/join)**: parallel gatewayが
  fork(入力1→出力2以上)またはjoin(入力2以上→出力1)を構成すること。
  入出とも複数の混合 gateway は違反(fork/join に分割する。REV-8)。
  gateway端点の4頂点規約はcheck_diamond_verticesが独立に担う

追加7チェックはリポジトリ内のテンプレ10種(`templates/*.drawio`)+
リファレンス5種(`references/reference-architectures/*.spec.json`)の
**計15ファイルで各0件**、
全17チェックはrouter-regression 12本+example-complexの現行ビルド13本で各0件を
確認済み(2026-07-18)。

任意の手元ディレクトリも加える場合は、`--sweep-dir label=/absolute/path` を
繰り返し指定する。リポジトリ固有でないパスは既定の検査対象に含めない。

### eval ごとの機械チェック対応

| eval | 推奨コマンド | 機械照合する expectation |
|---|---|---|
| 1 aws-web-3tier | `--spec <spec> --absent W8 W11` | 0/0・境界(W8/W11 無し) |
| 2 reference-architecture | `--spec <spec> --absent W12` | 0/0・番号整合(W12 無し) |
| 3 multi-account-org | `--spec <spec>` | 0/0・階層 W9(v1.3.1〜はバリデータ単体でも検出) |
| 4 multi-region-dr | `--spec <spec> --absent W11` | 0/0・Route53 グローバル・凡例(legend 未掲載はビルド段) |
| 5 multicloud | `--spec <spec>` | 0/0・貫通なし(E3/W7) |
| 6 er-diagram / 7 uml | `--spec <spec>` | 0/0 |
| 8 flowchart-approval | `--spec <spec>` | 0/0 |
| 9 high-degree-hub | `--spec <spec>` | 0/0・交差が目安内(I1 が WARN でなく INFO) |
| 10 terraform-to-diagram | `--spec <spec>` | 0/0(WAF/確定エッジの扱いはレポートで判断) |
| 11 modify-existing-drawio | `<out.drawio> --graph-superset files/modify/webapp.drawio` | 0/0・既存構成 1:1 保持 |
| 12 dense-abstraction | `--spec <spec>` | 0/0・交差目安(超過は理由付きで可) |
| 17 router-regression | `--spec <spec> --router --absent W5 E7` | 0/0・ルータ17チェック(第3R〜第7R)。R7項目が出現しない図では適用可能な不変条件のみ検査 |
| 18 r7-flow-er-uml-contracts | `--spec <spec> --router` | 0/0・decision頂点・safe id・両端ラベル・ER端別・stereotype。特定shape/fork/linkの発動は固定fixture |
| 19 architecture-correctness-dr | `--spec <spec> --absent W16 W17 W18 W19 W20 W21` | 0/0・アーキ6検査の非発火。AP9/AP13 は grader.md のルーブリック |
| 20 architecture-correctness-ha-3tier | `--spec <spec> --absent W16 W17 W18 W19 W20 W21` | 0/0・アーキ6検査の非発火。AP10 はルーブリック |

`check_diagram.py` は全チェック合格で exit 0、1つでも落ちれば exit 1。
判断系(Abstraction Notes・Coverage audit・references 参照・条件付きリソースの扱い)は
自動化せず、採点者が成果物とトランスクリプトで確認する。

### 独立採点(自己採点バイアスの排除)

採点は **eval 設計者でも実行エージェントでもない新品コンテキストのエージェント**に
任せる — 手順は [grader.md](grader.md)。オーケストレータは実行エージェントの
最終報告を run ディレクトリの `report.md` に保存し、grader は
`eval_metadata.json` + `outputs/` + `report.md` だけから採点する
(機械照合を先に走らせ、報告の自己申告は生成物の痕跡と突き合わせる)。
分散を見るため **runs_per_configuration ≥ 2 を推奨**。結果を公開するときは、
client / model / model version / 実行日 / OS・Python・draw.io version / 各 run の
`eval_metadata.json`・`grading.json`・生成物を揃える。これらの raw artifact を
同梱していない過去 run の集計値は、本リポジトリの再現可能な実測値として扱わない。
公平性のため with_skill / without_skill は同じ実行・目視環境を使い、
『references を参照した』等の skill 固有 assertion は lift と機能品質を分けて報告する。

## fixtures(`files/`)

- **`terraform-orders-api/`**(eval 10): 小さな root module。意図的に仕込んだ検証点 —
  ① env var 参照エッジ(Lambda→DynamoDB の `TABLE_NAME`)② トリガー配線(SQS→Lambda
  の event source mapping)③ **条件付きデッドコード**(`aws_wafv2_web_acl.front` は
  `count = var.enable_waf ? 1 : 0`、既定 false=未適用)。良いエージェントは確定エッジを
  反映し、WAF を稼働要素として描かず注記する。`tf_to_spec.py` は confirmed_edges 4本と
  WAF 条件付きの注記を自動生成する(検証済み)。
- **`modify/webapp.drawio`**(eval 11): スペックを持たない 0/0 の Web 三層
  (users→ALB→EC2→Aurora)。**監視(CloudWatch)を意図的に欠いている**。修正して
  監視を足す課題で、`--graph-superset` により既存構成の 1:1 保持を照合できる。
- **`router-regression/`**(eval 17–18): fail-before 検証用の固定スペック12本
  (multi-az-ecs = e17 相当 / pairs-anchor / fan-symmetry = 第3R、
  fan-mixed / pin-ladder / center-fork / sublane-step = 第5R。第4R の
  出射辺方向は `templates/example-complex.spec.json` を共用。第7Rは
  r7-decision / r7-id-labels-uml / r7-er-cardinality / r7-flow-shapes /
  r7-subprocess-link)+ `verify.py`。
  エージェント実走なしでルータ17チェックの判別力を再現確認できる — 現行エンジンで
  `python3 verify.py`(全 0 違反+fork 発動+二段ステップなし+W16〜W21 の
  誤り=発火・正解=非発火)、修正前エンジンのスナップショットを
  `--engine <旧 build_drawio.py> --expect-fail --era r3|r4|r5|r7|sem`
  で指すと、その世代の狙いのチェック(r5 の fork・二段ステップは verify.py 内の
  擬似チェック fork_absent / two_step_ends)が ≥1 違反することを確認する
  (era ごとの旧エンジン = r3: v1.5.0 / r4: v1.6.0 / r5: v1.7.0 /
  r7: 第7R開始前 backup8 / sem: SEM-3 実装前 v1.9.0 スナップショット。
  sem は旧 build_drawio.py と同じディレクトリに旧 validate_drawio.py を
  置くと validate 側の素通りも確認する)。
- **`sem-regression/`**(eval 19–20 と `--era sem`): アーキテクチャ正しさ
  W16〜W21 の固定 fixture。誤りスペック7本(`w16-*.spec.json` 〜
  `w21-*.spec.json` の最小形+`multiregion-prefix.spec.json` =
  example-multiregion の SEM-3 修正前形 = DR フェイルオーバー非対称の実誤り)、
  正解スペック6本(`ok/w16-ok.spec.json` 〜 — 同じ題材の正しい形。
  リージョナル WAF の region 内配置や CloudFront 起点のオリジン切替
  failover 線など、**誤検知しやすい正当形**を含む)、凍結産物7本
  (`broken/*.drawio` = 旧 v1.9.0 エンジンで誤りスペックをビルドした固定
  .drawio。W17/W18/W19 は現行エンジンがビルド拒否して産物を作れないため、
  バリデータ段の判別力はこの凍結産物だけが毎回実証できる — router-regression
  の broken/ と同型の REV-3 方式)。

## 前提環境

- `python3`(標準ライブラリのみ。ビルダー/バリデータ/tf_to_spec は外部依存なし)。
- 目視確認: draw.io CLI があれば PNG 直接書き出し。無ければ `build_drawio.py --emit-svg`
  → `qlmanage -t -s 2000 <svg> -o .` で PNG 化して Read(アイコンは色矩形代用)。
- `check_diagram.py` は本ファイルの1つ上の `scripts/` を自動参照するため、どの cwd
  からでも動く。

## 補足

- expectations の判定語彙・書き味は他スキル(article-craft 等)の evals.json に揃えている。
- eval を増やす/採点を回すときは、実行役と採点役を別コンテキストに分け、
  `evals/grader.md` の固定スキーマと機械照合を使う。

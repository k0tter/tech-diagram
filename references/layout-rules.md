# XML 手編集・絶対座標調整・手動配線ガイド

読むのは次の場面だけ: ① 既存 .drawio(スペックなし)を直接編集するとき、
② `--emit-abs` で出した abs.json をピンポイント修正するとき、
③ グリッドスペックのエッジを `points` で手動配線(凍結)するとき。
通常の作図(グリッドスペック→自動レイアウト)ではこのファイルは不要。

## グリッドスペックでの手動配線(points 凍結)

- **exit / entry / points の 3 点セットで書く**と、そのエッジだけ配線が固定される
  (格子探索・全体再配線の対象外になる)。exit+entry だけの両側ピンは、座標が
  一致しない限り斜め線 E4 になる — 必ず points で直交の折れ点を与える
- **points は描画後の最終座標**(メタパネルのシフト込み)。`--emit-svg` の SVG に
  写っている座標・`--emit-abs` の値をそのまま書いてよい
- 使いどころ: ルータは毎ビルド全エッジを引き直すため、1 本直すと別の 1 本が
  変わることがある。収束済みの長距離エッジから順に points で凍結すると安定する
- コンテナ宛エッジで経路だけ指定したいときも同様に 3 点セット(exit/entry の
  片方だけでは無視される)。それでも荒れるなら実際の消費先ノードを dst にする
- **W5(コンテナ題字貫通)を points の大迂回で隠さない**: 題字帯の経路回避と
  上辺 entry の帯右端オフセットはルータが自動で行う。それでも W5 が出るのは
  配置の症状 — 帯を塞いでいるノードを動かして自動配線に戻すのが正解
  (実例: 塞いでいたノードを 1 つ移動して手動 points を撤去 → 交差 2→0)

## 寸法の基準

| 項目 | 値 |
|---|---|
| アイコン | 78x78 固定。中心 cx/cy で指定 |
| 横の中心間隔 | ≥156px(ラベルが長いときは自動で広がる) |
| 縦のボックス間隔 | ≥44px(行高はその行のラベル行数に適応) |
| コンテナ内パディング | 上 34 / 左右 20 / 下 14 |
| 兄弟コンテナの間隔 | ≥20px(境界間の自由区間=回廊にエッジを通す。回廊は境界線から 22px 離れる) |
| サブネット最小 | 160x160(アイコン 1 個+ラベル) |

対称構造(Multi-AZ)は同一寸法・同一相対座標で複製する。ズレは一目でわかる。

- **上下パディングの非対称(上 34 / 下 14)に注意**: 題字帯のぶん上側が 20px
  厚い。Multi-AZ のペア経路(レプリケーション等)の脚長・折れ構造を揃えたい
  ときは AZ 行をハブ行を挟んで**鏡映対称**に組む — 行構成が非対称のままだと
  同種ペアの脚長が実測 24px 級でずれる(座標を 1px ずつ直すより行構成を直す)
- **同種兄弟コンテナ(同じ親・同じ type)はエンジンが既定で寸法を等化する**:
  縦積みは幅・横並びは高さを、広げる方向のみ揃える。等化で ERROR/WARN が
  増えるタブは自動でロールバックされる(INFO で報告)。固定したいときは
  トップレベルに `"equalize_containers": false`

## エッジ配線レシピ

- 全エッジに `exit`/`entry`([fx,fy]、0/0.25/0.5/0.75/1 から)と、直交になる
  `points`(絶対座標)を明示する。斜め線は E4 で落ちる。
- **回廊ルーティング**: エッジはアイコンやラベルの上を通さず、コンテナ間の
  22px 回廊・コンテナ内の余白帯を通す。コンテナ境界を横切るのは正常。
- **同一辺から複数エッジ**: exit を 0.25/0.5/0.75 に割り、回廊の x/y も
  エッジごとに 14〜20px ずらす(重走 E7 防止)。1 辺 3 本まで。
- **下辺の規約**(AWS 公式一頁物の流儀): 下向きに**出る**のは可 —
  `exit: [0.5, 1]` + `exit_dy: <ラベル高+2>` でキャプションの真下から
  まっすぐ出す(自動配線はリシェイプが自動でこの形にする)。ラベル付き
  アイコンの下辺に**入る**(上向き矢印)のは不可 — 左右辺から入れる
  (entity 箱・コンテナは下辺進入も可)。上辺は常に安全。
- **随伴サービス**(CloudFront への WAF/ACM 等): 相手の真上か横隣りに置き、
  短い破線スタブ 1 本で留める。exit をラベル幅の外(例 [0.2,1])にずらす。
- **K2,2(2↔2 の全結合)**: 平面上 1 交差が不可避。直角交差 1 箇所で許容するか、
  片側を図の外周に迂回させる。交差の許容目安はノード数連動(バリデータが表示する)。
- **ラベル**: `label_at` に「最長の水平セグメント中点の 12〜14px 上」の座標を
  指定する(E5 をほぼ確実に回避)。全エッジにラベルは不要。意味が自明な線は無ラベル。

## 修正の進め方

バリデータのエラーは座標のズレの症状。個別に 1px ずつ動かすより、
回廊の位置・列の cx 値を系統的に見直すほうが速い。交差(I1)は
「エッジ ID の組 @ 交点座標」で出るので、その 2 本の回廊選択だけを見直す。

## スタイル文字列(XML 手編集用)

アイコンのスタイルは `find_icon.py --style <name>` で正確な文字列が出る。
以下はコンテナ枠とエッジ。

フォント規約: fontFamily は全ラベル Arial(公式デッキ準拠)。ノード/コンテナ 12pt、
エッジラベルは 11pt(**意図的な差**: デッキ slide 12 の 12pt 規定は Icon Labels 対象。
エッジは主張を抑えて視線をノードに残すため 1pt 小さくしている)。

### コンテナ枠

共通プレフィックス `GRP`:
```
outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontFamily=Arial;fontStyle=0;container=1;pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;
```

| グループ | スタイル(GRP + 以下) |
|---|---|
| AWS Cloud | `grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;` |
| Region | `grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;` |
| VPC | `grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#AAB7B8;dashed=0;` |
| Public subnet | `grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;verticalAlign=top;align=left;spacingLeft=30;fontColor=#248814;dashed=0;` |
| Private subnet | `grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#00A4A6;fillColor=#E6F6F7;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=0;` |
| AWS Account | `grIcon=mxgraph.aws4.group_account;strokeColor=#CD2264;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#CD2264;dashed=0;` |
| EC2 contents | `grIcon=mxgraph.aws4.group_ec2_instance_contents;strokeColor=#D86613;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#D86613;dashed=0;` |
| Corporate DC | `grIcon=mxgraph.aws4.group_corporate_data_center;strokeColor=#7D8998;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#5A6C86;dashed=0;` |

Auto Scaling group のみ shape が `groupCenter`(GRP の `group;` を `groupCenter;` に変更):
`grIcon=mxgraph.aws4.group_auto_scaling_group;grStroke=1;strokeColor=#D86613;fillColor=none;verticalAlign=top;align=center;fontColor=#D86613;dashed=1;spacingTop=25;`

grIcon なしの素の枠(container 属性は同様に付ける):

| グループ | スタイル |
|---|---|
| Availability Zone | `fillColor=none;strokeColor=#147EBA;dashed=1;verticalAlign=top;fontStyle=0;fontColor=#147EBA;whiteSpace=wrap;html=1;container=1;fontFamily=Arial;pointerEvents=0;collapsible=0;recursiveResize=0;` |
| Security group | `fillColor=none;strokeColor=#DD3522;verticalAlign=top;fontStyle=0;fontColor=#DD3522;whiteSpace=wrap;html=1;container=1;fontFamily=Arial;pointerEvents=0;collapsible=0;recursiveResize=0;` |
| 汎用グループ | `fillColor=none;strokeColor=#5A6C86;dashed=1;verticalAlign=top;fontStyle=0;fontColor=#5A6C86;whiteSpace=wrap;html=1;container=1;fontFamily=Arial;pointerEvents=0;collapsible=0;recursiveResize=0;` |

### エッジ

共通ベース:
```
edgeStyle=orthogonalEdgeStyle;rounded=1;arcSize=8;orthogonalLoop=1;jettySize=auto;html=1;fontSize=11;fontFamily=Arial;fontColor=#232F3E;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;
```
main(実線)= ベース + `strokeColor=#232F3E;strokeWidth=1.5;`
角丸は `rounded=1;arcSize=8`(既定)。直角に戻すには style_extra に `rounded=0;`
sub(破線)= ベース + `strokeColor=#7D8998;strokeWidth=1.2;dashed=1;dashPattern=4 4;`

### カテゴリ色(2021+ 公式パレット)

`#ED7100` Compute/Containers | `#7AA116` Storage/IoT | `#C925D1` Database/DevTools |
`#8C4FFF` Networking/Analytics | `#DD344C` Security/FrontEnd | `#E7157B` AppIntegration/Management |
`#01A88D` AI・ML/Migration | `#232F3D` 汎用(ユーザー等)

#!/usr/bin/env python3
"""AWS アーキテクチャ図ジェネレータ。グリッドスペック(JSON)から .drawio を生成する。

ピクセル座標・配線は書かない。各ノードに整数の col/row(方眼紙のマス目)を
割り当てるだけで、ピクセル座標・コンテナのサイズと入れ子・エッジの直交配線・
ラベル位置は全てこのスクリプトが計算する。依存は Python 標準ライブラリのみ。

配線は回廊格子(セル間の隙間とセル中心線)上の最短路探索で行い、
交差・混雑・曲がりをコストとして複数の配線順序を試し、交差最少の結果を採用する。
アイコンの色/シェイプは icons-data.tsv から自動解決。生成後にバリデータを自動実行。

使い方:
  python3 build_drawio.py <spec.json> [-o out.drawio] [--no-validate] [--emit-abs]
                          [--optimize [秒]] [--emit-svg] [--route-cache]

  --emit-svg  : 簡易プレビュー SVG も出力(アイコンは色矩形代用。draw.io CLI が
                ない環境での目視確認用。複数タブは
                <out>.<01からの連番>-<安全化したタブ名>.svg)
  --emit-png  : 目視確認用 PNG を出力。draw.io CLI(drawio / macOS アプリ)を
                自動検出して実描画 PNG を書き出す(公式アイコン込み)。CLI が
                なければ --emit-svg と同じ SVG にフォールバックして通知する

  --optimize  : 配置ローカルサーチで col/row を改善しスペックへ書き戻す(既定 30 秒)。
                交差のみを最小化し、意味的な配置(対称性・帯)は保証しない。
                動かしたくないノードには "pin": true(col/row 指定が必須)
  --route-cache : 経路キャッシュ(<out>.routes.json)を有効化する。前回ビルドの
                エッジ経路を初期解として保持し、タブ全体のスコア(交差→題字→
                anti→折れ→長さ)が悪化しない限り同じ経路を維持する(pin 追加や
                エンジン改善で無関係なエッジが黙って動くのを防ぐ)。キャッシュは
                このフラグで作成され、以後はファイルが存在する限り読み書きされる
                (無効化はファイル削除)。ノード/エッジ集合(id・src/dst・col/row・
                コンテナ構成)が変わるとタブ単位で自動無効化される。タブの対応は
                名前で追跡し、名前が重複する場合は誤流用せず無効化する
  col/row が全ノードで未指定なら、エッジの流れから自動配置する(ドラフト品質)。
  このとき --optimize なしの通常ビルドでも、確定した col/row を入力スペックへ
  書き戻す(整形・キー順は dump_spec の形式に揃う)

グリッドスペック(複数タブは {"diagrams": [spec, ...]}):
{
  "name": "タブ名",
  "containers": [
    {"id":"cloud","label":"AWS Cloud","type":"aws_cloud"},
    {"id":"vpc","label":"VPC","type":"vpc","parent":"cloud"}
  ],
  "nodes": [
    {"id":"users","label":"ユーザー","icon":"users","col":0,"row":1},
    {"id":"ec2","label":"EC2 アプリ","icon":"ec2","col":3,"row":1,"parent":"vpc"},
    {"id":"lam2","label":"Lambda","icon":"lambda","col":1,"row":0,"ref":true}
  ],
  "edges": [
    {"id":"e1","src":"users","dst":"ec2","kind":"main","label":"HTTPS"}
  ]
}

キー解説:
  nodes.col/row   : 整数グリッド。col=左→右の流れ(1 ホップで +1)、row=段。
                    主フローは同一 row に並べる。対称構造は対称なマス目にする。
                    同一セルに 2 ノードは置けない。列幅はラベル長に応じて自動拡張
  containers      : 位置・サイズ指定不要(子ノードのマス目から自動算出)。親を先に
                    並べる。type: aws_cloud region vpc az public_subnet private_subnet
                    ou account security_group auto_scaling ec2_contents corporate_dc
                    generic
  nodes.icon      : icons-data.tsv の name(service 優先。"kind":"resource" で強制可)
  nodes.ref       : true で参照ノード(opacity=40。別タブへの再掲用)
  edges           : src/dst/kind(main=実線, sub=破線, ops=点線)/label。配線は自動。
                    "bidir":true で両矢印。コンテナも端点にできる(例: vpc→CloudWatch。
                    外周格子から障害物・交差を避け、境界セルが空く行を優先して接続)
  kinds           : {"名前": {"base":"sub","color":"#2E8B57"}} でカスタム線種を定義。
                    edges.kind と legend にその名前をそのまま使える(組み込みで足りないカテゴリ用)
  legend          : {"main":"同期", "repl":"複製", ...} で図の左下に凡例を自動生成
  badge_style     : "dark"(既定。濃紺+白数字)| "light"(白地+黒太字。公式
                    アイコンデッキの Numbered Callouts 準拠)。step バッジの配色
  equalize_containers : false で同種兄弟コンテナ(同じ親・同じ type、縦積み
                    または横並び)の寸法等化を無効化(既定 true=最大幅・
                    最大高に揃える。広げる方向のみで、接触が出る群は自動で見送り)

微調整のエスケープハッチ: --emit-abs で計算済み絶対座標スペック(<name>.abs.json、
出力 .drawio と同じ場所)を
出力し、部分編集して再生成できる(絶対形式: containers に x/y/w/h、nodes に cx/cy、
edges に exit:[fx,fy]/entry/points:[[x,y]..]/label_at:[x,y])。グリッドスペック内でも
edge に exit/entry/points を直接書けばその 1 本だけ手動配線にできる。
"""
from __future__ import annotations

import heapq
import html
import itertools
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, TypedDict

from _common import (COMPUTE_ICONS, CONTAINER_PARENTS, DB_ICONS,
                     DB_SUBNET_ICONS, EDGE_STACK_ICONS, EXTERNAL_CLIENT_ICONS,
                     GATEWAY_PLACEMENT, HA_TEXT_RE, ICON_ALIASES, LB_ICONS,
                     crossing_budget, icon_style, load_icons, resolve_icon,
                     seg_cross, text_size, text_width)

HERE = Path(__file__).resolve().parent

# ---- draw.io スタイル定義 ----

TEXT = ("text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
        "whiteSpace=wrap;rounded=0;fontSize=11;fontFamily=Arial;fontColor=#5A6C86;")

# リファレンスアーキテクチャ図の番号バッジ。トップレベル spec キー
# "badge_style" で選ぶ: 既定 "dark"=濃紺丸+白数字(公式一頁物 PDF の実例準拠)、
# "light"=白地+黒太字+濃紺ストローク(Architecture Icons デッキ 2025-07-31
# slide 13 "Numbered Callouts" 準拠)。公式内でも流儀が割れているためオプション化。
# awsdiagBadge はバリデータ向けマーカー(E1/E3 の対象から除外し W12 で集計)
BADGE_BASE = ("ellipse;html=1;fontSize=12;fontStyle=1;fontFamily=Arial;"
              "verticalAlign=middle;align=center;awsdiagBadge=1;")
BADGE_STYLES = {
    "dark": BADGE_BASE + "fillColor=#232F3E;strokeColor=#FFFFFF;fontColor=#FFFFFF;",
    "light": BADGE_BASE + "fillColor=#FFFFFF;strokeColor=#232F3E;fontColor=#000000;",
}

GRP = ("outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;"
       "fontFamily=Arial;"
       "fontStyle=0;container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
       "shape=mxgraph.aws4.group;")
PLAIN = ("verticalAlign=top;fontStyle=0;whiteSpace=wrap;html=1;container=1;"
         "fontFamily=Arial;pointerEvents=0;collapsible=0;recursiveResize=0;")
CONTAINER_STYLES = {
    "aws_cloud": GRP + "grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;",
    "region": GRP + "grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;",
    "vpc": GRP + "grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#AAB7B8;dashed=0;",
    "public_subnet": GRP + "grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;verticalAlign=top;align=left;spacingLeft=30;fontColor=#248814;dashed=0;",
    "private_subnet": GRP + "grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#00A4A6;fillColor=#E6F6F7;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=0;",
    "account": GRP + "grIcon=mxgraph.aws4.group_account;strokeColor=#CD2264;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#CD2264;dashed=0;",
    "ou": "fillColor=none;strokeColor=#CD2264;dashed=1;fontColor=#CD2264;" + PLAIN,
    "ec2_contents": GRP + "grIcon=mxgraph.aws4.group_ec2_instance_contents;strokeColor=#D86613;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#D86613;dashed=0;",
    "corporate_dc": GRP + "grIcon=mxgraph.aws4.group_corporate_data_center;strokeColor=#7D8998;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#5A6C86;dashed=0;",
    "auto_scaling": GRP.replace("group;", "groupCenter;") + "grIcon=mxgraph.aws4.group_auto_scaling_group;grStroke=1;strokeColor=#D86613;fillColor=none;verticalAlign=top;align=center;fontColor=#D86613;dashed=1;spacingTop=25;",
    "az": "fillColor=none;strokeColor=#147EBA;dashed=1;fontColor=#147EBA;" + PLAIN,
    "security_group": "fillColor=none;strokeColor=#DD3522;fontColor=#DD3522;" + PLAIN,
    "generic": "fillColor=none;strokeColor=#5A6C86;dashed=1;fontColor=#5A6C86;spacingLeft=10;" + PLAIN,
    # ---- Azure ----
    "mgmt_group": "fillColor=none;strokeColor=#5C2D91;dashed=1;fontColor=#5C2D91;" + PLAIN,
    "subscription": "fillColor=none;strokeColor=#0078D4;dashed=1;fontColor=#0078D4;" + PLAIN,
    "resource_group": "fillColor=none;strokeColor=#8A8886;dashed=1;fontColor=#605E5C;" + PLAIN,
    "vnet": "tdb=vpc;fillColor=none;strokeColor=#0078D4;fontColor=#0078D4;" + PLAIN,
    "az_subnet": "tdb=subnet;fillColor=#E8F2FB;strokeColor=#7FBAE3;fontColor=#1F6BB4;" + PLAIN,
    # ---- GCP ----
    "folder": "fillColor=none;strokeColor=#F9AB00;dashed=1;fontColor=#B57C00;" + PLAIN,
    "project": "fillColor=#F6F8FA;strokeColor=#DADCE0;fontColor=#5F6368;" + PLAIN,
    "gcp_vpc": "tdb=vpc;fillColor=none;strokeColor=#4285F4;fontColor=#4285F4;" + PLAIN,
    "gcp_subnet": "tdb=subnet;fillColor=#E8F0FE;strokeColor=#669DF6;fontColor=#1967D2;" + PLAIN,
    "gcp_zone": "fillColor=none;strokeColor=#BDC1C6;dashed=1;fontColor=#80868B;" + PLAIN,
    # フローチャートのスイムレーン(担当者・部署の帯)
    "lane": "fillColor=none;strokeColor=#5A6C86;fontColor=#5A6C86;fontStyle=1;" + PLAIN,
}

E_BASE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;arcSize=8;orthogonalLoop=1;"
          "jettySize=auto;html=1;fontSize=11;fontFamily=Arial;fontColor=#232F3E;"
          "labelBackgroundColor=#FFFFFF;endArrow=open;endFill=0;")
EDGE_STYLES = {
    "main": E_BASE + "strokeColor=#232F3E;strokeWidth=2;",
    "sub": E_BASE + "strokeColor=#7D8998;strokeWidth=1.5;dashed=1;dashPattern=4 4;",
    "ops": E_BASE + "strokeColor=#7D8998;strokeWidth=1.5;dashed=1;dashPattern=1 3;",
    # ER(クロウズフット)/ UML クラス図の関係線。後勝ちで E_BASE の矢印を上書き
    "er_11": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=ERone;startFill=0;startSize=12;endArrow=ERone;endFill=0;endSize=12;",
    "er_1n": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=ERone;startFill=0;startSize=12;endArrow=ERmany;endFill=0;endSize=14;",
    "er_0n": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=ERone;startFill=0;startSize=12;endArrow=ERzeroToMany;endFill=0;endSize=14;",
    # R7-5: 端別カーディナリティ。er_01n = 親側 0..1(○|。nullable FK)、
    # er_11n = 親側 厳密に 1(||。必須 FK)。どちらも子側はクロウズフット
    "er_01n": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=ERzeroToOne;startFill=0;startSize=14;endArrow=ERmany;endFill=0;endSize=14;",
    "er_11n": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=ERmandOne;startFill=0;startSize=12;endArrow=ERmany;endFill=0;endSize=14;",
    "er_nn": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=ERmany;startFill=0;startSize=14;endArrow=ERmany;endFill=0;endSize=14;",
    "uml_assoc": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;endArrow=open;endFill=0;endSize=10;",
    "uml_inherit": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;endArrow=block;endFill=0;endSize=16;",
    "uml_implement": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;dashed=1;dashPattern=4 4;endArrow=block;endFill=0;endSize=16;",
    "uml_compose": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=diamondThin;startFill=1;startSize=16;endArrow=none;",
    "uml_aggregate": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;startArrow=diamondThin;startFill=0;startSize=16;endArrow=none;",
    "uml_depend": E_BASE + "strokeColor=#232F3E;strokeWidth=1.2;dashed=1;dashPattern=4 4;endArrow=open;endFill=0;endSize=10;",
}

# R7-4: エッジ端ラベル(src_label/dst_label)。draw.io ネイティブの
# 「エッジの子ラベルセル」(mxGeometry x=±1 relative + offset)として出力する
END_LABEL_STYLE = ("edgeLabel;html=1;align=center;verticalAlign=middle;"
                   "resizable=0;points=[];fontSize=11;fontFamily=Arial;"
                   "fontColor=#232F3E;labelBackgroundColor=#FFFFFF;")


def dedupe_style(style: str) -> str:
    """style 文字列の重複キーを後勝ちで 1 つにする(見た目は不変)。

    E_BASE+kind の合成で endArrow 等が二重指定になり、人間や下流ツールが
    先頭の値を読んで誤解するのを防ぐ(draw.io 自体は後勝ちで解釈)。
    """
    out: dict[str, str | None] = {}
    for part in style.split(";"):
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            out[k] = v
        else:
            out[part] = None
    return ";".join(k if v is None else f"{k}={v}"
                    for k, v in out.items()) + ";"


def edge_style(e: dict, kinds: dict | None) -> str | None:
    """エッジのスタイルを解決する。kind は組み込み 3 種か spec の kinds 定義。

    kinds: {"名前": {"base": "main|sub|ops", "color": "#RRGGBB",
    "style_extra": "..."}}。意味カテゴリが 4 つ以上あるとき、エッジごとに
    style_extra を繰り返さず 1 箇所で定義するための仕組み。
    """
    if e.get("style"):
        return e["style"]
    k = e.get("kind", "main")
    if k in EDGE_STYLES:
        return EDGE_STYLES[k]
    d = (kinds or {}).get(k)
    if d is None:
        return None
    style = EDGE_STYLES.get(d.get("base", "sub"), EDGE_STYLES["sub"])
    if d.get("color"):
        style += f"strokeColor={d['color']};"
    return style + d.get("style_extra", "")


def kind_base(e: dict, kinds: dict | None) -> str:
    k = e.get("kind", "main")
    if k in EDGE_STYLES:
        return k
    return (kinds or {}).get(k, {}).get("base", "sub")


def resolve_badge_style(spec: dict) -> str:
    """spec の badge_style("dark"/"light"、省略時 dark)をスタイル文字列へ。

    グリッド経路は validate_spec が enum を先に検査する。ここでの die は
    abs スペック直書き(validate_spec を通らない)の backstop。
    """
    bs = spec.get("badge_style") or "dark"
    if bs not in BADGE_STYLES:
        die(f"badge_style '{bs}' は未知です"
            f"(候補: {' / '.join(sorted(BADGE_STYLES))})")
    return BADGE_STYLES[bs]

# ---- グリッド寸法 ----
# セル最小幅は 112(アイコン 78+余白)。ラベルが長い列は自動で広がる(適応型)。
# 行高はラベル行数に応じて適応(place() 内)。回廊内の平行レーン間隔は
# assign_lanes の LANE_STEP=14 を障害物余地で圧縮する機構が決める
# (GAP44 の実測で 4 レーン時 13.3px。過密は W1/E1 が backstop)
CELLW, CELLH = 112, 120       # セル(アイコン+ラベル領域)の最小(CELLH は上限側の目安)
GAPX, GAPY = 44, 44           # セル間の基本ギャップ(=配線回廊)
PAD, TOPB, BOTB = 20, 34, 14  # コンテナ枠 1 枚あたりの左右/上/下パディング
NEAR_FRAC = 0.15              # 自動端点(直行直線とその派生)が辺中心 0.5 から
                              # 離れてよい上限 frac(= 0.35〜0.65)。角近くの端点は
                              # 直線でも接続に見えない(FB3R: 接続感>直線>折れ点数)
TITLE_CLEAR = 8.0             # 直行直線とコンテナ題字帯の最小クリアランス
                              # (TOPB はバリデータ W2 の「ラベル下 34px」が下限)
MARGIN = 30
ICONBAND = 78                 # アイコン標準サイズ(中心線をこの帯で揃える)
CLEARANCE = 9                 # 配線とアイコン(ラベル込み)の最小間隔
LANE_STEP = 14.0              # 平行レーンの間隔(px)
LANE_MIN = 7.0                # レーン間隔の下限(バリデータ E7 の 6px 判定より上)。
                              # 圧縮でこれを割る回廊は「過負荷」としてギャップを広げる
FRAC_SLOTS = {1: [.5], 2: [.35, .65], 3: [.25, .5, .75], 4: [.2, .4, .6, .8]}

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, w, h


class SpecError(Exception):
    """スペック起因のエラー(メッセージはそのままユーザー向け)。"""


def die(msg: str) -> NoReturn:
    raise SpecError(msg)


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def esc_label(s: object) -> str:
    """ラベル用エスケープ。改行 \\n は <br> へ変換してから esc する
    (XML 属性の生改行は draw.io 上で空白化され、改行として描画されない)。"""
    return esc(str(s).replace("\n", "<br>"))


def g0(v: float) -> float:
    """XML 出力用に整数化(整数でなければ 0.1 単位に丸め)。"""
    return int(v) if float(v).is_integer() else round(float(v), 1)


def node_icon(icons: dict, node: dict) -> tuple[str, int, int]:
    """ノード定義からスタイル文字列と標準サイズを解決する。"""
    name = node.get("icon")
    if not name:
        die(f"node '{node.get('id')}' に icon がありません")
    try:
        row = resolve_icon(icons, name, node.get("kind"))
    except LookupError as exc:
        die(str(exc))
    return icon_style(row), int(row["w"]), int(row["h"])


ENTITY_STYLE = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                "fillColor=#FFFFFF;strokeColor=#232F3E;spacing=6;spacingTop=2;"
                "fontSize=12;fontFamily=Arial;")


FLOW_STYLES = {
    "process": "rounded=0;whiteSpace=wrap;html=1;fontFamily=Arial;fillColor=#FFFFFF;"
               "strokeColor=#232F3E;",
    "decision": "rhombus;whiteSpace=wrap;html=1;fontFamily=Arial;fillColor=#FFFFFF;"
                "strokeColor=#232F3E;",
    "terminator": "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fontFamily=Arial;"
                  "fillColor=#232F3E;fontColor=#FFFFFF;strokeColor=none;",
    "io": "shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1;"
          "whiteSpace=wrap;html=1;fontFamily=Arial;fillColor=#FFFFFF;strokeColor=#232F3E;",
    "document": "shape=document;whiteSpace=wrap;html=1;boundedLbl=1;fontFamily=Arial;"
                "fillColor=#FFFFFF;strokeColor=#232F3E;",
    "db": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;fontFamily=Arial;"
          "backgroundOutline=1;size=12;fillColor=#FFFFFF;strokeColor=#232F3E;",
    "subprocess": "shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;"
                  "fontFamily=Arial;fillColor=#FFFFFF;strokeColor=#232F3E;",
    "gateway": "shape=mxgraph.bpmn.gateway2;gwType=parallel;whiteSpace=wrap;html=1;"
               "fontFamily=Arial;fillColor=#FFFFFF;strokeColor=#232F3E;",
    "delay": "shape=delay;whiteSpace=wrap;html=1;fontFamily=Arial;"
             "fillColor=#FFFFFF;strokeColor=#232F3E;",
    "preparation": "shape=hexagon;perimeter=hexagonPerimeter2;fixedSize=1;"
                   "whiteSpace=wrap;html=1;fontFamily=Arial;fillColor=#FFFFFF;"
                   "strokeColor=#232F3E;",
    "junction": "ellipse;aspect=fixed;whiteSpace=wrap;html=1;fontFamily=Arial;"
                "fillColor=#FFFFFF;strokeColor=#232F3E;",
    "connector": "ellipse;aspect=fixed;whiteSpace=wrap;html=1;fontFamily=Arial;"
                 "fillColor=#FFFFFF;strokeColor=#232F3E;",
}


def is_entity(n: dict) -> bool:
    return n.get("shape") == "entity"


def is_flow(n: dict) -> bool:
    return n.get("shape") in FLOW_STYLES


def is_box(n: dict) -> bool:
    """ラベル内蔵の箱ノード(entity/フロー図形)。下辺も配線に使える。"""
    return is_entity(n) or is_flow(n)


def flow_geometry(n: dict) -> tuple[float, float]:
    """フロー図形の寸法をラベルから計算する。"""
    lines = str(n.get("label", "")).split("\n")
    tw = max((text_width(ln, 12) for ln in lines), default=0.0)
    th = 17.0 * max(len(lines), 1)
    shape = n["shape"]
    if shape == "gateway":
        return 64.0, 64.0
    if shape == "decision":   # ひし形は内接テキスト領域が狭い
        return max(140.0, tw * 1.7 + 30), max(70.0, th * 2.2)
    if shape == "terminator":
        return max(100.0, tw + 36), max(36.0, th + 16)
    if shape == "io":
        return max(140.0, tw + 44), max(44.0, th + 22)
    if shape == "db":
        return max(110.0, tw + 30), max(60.0, th + 34)
    if shape == "delay":
        return max(120.0, tw + 40), max(56.0, th + 24)
    if shape == "preparation":
        return max(140.0, tw + 52), max(56.0, th + 24)
    if shape == "junction":
        size = max(28.0, tw + 12, th + 10)
        return size, size
    if shape == "connector":
        size = max(42.0, tw + 18, th + 14)
        return size, size
    return max(120.0, tw + 28), max(44.0, th + 22)  # process/document/subprocess


def entity_geometry(n: dict) -> tuple[str, float, float]:
    """entity/クラス箱ノードの HTML ラベルと寸法 (label, w, h) を計算する。

    title が見出し、rows が属性(ER)/フィールド(UML)、rows2 がメソッド区画。
    stereotype(R7-6)はタイトル上に «...» 行を自動生成し、UML 慣例どおり
    abstract/interface はタイトルを、interface は操作(rows2)も斜体にする。
    """
    title = str(n.get("title", n.get("id")))
    st = n.get("stereotype")
    rows = n.get("rows") or []
    rows2 = list(n.get("rows2") or [])
    title_italic = st in ("abstract", "interface")
    thtml = f"<b>{title}</b>"
    if title_italic:
        thtml = f"<i>{thtml}</i>"
    body2 = [f"<i>{r}</i>" for r in rows2] if st == "interface" else rows2
    prefix = f"«{st}»<br>" if st else ""
    if title_italic:
        prefix = (f"<span style='font-weight:normal;font-style:normal'>"
                  f"«{st}»</span><br>")
    body = ""
    if rows or rows2:
        body += "<hr size='1'>" + "<br>".join(rows)
    if rows2:
        body += "<hr size='1'>" + "<br>".join(body2)
    if title_italic and body:
        body = ("<span style='font-weight:normal;font-style:normal'>"
                + body + "</span>")
    label = prefix + thtml + body
    texts = [title] + ([f"«{st}»"] if st else []) + list(rows) + rows2
    w = max(text_width(t, 12) for t in texts) + 26
    w = min(max(w, 140.0), 280.0)
    h = 30.0 + 17.0 * len(rows) + (12.0 + 17.0 * len(rows2) if rows2 else 0.0)
    if st:
        h += 15.0
    return label, w, max(h, 40.0)


JOG_MAX = 48.0
# リシェイプの直線候補で試す位置(スパン内の比率)。中央を最優先し、
# 中央が障害物・並走で塞がっている場合に外側へ広げて空きを探す
SWEEP_T = (0.5, 0.35, 0.65, 0.2, 0.8)


def straighten_polys(lay: Layout, items: list[tuple]) -> None:
    """階段状の小ジョグを潰して曲がりを減らす(配線後の美観処理)。

    items: (poly, src_box, src_slide可, dst_box, dst_slide可)。
    H-V-H / V-H-V の三連で中間セグメントが JOG_MAX px 以下なら、前後の
    線分を一直線に併合する。中間の三連は隣接線分を延ばして併合し、
    端点に接する三連は**端点を同じ辺の上でスライド**させて併合する
    (fan_out の端点分散が経路とずれてジョグになるため。ひし形は頂点固定
    なのでスライドしない)。併合後の線分がアイコン・ラベル・タイトル帯
    (lay.obstacles)に 4px 以内で触れる、他エッジと 8px 未満で重走する、
    または他エッジの端点 10px 以内に端点が寄る場合は見送る。
    9 要素目(任意)は流入辺規約の ban 集合 {(端子id, 辺)}(R7-15/A3)。
    辺を付け替えるリシェイプは ban された辺への付け替えを行わない
    (実測: 上辺入射に規約強制した f11 を L 字リシェイプが右辺へ
    付け替え、W15 が復活していた)。
    """
    polys = [it[0] for it in items]
    hb, vb = container_borders(lay)

    def blocked(a: Point, b: Point, self_poly: list[Point]) -> bool:
        (x1, y1), (x2, y2) = a, b
        lo_x, hi_x = min(x1, x2), max(x1, x2)
        lo_y, hi_y = min(y1, y2), max(y1, y2)
        for bx, by, bw, bh in list(lay.obstacles) + list(lay.title_bands):
            if (lo_x < bx + bw + 4 and bx - 4 < hi_x
                    and lo_y < by + bh + 4 and by - 4 < hi_y):
                return True
        horiz = abs(y1 - y2) < 1
        # コンテナ境界線との並走は二重線に見えるため見送る
        # (11px = HUG_DIST。バリデータ W13 の 10px/40px より厳しめに取る)
        if horiz:
            for by_, bx1_, bx2_ in hb:
                if abs(y1 - by_) < 11 and \
                        min(hi_x, bx2_) - max(lo_x, bx1_) > 40:
                    return True
        else:
            for bx_, by1_, by2_ in vb:
                if abs(x1 - bx_) < 11 and \
                        min(hi_y, by2_) - max(lo_y, by1_) > 40:
                    return True
        for other in polys:
            if other is self_poly:
                continue
            for c, d in zip(other, other[1:]):
                if horiz and abs(c[1] - d[1]) < 1 and abs(c[1] - y1) < 8 \
                        and min(c[0], d[0]) < hi_x - 8 and lo_x + 8 < max(c[0], d[0]):
                    return True
                if not horiz and abs(c[0] - d[0]) < 1 and abs(c[0] - x1) < 8 \
                        and min(c[1], d[1]) < hi_y - 8 and lo_y + 8 < max(c[1], d[1]):
                    return True
        return False

    def term_clear(pt: Point, self_poly: list[Point]) -> bool:
        for other in polys:
            if other is self_poly:
                continue
            for q in (other[0], other[-1]):
                if math.dist(pt, q) < 10:
                    return False
        return True

    def slide_ok(pt: Point, box: Rect, first_h: bool) -> bool:
        x, y, w, h = box
        if first_h:   # L/R 辺 → y をスライド
            return y + 0.12 * h <= pt[1] <= y + 0.88 * h
        return x + 0.12 * w <= pt[0] <= x + 0.88 * w

    all_obs = list(lay.obstacles) + list(lay.title_bands)

    # 2 パス: 1 パス目で他線がリシェイプされると、1 パス目では旧形状との
    # 並走・交差で弾かれた候補が 2 パス目で通るようになる(処理順の依存を緩和)
    for it in items + items:
        poly, sbox, s_slide, dbox, d_slide, ebounds = it[:6]
        # 7 要素目以降はリシェイプ用(単体テスト等の 6 要素はサイド変更なし)
        sid, did = it[6] if len(it) > 6 else (None, None)
        allowed = it[7] if len(it) > 7 else frozenset()
        bans = it[8] if len(it) > 8 else frozenset()

        def side_ok(term: str | None, side: str) -> bool:
            return term is None or (term, side) not in bans

        def in_bounds(a: Point, b: Point) -> bool:
            if ebounds is None:
                return True
            bx, by, bw2, bh2 = ebounds
            for px_, py_ in (a, b):
                if (px_ < bx - 30 or px_ > bx + bw2 + 30
                        or py_ < by - 30 or py_ > by + bh2 + 30):
                    return False
            return True

        # --- 最小形状へのリシェイプ(直線 → L 字)。コの字・多段 Z は中間
        # セグメントが JOG_MAX を超えるため下の三連併合では消えない(実QAで
        # 「一直線で引けるのにカクカク曲がる」と指摘された形)。障害物ヒット
        # 集合の非拡大・境界並走・他線との重走・交差数の非増加・出入り方向の
        # 整合をすべて満たすときだけ、折れ線ごと最小形へ置き換える ---
        def poly_hits(p: list[Point]) -> set:
            out: set[int] = set()
            for a_, b_ in zip(p, p[1:]):
                lo_x, hi_x = min(a_[0], b_[0]), max(a_[0], b_[0])
                lo_y, hi_y = min(a_[1], b_[1]), max(a_[1], b_[1])
                for idx, (bx, by, bw, bh) in enumerate(
                        list(lay.obstacles) + list(lay.title_bands)):
                    if (lo_x < bx + bw + 4 and bx - 4 < hi_x
                            and lo_y < by + bh + 4 and by - 4 < hi_y):
                        out.add(idx)
            return out

        def seg_clear(a_: Point, b_: Point) -> bool:
            """境界並走と他線との重走のみ(障害物はヒット集合側で判定)。"""
            (x1, y1), (x2, y2) = a_, b_
            lo_x, hi_x = min(x1, x2), max(x1, x2)
            lo_y, hi_y = min(y1, y2), max(y1, y2)
            horiz = abs(y1 - y2) < 1
            # 枠線並走はバリデータ W13(10px/40px)より厳しめの 11px で弾く
            if horiz:
                for by_, bx1_, bx2_ in hb:
                    if abs(y1 - by_) < 11 and \
                            min(hi_x, bx2_) - max(lo_x, bx1_) > 40:
                        return False
            else:
                for bx_, by1_, by2_ in vb:
                    if abs(x1 - bx_) < 11 and \
                            min(hi_y, by2_) - max(lo_y, by1_) > 40:
                        return False
            for other in polys:
                if other is poly:
                    continue
                for c_, d_ in zip(other, other[1:]):
                    if horiz and abs(c_[1] - d_[1]) < 1 and abs(c_[1] - y1) < 8 \
                            and min(c_[0], d_[0]) < hi_x - 8 \
                            and lo_x + 8 < max(c_[0], d_[0]):
                        return False
                    if not horiz and abs(c_[0] - d_[0]) < 1 and abs(c_[0] - x1) < 8 \
                            and min(c_[1], d_[1]) < hi_y - 8 \
                            and lo_y + 8 < max(c_[1], d_[1]):
                        return False
            return True

        def cross_count(p: list[Point]) -> int:
            n_ = 0
            for a_, b_ in zip(p, p[1:]):
                for other in polys:
                    if other is poly:
                        continue
                    for c_, d_ in zip(other, other[1:]):
                        if seg_cross(a_, b_, c_, d_):
                            n_ += 1
            return n_

        def pierces(a_: Point, b_: Point, box: Rect) -> bool:
            """線分が矩形の内部を横切るか(縁の上を走る・触れるだけは除く)。"""
            x, y, w, h = box
            lo_x, hi_x = min(a_[0], b_[0]), max(a_[0], b_[0])
            lo_y, hi_y = min(a_[1], b_[1]), max(a_[1], b_[1])
            return (lo_x < x + w - .5 and x + .5 < hi_x
                    and lo_y < y + h - .5 and y + .5 < hi_y)

        def rect_touch(a_: Rect, b_: Rect) -> bool:
            return (a_[0] < b_[0] + b_[2] + 1 and b_[0] - 1 < a_[0] + a_[2]
                    and a_[1] < b_[1] + b_[3] + 1 and b_[1] - 1 < a_[1] + a_[3])

        # 自ノードの障害物矩形(アイコン+ラベル)はスタブが必然的に跨ぐ
        # ため貫通チェックから除外する。他ノードは近接(ヒット集合)より
        # 強く「内部横断は旧形状が何であれ不可」とする(かすめ→貫通への
        # エスカレーションを防ぐ)
        chk_obs = [ob for ob in all_obs
                   if not (rect_touch(ob, sbox) or rect_touch(ob, dbox))]
        # src/dst の祖先でないコンテナの通過も不可(ルータと同じ規約)
        chk_cont = [lay.boxes[c] for c in lay.cmap
                    if c not in allowed and c in lay.boxes]

        def try_reshape(np_: list[Point]) -> bool:
            for a_, b_ in zip(np_, np_[1:]):
                if not in_bounds(a_, b_) or not seg_clear(a_, b_):
                    return False
                for ob in chk_obs:
                    if pierces(a_, b_, ob):
                        return False
                for cb in chk_cont:
                    if pierces(a_, b_, cb):
                        return False
            if not poly_hits(np_) <= poly_hits(poly):
                return False
            if cross_count(np_) > cross_count(poly):
                return False
            if math.dist(np_[0], poly[0]) > .5 and not term_clear(np_[0], poly):
                return False
            if math.dist(np_[-1], poly[-1]) > .5 and not term_clear(np_[-1], poly):
                return False
            poly[:] = [(g0(x_), g0(y_)) for x_, y_ in np_]
            return True

        if len(poly) >= 3:  # 曲がり 1 回以上が対象
            sp, ep = poly[0], poly[-1]
            first_h = abs(sp[1] - poly[1][1]) < 1
            last_h = abs(ep[1] - poly[-2][1]) < 1
            sdx = poly[1][0] - sp[0] if first_h else 0.0
            sdy = poly[1][1] - sp[1] if not first_h else 0.0
            edx = ep[0] - poly[-2][0] if last_h else 0.0
            edy = ep[1] - poly[-2][1] if not last_h else 0.0
            sx, sy, sw, sh = sbox
            dx_, dy_, dw, dh = dbox
            reshaped = False
            if first_h == last_h and len(poly) >= 4:
                # 直線候補(辺を保つ): 両端の辺上スライド範囲が重なる共通
                # 座標を探す。出発方向と全体方向が一致するときだけ
                # (逆向きは自箱を貫く)
                if first_h and sdx * (ep[0] - sp[0]) > 0:
                    lo = max(sy + .12 * sh, dy_ + .12 * dh)
                    hi = min(sy + .88 * sh, dy_ + .88 * dh)
                    for cy in (sp[1], ep[1],
                               *(lo + t * (hi - lo) for t in SWEEP_T)):
                        if not (lo <= cy <= hi):
                            continue
                        if (abs(cy - sp[1]) > .5 and not s_slide) or \
                           (abs(cy - ep[1]) > .5 and not d_slide):
                            continue
                        if try_reshape([(sp[0], cy), (ep[0], cy)]):
                            reshaped = True
                            break
                elif not first_h and sdy * (ep[1] - sp[1]) > 0:
                    lo = max(sx + .12 * sw, dx_ + .12 * dw)
                    hi = min(sx + .88 * sw, dx_ + .88 * dw)
                    for cx in (sp[0], ep[0],
                               *(lo + t * (hi - lo) for t in SWEEP_T)):
                        if not (lo <= cx <= hi):
                            continue
                        if (abs(cx - sp[0]) > .5 and not s_slide) or \
                           (abs(cx - ep[0]) > .5 and not d_slide):
                            continue
                        if try_reshape([(cx, sp[1]), (cx, ep[1])]):
                            reshaped = True
                            break
            # 下辺の扱い(AWS 公式一頁物の流儀):
            #  - 出発(下向き)はキャプションの真下から出す(exitDy 相当。
            #    公式 PDF の CloudFront→S3 等はこの形)
            #  - 進入(上向き)は entity 箱・コンテナのみ。アイコンには
            #    キャプションが載るため下辺から入らず左右辺を使う
            def bottom_exit_y(tid: str | None, box: Rect) -> float | None:
                if tid is None:
                    return None
                if tid in lay.cmap or tid in lay.box_nodes:
                    return box[1] + box[3]
                fb = lay.fullb.get(tid)
                return (fb[1] + fb[3] + 2) if fb else box[1] + box[3]

            def bottom_entry_ok(tid: str | None) -> bool:
                return tid is not None and (tid in lay.cmap
                                            or tid in lay.box_nodes)

            if not reshaped and s_slide and d_slide and sid is not None:
                # 直線候補(辺の付け替え): 箱同士が軸方向に離れ、直交スパン
                # (0.12–0.88)が重なるなら、向かい合う辺同士をまっすぐ結ぶ。
                # ルータが左右の辺を選んで回り込んだ「コの字」をここで潰す。
                # 下流の exit/entry・端点分離は端点座標から辺を再推定する
                lo = max(sx + .12 * sw, dx_ + .12 * dw)
                hi = min(sx + .88 * sw, dx_ + .88 * dw)
                if hi - lo > 1:
                    ya = yb = None
                    sbot = bottom_exit_y(sid, sbox)
                    if sbot is not None and sbot + 4 < dy_ - 8 \
                            and side_ok(sid, "B") and side_ok(did, "T"):
                        ya, yb = sbot, dy_             # src が上 → 下向き
                    elif dy_ + dh < sy - 8 and bottom_entry_ok(did) \
                            and side_ok(sid, "T") and side_ok(did, "B"):
                        ya, yb = sy, dy_ + dh          # src が下 → 上向き
                    if ya is not None:
                        for cx in (*(lo + t * (hi - lo) for t in SWEEP_T),
                                   sp[0], ep[0]):
                            if lo <= cx <= hi and \
                                    try_reshape([(cx, ya), (cx, yb)]):
                                reshaped = True
                                break
                if not reshaped:
                    lo = max(sy + .12 * sh, dy_ + .12 * dh)
                    hi = min(sy + .88 * sh, dy_ + .88 * dh)
                    if hi - lo > 1:
                        if sx + sw < dx_ - 8 and side_ok(sid, "R") \
                                and side_ok(did, "L"):
                            xa, xb = sx + sw, dx_      # src が左 → 右向き
                        elif dx_ + dw < sx - 8 and side_ok(sid, "L") \
                                and side_ok(did, "R"):
                            xa, xb = sx, dx_ + dw      # src が右 → 左向き
                        else:
                            xa = xb = None
                        if xa is not None:
                            for cy in (*(lo + t * (hi - lo)
                                         for t in SWEEP_T),
                                       sp[1], ep[1]):
                                if lo <= cy <= hi and \
                                        try_reshape([(xa, cy), (xb, cy)]):
                                    reshaped = True
                                    break
            if not reshaped and first_h != last_h and len(poly) >= 4:
                # L 字候補(辺を保つ): 出発・進入方向がともに元と同じ向き
                corner = (ep[0], sp[1]) if first_h else (sp[0], ep[1])
                dir_ok = ((corner[0] - sp[0]) * sdx > 0 if first_h
                          else (corner[1] - sp[1]) * sdy > 0)
                ent_ok = ((ep[1] - corner[1]) * edy >= 0 if first_h
                          else (ep[0] - corner[0]) * edx >= 0)
                if dir_ok and ent_ok:
                    reshaped = try_reshape([sp, corner, ep])
            if not reshaped and len(poly) >= 4 and d_slide and did is not None:
                # L 字候補(進入辺の付け替え): 出発は元の辺・向きのまま、
                # dst には正面の辺へ垂直に入る(H-V-H の 2 曲がりを 1 に)
                if first_h:
                    cx = dx_ + dw / 2
                    if sdx * (cx - sp[0]) > 0:
                        ey = dy_ if sp[1] < dy_ - 8 \
                            and side_ok(did, "T") else \
                            (dy_ + dh if sp[1] > dy_ + dh + 8
                             and bottom_entry_ok(did)
                             and side_ok(did, "B") else None)
                        if ey is not None:
                            reshaped = try_reshape(
                                [sp, (cx, sp[1]), (cx, ey)])
                else:
                    cy = dy_ + dh / 2
                    if sdy * (cy - sp[1]) > 0:
                        ex_ = dx_ if sp[0] < dx_ - 8 \
                            and side_ok(did, "L") else \
                            (dx_ + dw if sp[0] > dx_ + dw + 8
                             and side_ok(did, "R") else None)
                        if ex_ is not None:
                            reshaped = try_reshape(
                                [sp, (sp[0], cy), (ex_, cy)])
            if not reshaped and len(poly) >= 4 and s_slide and sid is not None:
                # L 字候補(出発辺の付け替え): 進入は元の辺・向きのまま、
                # src からは正面の辺から垂直に出る
                if last_h:
                    cx = sx + sw / 2
                    sbot = bottom_exit_y(sid, sbox)
                    if edx * (ep[0] - cx) > 0:
                        sy_ = sbot if sbot is not None \
                            and ep[1] > sbot + 8 \
                            and side_ok(sid, "B") else \
                            (sy if ep[1] < sy - 8
                             and side_ok(sid, "T") else None)
                        if sy_ is not None:
                            try_reshape([(cx, sy_), (cx, ep[1]), ep])
                else:
                    cy = sy + sh / 2
                    if edy * (ep[1] - cy) > 0:
                        sx_ = sx + sw if ep[0] > sx + sw + 8 \
                            and side_ok(sid, "R") else \
                            (sx if ep[0] < sx - 8
                             and side_ok(sid, "L") else None)
                        if sx_ is not None:
                            try_reshape([(sx_, cy), (ep[0], cy), ep])

        for _ in range(4):
            changed = False
            i = 0
            while i + 3 < len(poly):
                a, b, c, d = poly[i], poly[i + 1], poly[i + 2], poly[i + 3]
                ab_h = abs(a[1] - b[1]) < 1
                cd_h = abs(c[1] - d[1]) < 1
                if ab_h != cd_h or math.dist(b, c) > JOG_MAX:
                    i += 1
                    continue
                done = False
                if i == 0:        # 始端を辺上でスライドして c-d の線へ
                    na = (a[0], c[1]) if ab_h else (c[0], a[1])
                    if (s_slide and slide_ok(na, sbox, ab_h)
                            and term_clear(na, poly)
                            and in_bounds(na, d)
                            and not blocked(na, d, poly)):
                        poly[0] = na
                        del poly[1:3]
                        done = True
                else:             # 中間: a 側の直前セグメントを延ばす
                    na = (a[0], c[1]) if ab_h else (c[0], a[1])
                    if in_bounds(na, d) and not blocked(na, d, poly) \
                            and not blocked(poly[i - 1], na, poly):
                        poly[i] = na
                        del poly[i + 1:i + 3]
                        done = True
                if not done and i + 3 == len(poly) - 1:  # 終端スライド
                    nd = (d[0], b[1]) if ab_h else (b[0], d[1])
                    if (d_slide and slide_ok(nd, dbox, ab_h)
                            and term_clear(nd, poly)
                            and in_bounds(a, nd)
                            and not blocked(a, nd, poly)):
                        poly[-1] = nd
                        del poly[i + 1:i + 3]
                        done = True
                elif not done and i + 4 < len(poly):      # 中間: d 側を延ばす
                    nd = (d[0], b[1]) if ab_h else (b[0], d[1])
                    if in_bounds(a, nd) and not blocked(a, nd, poly) \
                            and not blocked(nd, poly[i + 4], poly):
                        poly[i + 1] = nd
                        del poly[i + 2:i + 4]
                        done = True
                if done:
                    changed = True
                else:
                    i += 1
            if not changed:
                break


def _slide_end(lay: Layout, poly: list[Point], at_end: bool,
               delta: float, box: Rect, side: str,
               all_polys: list[list[Point]],
               ebounds: Rect | None = None, exact: bool = False) -> bool:
    """端点を同じ辺に沿って delta ずらす(最終セグメントごと平行移動)。

    辺の 10%〜90% を出る場合、またはスライドで**新たに**障害物・題字帯へ
    触れる場合(元の位置で既に触れていた分は許容)は失敗して False。
    単独ポート(同じ辺に他エッジの端点が無い)の端点は、辺中心 ±NEAR_FRAC
    (frac 0.35〜0.65)の外へ出るスライドを帯端でクランプする(R4-4。
    ±12〜14px のずらしが 78px アイコンで frac ~0.68 の「接続して見えない」
    端点を作っていた穴)。クランプ後 8px 未満しか動けない・方向が反転する
    なら失敗。exact=True(題字帯回避)は部分適用が無意味なので、クランプが
    必要になった時点で失敗する。同一辺に複数付くポート群は対称ラダー
    (0.15〜0.85)が正当なので従来どおり 10%〜90% のみ。
    """
    pts = poly if not at_end else poly[::-1]
    if len(pts) < 2:
        return False
    p0, p1 = pts[0], pts[1]
    horiz_side = side in "LR"    # L/R 辺 → 端点は y 方向へ動く
    x, y, w, h = box

    def same_side(q: Point) -> bool:
        # p0 と同じ辺に載る端点か(dodge は side を軸指定にしか使わない
        # ため、辺そのものは p0 の座標から特定する)
        if horiz_side:
            return abs(q[0] - p0[0]) < 2 and y - 2 <= q[1] <= y + h + 2
        return abs(q[1] - p0[1]) < 2 and x - 2 <= q[0] <= x + w + 2

    single = not any(same_side(q) for other in all_polys if other is not poly
                     for q in (other[0], other[-1]))

    def banded(cur: float, lo_edge: float, length: float) -> float | None:
        nv = cur + delta
        if single:
            b_lo = lo_edge + (.5 - NEAR_FRAC) * length
            b_hi = lo_edge + (.5 + NEAR_FRAC) * length
            nc = min(b_hi, max(b_lo, nv))
            if nc != nv:
                if exact or (nc - cur) * delta <= 0 or abs(nc - cur) < 8.0:
                    return None
                nv = nc
        if not (lo_edge + 0.10 * length <= nv <= lo_edge + 0.90 * length):
            return None
        return nv

    if horiz_side:
        ny = banded(p0[1], y, h)
        if ny is None:
            return False
        np0, np1 = (p0[0], ny), (p1[0], ny)
    else:
        nx = banded(p0[0], x, w)
        if nx is None:
            return False
        np0, np1 = (nx, p0[1]), (nx, p1[1])

    def hits(a: Point, b: Point) -> frozenset:
        lo_x, hi_x = min(a[0], b[0]), max(a[0], b[0])
        lo_y, hi_y = min(a[1], b[1]), max(a[1], b[1])
        out = set()
        for idx, (bx, by, bw, bh) in enumerate(lay.obstacles):
            if (lo_x < bx + bw + 2 and bx - 2 < hi_x
                    and lo_y < by + bh + 2 and by - 2 < hi_y):
                out.add(idx)
        return frozenset(out)

    if not hits(np0, np1) <= hits(p0, p1):
        return False   # スライドで新たな障害物に触れる
    lo_x, hi_x = min(np0[0], np1[0]), max(np0[0], np1[0])
    lo_y, hi_y = min(np0[1], np1[1]), max(np0[1], np1[1])
    horiz = abs(np0[1] - np1[1]) < 1
    for other in all_polys:
        if other is poly:
            continue
        for c, d in zip(other, other[1:]):
            if horiz and abs(c[1] - d[1]) < 1 and abs(c[1] - np0[1]) < 8 \
                    and min(c[0], d[0]) < hi_x - 8 and lo_x + 8 < max(c[0], d[0]):
                return False   # 他線と重走してしまう
            if not horiz and abs(c[0] - d[0]) < 1 and abs(c[0] - np0[0]) < 8 \
                    and min(c[1], d[1]) < hi_y - 8 and lo_y + 8 < max(c[1], d[1]):
                return False
    for bx, by, bw, bh in lay.title_bands:
        if (lo_x < bx + bw + 2 and bx - 2 < hi_x
                and lo_y < by + bh + 2 and by - 2 < hi_y):
            return False   # 題字帯へ入るスライドは見送り
    for other in all_polys:
        if other is poly:
            continue
        for q in (other[0], other[-1]):
            if math.dist(np0, q) < 10 and math.dist(np0, q) < math.dist(p0, q):
                return False   # 他端点へ近づいて密着するスライドは見送り
    if ebounds is not None:
        ex_, ey_, ew_, eh_ = ebounds
        for px_, py_ in (np0, np1):
            if (px_ < ex_ - 30 or px_ > ex_ + ew_ + 30
                    or py_ < ey_ - 30 or py_ > ey_ + eh_ + 30):
                return False   # 共通祖先の外へ出るスライドは見送り
    if at_end:
        poly[-1], poly[-2] = np0, np1
    else:
        poly[0], poly[1] = np0, np1
    return True


def point_side(box: Rect, pt: Point, fallback: str) -> str:
    """端点座標から実際に載っている辺を推定する。

    straighten_polys のリシェイプは辺の付け替え(左右→上下)を行うため、
    ルート由来の辺文字は当てにならない。縁上になければ外側領域で分類する
    (exitDy 付きの「キャプション下」アンカーは箱の下の外側に落ちる)。
    """
    x, y, w, h = box
    d = {"L": abs(pt[0] - x), "R": abs(pt[0] - (x + w)),
         "T": abs(pt[1] - y), "B": abs(pt[1] - (y + h))}
    side = min(d, key=lambda k: d[k])
    if d[side] < 2:
        return side
    if x - 2 <= pt[0] <= x + w + 2:
        if pt[1] >= y + h:
            return "B"
        if pt[1] <= y:
            return "T"
    if y - 2 <= pt[1] <= y + h + 2:
        if pt[0] <= x:
            return "L"
        if pt[0] >= x + w:
            return "R"
    return fallback


def separate_terminals(lay: Layout, pending: list[tuple],
                       edge_bounds: dict | None = None) -> None:
    """端点まわりの視認性を最終保証する 2 つの後処理。

    (1) 同一ノード・同一辺に付く端点同士を 12px 以上離す(矢じりが重なる)。
    (2) 端点の矢じり延長線上 18px 以内を他エッジの同軸セグメントが走る場合、
        端点を 12px ずらして「1 本の連続線」に見える誤読を防ぐ。
    どちらもひし形(頂点固定)や辺の端に近い端点はずらさず、動かせない
    ときは現状維持(バリデータ W6 が検出する)。
    """
    recs = []   # (poly, at_end, node_id, side, box, coord)
    for _, e, r, poly in pending:
        if r is None:
            continue
        eb_ = (edge_bounds or {}).get(e["id"])
        for at_end, term, rside in ((False, e["src"], r.exit[0]),
                                    (True, e["dst"], r.entry[0])):
            pt = poly[-1] if at_end else poly[0]
            # リシェイプで辺が付け替わり得るため座標から辺を再推定する
            side = point_side(lay.boxes[term], pt, rside)
            coord = pt[1] if side in "LR" else pt[0]
            recs.append((poly, at_end, term, side, lay.boxes[term], coord, e,
                         eb_))
    all_polys = [poly for _, _, _, poly in pending]

    # (1) 同一辺の端点分離
    groups: dict[tuple, list] = {}
    for rec in recs:
        groups.setdefault((rec[2], rec[3]), []).append(rec)
    for (term, side), members in sorted(groups.items()):
        if len(members) < 2 or term in lay.diamond:
            continue   # ひし形は頂点固定(R7-16)— 辺上スライドで離さない
        members.sort(key=lambda rec: rec[5])
        for i in range(1, len(members)):
            prev = members[i - 1]
            cur = members[i]
            gapv = cur[5] - prev[5]
            if gapv >= 12:
                continue
            need = 13 - gapv
            if _slide_end(lay, cur[0], cur[1], need, cur[4], side,
                          all_polys, cur[7]):
                members[i] = (*cur[:5], cur[5] + need, *cur[6:])
            elif _slide_end(lay, prev[0], prev[1], -need, prev[4], side,
                            all_polys, prev[7]):
                members[i - 1] = (*prev[:5], prev[5] - need, *prev[6:])
            elif (_slide_end(lay, cur[0], cur[1], need / 2, cur[4], side,
                             all_polys, cur[7])
                  and _slide_end(lay, prev[0], prev[1], -need / 2, prev[4],
                                 side, all_polys, prev[7])):
                members[i] = (*cur[:5], cur[5] + need / 2, *cur[6:])
                members[i - 1] = (*prev[:5], prev[5] - need / 2, *prev[6:])

    # (2) 矢じり延長線上の他線融合
    for poly, at_end, term, side, box, coord, e, eb_ in recs:
        if term in lay.diamond:
            continue   # ひし形は頂点固定(R7-16)
        tip = poly[-1] if at_end else poly[0]
        nxt = poly[-2] if at_end else poly[1]
        horiz = abs(tip[1] - nxt[1]) < 1     # 最終セグメントは水平か
        for other in all_polys:
            if other is poly:
                continue
            fused = False
            for c, d in zip(other, other[1:]):
                o_h = abs(c[1] - d[1]) < 1
                if o_h != horiz:
                    continue
                if horiz and abs(c[1] - tip[1]) < 5:
                    near = min(abs(c[0] - tip[0]), abs(d[0] - tip[0]))
                    inside = min(c[0], d[0]) - 2 <= tip[0] <= max(c[0], d[0]) + 2
                    if near < 18 or inside:
                        fused = True
                if not horiz and abs(c[0] - tip[0]) < 5:
                    near = min(abs(c[1] - tip[1]), abs(d[1] - tip[1]))
                    inside = min(c[1], d[1]) - 2 <= tip[1] <= max(c[1], d[1]) + 2
                    if near < 18 or inside:
                        fused = True
                if fused:
                    break
            if fused:
                if not _slide_end(lay, poly, at_end, 12.0, box, side,
                                  all_polys, eb_):
                    _slide_end(lay, poly, at_end, -12.0, box, side,
                               all_polys, eb_)
                break


def dodge_title_bands(lay: Layout, pending: list[tuple],
                      edge_bounds: dict) -> None:
    """コンテナ題字帯を横切るセグメントを帯の外へ平行移動する。

    行レーンが入れ子コンテナの題字と同じ高さに来ると、ルータはペナルティを
    払ってでも帯上を走らざるを得ない(避け先の格子線が無い)。ここで
    ±十数 px の平行移動により文字の上から線を退かす。端に接する
    セグメントは _slide_end(端点スライド)で対応。移動先が障害物・他線・
    別の帯・共通祖先の外に当たる場合は見送る(W5 が残って検出される)。
    """
    polys = [poly for _, _, _, poly in pending]

    def seg_clear(a: Point, b: Point, self_poly) -> bool:
        lo_x, hi_x = min(a[0], b[0]), max(a[0], b[0])
        lo_y, hi_y = min(a[1], b[1]), max(a[1], b[1])
        for bx, by, bw, bh in list(lay.obstacles) + list(lay.title_bands):
            if (lo_x < bx + bw + 3 and bx - 3 < hi_x
                    and lo_y < by + bh + 3 and by - 3 < hi_y):
                return False
        horiz = abs(a[1] - b[1]) < 1
        for other in polys:
            if other is self_poly:
                continue
            for c, d in zip(other, other[1:]):
                if horiz and abs(c[1] - d[1]) < 1 and abs(c[1] - a[1]) < 8 \
                        and min(c[0], d[0]) < hi_x - 8 and lo_x + 8 < max(c[0], d[0]):
                    return False
                if not horiz and abs(c[0] - d[0]) < 1 and abs(c[0] - a[0]) < 8 \
                        and min(c[1], d[1]) < hi_y - 8 and lo_y + 8 < max(c[1], d[1]):
                    return False
        return True

    for _, e, r, poly in pending:
        if r is None:
            continue
        eb = edge_bounds.get(e["id"])
        for _round in range(2):
            moved = False
            for i in range(len(poly) - 1):
                a, b = poly[i], poly[i + 1]
                horiz = abs(a[1] - b[1]) < 1
                for bx, by, bw, bh in lay.title_bands:
                    lo_x, hi_x = min(a[0], b[0]), max(a[0], b[0])
                    lo_y, hi_y = min(a[1], b[1]), max(a[1], b[1])
                    if not (lo_x < bx + bw and bx < hi_x
                            and lo_y < by + bh and by < hi_y):
                        continue
                    if horiz:
                        deltas = sorted((by - 5 - a[1], by + bh + 5 - a[1]),
                                        key=abs)
                    else:
                        deltas = sorted((bx - 5 - a[0], bx + bw + 5 - a[0]),
                                        key=abs)
                    for dv in deltas:
                        if horiz:
                            na, nb = (a[0], a[1] + dv), (b[0], b[1] + dv)
                        else:
                            na, nb = (a[0] + dv, a[1]), (b[0] + dv, b[1])
                        if eb is not None:
                            ex_, ey_, ew_, eh_ = eb
                            if any(px < ex_ - 30 or px > ex_ + ew_ + 30
                                   or py < ey_ - 30 or py > ey_ + eh_ + 30
                                   for px, py in (na, nb)):
                                continue
                        if i == 0 and i + 1 == len(poly) - 1:
                            break   # 直行 1 セグメントは動かせない
                        if i == 0:   # 始端ごとスライド
                            if e["src"] in lay.diamond:
                                break   # ひし形は頂点固定(R7-16)
                            side = "LR" if horiz else "TB"
                            ok = _slide_end(lay, poly, False, dv,
                                            lay.boxes[e["src"]],
                                            "L" if horiz else "T",
                                            polys, eb, exact=True)
                            if ok:
                                moved = True
                            break
                        if i + 1 == len(poly) - 1:   # 終端ごとスライド
                            if e["dst"] in lay.diamond:
                                break   # ひし形は頂点固定(R7-16)
                            ok = _slide_end(lay, poly, True, dv,
                                            lay.boxes[e["dst"]],
                                            "L" if horiz else "T",
                                            polys, eb, exact=True)
                            if ok:
                                moved = True
                            break
                        if seg_clear(na, nb, poly):
                            poly[i], poly[i + 1] = na, nb
                            moved = True
                            break
                    break
            if not moved:
                break


def separate_corun_runs(lay: Layout, pending: list[tuple],
                        edge_bounds: dict) -> None:
    """最終折れ線同士の同軸並走(E7 予備軍)を中間セグメント移動で分離する。

    assign_lanes は「同じ格子座標を共有する中間 Run」の集合しか見ない —
    直行直線(単一 Run)はレーン割当の対象外で、崩壊レイアウトでは別の
    格子線が同座標近くに落ちて別グループになり、後処理(straighten /
    dodge)で動いた線も再割当されない。すり抜けた並走ペアを、手動配線
    規約と同じ LANE_STEP(14px)を目標に、動かせる側(中間セグメント)の
    平行移動で分離する(FB第3R 指摘1)。同一 src のペアは fork トランクの
    意図的な同走なので対象外。ガード: 障害物・題字帯 3px、共通祖先
    +30px、隣接セグメントの反転禁止、他線と新たな 7px 未満の並走を
    作らない。動かせなければ現状維持(バリデータ E7 が検出する)。
    """
    segs: list[list] = []   # [poly, i, axis, coord, lo, hi, movable, e]
    for _, e, r, poly in pending:
        for i in range(len(poly) - 1):
            a, b = poly[i], poly[i + 1]
            vert = abs(a[0] - b[0]) < 0.75
            horiz = abs(a[1] - b[1]) < 0.75
            if vert == horiz:
                continue     # 斜め or 長さ 0
            coord = a[0] if vert else a[1]
            lo, hi = sorted((a[1], b[1]) if vert else (a[0], b[0]))
            movable = r is not None and 0 < i < len(poly) - 2
            segs.append([poly, i, "v" if vert else "h", coord, lo, hi,
                         movable, e])

    def clear_at(sg: list, nc: float) -> bool:
        poly, i, ax, _c, lo, hi, _m, e = sg
        rect = ((nc - 3, lo, 6, hi - lo) if ax == "v"
                else (lo, nc - 3, hi - lo, 6))
        for ob in list(lay.obstacles) + list(lay.title_bands):
            if _rect_hits(rect, ob):
                return False
        eb = edge_bounds.get(e["id"])
        if eb is not None:
            ex_, ey_, ew_, eh_ = eb
            for px_, py_ in (((nc, lo), (nc, hi)) if ax == "v"
                             else ((lo, nc), (hi, nc))):
                if (px_ < ex_ - 30 or px_ > ex_ + ew_ + 30
                        or py_ < ey_ - 30 or py_ > ey_ + eh_ + 30):
                    return False
        # 隣接セグメントが反転(ジグザグ化)・消滅する移動は見送り
        for pt in (poly[i - 1], poly[i + 2]):
            pn = pt[0] if ax == "v" else pt[1]
            if (sg[3] - pn) * (nc - pn) <= 0 or abs(nc - pn) < 4:
                return False
        # 新たな並走(LANE_MIN 未満)を作らない
        for sg2 in segs:
            if sg2[0] is poly or sg2[2] != ax:
                continue
            if (abs(sg2[3] - nc) < LANE_MIN
                    and sg2[4] < hi - 8 and lo + 8 < sg2[5]):
                return False
        return True

    def apply(sg: list, nc: float) -> None:
        poly, i, ax = sg[0], sg[1], sg[2]
        if ax == "v":
            poly[i] = (nc, poly[i][1])
            poly[i + 1] = (nc, poly[i + 1][1])
        else:
            poly[i] = (poly[i][0], nc)
            poly[i + 1] = (poly[i + 1][0], nc)
        sg[3] = nc

    for si in range(len(segs)):
        for sj in range(si + 1, len(segs)):
            a, b = segs[si], segs[sj]
            if a[0] is b[0] or a[2] != b[2]:
                continue
            if a[7]["src"] == b[7]["src"]:
                continue     # fork トランクの意図的な同走
            if abs(a[3] - b[3]) >= LANE_MIN:
                continue
            if not (a[4] < b[5] - 12 and b[4] < a[5] - 12):
                continue     # 重なり 12px 以下は並走に見えない
            done = False
            for sg, other in ((a, b), (b, a)):
                if not sg[6]:
                    continue
                for nc in sorted((other[3] + LANE_STEP, other[3] - LANE_STEP),
                                 key=lambda c: abs(c - sg[3])):
                    if clear_at(sg, nc):
                        apply(sg, nc)
                        done = True
                        break
                if done:
                    break


def snap_diamond_ends(lay: Layout, pending: list[tuple]) -> None:
    """diamond 端点を頂点(辺中心)へ戻す最終安全網(R7-16)。

    端点調整系(fan スロット・deconflict・separate_terminals・dodge・
    straighten)は diamond の端点を動かさない規約だが、経路のどこかで
    取りこぼしても、出力の exit/entry frac が斜辺上の点にならないよう
    最終折れ線の段階で強制的にスナップする。最終セグメントごと平行移動
    するため直交性は保たれる。障害物・他線の検査はしない(ずれた端点を
    放置する方が「斜辺に刺さる線」で確実に悪いため。重なりが生じれば
    バリデータ W6/E7 が検出する)。
    """
    for _, e, r, poly in pending:
        if r is None or len(poly) < 2:
            continue
        for term, at_end in (("src", False), ("dst", True)):
            tid = e[term]
            if tid not in lay.diamond or tid not in lay.boxes:
                continue
            pt = poly[-1] if at_end else poly[0]
            nxt = poly[-2] if at_end else poly[1]
            x, y, w, h = lay.boxes[tid]
            cx, cy = x + w / 2, y + h / 2
            horiz = abs(pt[1] - nxt[1]) < abs(pt[0] - nxt[0])
            # 最終セグメントの向きで辺を判定: 水平 → L/R 辺(y を中心へ)、
            # 垂直 → T/B 辺(x を中心へ)
            axis = 1 if horiz else 0
            target = cy if horiz else cx
            if abs(pt[axis] - target) < 0.75:
                continue
            if len(poly) == 2:
                other = e["dst" if term == "src" else "src"]
                if other in lay.diamond and \
                        abs(pt[axis] - target) > 0.75:
                    # 直行線の両端がひし形: 中心が揃う場合のみ動かせる
                    ocx, ocy = lay.center(other)
                    if abs((ocy if horiz else ocx) - target) > 0.75:
                        continue
            i0, i1 = (-1, -2) if at_end else (0, 1)
            for i in (i0, i1):
                p = poly[i]
                poly[i] = (p[0], target) if horiz else (target, p[1])


def pick_label_at(lay: Layout, label: str, poly: list[Point],
                  all_polys: list[list[Point]] = (),
                  placed: list[tuple] = (),
                  borders: tuple[list, list] = ((), ())) -> list[float]:
    """エッジラベルの位置を選ぶ。

    ハード条件: ラベル箱がノード・題字帯(lay.obstacles)、他エッジの線分、
    既配置の他ラベル箱を欠かない。横線ではセグメント長 ≥ ラベル幅+16
    (自線が両側に見える)。ソフト条件: コンテナ境界線を白抜きしない。
    ソフトまで満たす候補 → ハードのみ → 従来の最長横線中点、の順に妥協。
    """
    lw, lh = text_size(str(label), 11)
    hb, vb = borders
    segs = [(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
    hsegs = sorted((sg for sg in segs if abs(sg[0][0] - sg[1][0]) >= 40),
                   key=lambda sg: -abs(sg[0][0] - sg[1][0]))
    vsegs = sorted((sg for sg in segs if abs(sg[0][1] - sg[1][1]) >= 40),
                   key=lambda sg: -abs(sg[0][1] - sg[1][1]))

    def box_at(x: float, y: float) -> tuple[float, float, float, float]:
        return (x - lw / 2, y - lh / 2, x + lw / 2, y + lh / 2)

    def hard_ok(x: float, y: float) -> bool:
        x1, y1, x2, y2 = box_at(x, y)
        if y1 < 2:
            # ページ上端より上は不可 — meta パネル挿入時に全体が下へシフト
            # するため、上端の外に浮かせたラベルは meta の帯に着地する
            return False
        # バリデータ E5 は他ノードへの食い込みを 1px も許さない。
        # 旧来の「3px までのかすり許容」は E5 との不一致窓だった
        for bx, by, bw, bh in list(lay.obstacles) + list(lay.title_bands):
            if x1 < bx + bw + 1 and bx - 1 < x2 \
                    and y1 < by + bh + 1 and by - 1 < y2:
                return False
        for pb in placed:   # 既配置ラベルと重ねない
            if x1 < pb[2] + 4 and pb[0] - 4 < x2 \
                    and y1 < pb[3] + 4 and pb[1] - 4 < y2:
                return False
        for other in all_polys:   # 他エッジの線を白抜きで消さない
            if other is poly:
                continue
            for c, d in zip(other, other[1:]):
                if abs(c[1] - d[1]) < 1:   # 水平線
                    if y1 + 3 < c[1] < y2 - 3 \
                            and min(c[0], d[0]) < x2 - 3 and x1 + 3 < max(c[0], d[0]):
                        return False
                else:                       # 垂直線
                    if x1 + 3 < c[0] < x2 - 3 \
                            and min(c[1], d[1]) < y2 - 3 and y1 + 3 < max(c[1], d[1]):
                        return False
        return True

    def soft_ok(x: float, y: float) -> bool:
        x1, y1, x2, y2 = box_at(x, y)
        for by_, bx1_, bx2_ in hb:
            if y1 < by_ < y2 and min(x2, bx2_) - max(x1, bx1_) > 6:
                return False
        for bx_, by1_, by2_ in vb:
            if x1 < bx_ < x2 and min(y2, by2_) - max(y1, by1_) > 6:
                return False
        return True

    def overlap_depth(x: float, y: float) -> float:
        """候補の違反量(アイコン食い込み面積+既配置ラベル+他線貫通+境界白抜き)。"""
        x1, y1, x2, y2 = box_at(x, y)
        pen = 0.0
        for bx, by, bw, bh in lay.obstacles:
            ox = min(x2, bx + bw) - max(x1, bx)
            oy = min(y2, by + bh) - max(y1, by)
            if ox > 0 and oy > 0:
                pen += ox * oy
        for pb in placed:   # 既配置のラベル・バッジ箱(勘定しないと、短い
            ox = min(x2, pb[2]) - max(x1, pb[0])   # エッジで違反 0 と誤判定し
            oy = min(y2, pb[3]) - max(y1, pb[1])   # バッジがラベル中心に落ちる)
            if ox > 0 and oy > 0:
                pen += ox * oy
        for other in all_polys:
            if other is poly:
                continue
            for c, d in zip(other, other[1:]):
                if abs(c[1] - d[1]) < 1:
                    if y1 + 2 < c[1] < y2 - 2 \
                            and min(c[0], d[0]) < x2 and x1 < max(c[0], d[0]):
                        pen += 400.0
                elif x1 + 2 < c[0] < x2 - 2 \
                        and min(c[1], d[1]) < y2 and y1 < max(c[1], d[1]):
                    pen += 400.0
        if not soft_ok(x, y):
            pen += 60.0
        return pen

    cands = [(sg, True) for sg in hsegs] + [(sg, False) for sg in vsegs]
    fallback: tuple[float, list[float]] | None = None
    for strict in (True, False):
        for (a, b), horiz in cands:
            if horiz and abs(a[0] - b[0]) < lw + 16:
                continue  # 自線を覆い切ると線が分断されて見える
            for t in (.5, .38, .62, .28, .72, .2, .8):
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                if hard_ok(x, y) and (not strict or soft_ok(x, y)):
                    return [g0(x), g0(y)]
                if not strict:
                    d = overlap_depth(x, y)
                    if fallback is None or d < fallback[0]:
                        fallback = (d, [g0(x), g0(y)])
    if fallback is not None:   # 適地なし: 違反最小の候補
        if fallback[0] >= 300.0 or fallback[0] > 0:   # 欠けを作るなら浮かせる
            fx, fy = fallback[1]
            for ox_, oy_ in ((0, -(lh / 2 + 9)), (0, lh / 2 + 9),
                             (-(lw / 2 + 9), 0), (lw / 2 + 9, 0),
                             (0, -(lh + 20)), (0, lh + 20),
                             (-(lw / 2 + 24), 0), (lw / 2 + 24, 0)):
                if hard_ok(fx + ox_, fy + oy_) and soft_ok(fx + ox_, fy + oy_):
                    return [g0(fx + ox_), g0(fy + oy_)]
            for ox_, oy_ in ((0, -(lh / 2 + 9)), (0, lh / 2 + 9),
                             (0, -(lh + 20)), (0, lh + 20)):
                if hard_ok(fx + ox_, fy + oy_):
                    return [g0(fx + ox_), g0(fy + oy_)]
            # 軸沿いの浮かせが全滅(ページ端の回廊束に囲まれた等)。
            # 違反位置を受け入れる前に近傍を粗く走査して合法地を探す
            for rad in (20.0, 40.0, 60.0):
                for ox_ in (-rad, 0.0, rad):
                    for oy_ in (-rad, 0.0, rad):
                        if (ox_ or oy_) and hard_ok(fx + ox_, fy + oy_) \
                                and soft_ok(fx + ox_, fy + oy_):
                            return [g0(fx + ox_), g0(fy + oy_)]
        return fallback[1]
    a, b = (hsegs[0] if hsegs
            else max(segs, key=lambda sg: math.dist(sg[0], sg[1])))
    return [g0((a[0] + b[0]) / 2), g0((a[1] + b[1]) / 2)]


def project_label(poly: list[Point], target: Point) -> tuple[float, Point]:
    """折れ線上へ target を射影し (x_param, offset) を返す。"""
    lens = [math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
    total = sum(lens)
    if total == 0:
        return 0.0, (0.0, 0.0)
    best = (1e18, 0.0, (0.0, 0.0))
    acc = 0.0
    for i, ln in enumerate(lens):
        (x1, y1), (x2, y2) = poly[i], poly[i + 1]
        if ln == 0:
            continue
        t = max(0.0, min(1.0, ((target[0] - x1) * (x2 - x1)
                               + (target[1] - y1) * (y2 - y1)) / ln ** 2))
        px, py = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
        d = math.dist((px, py), target)
        if d < best[0]:
            best = (d, acc + t * ln, (target[0] - px, target[1] - py))
        acc += ln
    return 2 * best[1] / total - 1, best[2]


def _end_label_offset(poly: list[Point], at_end: bool,
                      label: str) -> tuple[float, float]:
    """端ラベルの既定オフセット(端点からラベル中心まで。探索なしの素朴版)。

    grid 経路では pick_end_label_at が障害物回避込みで位置を決める。ここは
    abs スペック直書き・手動配線(pending に乗らない)のフォールバック:
    端点の隣接セグメント沿いに 18px 進み、線から垂直に浮かせる。
    """
    lw, lh = text_size(str(label), 11)
    pt = poly[-1] if at_end else poly[0]
    nxt = poly[-2] if at_end else poly[1]
    if abs(nxt[1] - pt[1]) <= abs(nxt[0] - pt[0]):   # 水平セグメント → 線の上
        sx = 1.0 if nxt[0] >= pt[0] else -1.0
        return sx * (18.0 + lw / 2), -(lh / 2 + 4.0)
    sy = 1.0 if nxt[1] >= pt[1] else -1.0            # 垂直セグメント → 線の右
    return lw / 2 + 5.0, sy * (18.0 + lh / 2)


def pick_end_label_at(lay: Layout, label: str, poly: list[Point], at_end: bool,
                      all_polys: list[list[Point]] = (),
                      placed: list[tuple] = (),
                      borders: tuple[list, list] = ((), ())) -> list[float]:
    """エッジ端ラベル(src_label/dst_label)の位置を選ぶ(R7-4)。

    端点の隣接セグメント沿いに端点から近い順で候補を走査する。線沿いの
    開始距離は 18px から(ER/UML の線端マーカー長 12〜16px を白背景で
    消さない)、ラベル箱は線から垂直に浮かせる。ハード条件はノード箱・
    題字帯・既配置ラベル・他線(pick_label_at と同じ余白)。ソフト条件は
    コンテナ境界線の白抜き。全滅時は違反面積が最小の候補へ妥協する。
    """
    lw, lh = text_size(str(label), 11)
    pt = poly[-1] if at_end else poly[0]
    nxt = poly[-2] if at_end else poly[1]
    horiz = abs(nxt[1] - pt[1]) <= abs(nxt[0] - pt[0])
    seg_len = abs(nxt[0] - pt[0]) if horiz else abs(nxt[1] - pt[1])
    ux = ((1.0 if nxt[0] >= pt[0] else -1.0), 0.0) if horiz \
        else (0.0, (1.0 if nxt[1] >= pt[1] else -1.0))
    half = lw / 2 if horiz else lh / 2      # 線沿い方向のラベル半幅
    perp = lh / 2 + 4.0 if horiz else lw / 2 + 5.0
    obs = list(lay.obstacles) + list(lay.title_bands)
    hb, vb = borders

    def cand_at(d: float, s: float, extra: float) -> Point:
        cx = pt[0] + ux[0] * (d + half)
        cy = pt[1] + ux[1] * (d + half)
        if horiz:
            return cx, cy + s * (perp + extra)
        return cx + s * (perp + extra), cy

    def hard_ok(x: float, y: float) -> bool:
        x1, y1, x2, y2 = x - lw / 2, y - lh / 2, x + lw / 2, y + lh / 2
        if y1 < 2:
            return False
        for bx, by, bw, bh in obs:
            if x1 < bx + bw + 1 and bx - 1 < x2 \
                    and y1 < by + bh + 1 and by - 1 < y2:
                return False
        for pb in placed:
            if x1 < pb[2] + 4 and pb[0] - 4 < x2 \
                    and y1 < pb[3] + 4 and pb[1] - 4 < y2:
                return False
        for other in all_polys:
            for c, d2 in zip(other, other[1:]):
                if abs(c[1] - d2[1]) < 1:      # 水平線
                    if y1 + 3 < c[1] < y2 - 3 \
                            and min(c[0], d2[0]) < x2 - 3 and x1 + 3 < max(c[0], d2[0]):
                        return False
                elif x1 + 3 < c[0] < x2 - 3 \
                        and min(c[1], d2[1]) < y2 - 3 and y1 + 3 < max(c[1], d2[1]):
                    return False
        return True

    def soft_ok(x: float, y: float) -> bool:
        x1, y1, x2, y2 = x - lw / 2, y - lh / 2, x + lw / 2, y + lh / 2
        for by_, bx1_, bx2_ in hb:
            if y1 < by_ < y2 and min(x2, bx2_) - max(x1, bx1_) > 6:
                return False
        for bx_, by1_, by2_ in vb:
            if x1 < bx_ < x2 and min(y2, by2_) - max(y1, by1_) > 6:
                return False
        return True

    def overlap_depth(x: float, y: float) -> float:
        x1, y1, x2, y2 = x - lw / 2, y - lh / 2, x + lw / 2, y + lh / 2
        pen = 0.0
        for bx, by, bw, bh in obs:
            ox = min(x2, bx + bw) - max(x1, bx)
            oy = min(y2, by + bh) - max(y1, by)
            if ox > 0 and oy > 0:
                pen += ox * oy
        for pb in placed:
            ox = min(x2, pb[2]) - max(x1, pb[0])
            oy = min(y2, pb[3]) - max(y1, pb[1])
            if ox > 0 and oy > 0:
                pen += ox * oy
        for other in all_polys:
            for c, d2 in zip(other, other[1:]):
                if abs(c[1] - d2[1]) < 1:
                    if y1 + 2 < c[1] < y2 - 2 \
                            and min(c[0], d2[0]) < x2 and x1 < max(c[0], d2[0]):
                        pen += 400.0
                elif x1 + 2 < c[0] < x2 - 2 \
                        and min(c[1], d2[1]) < y2 and y1 < max(c[1], d2[1]):
                    pen += 400.0
        if not soft_ok(x, y):
            pen += 60.0
        return pen

    sides = (-1.0, 1.0) if horiz else (1.0, -1.0)   # 横線=上優先 / 縦線=右優先
    fallback: tuple[float, list[float]] | None = None
    for strict in (True, False):
        for d in (18.0, 26.0, 36.0, 48.0, 10.0):
            # セグメントの曲がりを越えてまで遠ざけない。ただし超過候補も
            # 非 strict では減点付きで overlap_depth 評価に回す(R7 REV-4:
            # セグメント長超ラベルで衝突回避が全バイパスされ素朴配置に
            # 落ちていた — 障害物・他線・既配置ラベルを見ずに置く欠陥)
            over = d + 2 * half - max(seg_len + 20.0, 40.0)
            if over > 0.0 and strict:
                continue
            for s in sides:
                for extra in (0.0, 6.0, 14.0):
                    x, y = cand_at(d, s, extra)
                    if over <= 0.0 and hard_ok(x, y) \
                            and (not strict or soft_ok(x, y)):
                        return [g0(x), g0(y)]
                    if not strict:
                        dep = overlap_depth(x, y) + max(over, 0.0)
                        if fallback is None or dep < fallback[0]:
                            fallback = (dep, [g0(x), g0(y)])
    if fallback is not None:
        return fallback[1]
    x, y = cand_at(18.0, sides[0], 0.0)   # 極短セグメント: 素朴位置で最善努力
    return [g0(x), g0(y)]


# ====================================================================
# 回廊格子ルータ
# ====================================================================

DIRS = {"R": (1, 0), "L": (-1, 0), "D": (0, 1), "U": (0, -1)}
OPP = {"R": "L", "L": "R", "D": "U", "U": "D"}
AXIS = {"R": "h", "L": "h", "D": "v", "U": "v"}


@dataclass
class Run:
    """折れ線を構成する 1 直線区間。axis="h" なら coord は y、"v" なら x。"""
    axis: str
    coord: float


@dataclass
class NodeRoute:
    """ノード間エッジの配線結果(fan-out 前は端点 frac 0.5)。"""
    exit: tuple[str, float]      # (辺 L/R/T/B, frac)
    entry: tuple[str, float]
    runs: list[Run]
    direct: bool                 # 単一直線(fan-out で 0.5 固定)


class Router:
    """回廊格子上の Dijkstra で直交ルートを探索する。

    格子線 = 回廊(セル境界の隙間の中心)とセル中心線。占有セルのアイコン
    (ラベル込み+クリアランス)と交わる格子区間は通行不可。コストは
    距離 + 曲がり + 既存ルートとの区間共有 + 既存ルートの横断。
    """

    BEND = 55.0        # 曲がり 1 回
    SHARE = 70.0       # 既存ルートと同一区間を共有(1 本につき)
    CROSS = 400.0      # 既存ルートを横断(1 本につき)
    # 出入り辺の方向不一致(_dir_penalty が余弦で傾斜させる)。
    # MISALIGN = 垂直(余弦 0)の基準値、ANTI_ALIGN = 真後ろ(余弦 -1)の
    # 上限値。旧実装は「向いていない辺は一律 25」の二値で、行き先と逆の
    # 辺から出て回り込む線も 25 で済んだ(実使用FB第4R 指摘A)。
    # ANTI_ALIGN は 120 で dense/multiregion テンプレの交差が +1 ずつ
    # 退行する実測があり、非退行の上限として 80 に置く(強く嫌うが、
    # 行き先側が障害物・題字帯で全滅した図の逃げ道は残る)
    MISALIGN = 25.0
    ANTI_ALIGN = 80.0
    # 迂回修復パス(route_all 末尾)が一時的に上書きする緩和コスト。
    # 通常探索は交差回避を距離より優先するが、修復時は距離を主役に戻す
    RELAX_SHARE = 35.0
    RELAX_CROSS = 120.0

    def __init__(self, xs: list[float], ys: list[float], obstacles: list[Rect],
                 clearance: float = CLEARANCE, borders: list[Rect] = (),
                 title_bands: list[Rect] = ()):
        self.xs, self.ys = xs, ys
        self.blocked: set[tuple] = set()          # ("h", i, j) / ("v", i, j)
        self._block_segments(obstacles, clearance)
        self.hug: set[tuple] = set()              # 境界線に並走する区間
        self._hug_segments(borders)
        self.titlepen: set[tuple] = set()         # コンテナ題字帯を通る区間
        self._title_segments(title_bands)
        self.share: dict[tuple, int] = {}         # 区間 → 使用数
        self.passes: dict[tuple, int] = {}        # (axis, i, j) → 直進通過数
        self._tick = 0

    def _block_segments(self, obstacles: list[Rect], clearance: float) -> None:
        boxes = [(x - clearance, y - clearance, x + w + clearance, y + h + clearance)
                 for x, y, w, h in obstacles]
        for j, y in enumerate(self.ys):
            for i in range(len(self.xs) - 1):
                x1, x2 = self.xs[i], self.xs[i + 1]
                if any(b[1] < y < b[3] and b[0] < x2 and x1 < b[2] for b in boxes):
                    self.blocked.add(("h", i, j))
        for i, x in enumerate(self.xs):
            for j in range(len(self.ys) - 1):
                y1, y2 = self.ys[j], self.ys[j + 1]
                if any(b[0] < x < b[2] and b[1] < y2 and y1 < b[3] for b in boxes):
                    self.blocked.add(("v", i, j))

    def _hug_segments(self, borders: list[Rect]) -> None:
        """コンテナ境界線から HUG_DIST px 以内を並走する格子区間を前計算する。

        境界とほぼ同座標を長距離走る線は「二重境界」に見える(実利用 QA で
        6 件)。横切るのは正常なので、並走区間だけを HUG ペナルティで嫌う。
        """
        HUG_DIST = 11.0  # 7 だと BOTB/2=7px のガター線が丁度すり抜ける(実QA指摘)
        BLOCK_DIST = 10.0 - 1e-6  # W13(10px 未満)確定の距離は通行禁止。
        # 正規ガター(PAD/2 = ちょうど 10.0px)は生存する厳密未満判定
        hb = []  # (y, x1, x2)
        vb = []  # (x, y1, y2)
        for x, y, w, h in borders:
            hb += [(y, x, x + w), (y + h, x, x + w)]
            vb += [(x, y, y + h), (x + w, y, y + h)]
        for j, y in enumerate(self.ys):
            near = [(abs(y - by), x1, x2) for by, x1, x2 in hb
                    if abs(y - by) < HUG_DIST]
            if not near:
                continue
            for i in range(len(self.xs) - 1):
                x1, x2 = self.xs[i], self.xs[i + 1]
                for d, b1, b2 in near:
                    if x1 < b2 - 10 and b1 + 10 < x2:
                        (self.blocked if d < BLOCK_DIST
                         else self.hug).add(("h", i, j))
        for i, x in enumerate(self.xs):
            near = [(abs(x - bx), y1, y2) for bx, y1, y2 in vb
                    if abs(x - bx) < HUG_DIST]
            if not near:
                continue
            for j in range(len(self.ys) - 1):
                y1, y2 = self.ys[j], self.ys[j + 1]
                for d, b1, b2 in near:
                    if y1 < b2 - 10 and b1 + 10 < y2:
                        (self.blocked if d < BLOCK_DIST
                         else self.hug).add(("v", i, j))

    def _title_segments(self, bands: list[Rect]) -> None:
        """コンテナ題字帯を通る格子区間を前計算する(TITLE ペナルティ)。"""
        for x, y, w, h in bands:
            for j, yy in enumerate(self.ys):
                if not (y - 2 < yy < y + h + 2):
                    continue
                for i in range(len(self.xs) - 1):
                    if self.xs[i] < x + w and x < self.xs[i + 1]:
                        self.titlepen.add(("h", i, j))
            for i, xx in enumerate(self.xs):
                if not (x - 2 < xx < x + w + 2):
                    continue
                for j in range(len(self.ys) - 1):
                    if self.ys[j] < y + h and y < self.ys[j + 1]:
                        self.titlepen.add(("v", i, j))

    def reset(self) -> None:
        self.share.clear()
        self.passes.clear()

    # -- コスト補助 --

    def _seg(self, p: tuple[int, int], d: str) -> tuple:
        dx, dy = DIRS[d]
        i, j = p
        if AXIS[d] == "h":
            return ("h", min(i, i + dx), j)
        return ("v", i, min(j, j + dy))

    def _seg_len(self, p: tuple[int, int], d: str) -> float:
        dx, dy = DIRS[d]
        if AXIS[d] == "h":
            return abs(self.xs[p[0] + dx] - self.xs[p[0]])
        return abs(self.ys[p[1] + dy] - self.ys[p[1]])

    def register_poly(self, poly: list[Point], weight: int = 1) -> list[tuple]:
        """格子外で決まった折れ線を通過情報として登録し、取り消し用レコードを返す。

        コンテナ端点・手動配線のエッジ、および狙い撃ち再配線時の
        「避けたい相手ルート」の重み付けに使う。
        """
        rec: list[tuple] = []

        def mark(key: tuple) -> None:
            self.passes[key] = self.passes.get(key, 0) + weight
            rec.append((key, weight))

        for k in range(len(poly) - 1):
            (x1, y1), (x2, y2) = poly[k], poly[k + 1]
            if abs(y1 - y2) <= 1:      # 水平区間
                lo, hi = min(x1, x2), max(x1, x2)
                for i, x in enumerate(self.xs):
                    if lo + 1 < x < hi - 1:
                        for j, y in enumerate(self.ys):
                            if abs(y - y1) < 8:
                                mark(("h", i, j))
            elif abs(x1 - x2) <= 1:    # 垂直区間
                lo, hi = min(y1, y2), max(y1, y2)
                for j, y in enumerate(self.ys):
                    if lo + 1 < y < hi - 1:
                        for i, x in enumerate(self.xs):
                            if abs(x - x1) < 8:
                                mark(("v", i, j))
        return rec

    def unregister(self, rec: list[tuple]) -> None:
        for key, weight in rec:
            self.passes[key] -= weight
            if self.passes[key] <= 0:
                del self.passes[key]

    # -- 探索 --

    OUTSIDE = 6.0
    HUG = 0.80       # 境界並走 1px あたり。0.2 では 390px の並走(78)が曲がり
                     # 2 回の迂回(110)に勝ってしまい枠に貼り付く(実QA指摘)
    TITLE = 8.0      # コンテナ題字帯 1px あたり(文字の上を線が走るのを強く嫌う)   # 共通祖先コンテナ外を通る 1px あたりの追加コスト

    def search(self, seeds: list[tuple[tuple[int, int], str, float]],
               targets: dict[tuple[int, int], list],
               bounds: Rect | None = None,
               avoid: list[Rect] = (),
               hard_bounds: bool = False,
               strict_bounds: bool = False
               ) -> tuple[tuple | None, dict]:
        """A* で最良ターゲットへの経路を探す。

        seeds: (格子点, 方向, 初期コスト)。
        targets: 格子点 → [(辺, frac, 進入方向, 進入コスト), ...]。
        ヒューリスティックは最寄りターゲットへの L1 距離(距離コストの下界で
        consistent)。ターゲット確定後、f が最良合計以上になったら打ち切る。
        bounds を渡すと、その矩形の外を通る区間に OUTSIDE ペナルティが乗る
        (AWS Cloud 内で完結する通信が境界外=インターネット側を通って見える
        ことを防ぐ)。返り値: ((状態, 辺, frac) | None, parent)。
        """
        if bounds is not None:
            # strict: トップレベル境界(網の境界)はリングなし。
            # hard: 入れ子コンテナはすぐ外の回廊(リング)まで正常な経路
            ring = 0.0 if strict_bounds else (30.0 if hard_bounds else 4.0)
            bx1, by1 = bounds[0] - ring, bounds[1] - ring
            bx2 = bounds[0] + bounds[2] + ring
            by2 = bounds[1] + bounds[3] + ring
        avoid_rects = [(a[0] + 2, a[1] + 2, a[0] + a[2] - 2, a[1] + a[3] - 2)
                       for a in avoid]
        xs, ys = self.xs, self.ys
        tpts = [(xs[i], ys[j]) for i, j in targets]
        hcache: dict[tuple[int, int], float] = {}

        def h(pt):
            if _NO_ASTAR:
                return 0.0
            v = hcache.get(pt)
            if v is None:
                x, y = xs[pt[0]], ys[pt[1]]
                v = min(abs(x - tx) + abs(y - ty) for tx, ty in tpts)
                hcache[pt] = v
            return v

        dist: dict[tuple, float] = {}
        parent: dict[tuple, tuple | None] = {}
        pq: list[tuple] = []
        best_total = math.inf
        best: tuple | None = None
        for pt, d, cost in seeds:
            state = (pt, d)
            if cost < dist.get(state, math.inf):
                dist[state] = cost
                parent[state] = None
                self._tick += 1
                # 同コストならターゲットに近い状態を先に(直進的な経路を好む)
                heapq.heappush(pq, (cost + h(pt), h(pt), self._tick, state))
        W, H = len(xs), len(ys)
        share = self.share
        passes = self.passes
        blocked = self.blocked
        while pq:
            f, _, _, state = heapq.heappop(pq)
            if f >= best_total:
                break
            pt, d = state
            g = dist[state]
            if f - 1e-6 > g + h(pt):
                continue  # 古いエントリ
            evals = targets.get(pt)
            if evals:
                for side, frac, need_d, tcost in evals:
                    tot = g + tcost + (self.BEND if d != need_d else 0.0)
                    if tot < best_total:
                        best_total = tot
                        best = (state, side, frac)
            i, j = pt
            for nd, (dx, dy) in DIRS.items():
                if nd == OPP[d]:
                    continue
                ni, nj = i + dx, j + dy
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                seg = self._seg(pt, nd)
                if seg in blocked:
                    continue
                perp = "v" if AXIS[nd] == "h" else "h"
                slen = self._seg_len(pt, nd)
                c2 = (g + slen
                      + (self.BEND if nd != d else 0.0)
                      + (self.HUG * slen if seg in self.hug else 0.0)
                      + (self.TITLE * slen if seg in self.titlepen else 0.0)
                      + self.SHARE * share.get(seg, 0)
                      + self.CROSS * passes.get((perp, ni, nj), 0))
                if bounds is not None or avoid_rects:
                    mx = (xs[i] + xs[ni]) / 2
                    my = (ys[j] + ys[nj]) / 2
                    if bounds is not None and (mx < bx1 or mx > bx2
                                               or my < by1 or my > by2):
                        if hard_bounds:
                            continue
                        c2 += slen * self.OUTSIDE
                    for a1, a2_, a3, a4 in avoid_rects:
                        if a1 < mx < a3 and a2_ < my < a4:
                            c2 += slen * self.OUTSIDE
                            break
                nstate = ((ni, nj), nd)
                if c2 < dist.get(nstate, math.inf) - 1e-9:
                    dist[nstate] = c2
                    parent[nstate] = state
                    self._tick += 1
                    hn = h((ni, nj))
                    heapq.heappush(pq, (c2 + hn, hn, self._tick, nstate))
        return best, parent

    # -- 経路の確定・取り消し --

    def commit(self, path: list[tuple[int, int]],
               stub_marks: list[tuple[str, tuple[int, int]]]) -> list[tuple]:
        """経路を登録し、取り消し用のレコードを返す。"""
        rec: list[tuple] = []
        for k in range(len(path) - 1):
            d = self._dir_between(path[k], path[k + 1])
            seg = self._seg(path[k], d)
            self.share[seg] = self.share.get(seg, 0) + 1
            rec.append(("share", seg))
        for k in range(1, len(path) - 1):
            din = self._dir_between(path[k - 1], path[k])
            dout = self._dir_between(path[k], path[k + 1])
            axes = {AXIS[din], AXIS[dout]}
            for ax in axes:
                key = (ax, path[k][0], path[k][1])
                self.passes[key] = self.passes.get(key, 0) + 1
                rec.append(("pass", key))
        for ax, pt in stub_marks:
            key = (ax, pt[0], pt[1])
            self.passes[key] = self.passes.get(key, 0) + 1
            rec.append(("pass", key))
        return rec

    def uncommit(self, rec: list[tuple]) -> None:
        for kind, key in rec:
            book = self.share if kind == "share" else self.passes
            book[key] -= 1
            if book[key] <= 0:
                del book[key]

    def recommit(self, rec: list[tuple]) -> list[tuple]:
        """uncommit したレコードをそのまま再適用する(狙い撃ち再配線の巻き戻し用)。"""
        for kind, key in rec:
            book = self.share if kind == "share" else self.passes
            book[key] = book.get(key, 0) + 1
        return rec

    def contested(self, path: list[tuple[int, int]], rec: list[tuple]) -> bool:
        """コミット済み経路が他ルートと競合(共有・交差)しているか。

        未競合ならリップアップ再配線しても結果は変わらないので省略できる。
        """
        own: dict[tuple, int] = {}
        for kind, key in rec:
            if kind == "pass":
                own[key] = own.get(key, 0) + 1
            elif self.share.get(key, 0) > 1:
                return True
        for pt in path:
            for ax in ("h", "v"):
                key = (ax, pt[0], pt[1])
                if self.passes.get(key, 0) > own.get(key, 0):
                    return True
        return False

    @staticmethod
    def _dir_between(a: tuple[int, int], b: tuple[int, int]) -> str:
        if b[0] != a[0]:
            return "R" if b[0] > a[0] else "L"
        return "D" if b[1] > a[1] else "U"


# ====================================================================
# グリッドレイアウトエンジン
# ====================================================================

@dataclass
class Layout:
    """セル割り当てから計算した絶対座標のコンテキスト。"""
    C: int
    R: int
    xs: list[float] = field(default_factory=list)   # 格子線 x(偶数=回廊, 奇数=セル中心)
    ys: list[float] = field(default_factory=list)
    boxes: dict[str, Rect] = field(default_factory=dict)
    cell: dict[str, tuple[int, int]] = field(default_factory=dict)
    cmap: dict[str, dict] = field(default_factory=dict)
    cext: dict[str, tuple] = field(default_factory=dict)  # コンテナのセル範囲
    occ: dict[tuple[int, int], str] = field(default_factory=dict)  # セル → ノード id
    parents: dict[str, str | None] = field(default_factory=dict)  # id → 親コンテナ
    box_nodes: set[str] = field(default_factory=set)  # entity 箱(下辺も配線可)
    # 手動 pin エッジの端点台帳 (ノードid, 辺) → frac 群。自動スロット割当が
    # pin 済みポートに他エッジを重ねないための情報 (外部FB A-3)
    pinned_ports: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    diamond: set[str] = field(default_factory=set)   # decision/gateway(端点は頂点固定)
    flow_boxes: set[str] = field(default_factory=set)  # diamond 以外のフロー図形(R7-A3)
    # 流入辺の方向規約(R7-15 ひし形頂点 + R7-A3 フロー箱の上辺入射)を
    # route_edge に伝える ban 集合。eid → {(端子id, 辺), ...}。
    # route_all が entry_conventions() で構築する
    diamond_bans: dict[str, frozenset] = field(default_factory=dict)
    title_bands: list[Rect] = field(default_factory=list)  # コンテナ題字帯
    xi_corr: list[int] = field(default_factory=list)  # 回廊 b → xs 添字
    xi_band: list[int] = field(default_factory=list)  # セル中心 c → xs 添字
    yi_corr: list[int] = field(default_factory=list)
    yi_band: list[int] = field(default_factory=list)
    obstacles: list[Rect] = field(default_factory=list)  # アイコン+ラベルの矩形
    fullb: dict[str, Rect] = field(default_factory=dict)  # id → アイコン+ラベル全体箱
    equalized: bool = False   # R4-6 の寸法等化を 1 グループ以上適用したか

    def center(self, tid: str) -> Point:
        x, y, w, h = self.boxes[tid]
        return x + w / 2, y + h / 2

    def side_point(self, tid: str, side: str, f: float) -> Point:
        x, y, w, h = self.boxes[tid]
        return {"L": (x, y + f * h), "R": (x + w, y + f * h),
                "T": (x + f * w, y), "B": (x + f * w, y + h)}[side]


def to_frac(side: str, f: float) -> list[float]:
    return {"L": [0, f], "R": [1, f], "T": [f, 0], "B": [f, 1]}[side]


def free_cell_suggestions(target: tuple[int, int], occ: dict, exts: list[tuple],
                          bounds: tuple[int, int], limit: int = 3) -> list[tuple]:
    """target 近傍の空きセル(どのコンテナ範囲にも入らない)を近い順に返す。"""
    C, R = bounds
    cands = []
    for c in range(0, C + 2):
        for r in range(0, R + 2):
            if (c, r) in occ:
                continue
            if any(e[0] <= c <= e[2] and e[1] <= r <= e[3] for e in exts):
                continue
            cands.append((abs(c - target[0]) + abs(r - target[1]), c, r))
    cands.sort()
    return [(c, r) for _, c, r in cands[:limit]]


def assign_cells(nodes: list[dict]) -> tuple[dict, dict]:
    """ノードにセルを割り当てる。重複はエラー。"""
    cell: dict[str, tuple[int, int]] = {}
    occ: dict[tuple[int, int], str] = {}
    for n in nodes:
        if "col" not in n or "row" not in n:
            die(f"node '{n.get('id')}' に col/row がありません")
        key = (int(n["col"]), int(n["row"]))
        if key in occ:
            C = max(c for c, _ in occ) + 1
            R = max(r for _, r in occ) + 1
            sug = free_cell_suggestions(key, occ, [], (C, R))
            die(f"セル {key} が重複しています: '{occ[key]}' と '{n['id']}'。"
                f"空きセル候補: {sug}")
        cell[n["id"]] = key
        occ[key] = n["id"]
    return cell, occ


def container_extents(conts: list[dict], nodes: list[dict], cell: dict,
                      occ: dict) -> tuple[dict, dict]:
    """コンテナのセル範囲を子ノードから求め、矩形の整合性を検証する。"""
    cmap = {c["id"]: c for c in conts}

    def chain(pid):
        seen = []
        while pid and pid != "1":
            if pid not in cmap:
                die(f"parent '{pid}' が containers にありません(親→子の順で定義)")
            seen.append(pid)
            pid = cmap[pid].get("parent")
        return seen

    parents = {n["id"]: set(chain(n.get("parent"))) for n in nodes}
    ext: dict[str, tuple] = {}
    for c in conts:
        ids = [n["id"] for n in nodes if c["id"] in parents[n["id"]]]
        if not ids:
            die(f"container '{c['id']}' に子ノードがいません")
        cs = [cell[i][0] for i in ids]
        rs = [cell[i][1] for i in ids]
        ext[c["id"]] = (min(cs), min(rs), max(cs), max(rs))

    canc = {c["id"]: set(chain(c.get("parent"))) for c in conts}
    for i in range(len(conts)):
        for j in range(i + 1, len(conts)):
            a, b = conts[i]["id"], conts[j]["id"]
            if a in canc[b] or b in canc[a]:
                continue
            ea, eb = ext[a], ext[b]
            if ea[0] <= eb[2] and eb[0] <= ea[2] and ea[1] <= eb[3] and eb[1] <= ea[3]:
                die(f"コンテナ '{a}'(col {ea[0]}-{ea[2]}, row {ea[1]}-{ea[3]})と "
                    f"'{b}'(col {eb[0]}-{eb[2]}, row {eb[1]}-{eb[3]})のセル範囲が"
                    "重なっています(col/row を調整)")

    C = max(c for c, _ in cell.values())
    R = max(r for _, r in cell.values())
    for c in conts:
        e0 = ext[c["id"]]
        for n in nodes:
            if c["id"] in parents[n["id"]]:
                continue
            cc, rr = cell[n["id"]]
            if e0[0] <= cc <= e0[2] and e0[1] <= rr <= e0[3]:
                sug = free_cell_suggestions((cc, rr), occ, list(ext.values()), (C, R))
                die(f"ノード '{n['id']}' がコンテナ '{c['id']}' の範囲内のセル "
                    f"({cc},{rr}) にいます(所属させるか移動)。空きセル候補: {sug}")
    return ext, parents


def _grow_cols_for_vertical_pairs(edges: list, nodes: list[dict], cmap: dict,
                                  ext: dict, cell: dict, sizes: dict,
                                  colw: list[float], cellX: list[float],
                                  off) -> bool:
    """縦並びペアの垂直直線の中心 x=0.5 が題字帯に塞がれる列の幅を広げる。

    同一列で行が異なる 2 ノード間のエッジは _direct_axis_route が垂直直線で
    結ぶが、行き先サブネットの題字帯(左端 +28px から文字幅ぶん)が列中心に
    掛かると、旧実装は「±NEAR_FRAC 内でずらした直線」を先に採用して中心から
    11px 前後ずれた線を作った(実使用FB第4R 指摘C: 0.6484)。優先順位を
    「中心 → 列幅拡張で中心確保 → 帯内シフト → ジョグ → 格子」に再構成し、
    ここでは「新しい列中心が題字帯右端 + TITLE_CLEAR に届く」最小幅へ該当列を
    広げる(colw[cc] += 2×不足量。列中心は Δ/2 しか動かないため)。
    ラベル等の障害物は配置後にしか確定しないため対象外
    (その場合は従来どおり帯内シフト/格子探索が受ける)。戻り値: 変更の有無。
    """
    nmap = {n["id"]: n for n in nodes}

    def chain(nid: str) -> list[str]:
        out, cur = [], nmap[nid].get("parent")
        while cur in cmap:
            out.append(cur)
            cur = cmap[cur].get("parent")
        return out

    def cut(ivs: list[tuple[float, float]], u: float, v: float) -> list:
        # _nearest_free と同じ包含規約(境界=クリアランスちょうどは有効)
        nxt = []
        for p, q in ivs:
            if v < p or q < u:
                nxt.append((p, q))
                continue
            if p <= u:
                nxt.append((p, min(q, u)))
            if v <= q:
                nxt.append((max(p, v), q))
        return nxt

    grew = False
    for e in edges:
        if not isinstance(e, dict) or "exit" in e or "entry" in e:
            continue   # 手動配線エッジは対象外
        s, d = e.get("src"), e.get("dst")
        if s == d or s not in nmap or d not in nmap:
            continue
        if nmap[s].get("on_boundary") or nmap[d].get("on_boundary"):
            continue   # 境界またぎノードは列中心に居ない
        (c1, r1), (c2, r2) = cell[s], cell[d]
        if c1 != c2 or r1 == r2:
            continue
        if r1 > r2 and not is_box(nmap[d]):
            continue   # 上向きの下辺進入は entity 箱のみ(直行ルートと同条件)
        low = s if r1 > r2 else d       # 下側ノード。その非共有祖先の top
        up = d if low == s else s       # 境界(題字帯)を直線が跨ぐ
        up_anc = set(chain(up))
        crossed = []
        for cid in chain(low):
            if cid in up_anc:
                break
            crossed.append(cid)
        if not crossed:
            continue
        # 両端と無関係なコンテナが行間を占める場合は直行自体が成立しない
        ra, rb = sorted((r1, r2))
        rel = up_anc | set(chain(low))
        if any(cid not in rel and ex[0] <= c1 <= ex[2]
               and ex[1] < rb and ra < ex[3]
               for cid, ex in ext.items()):
            continue
        cx = cellX[c1] + colw[c1] / 2
        # 探索幅は辺中心 ±NEAR_FRAC(0.35〜0.65)。v1.5.0 の「アイコン幅の
        # 重なり全域」は端点をほぼ角(frac 0.92)へ追いやる「浮いた線」を
        # 作った(FB第3R 指摘2)ため、_direct_axis_route と揃えて絞る
        m = NEAR_FRAC * min(sizes[s][0], sizes[d][0])
        lo_x, hi_x = cx - m, cx + m
        if hi_x <= lo_x:
            continue
        ivs = [(lo_x, hi_x)]
        need = None
        for cid in crossed:
            label = cmap[cid].get("label")
            if not label:
                continue
            ex = ext[cid]
            x1 = cellX[ex[0]] - off(cid, "l")
            x2 = cellX[ex[2]] + colw[ex[2]] + off(cid, "r")
            tw = min(text_width(str(label), 12) + 12, x2 - x1 - 28)
            if tw <= 0:
                continue
            ivs = cut(ivs, x1 + 28 - TITLE_CLEAR, x1 + 28 + tw + TITLE_CLEAR)
            # 拡張後は帯幅のコンテナ幅キャップ(w-28)が外れるため、
            # 需要は文字幅そのものの帯右端で見積もる
            need = max(need or 0.0,
                       x1 + 28 + text_width(str(label), 12) + 12 + TITLE_CLEAR)
        if need is None or any(p <= cx <= q for p, q in ivs):
            continue   # 帯なし/中心 0.5 がすでに通る → 拡張不要
        # 複製ペアの縦線は中心 0.5 が最優先(実使用FB第4R 指摘C:
        # 「ずらした直線」0.6484 より、列を広げて中心レーンを空ける)。
        # 拡張量は「新しい列中心が帯右端+TITLE_CLEAR に届く」量
        # (中心は Δ/2 しか動かないため 2 倍)。
        # +0.25px は浮動小数の再計算誤差で「ちょうど境界」が割れないための余裕
        new_w = colw[c1] + 2 * (need - cx) + 0.25
        # 389 ≈ 322(ラベル由来の列幅上限)+ 2×33(既定アイコン列で帯右端が
        # 中心を越え得る最大量)。中心優先化で必要拡張が旧 365(±NEAR_FRAC
        # 探索の水準)より 2×NEAR_FRAC×アイコン幅ぶん増えるため追随させた。
        # 回廊はセル間ギャップ(GAPX)側にあり列幅拡張では痩せない。
        # 超える拡張は諦めて帯内シフト → 中心出射ジョグ → 格子探索の
        # フォールバックに任せる
        if new_w > 389.0:
            continue
        colw[c1] = new_w
        grew = True
    return grew


def _equalize_sibling_containers(lay: Layout, conts: list[dict], ext: dict,
                                 nodes: list[dict], sizes: dict, cell: dict,
                                 cellX: list[float], cellY: list[float],
                                 colw: list[float], rowband: list[float]
                                 ) -> bool:
    """同じ親・同じ type の兄弟コンテナ群の寸法を揃える(R4-6)。

    サブネット等の同種コンテナは、中身のラベル長・列スパンの違いで幅
    (横並びなら高さ)が個別に伸び、実使用で「ガタガタ」と指摘された。
    縦積み(行レンジが互いに素・列レンジが重なる)グループは x スパンを
    グループの和集合 [min x1, max x2] へ、横並びは y スパンを同様に広げる
    — 広げる方向のみ(安全側)で、目標座標は必ずグループ内の既存境界
    座標。中身のセル中心は動かさず、斜め・格子状の混在配置は対象外。
    広げた矩形が「親からのはみ出し / 無関係コンテナへの接触 / 非所属
    ノードへの接触」を起こすグループは等化を諦めて現状維持。
    セル範囲(ext)を広げる方式も試したが、回廊・レーンが全域で組み
    変わり dense テンプレの交差が 4→8 に退行したため「レイアウト後の
    箱だけ広げ、配線への波及は _build の結果ロールバック(等化で
    ERROR/WARN が増えたタブは等化なしで作り直す)で受け止める」設計を
    採る。トップレベル "equalize_containers": false でオプトアウト。
    返り値: 1 グループでも等化を適用したか。
    """
    def node_rect(n: dict) -> Rect:
        # place() のノード配置ループと同じ計算(アイコン+ラベル)。
        # on_boundary は現時点の親境界へ吸着させて評価する
        w, h = sizes[n["id"]]
        cc, rr = cell[n["id"]]
        cx = cellX[cc] + colw[cc] / 2
        cy = cellY[rr] + rowband[rr] / 2
        ob = n.get("on_boundary")
        pb = lay.boxes.get(n.get("parent")) if ob else None
        if pb is not None:
            cx = {"left": pb[0], "right": pb[0] + pb[2]}.get(ob, cx)
            cy = {"top": pb[1], "bottom": pb[1] + pb[3]}.get(ob, cy)
        x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        if not is_box(n) and n.get("label"):
            lw, lh = text_size(n["label"], 12)
            x1, x2 = min(x1, cx - lw / 2), max(x2, cx + lw / 2)
            y2 += 2 + lh
        return (x1, y1, x2 - x1, y2 - y1)

    def hits(a: Rect, b: Rect, m: float) -> bool:
        return (a[0] < b[0] + b[2] + m and b[0] - m < a[0] + a[2]
                and a[1] < b[1] + b[3] + m and b[1] - m < a[1] + a[3])

    groups: dict[tuple, list[str]] = {}
    for c in conts:
        t = c.get("type")
        if not t or t == "lane":   # lane は先行のレンジ統一が既に揃えている
            continue
        groups.setdefault((c.get("parent") or "1", t), []).append(c["id"])

    applied = False
    for (pid, _t), ids in groups.items():
        if len(ids) < 2:
            continue
        exts = [ext[i] for i in ids]
        pairs = [(exts[i], exts[j]) for i in range(len(exts))
                 for j in range(i + 1, len(exts))]
        rows_disj = all(a[3] < b[1] or b[3] < a[1] for a, b in pairs)
        cols_disj = all(a[2] < b[0] or b[2] < a[0] for a, b in pairs)
        cols_over = all(a[0] <= b[2] and b[0] <= a[2] for a, b in pairs)
        rows_over = all(a[1] <= b[3] and b[1] <= a[3] for a, b in pairs)
        boxes = [lay.boxes[i] for i in ids]
        if rows_disj and cols_over:      # 縦積み → 幅を揃える
            t1 = min(b[0] for b in boxes)
            t2 = max(b[0] + b[2] for b in boxes)
            news = {i: (t1, b[1], t2 - t1, b[3]) for i, b in zip(ids, boxes)}
        elif cols_disj and rows_over:    # 横並び → 高さを揃える
            t1 = min(b[1] for b in boxes)
            t2 = max(b[1] + b[3] for b in boxes)
            news = {i: (b[0], t1, b[2], t2 - t1) for i, b in zip(ids, boxes)}
        else:
            continue
        grown = [i for i in ids
                 if any(abs(u - v) > 0.5
                        for u, v in zip(news[i], lay.boxes[i]))]
        if not grown:
            continue
        ok = True
        for cid in grown:
            nb = news[cid]
            rel = set(ancestors(lay, cid))
            px_box = lay.boxes.get(pid)
            if px_box is not None:       # 親の内側 6px に収まること(防御)
                px, py, pw, ph = px_box
                if (nb[0] < px + 6 or nb[1] < py + 6
                        or nb[0] + nb[2] > px + pw - 6
                        or nb[1] + nb[3] > py + ph - 6):
                    ok = False
                    break
            for c2 in conts:             # 無関係コンテナ(祖先・子孫以外)
                cid2 = c2["id"]
                if (cid2 == cid or cid2 in rel
                        or cid in ancestors(lay, cid2)):
                    continue
                if hits(nb, lay.boxes[cid2], 8.0):
                    ok = False
                    break
            if not ok:
                break
            for n in nodes:              # 非所属ノード(ラベル込み)
                if cid in ancestors(lay, n["id"]):
                    continue
                if hits(nb, node_rect(n), 8.0):
                    ok = False
                    break
            if not ok:
                break
        if ok:
            for cid in ids:
                lay.boxes[cid] = news[cid]
            applied = True
    return applied


def place(spec: dict, icons: dict) -> tuple[Layout, list[dict], list[dict], list[Rect]]:
    """セル割り当て → 絶対座標(コンテナ・ノード)と回廊格子を計算する。"""
    conts = spec.get("containers", [])
    nodes = spec.get("nodes", [])
    cell, occ = assign_cells(nodes)
    ext, _ = container_extents(conts, nodes, cell, occ)
    # スイムレーン(type=lane)は「図の全長を貫く帯」が記法。レーン同士で
    # 直交軸の範囲を統一する(縦レーン=行範囲を、横レーン=列範囲を揃える)
    lanes = [c["id"] for c in conts if c.get("type") == "lane"]
    if len(lanes) >= 2:
        cs = [ext[i] for i in lanes]
        col_disjoint = all(a[2] < b[0] or b[2] < a[0]
                           for i, a in enumerate(cs) for b in cs[i + 1:])
        if col_disjoint:   # 縦レーン(フローは上→下)
            r1, r2 = min(e[1] for e in cs), max(e[3] for e in cs)
            for i in lanes:
                e = ext[i]
                ext[i] = (e[0], r1, e[2], r2)
        else:              # 横レーン
            c1_, c2_ = min(e[0] for e in cs), max(e[2] for e in cs)
            for i in lanes:
                e = ext[i]
                ext[i] = (c1_, e[1], c2_, e[3])
    cmap = {c["id"]: c for c in conts}
    C = max(c for c, _ in cell.values())
    R = max(r for _, r in cell.values())

    # 境界ごとの枠線スタック → セル座標。オフセットは px 単位
    # (off / edge_off は sizes 計算後に定義 — on_boundary の breach が
    # アイコン寸法に依存するため)
    kids_of: dict[str, list[str]] = {}
    for c in conts:
        kids_of.setdefault(c.get("parent") or "1", []).append(c["id"])
    SIDE = {"l": 0, "t": 1, "r": 2, "b": 3}
    BORDER_PAD = {"l": float(PAD), "r": float(PAD),
                  "t": float(TOPB), "b": float(BOTB)}

    # 列幅: ラベルが長い列は自動で広げる(隣接ラベルの E1 重なり防止)
    colw = [float(CELLW)] * (C + 1)
    sizes: dict[str, tuple[float, float]] = {}   # id → (w, h)
    for n in nodes:
        if is_entity(n):
            _lbl, iw, ih = entity_geometry(n)
        elif is_flow(n):
            iw, ih = flow_geometry(n)
        else:
            _, iw, ih = node_icon(icons, n)
        w = float(n.get("w", iw))
        h = float(n.get("h", ih))
        sizes[n["id"]] = (w, h)
        need = w + 16
        if n.get("label") and not is_entity(n):
            need = max(need, text_size(n["label"], 12)[0] + 14)
        cc = cell[n["id"]][0]
        # 上限 322 = 極端な長文ラベル(384px 級)がはみ出しても隣の列ギャップ
        # (GAPX=44)に 13px の配線回廊が残る値(GAPX とセットで調整すること)
        colw[cc] = max(colw[cc], min(need, 322.0))

    # 行高: entity 箱は高さがまちまちなので、行ごとに帯の高さを自動拡張する。
    # アイコン行のラベル余白は「その行の最大ラベル行数」に適応させる
    # (1 行ラベルの行に 2 行ぶんの余白 42px を常に確保していたのが余白過多の主因)
    rowband = [float(ICONBAND)] * (R + 1)
    has_icon = [False] * (R + 1)
    lab_lines = [0] * (R + 1)
    for n in nodes:
        rr = cell[n["id"]][1]
        rowband[rr] = max(rowband[rr], sizes[n["id"]][1])
        if not is_entity(n):
            has_icon[rr] = True
            # フロー図形のラベルは箱の内側(flow_geometry が箱高に反映済み)
            # なので、帯下の余白を数えるのは外付けラベルのアイコンだけ
            if n.get("label") and not is_flow(n):
                lines = len(re.split(r"<br\s*/?>|\n", str(n["label"])))
                lab_lines[rr] = max(lab_lines[rr], lines)
    # ノードのない行/列は潰す(空きインデックスがそのまま余白の海になる問題)。
    # 連続する空きは「使用行→使用行」の間隔が 2 ギャップぶんに収まり、帯の
    # 分離感は残る。格子線の座標衝突を避けるため 8px だけ残す
    used_rows = {r for _, r in cell.values()}
    used_cols = {c for c, _ in cell.values()}
    rowh = [max(rowband[r] + (16.0 * lab_lines[r] + 12.0 if has_icon[r]
                              else 24.0),
                ICONBAND + 12.0 if has_icon[r] else 0.0)
            if r in used_rows else 8.0
            for r in range(R + 1)]
    for c in range(C + 1):
        if c not in used_cols:
            colw[c] = 8.0

    # on_boundary ノードは親枠線をアイコン半分だけ外へはみ出す。またぎ方向の
    # すぐ外側に祖先コンテナの枠線が立つ(枠線同士の間隔が既定の 20/34/14px)
    # と、はみ出した半分が祖先枠線に重なり「どの境界をまたいだか」判別できない。
    # そこで、はみ出し量(アイコンの 1/2)+クリアランス(同 1/2)を
    # 「親枠線とそのすぐ外側の枠線の間の要求パディング」として breach に記録し、
    # off() の再帰で祖先側へ伝播させる(フラッシュな該当側だけ局所的に広がる)
    breach: dict[tuple[str, str], float] = {}
    for n in nodes:
        ob, p_ = n.get("on_boundary"), n.get("parent")
        if ob in ("left", "right", "top", "bottom") and p_ in cmap:
            w_, h_ = sizes[n["id"]]
            key = (p_, ob[0])  # left→l / right→r / top→t / bottom→b
            breach[key] = max(breach.get(key, 0.0),
                              float(w_ if ob in ("left", "right") else h_))

    off_memo: dict[tuple[str, str], float] = {}

    def off(cid, side):
        """cid の side 枠線の、セル境界からの外向きオフセット(px)。

        既定はネスト 1 段あたり BORDER_PAD。フラッシュ(同じセル境界に立つ)
        子枠線が on_boundary の breach を持つ場合、その子との間隔だけ広がる。
        """
        key = (cid, side)
        if key not in off_memo:
            i, base = SIDE[side], BORDER_PAD[side]
            off_memo[key] = max(
                [base] + [off(k, side) + max(base, breach.get((k, side), 0.0))
                          for k in kids_of.get(cid, [])
                          if ext[k][i] == ext[cid][i]])
        return off_memo[key]

    def edge_off(val, side):
        """セル境界 val の side 側に立つ枠線スタック全体の所要幅(px)。"""
        i = SIDE[side]
        return max((off(c["id"], side) for c in conts
                    if ext[c["id"]][i] == val), default=0.0)

    def compute_cellX() -> list[float]:
        xs_ = [0.0] * (C + 1)
        xs_[0] = MARGIN + edge_off(0, "l")
        for c in range(1, C + 1):
            gap = GAPX if (c - 1 in used_cols or c in used_cols) else 0.0
            xs_[c] = (xs_[c - 1] + colw[c - 1] + edge_off(c - 1, "r")
                      + gap + edge_off(c, "l"))
        return xs_

    cellX = compute_cellX()
    # 縦並びペアの垂直直線(指摘2)が題字帯で全滅する列だけ幅を広げる。
    # 拡張が別コンテナの帯幅キャップを外す連鎖に備えて数回だけ収束させる
    for _ in range(3):
        if not _grow_cols_for_vertical_pairs(spec.get("edges") or [], nodes,
                                             cmap, ext, cell, sizes, colw,
                                             cellX, off):
            break
        cellX = compute_cellX()
    cellY = [0.0] * (R + 1)
    cellY[0] = MARGIN + edge_off(0, "t")
    for r in range(1, R + 1):
        gap = GAPY if (r - 1 in used_rows or r in used_rows) else 0.0
        cellY[r] = (cellY[r - 1] + rowh[r - 1] + edge_off(r - 1, "b")
                    + gap + edge_off(r, "t"))

    lay = Layout(C=C, R=R, cell=cell, cmap=cmap, cext=ext, occ=occ)
    for c in conts:
        p_ = c.get("parent")
        lay.parents[c["id"]] = p_ if p_ in cmap else None
    for n in nodes:
        p_ = n.get("parent")
        lay.parents[n["id"]] = p_ if p_ in cmap else None

    # コンテナの絶対座標
    for c in conts:
        c1, r1, c2, r2 = ext[c["id"]]
        x1 = cellX[c1] - off(c["id"], "l")
        x2 = cellX[c2] + colw[c2] + off(c["id"], "r")
        y1 = cellY[r1] - off(c["id"], "t")
        y2 = cellY[r2] + rowh[r2] + off(c["id"], "b")
        lay.boxes[c["id"]] = (x1, y1, x2 - x1, y2 - y1)

    # 同種兄弟コンテナの寸法等化(R4-6)。題字帯・出力・ノード配置より
    # 前に行い、下流(on_boundary ノード・ガター・ルータ)は等化後の箱を
    # 見る。適用の有無は lay.equalized に記録し、_build が「等化で
    # ERROR/WARN が増えたタブだけ等化なしで作り直す」判断に使う
    lay.equalized = False
    if spec.get("equalize_containers", True):
        lay.equalized = _equalize_sibling_containers(
            lay, conts, ext, nodes, sizes, cell, cellX, cellY, colw, rowband)

    out_conts = []
    for c in conts:
        x1, y1, cw_, ch_ = lay.boxes[c["id"]]
        x2 = x1 + cw_
        if c.get("label"):  # タイトル文字帯(格子は塞がず重いペナルティで嫌う)
            # 実テキストは spacingLeft=30 から。左の空白 28px は帯に含めない。
            # 幅がコンテナに収まらない題字は draw.io が折り返して描くため、
            # 帯の高さも行数ぶん確保する(1 行モデルのままだと 2 行目の
            # 文字列上をジョグ・直行直線が「検査は通るのに文字を跨ぐ」)
            full_tw = text_width(str(c["label"]), 12) + 12
            tw = min(full_tw, x2 - x1 - 28)
            if tw > 0:
                lines_ = max(1, math.ceil(full_tw / max(tw, 1.0)))
                lay.title_bands.append((x1 + 28, y1 + 3, tw, 16.0 * lines_))
        oc = dict(c)
        oc.update({"x": g0(x1), "y": g0(y1), "w": g0(cw_), "h": g0(ch_)})
        out_conts.append(oc)

    # ノードの絶対座標(中心線は行のアイコン帯中央で統一)+ 配線障害物
    out_nodes = []
    obstacles = lay.obstacles
    for n in nodes:
        w, h = sizes[n["id"]]
        cc, rr = cell[n["id"]]
        cx = cellX[cc] + colw[cc] / 2
        cy = cellY[rr] + rowband[rr] / 2
        # on_boundary: ゲートウェイ系(IGW/VGW 等)を親コンテナの枠線上に
        # センターまたぎで置く(AWS 公式図の慣例)。コンテナは先行ループで
        # 配置済み。親が未定義でも落とさない(validate_spec が後で die する。
        # eval_layout は SpecError しか捕捉しないため KeyError を漏らさない)
        ob = n.get("on_boundary")
        pb = lay.boxes.get(n.get("parent")) if ob else None
        if pb is not None:
            if ob == "left":
                cx = pb[0]
            elif ob == "right":
                cx = pb[0] + pb[2]
            elif ob == "top":
                cy = pb[1]
            elif ob == "bottom":
                cy = pb[1] + pb[3]
        lay.boxes[n["id"]] = (cx - w / 2, cy - h / 2, w, h)
        x1, y1 = cx - w / 2, cy - h / 2
        x2, y2 = cx + w / 2, cy + h / 2
        if is_box(n):
            lay.box_nodes.add(n["id"])   # ラベルは箱の中 → 下辺も配線に使える
            if n.get("shape") in ("decision", "gateway"):
                lay.diamond.add(n["id"])   # ひし形: 出入りは頂点(0.5)のみ
            elif is_flow(n):
                lay.flow_boxes.add(n["id"])   # R7-A3 流入辺規約(entity は対象外)
        elif n.get("label"):
            lw, lh = text_size(n["label"], 12)
            x1, x2 = min(x1, cx - lw / 2), max(x2, cx + lw / 2)
            y2 += 2 + lh
        obstacles.append((x1, y1, x2 - x1, y2 - y1))
        lay.fullb[n["id"]] = (x1, y1, x2 - x1, y2 - y1)
        on = {k: v for k, v in n.items()
              if k not in ("col", "row", "on_boundary")}
        if pb is not None:  # バリデータが「意図的なまたぎ」と識別するマーカー
            on["style_extra"] = n.get("style_extra", "") + "awsdiagBoundary=1;"
        on.update({"cx": g0(cx), "cy": g0(cy)})
        out_nodes.append(on)

    # 回廊格子: 偶数 index = 回廊、奇数 index = セル中心線。
    # 回廊は「隙間全体の中点」ではなく「コンテナ境界を除いた自由区間(GAP 幅)の
    # 中央」に置く。中点方式だと境界が偏って挟まる箇所(例: リージョン+VPC の
    # 2 枚が片側に立つ)で回廊が境界線の 2〜4px 隣に落ち、エッジが枠線と
    # 長距離並走して被って見える
    def corrX(b):
        if b <= 0:
            return max(15.0, cellX[0] - edge_off(0, "l") - GAPX / 2)
        if b > C:
            return cellX[C] + colw[C] + edge_off(C, "r") + GAPX / 2
        lo = cellX[b - 1] + colw[b - 1] + edge_off(b - 1, "r")
        hi = cellX[b] - edge_off(b, "l")
        return (lo + hi) / 2

    def corrY(b):
        if b <= 0:
            return max(15.0, cellY[0] - edge_off(0, "t") - GAPY / 2)
        if b > R:
            return cellY[R] + rowh[R] + edge_off(R, "b") + GAPY / 2
        lo = cellY[b - 1] + rowh[b - 1] + edge_off(b - 1, "b")
        hi = cellY[b] - edge_off(b, "t")
        return (lo + hi) / 2

    # 格子線: 回廊・セル中心に加え、各コンテナ境界のすぐ内側のガター(内周路)。
    # ガターが無いと、コンテナ内で完結すべき長距離線の逃げ道が境界の外にしかなくなる
    xset = {corrX(b) for b in range(C + 2)} | {cellX[c] + colw[c] / 2
                                              for c in range(C + 1)}
    yset = {corrY(r) for r in range(R + 2)} | {cellY[r] + rowband[r] / 2
                                              for r in range(R + 1)}
    top_conts = [c for c in conts if c.get("parent") not in cmap]
    for c in top_conts:  # 最上位コンテナ(AWS Cloud 等)の内周ガターのみ追加
        bx, by, bw, bh = lay.boxes[c["id"]]
        # 内周ガターは枠線から 12px 内側(W13 の 10px 判定より外)。
        # 中身に近すぎる区間はルータの CLEARANCE 遮断で自然に使われない
        xset |= {bx + 12.0, bx + bw - 12.0}
        yset |= {by + TOPB / 2, by + bh - 12.0}

    def dedupe(vals: set[float]) -> list[float]:
        out: list[float] = []
        for v in sorted(vals):
            if not out or v - out[-1] > 6.0:
                out.append(v)
        return out

    lay.xs = dedupe(xset)
    lay.ys = dedupe(yset)

    def idx_of(arr: list[float], v: float) -> int:
        return min(range(len(arr)), key=lambda i: abs(arr[i] - v))

    lay.xi_corr = [idx_of(lay.xs, corrX(b)) for b in range(C + 2)]
    lay.xi_band = [idx_of(lay.xs, cellX[c] + colw[c] / 2) for c in range(C + 1)]
    lay.yi_corr = [idx_of(lay.ys, corrY(r)) for r in range(R + 2)]
    lay.yi_band = [idx_of(lay.ys, cellY[r] + rowband[r] / 2) for r in range(R + 1)]

    # ガターを持つ最上位コンテナのラベル帯(左上のタイトル)は障害物にして、
    # ガターの線がタイトル文字を横切らないようにする
    for c in top_conts:
        bx, by, bw, bh = lay.boxes[c["id"]]
        lw = 40 + text_width(str(c.get("label", "")), 12) + 16
        obstacles.append((bx, by, min(lw, bw), TOPB - 6))

    return lay, out_conts, out_nodes


# ---- エッジ配線 ----

Stub = tuple[str, float, tuple[int, int], str, float]  # (辺, frac, 格子点, 方向, コスト)


_SIDE_NORMAL = {"L": (-1.0, 0.0), "R": (1.0, 0.0),
                "T": (0.0, -1.0), "B": (0.0, 1.0)}


def _dir_penalty(side: str, dx: float, dy: float) -> float:
    """出入り辺の方向不一致ペナルティ(辺の外向き法線と相手方向の余弦で傾斜)。

    dx, dy = 自分の中心から相手端点の中心へのベクトル。余弦 fc に対し、
    正面(fc=1)は 0、垂直(fc=0)は MISALIGN、そこから反対側(fc=-1)へ
    向けて ANTI_ALIGN まで線形に強まる。旧実装は「向いていない辺は一律
    25」の二値で、行き先方向をほぼ見ず、行き先と逆の辺から出て回り込む
    線を許した(実使用FB第4R 指摘A)。行き先寄りの辺(0<fc<1)は旧値より
    軽くなるので同格候補間の自然な辺が勝ちやすく、反対側は強罰。禁止は
    しない — 行き先側の辺が障害物・題字帯で全滅している図では従来どおり
    他の辺へ逃げられる。垂直の基準値を 25 から上げる案は、テンプレ実測で
    dense の交差 4→6以上の退行を生むため不採用(混雑図では側面選択の
    自由度が交差回避に効いている)。
    """
    n = math.hypot(dx, dy)
    if n < 1e-9:
        return 0.0
    nx, ny = _SIDE_NORMAL[side]
    fc = (nx * dx + ny * dy) / n
    if fc >= 0.0:
        return Router.MISALIGN * (1.0 - fc)
    return Router.MISALIGN + (Router.ANTI_ALIGN - Router.MISALIGN) * -fc


def node_stubs(lay: Layout, nid: str, other_center: Point,
               entering: bool) -> list[Stub]:
    """ノードの出入り可能な辺と接続先格子点を返す。

    返り値: (辺, 辺上の位置 frac, 格子点, スタブ方向(entering 時は最終進入方向),
    スタブ長+ペナルティ)。アイコンの下辺はラベルがあるため使わない。
    """
    c, r = lay.cell[nid]
    x, y, w, h = lay.boxes[nid]
    cx, cy = lay.center(nid)
    ox, oy = other_center
    out = []
    xL, xR = lay.xi_corr[c], lay.xi_corr[c + 1]
    xB, yB, yT = lay.xi_band[c], lay.yi_band[r], lay.yi_corr[r]
    sides = [
        ("L", (xL, yB), "L", "R", x - lay.xs[xL]),
        ("R", (xR, yB), "R", "L", lay.xs[xR] - (x + w)),
        ("T", (xB, yT), "U", "D", y - lay.ys[yT]),
    ]
    if nid in lay.box_nodes:  # entity 箱は下にラベルが無いので下辺も使える
        yBot = lay.yi_corr[r + 1]
        sides.append(("B", (xB, yBot), "D", "U",
                      lay.ys[yBot] - (y + h)))
    for side, pt, d_out, d_in, slen in sides:
        cost = max(slen, 0.0) + _dir_penalty(side, ox - cx, oy - cy)
        # スタブ線分がコンテナ題字帯を貫くなら重罰(題字直下ノードの上辺進入等)
        gx, gy = lay.xs[pt[0]], lay.ys[pt[1]]
        if side == "L":
            seg = ((gx, gy), (x, gy))
        elif side == "R":
            seg = ((gx, gy), (x + w, gy))
        elif side == "T":
            seg = ((gx, gy), (gx, y))
        else:
            seg = ((gx, gy), (gx, y + h))
        cost += title_pen(lay, *seg)
        out.append((side, .5, pt, d_in if entering else d_out, cost))
    return out


def _title_blocks(lay: Layout, cid: str, gy: float,
                  xx: float | None = None) -> list[tuple[float, float]] | None:
    """コンテナ cid の上辺進入 x を塞ぐ題字帯の x 区間(クリアランス込み)。

    対象は、回廊 gy から上辺 y までの降下スタブが縦に横切る帯(祖先の題字)と、
    cid 自身の題字(上辺のすぐ内側 — 線分交差はしないが矢先が文字の上に載る)。
    自分の題字は左端が x+28 固定で、帯の左は幅 20px 弱の隅ポケットしか
    残らないため、コンテナ左端まで塞いで右側へ避けさせる。
    xx を渡すと「xx がどれかの帯に当たるときだけ」全ブロックを返し、
    当たらなければ None(呼び出し側の早期判定用)。
    """
    x, y, w, h = lay.boxes[cid]
    blocks: list[tuple[float, float]] = []
    hit = False
    for bx, by, bw, bh in lay.title_bands:
        if not (by + bh > min(gy, y) and by < y + 20.0):
            continue    # 降下スタブにも上辺直下にも掛からない帯
        own = abs(bx - (x + 28.0)) < 1.0 and abs(by - (y + 3.0)) < 1.0
        if by >= y and not own:
            continue    # 上辺より下は自分の題字だけが対象(他コンテナの帯は無関係)
        u, v = bx - TITLE_CLEAR, bx + bw + TITLE_CLEAR
        if own:         # 自分の題字帯: 左ポケット(幅 20px 弱)を使わない
            u = x
        blocks.append((u, v))
        if xx is not None and u < xx < v:
            hit = True
    if xx is not None and not hit:
        return None
    return blocks


def _title_free_x(lay: Layout, cid: str, gy: float, xx: float) -> float | None:
    """上辺進入 x=xx が題字帯に当たるとき、コンテナ内で最も近い空き x。"""
    x, _y, w, _h = lay.boxes[cid]
    blocks = _title_blocks(lay, cid, gy)
    return _nearest_free(xx, x + 8.0, x + w - 8.0, blocks or [])


def container_stubs(lay: Layout, cid: str, other_center: Point,
                    entering: bool) -> list[Stub]:
    """コンテナの外周に沿った出入り口(全周の回廊格子点)を返す。

    横断的関心事(監視・CI/CD 等)をコンテナ端点に集約したときも、
    ノードと同じ格子探索で障害物・交差を避けた配線ができる。
    境界のすぐ内側のセルが埋まっている位置は、矢印がそのノードを
    指しているように見えるためペナルティを付けて空き行/列を優先する。
    """
    OCCUPIED = 90.0
    c1, r1, c2, r2 = lay.cext[cid]
    x, y, w, h = lay.boxes[cid]
    cx, cy = lay.center(cid)
    ox, oy = other_center
    # 相手が自分の内側(内包エッジ: cloud→内部ノード等)ならスタブは内向き
    inside = x < ox < x + w and y < oy < y + h
    FLIP = {"L": "R", "R": "L", "U": "D", "D": "U"}

    def dd(ent: str, ext: str) -> str:
        d = ent if entering else ext
        return FLIP[d] if inside else d

    out = []
    for r in range(r1, r2 + 1):
        yy = lay.ys[lay.yi_band[r]]
        frac = (yy - y) / h
        mis = _dir_penalty("L", ox - cx, oy - cy)
        mis += OCCUPIED if (c1, r) in lay.occ else 0.0
        mis += title_pen(lay, (lay.xs[lay.xi_corr[c1]], yy), (x, yy))
        out.append(("L", frac, (lay.xi_corr[c1], lay.yi_band[r]),
                    dd("R", "L"),
                    max(x - lay.xs[lay.xi_corr[c1]], 0.0) + mis))
        mis = _dir_penalty("R", ox - cx, oy - cy)
        mis += OCCUPIED if (c2, r) in lay.occ else 0.0
        mis += title_pen(lay, (lay.xs[lay.xi_corr[c2 + 1]], yy), (x + w, yy))
        out.append(("R", frac, (lay.xi_corr[c2 + 1], lay.yi_band[r]),
                    dd("L", "R"),
                    max(lay.xs[lay.xi_corr[c2 + 1]] - (x + w), 0.0) + mis))
    for c in range(c1, c2 + 1):
        xx = lay.xs[lay.xi_band[c]]
        frac = (xx - x) / w
        gy = lay.ys[lay.yi_corr[r1]]
        mis = _dir_penalty("T", ox - cx, oy - cy)
        mis += OCCUPIED if (c, r1) in lay.occ else 0.0
        # 上辺進入(出射)の降下線が題字文字に当たる列は、帯の外の x へ
        # 自動オフセットする(実使用FB第4R 指摘B: TGW→直下アカウントの
        # 降下がタイトル文字を貫通/矢先が題字に載る)。避け先が無ければ
        # 従来どおり title_pen を課したまま残す(他の辺への逃げ道)
        tpen = title_pen(lay, (xx, gy), (xx, y))
        if tpen == 0.0 and _title_blocks(lay, cid, gy, xx) is not None:
            tpen = 1800.0    # 矢先が自分の題字文字の上に載る(W5 未満の視認 NG)
        if tpen:
            fx = _title_free_x(lay, cid, gy, xx)
            if fx is not None:
                frac = (fx - x) / w
                mis += 0.15 * abs(fx - xx)   # 素で空いている列を優先させる程度
                tpen = 0.0
        mis += tpen
        out.append(("T", frac, (lay.xi_band[c], lay.yi_corr[r1]),
                    dd("D", "U"),
                    max(y - gy, 0.0) + mis))
        mis = _dir_penalty("B", ox - cx, oy - cy)
        mis += OCCUPIED if (c, r2) in lay.occ else 0.0
        mis += title_pen(lay, (xx, lay.ys[lay.yi_corr[r2 + 1]]), (xx, y + h))
        out.append(("B", (xx - x) / w,
                    (lay.xi_band[c], lay.yi_corr[r2 + 1]),
                    dd("U", "D"),
                    max(lay.ys[lay.yi_corr[r2 + 1]] - (y + h), 0.0) + mis))
    return out


def terminal_stubs(lay: Layout, tid: str, other_center: Point,
                   entering: bool) -> list[Stub]:
    if tid in lay.cmap:
        return container_stubs(lay, tid, other_center, entering)
    return node_stubs(lay, tid, other_center, entering)


def ancestors(lay: Layout, tid: str) -> list[str]:
    """tid の祖先コンテナ id を内側から外側の順で返す。"""
    out = []
    cur = lay.parents.get(tid)
    while cur is not None:
        out.append(cur)
        cur = lay.parents.get(cur)
    return out


def lca_container(lay: Layout, src: str, dst: str) -> str | None:
    """両端点の最も内側の共通祖先コンテナ id(なければ None)。"""
    bset = set(ancestors(lay, dst))
    if dst in lay.cmap:
        bset.add(dst)
    chain = ([src] if src in lay.cmap else []) + ancestors(lay, src)
    for cid in chain:  # 内側から外側の順
        if cid in bset:
            return cid
    return None


def lca_bounds(lay: Layout, src: str, dst: str) -> Rect | None:
    """両端点の最も内側の共通祖先コンテナの矩形(なければ None)。

    この矩形内で完結すべき配線が外(例: AWS Cloud の外)へ出ると、
    インターネット経由の通信に見えてしまうため、探索でペナルティを課す。
    端点自身がコンテナの場合はそれも共通領域の候補に含める
    (内包エッジ cloud→内部ノード は cloud 内で完結すべき)。
    """
    cid = lca_container(lay, src, dst)
    return lay.boxes[cid] if cid else None


BOUNDARY_TRANSIT = {"aws_cloud", "account", "ou", "corporate_dc", "mgmt_group",
                    "subscription", "resource_group", "folder", "project"}


def transit_avoid(lay: Layout, src: str, dst: str) -> list[Rect]:
    """経由してはいけない矩形 = どちらの端点にも無関係な境界コンテナ。

    マルチクラウド図で AWS→GCP の線が Azure の箱を突っ切ると Azure 経由の
    通信に見えてしまう。アカウント間の線が第三のアカウントを貫通するのも同じ。
    対象は最上位コンテナと管理境界型(BOUNDARY_TRANSIT。ネストしていてもよい)。
    サブネット等のネットワーク内側コンテナは対象外(横切るのが正常なため)。
    """
    related = set(ancestors(lay, src)) | set(ancestors(lay, dst)) | {src, dst}
    return [lay.boxes[cid] for cid, parent in lay.parents.items()
            if cid in lay.cmap and cid not in related
            and (parent is None
                 or lay.cmap[cid].get("type") in BOUNDARY_TRANSIT)]


def _nearest_free(target: float, a: float, b: float,
                  blocks: list[tuple[float, float]]) -> float | None:
    """[a, b] から blocks(開区間)を除いた残りで target に最も近い座標。

    blocks が全域を覆えば None。target が空き区間内ならそのまま返る
    (直行ルートの「中心が通るなら中心」を保つ)。
    """
    if b < a:
        return None
    ivs = [(a, b)]
    for u, v in blocks:
        nxt = []
        for p, q in ivs:
            if v < p or q < u:
                nxt.append((p, q))
                continue
            # 境界は許容(クリアランスちょうどの位置は有効)— 幅 0 の
            # 点区間も残す。拡張プリパスの cut と同じ包含規約にすること
            if p <= u:
                nxt.append((p, min(q, u)))
            if v <= q:
                nxt.append((max(p, v), q))
        ivs = nxt
    best = None
    for p, q in ivs:
        c = min(max(target, p), q)
        if best is None or abs(c - target) < abs(best - target):
            best = c
    return best


def _direct_axis_route(lay: Layout, e: dict, ban: frozenset = frozenset()
                       ) -> tuple[NodeRoute, tuple] | None:
    """同一列(行)で中心が揃う 2 ノード間の直交直線ルート(格子探索より優先)。

    格子探索は回廊の共有ペナルティや題字帯回避で軸上の最短路を嫌い、
    隣の回廊へ「コ」の字迂回を選ぶことがある。同軸ノード間の垂直(水平)
    直線は最短・最少曲がりで視覚的にも最も自然なので、間の直線帯に障害物
    (他ノード・ラベル・無関係な境界コンテナ)が無ければ探索せず直行させる。
    コンテナ題字帯だけは「塞がれた区間」として扱い、辺中心 ±NEAR_FRAC
    (0.35〜0.65)でずらした直線(exit/entry frac を揃えた垂直/水平線)、
    次いで中心出射+最小ジョグを試す(FB第2R 指摘2 / 第3R 指摘2)。
    他エッジとの交差・共有は不採用の理由にしない。
    縦の下向きはアイコン下辺(キャプション下 = exit_dy)から出て相手の
    上辺へ。上向きの下辺進入は entity 箱のみ(アイコンはキャプションが載る)。
    """
    src, dst = e["src"], e["dst"]
    if src == dst or src not in lay.cell or dst not in lay.cell:
        return None
    (c1, r1), (c2, r2) = lay.cell[src], lay.cell[dst]
    sb, db = lay.boxes[src], lay.boxes[dst]
    scx, scy = lay.center(src)
    dcx, dcy = lay.center(dst)
    if c1 == c2 and r1 != r2 and abs(scx - dcx) < 0.75:
        axis, line = "v", scx
        if r1 < r2:      # 下向き: キャプション下から出て上辺へ
            es, ns = "B", "T"
            fb = lay.fullb.get(src, sb)
            lo = sb[1] + sb[3] if src in lay.box_nodes else fb[1] + fb[3] + 2
            hi = db[1]
        else:            # 上向き: 下辺進入できるのは entity 箱のみ
            if dst not in lay.box_nodes:
                return None
            es, ns = "T", "B"
            lo, hi = db[1] + db[3], sb[1]
        band = (line - 24.0, lo, 48.0, hi - lo)
    elif r1 == r2 and c1 != c2 and abs(scy - dcy) < 0.75:
        axis, line = "h", scy
        if c1 < c2:
            es, ns = "R", "L"
            lo, hi = sb[0] + sb[2], db[0]
        else:
            es, ns = "L", "R"
            lo, hi = db[0] + db[2], sb[0]
        band = (lo, line - 24.0, hi - lo, 48.0)
    else:
        return None
    if hi - lo <= 12 or (src, es) in ban or (dst, ns) in ban:
        return None

    bx1, by1 = band[0], band[1]
    bx2, by2 = band[0] + band[2], band[1] + band[3]

    def in_band(rect: Rect) -> bool:
        x, y, w, h = rect
        return x < bx2 and bx1 < x + w and y < by2 and by1 < y + h

    def touches(a: Rect, b: Rect) -> bool:
        return (a[0] < b[0] + b[2] + 1 and b[0] - 1 < a[0] + a[2]
                and a[1] < b[1] + b[3] + 1 and b[1] - 1 < a[1] + a[3])

    # 自ノードのアイコン+ラベル箱はスタブが必然的に接するため除外する。
    # 障害物・無関係境界が中心線 ±24px を塞ぐ場合は従来どおり格子探索へ
    obs = [ob for ob in lay.obstacles
           if not (touches(ob, sb) or touches(ob, db))]
    avoid = transit_avoid(lay, src, dst)
    for ob in obs:
        if in_band(ob):
            return None
    for av in avoid:
        if in_band(av):
            return None

    # 題字帯は「塞がれた区間」として扱い、辺中心 ±NEAR_FRAC(frac 0.35〜
    # 0.65)の範囲でずらした直線を探す(指摘2: 行き先サブネットの題字が
    # 中心線に当たる縦並び複製ペア)。v1.5.0 の「両ノード幅の重なり全域」
    # 探索は端点をほぼ角(frac 0.92)まで追いやり、直線でも接続に見えない
    # 「浮いた線」を作った — 優先は 接続感 > 直線 > 折れ点最少(FB第3R)。
    # 中心が題字帯から TITLE_CLEAR 以上離れていればそのまま(exit/entry
    # 0.5)。ずらす場合も障害物・無関係境界からは 24px、題字帯からは
    # TITLE_CLEAR を確保する。この範囲で直線が引けなければ、中心出射の
    # まま塞ぐ矩形だけを最小ジョグでまたぐ(_jog_axis_route。列幅の拡張は
    # 配置段 _grow_cols_for_vertical_pairs が先に試している)
    if axis == "v":
        margin = NEAR_FRAC * min(sb[2], db[2])
    else:
        margin = NEAR_FRAC * min(sb[3], db[3])
    na, nb = line - margin, line + margin

    def lspan(r_: Rect) -> tuple[float, float]:      # 線軸方向の範囲
        return (r_[0], r_[0] + r_[2]) if axis == "v" else (r_[1], r_[1] + r_[3])

    def cspan(r_: Rect) -> tuple[float, float]:      # 進行軸方向の範囲
        return (r_[1], r_[1] + r_[3]) if axis == "v" else (r_[0], r_[0] + r_[2])

    blockers = []    # (u, v, p, q): 線軸レンジ(クリア込み)+進行軸レンジ
    for rects, clear in ((lay.title_bands, TITLE_CLEAR),
                         (obs, 24.0), (avoid, 24.0)):
        for r_ in rects:
            p, q = cspan(r_)
            if p < hi and lo < q:
                u, v = lspan(r_)
                blockers.append((u - clear, v + clear, p, q))
    pos = _nearest_free(line, na, nb, [(u, v) for u, v, _, _ in blockers])
    if pos is not None and abs(pos - line) > 1e-6 \
            and (src in lay.diamond or dst in lay.diamond):
        pos = None   # ひし形は頂点固定(R7-16)→ ずらし直線ではなく中心ジョグへ

    # 占有登録は格子探索が刻む範囲(両ノードのスタブ格子点の間)に合わせる。
    # 端点セルの内部まで claim すると、同じノードの他エッジのスタブ区間に
    # 共有ペナルティが乗り、無関係なエッジの経路が動いてしまう
    if axis == "v":
        ix = lay.xi_band[c1]
        ra, rb = min(r1, r2), max(r1, r2)
        j1, j2 = lay.yi_corr[ra + 1], lay.yi_corr[rb]
        path = [(ix, j) for j in range(j1, j2 + 1)]
        if r1 > r2:
            path.reverse()
    else:
        jy = lay.yi_band[r1]
        ca, cb = min(c1, c2), max(c1, c2)
        i1, i2 = lay.xi_corr[ca + 1], lay.xi_corr[cb]
        path = [(i, jy) for i in range(i1, i2 + 1)]
        if c1 > c2:
            path.reverse()
    stub_marks = [(axis, path[0]), (axis, path[-1])]

    if pos is None:
        jog = _jog_axis_route(lay, e, axis, line, lo, hi, es, ns, blockers)
        if jog is None:
            return None
        return jog, (path, stub_marks)
    f1 = f2 = .5
    if abs(pos - line) > 1e-6:
        if axis == "v":
            f1, f2 = (pos - sb[0]) / sb[2], (pos - db[0]) / db[2]
        else:
            f1, f2 = (pos - sb[1]) / sb[3], (pos - db[1]) / db[3]
        line = pos
    route = NodeRoute(exit=(es, f1), entry=(ns, f2),
                      runs=[Run(axis, line)], direct=True)
    return route, (path, stub_marks)


def _jog_axis_route(lay: Layout, e: dict, axis: str, line: float,
                    lo: float, hi: float, es: str, ns: str,
                    blockers: list[tuple]) -> NodeRoute | None:
    """中心出射の直線が塞がれたときの最小ジョグ(v–h–v–h–v)ルート。

    端点は両ノードとも辺中心 0.5 のまま、中心線を塞ぐ矩形の進行方向
    レンジ [p1, q1] だけを横の空き座標 xj へ逃げてまたぐ。端(角)から
    出る完全直線より、中心から出る小さな段差の方が接続として自然
    (FB第3R 指摘2)。ジョグの縦横セグメントも題字帯・障害物・無関係
    境界を横切らない(W5 予防)。成立しなければ None(格子探索へ)。
    """
    hit = [b for b in blockers if b[0] <= line <= b[1]]
    if not hit:
        return None

    def lspan_r(r_: Rect) -> tuple[float, float]:
        return (r_[0], r_[0] + r_[2]) if axis == "v" else (r_[1], r_[1] + r_[3])

    def cspan_r(r_: Rect) -> tuple[float, float]:
        return (r_[1], r_[1] + r_[3]) if axis == "v" else (r_[0], r_[0] + r_[2])

    # またぎ幅 8px・再進入レグ 4px 以上。コンテナ題字帯(下端 y+19)の
    # 直下に TOPB=34 でノードが座る標準形で 19+8=27 ≤ 34−4 が成立する幅
    p1 = min(b[2] for b in hit) - 8.0
    q1 = max(b[3] for b in hit) + 8.0
    # 左上角バッジ(grIcon 28px 角)は title_bands(x+28 から)の外 —
    # ジョグ線・レグが横切ると錠前アイコン等を跨ぐ(検査は通るが視認 NG)
    badges = []
    for cid_, c_ in lay.cmap.items():
        if "grIcon" in CONTAINER_STYLES.get(c_.get("type", ""), ""):
            bb_ = lay.boxes[cid_]
            badges.append((bb_[0], bb_[1], 28.0, 30.0))
    # 横レグがコンテナ枠線の 10px 未満の隣を走ると W13(枠線と二重に
    # 見える)— 枠線から離れる側(p1 は外へ、q1 は内へ)へ押し出す
    border_lines = []
    for cid_ in lay.cmap:
        cb_ = lay.boxes[cid_]
        border_lines += ([cb_[1], cb_[1] + cb_[3]] if axis == "v"
                         else [cb_[0], cb_[0] + cb_[2]])
    for bl_ in sorted(border_lines, reverse=True):
        if abs(p1 - bl_) < 10.0:
            p1 = bl_ - 10.0
    for bl_ in sorted(border_lines):
        if abs(q1 - bl_) < 10.0:
            q1 = bl_ + 10.0
    if p1 < lo + 4 or q1 > hi - 4:
        return None    # またぎ区間が端点スタブに食い込む
    # ジョグ縦(横)線の空き探索: またぎ区間 [p1, q1] と交わる矩形だけが
    # 塞ぐ。枠線 ±10px(W13 は 10px 未満×40px 以上で発火)と角バッジも
    # 避け、移動先は共通祖先コンテナ内(±8px)かつ中心 ±200px に限る
    lca = lca_container(lay, e["src"], e["dst"])
    if lca is not None:
        bx_, by_, bw_, bh_ = lay.boxes[lca]
        blo, bhi = ((bx_ + 8.0, bx_ + bw_ - 8.0) if axis == "v"
                    else (by_ + 8.0, by_ + bh_ - 8.0))
    else:
        blo, bhi = line - 200.0, line + 200.0
    blo, bhi = max(blo, line - 200.0), min(bhi, line + 200.0)
    jog_blocks = [(u, v) for u, v, p, q in blockers if p < q1 and p1 < q]
    for bx_, by_, bw_, bh_ in badges:
        bp, bq = cspan_r((bx_, by_, bw_, bh_))
        if bp < q1 and p1 < bq:
            bu, bv = lspan_r((bx_, by_, bw_, bh_))
            jog_blocks.append((bu - 6.0, bv + 6.0))
    for cid_ in lay.cmap:
        cb_ = lay.boxes[cid_]
        cp, cq = ((cb_[1], cb_[1] + cb_[3]) if axis == "v"
                  else (cb_[0], cb_[0] + cb_[2]))
        if cp < q1 and p1 < cq:      # またぎ区間に届く枠のみ
            for bl_ in ((cb_[0], cb_[0] + cb_[2]) if axis == "v"
                        else (cb_[1], cb_[1] + cb_[3])):
                jog_blocks.append((bl_ - 10.0, bl_ + 10.0))
    # 空き区間から候補(区間内で line に最も近い点)を近い順に試し、
    # 横(縦)レグ(p1・q1 上、line〜xj)が塞がれない最初の xj を採用する
    # (最近傍 1 点だけだと、レグがバッジ等に当たる側で全滅する)
    ivs = [(blo, bhi)]
    for u, v in jog_blocks:
        nxt = []
        for a_, b_ in ivs:
            if v < a_ or b_ < u:
                nxt.append((a_, b_))
                continue
            if a_ <= u:
                nxt.append((a_, min(b_, u)))
            if v <= b_:
                nxt.append((max(a_, v), b_))
        ivs = nxt
    cands = sorted({min(max(line, a_), b_) for a_, b_ in ivs},
                   key=lambda c_: abs(c_ - line))

    def legs_clear(xj_: float) -> bool:
        ja, jb = min(line, xj_), max(line, xj_)
        for u, v, p, q in blockers:
            for yy in (p1, q1):
                if p - 4.0 < yy < q + 4.0 and u < jb and ja < v:
                    return False
        for bd_ in badges:
            bp, bq = cspan_r(bd_)
            bu, bv = lspan_r(bd_)
            for yy in (p1, q1):
                if bp - 4.0 < yy < bq + 4.0 and bu - 4.0 < jb and ja < bv + 4.0:
                    return False
        return True

    xj = next((c_ for c_ in cands
               if abs(c_ - line) >= 6.0 and legs_clear(c_)), None)
    if xj is None:
        return None
    perp = "h" if axis == "v" else "v"
    fwd = es in ("B", "R")               # 下向き/右向きに進むか
    j1, j2 = (p1, q1) if fwd else (q1, p1)
    return NodeRoute(exit=(es, .5), entry=(ns, .5),
                     runs=[Run(axis, line), Run(perp, j1), Run(axis, xj),
                           Run(perp, j2), Run(axis, line)], direct=False)


def entry_conventions(lay: Layout, node_edges: list[dict],
                      kinds: dict | None = None) -> dict[str, frozenset]:
    """フロー図形の流入辺規約(R7-15 + R7-A3)を 1 つの ban 集合へ写す。

    diamond_conventions(ひし形の頂点規約)と box_entry_conventions
    (四角いフロー箱の上辺入射規約)の統合窓口。対象ノード集合が排他
    (lay.diamond / lay.flow_boxes)なので二重適用は起きない。
    返り値は eid → {(端子id, 辺), ...}(route_edge が常にマージする)。
    """
    bans: dict[str, set] = {}
    diamond_conventions(lay, node_edges, kinds, bans)
    box_entry_conventions(lay, node_edges, bans)
    return {eid: frozenset(v) for eid, v in bans.items()}


def box_entry_conventions(lay: Layout, node_edges: list[dict],
                          bans: dict[str, set]) -> None:
    """フロー箱(diamond 以外の全フロー図形)の流入辺規約(R7-A3)。

    decision の頂点規約(R7-15)を process/io/document/db/subprocess/
    terminator 等の箱へ一般化する。単純な 2 箱では素の探索でも上辺に
    入るが、混雑した配置(fork の分岐先で子が別ノードへの流出も持つ等)
    ではルータが交差・重なり回避を優先して側辺に落とす(実測: fork
    gateway→在庫引当が exit=(0.5,1) なのに entry=(1,0.5) 右辺)ため、
    コスト選択に任せず禁止で強制する:
      - 上方の src(src 下端 ≤ dst 上端)からの流入は上辺(T)のみ。
        diamond と違い辺上に複数ポートを並べられる(fan スロットが
        辺中心 0.5 対称に分配)ため、上方流入が複数でも全て上辺を
        分け合う
      - 同じ行の src(垂直重なりあり)は現状維持(側辺を選ぶルータの
        選好に任せる)
      - 下方の src(戻り)は上辺を使わない(references/flowchart.md の
        戻りフロー配置原則と整合)
    流出辺は制約しない(はい=下 等の出射規約・R4-1 の出射方向選好は
    既存機構のまま)。上辺が物理的に塞がれて到達不能な場合は
    route_edge が規約を外して再探索する(逃げ道 — 残る違反は
    バリデータ W15 が検出する)。
    """
    for e in node_edges:
        d = e["dst"]
        if (e["src"] == d or d not in lay.flow_boxes
                or d not in lay.boxes or e["src"] not in lay.boxes):
            continue
        dx, dy, dw, dh = lay.boxes[d]
        sx, sy, sw, sh = lay.boxes[e["src"]]
        if sy + sh <= dy:            # 上方 → 上辺のみ
            bans.setdefault(e["id"], set()).update((d, s) for s in "LRB")
        elif sy >= dy + dh:          # 下方(戻り)→ 上辺は使わない
            bans.setdefault(e["id"], set()).add((d, "T"))


def diamond_conventions(lay: Layout, node_edges: list[dict],
                        kinds: dict | None, bans: dict[str, set]) -> None:
    """decision(ひし形)の流入頂点規約(R7-15)を ban 集合へ写す。

    フローチャート標準(references/flowchart.md「上=入、左右下=出」)を
    ルータのコスト選択に任せず強制する:
      - 上方の src からの流入は上頂点(T)。複数あれば main 線種 > 水平
        ずれ最小 > spec 順で 1 本が T を取り、残りは src 側の側頂点へ
      - 同行の src からの流入は src 側の側頂点(L/R)
      - 下方の src からの流入(戻り)は上頂点を使わない(B/L/R は選択自由)
      - 流入が T を取る diamond では、流出も T を使わない
    上下は src 中心 y と diamond の箱の比較(上端より上=上方、下端より
    下=下方)。bans(eid → {(端子id, 辺), ...})へ追記する。
    """
    def ban_all_but(eid: str, d: str, want: str) -> None:
        bans.setdefault(eid, set()).update(
            (d, s) for s in "LRTB" if s != want)

    for d in sorted(lay.diamond):
        if d not in lay.boxes:
            continue
        dx, dy, dw, dh = lay.boxes[d]
        dcx = dx + dw / 2
        above: list[tuple[int, dict]] = []
        outs: list[dict] = []
        for i, e in enumerate(node_edges):
            if e["src"] == e["dst"]:
                continue
            if e["dst"] == d and e["src"] in lay.boxes:
                scx, scy = lay.center(e["src"])
                if scy < dy:            # 上方 → 上頂点の候補
                    above.append((i, e))
                elif scy <= dy + dh:    # 同行 → src 側の側頂点
                    ban_all_but(e["id"], d, "L" if scx < dcx else "R")
                else:                   # 下方(戻り)→ 上頂点は使わない
                    bans.setdefault(e["id"], set()).add((d, "T"))
            elif e["src"] == d and e["dst"] in lay.boxes:
                outs.append(e)
        if not above:
            continue
        above.sort(key=lambda item: (
            kind_base(item[1], kinds) != "main",
            abs(lay.center(item[1]["src"])[0] - dcx), item[0]))
        ban_all_but(above[0][1]["id"], d, "T")
        for _i, e in above[1:]:         # 上頂点は 1 本 — 残りは側頂点へ
            scx = lay.center(e["src"])[0]
            ban_all_but(e["id"], d, "L" if scx < dcx else "R")
        for e in outs:
            bans.setdefault(e["id"], set()).add((d, "T"))


def route_edge(router: Router, lay: Layout, e: dict,
               ban: frozenset = frozenset(), hard_only: bool = False
               ) -> tuple[NodeRoute, tuple] | None:
    """エッジ 1 本(端点はノードでもコンテナでもよい)を格子上で配線する。

    ban: {(端子id, 辺)} — その端子でその辺を使わない(ひし形の頂点衝突回避)。
    lay.diamond_bans(R7-15/A3 の流入辺規約)は常にマージする。規約 ban の
    せいで到達不能になる場合のみ規約を外して再探索する(未配線 WARN より
    規約違反の方がまし — 残った違反はバリデータ W15 が検出する)。
    到達不能なら None。返り値: (NodeRoute, Router.commit へ渡す引数)。
    """
    extra = lay.diamond_bans.get(e["id"], frozenset()) \
        if lay.diamond_bans else frozenset()
    base = frozenset(ban)
    if extra and not extra <= base:
        found = _route_edge_banned(router, lay, e, base | extra, hard_only)
        if found is not None:
            return found
    return _route_edge_banned(router, lay, e, base, hard_only)


def _route_edge_banned(router: Router, lay: Layout, e: dict,
                       ban: frozenset, hard_only: bool
                       ) -> tuple[NodeRoute, tuple] | None:
    found = _direct_axis_route(lay, e, ban)
    if found is not None:
        return found
    src, dst = e["src"], e["dst"]
    exits = [s for s in terminal_stubs(lay, src, lay.center(dst),
                                       entering=False)
             if (src, s[0]) not in ban]
    seeds = [(pt, d, cost) for _, _, pt, d, cost in exits]
    src_sides = {pt: (side, frac) for side, frac, pt, _, _ in exits}
    targets: dict[tuple[int, int], list] = {}
    for side, frac, pt, need_d, cost in terminal_stubs(lay, dst, lay.center(src),
                                                       entering=True):
        if (dst, side) in ban:
            continue
        targets.setdefault(pt, []).append((side, frac, need_d, cost))

    lca = lca_container(lay, src, dst)
    bounds = lay.boxes[lca] if lca else None
    # トップレベルコンテナ(aws_cloud / corporate_dc 等)は意味論的な網の
    # 境界 — 内部通信が 1px でも外(=インターネット側)を走ると誤読される
    # ため外周リングも許さない。入れ子コンテナは従来どおりリング可
    # (小さなサブネットは内部に回廊が無く、すぐ外の回廊が正常な経路)
    strict = lca is not None and lay.parents.get(lca) is None
    avoid = transit_avoid(lay, src, dst)
    # 共通祖先の外は原則禁止(内部通信が外周を走ると誤読される)。
    # 禁止では届かない場合のみ、従来のペナルティ方式で再探索する
    best, parent = router.search(seeds, targets, bounds, avoid,
                                 hard_bounds=True, strict_bounds=strict)
    if best is None and bounds is not None and not hard_only:
        best, parent = router.search(seeds, targets, bounds, avoid)
    if best is None:
        return None

    # 経路復元
    path = []
    state = best[0]
    while state is not None:
        path.append(state[0])
        state = parent[state]
    path.reverse()
    exit_side, exit_frac = src_sides[path[0]]
    entry_side, entry_frac = best[1], best[2]

    # 格子経路 → Run 列(スタブと同軸の区間はマージ)
    runs = [Run("h" if exit_side in "LR" else "v", 0.0)]
    for k in range(len(path) - 1):
        ax = "h" if path[k][1] == path[k + 1][1] else "v"
        if ax != runs[-1].axis:
            coord = lay.ys[path[k][1]] if ax == "h" else lay.xs[path[k][0]]
            runs.append(Run(ax, coord))
    entry_ax = "h" if entry_side in "LR" else "v"
    if entry_ax != runs[-1].axis:
        runs.append(Run(entry_ax, 0.0))

    route = NodeRoute(exit=(exit_side, exit_frac), entry=(entry_side, entry_frac),
                      runs=runs, direct=len(runs) == 1)
    stub_marks = [(runs[0].axis, path[0]), (runs[-1].axis, path[-1])]
    return route, (path, stub_marks)


def _dedupe_diamond_sides(router: Router, lay: Layout,
                          node_edges: list[dict],
                          routes: dict[str, NodeRoute], recs: dict,
                          kinds: dict | None = None) -> bool:
    """diamond の同一辺に付いた複数端点を頂点の再割当で解消する(R7-16)。

    ひし形の端点は頂点固定で、fan 系の辺上分散(スロット・ラダー)が
    使えないため、辺の専有(1 辺 1 端点)が唯一の重なり回避になる。
    争いのある diamond では「負けた端点を残り物の辺へ追う」のではなく、
    動かせる端点全体で総 facing(端点の辺法線と相手方向の余弦。main
    線種は +0.15 加点)最大の全単射を選び直す — 残り物方式は先着の
    ルータ解(交差最適だが逆向き)に引きずられ、相手が左なのに右辺
    という割当を作る(01-approval f4/f5 の実測)。規約で辺が 1 つに
    固定された端点(上方流入の T 等)は動かさない。引き直せない端点は
    現状維持(頂点に積み重なり、バリデータ W6/E7 が検出する)。
    引き直しでもう一方の端の diamond に新たな重なりが出得るため 2 周
    まで回す。返り値: 変更が生じたか。
    """
    idx = {e["id"]: i for i, e in enumerate(node_edges)}
    changed = False
    for _sweep in range(2):
        moved = False
        for d in sorted(lay.diamond):
            if d not in lay.boxes:
                continue
            dcx, dcy = lay.center(d)
            members: list[tuple] = []   # (e, 相手端, exit/entry)
            for e in node_edges:
                r = routes.get(e["id"])
                if not isinstance(r, NodeRoute) or e["src"] == e["dst"]:
                    continue
                if e["src"] == d:
                    members.append((e, "dst", "exit"))
                if e["dst"] == d:
                    members.append((e, "src", "entry"))
            cur = {id(m): getattr(routes[m[0]["id"]], m[2])[0]
                   for m in members}
            n_side: dict[str, int] = {}
            for m in members:
                n_side[cur[id(m)]] = n_side.get(cur[id(m)], 0) + 1
            if all(n <= 1 for n in n_side.values()):
                continue

            def allowed(m) -> list[str]:
                dban = lay.diamond_bans.get(m[0]["id"], frozenset())
                return [s for s in "TLRB" if (d, s) not in dban]

            fixed = [m for m in members
                     if len(allowed(m)) == 1 or m[0]["id"] not in recs]
            movable = sorted((m for m in members if m not in fixed),
                             key=lambda m: idx[m[0]["id"]])
            avail = [s for s in "TLRB"
                     if s not in {cur[id(m)] for m in fixed}]
            if len(movable) > len(avail):
                continue   # 辺 5 本以上: 全単射不能 → 積み重なりで現状維持

            def facing(m, side: str) -> float:
                e, other_term, _attr = m
                ox, oy = lay.center(e[other_term])
                vx, vy = ox - dcx, oy - dcy
                norm = math.hypot(vx, vy) or 1.0
                nx_, ny_ = _SIDE_NORMAL[side]
                f = (nx_ * vx + ny_ * vy) / norm
                return f + (0.15 if kind_base(m[0], kinds) == "main" else 0.0)

            best_perm, best_score = None, None
            for perm in itertools.permutations(avail, len(movable)):
                if any(s not in allowed(m) for m, s in zip(movable, perm)):
                    continue
                sc = sum(facing(m, s) for m, s in zip(movable, perm))
                if best_score is None or sc > best_score + 1e-9:
                    best_perm, best_score = perm, sc
            if best_perm is None:
                continue
            for m, want in zip(movable, best_perm):
                e, _ot, attr = m
                eid = e["id"]
                if cur[id(m)] == want:
                    continue
                ban = frozenset((d, s) for s in "TLRB" if s != want)
                old_rec, old_path = recs[eid]
                router.uncommit(old_rec)
                found = route_edge(router, lay, e, ban)
                if found is None or getattr(found[0], attr)[0] != want:
                    # 割当先へ引けない → 現状維持(残る重なりは W6/E7 へ)
                    recs[eid] = (router.recommit(old_rec), old_path)
                    continue
                routes[eid], (npath, marks) = found
                recs[eid] = (router.commit(npath, marks), npath)
                moved = changed = True
        if not moved:
            break
    return changed


def pinned_coords(lay: Layout, e: dict, route: NodeRoute
                  ) -> tuple[Point, Point, list[float]]:
    """端点座標と、端点に固定した各 Run の線座標を返す。"""
    es, ef = route.exit
    ns, nf = route.entry
    sp = lay.side_point(e["src"], es, ef)
    ep = lay.side_point(e["dst"], ns, nf)
    if es == "B" and e["src"] in lay.cell and e["src"] not in lay.box_nodes:
        # アイコンの下辺出射(直行ルート)はキャプションの真下から出す
        # (exitDy 相当。出力段が poly[0] とアイコン下辺の差から exit_dy を導く)
        fb = lay.fullb.get(e["src"])
        if fb is not None:
            sp = (sp[0], fb[1] + fb[3] + 2)
    coords = [r.coord for r in route.runs]
    coords[0] = sp[1] if es in "LR" else sp[0]
    coords[-1] = ep[1] if ns in "LR" else ep[0]
    return sp, ep, coords


def route_geometry(lay: Layout, e: dict, route: NodeRoute,
                   offsets: dict[int, float] | None = None
                   ) -> tuple[Point, Point, list[list[float]]]:
    """Run 列から端点座標と waypoint(折れ点)を計算する。

    offsets は assign_lanes が決めた中間 Run のレーンずらし量(run index → px)。
    """
    sp, ep, coords = pinned_coords(lay, e, route)
    if offsets:
        for i, off in offsets.items():
            coords[i] += off
    wps: list[list[float]] = []
    for i in range(len(route.runs) - 1):
        axis = route.runs[i].axis
        x = coords[i] if axis == "v" else coords[i + 1]
        y = coords[i] if axis == "h" else coords[i + 1]
        if not wps or abs(wps[-1][0] - x) > 0.01 or abs(wps[-1][1] - y) > 0.01:
            wps.append([x, y])
    return sp, ep, wps


def lane_room(lay: Layout, axis: str, coord: float, lo: float, hi: float,
              cap: float = 28.0) -> tuple[float, float]:
    """格子線(axis, coord)の区間 [lo, hi] を平行移動できる余地を(負側, 正側)で返す。

    アイコン(ラベル込み)とページ端に CLEARANCE を、コンテナ枠線に
    BORDER_CLEAR を確保できる範囲に制限する(枠線を見ないと、レーンシフトが
    回廊中心 22px から ±14px 動いて枠の 8px 隣に落ち、枠線と並走して見える)。
    cap は探索上限(既定 ±28px)。過負荷回廊の伸長後はレーン数に応じて
    広げないと、せっかく作った幅を認識できない。
    """
    BORDER_CLEAR = 12.0
    neg = pos = cap
    neg = min(neg, coord - 8.0)  # ページ端
    for ox, oy, ow, oh in lay.obstacles:
        if axis == "v":
            if oy - 4 <= hi and lo <= oy + oh + 4:
                if ox + ow <= coord:
                    neg = min(neg, coord - (ox + ow) - CLEARANCE)
                elif ox >= coord:
                    pos = min(pos, ox - coord - CLEARANCE)
        else:
            if ox - 4 <= hi and lo <= ox + ow + 4:
                if oy + oh <= coord:
                    neg = min(neg, coord - (oy + oh) - CLEARANCE)
                elif oy >= coord:
                    pos = min(pos, oy - coord - CLEARANCE)
    for cid in lay.cmap:
        bx, by, bw, bh = lay.boxes[cid]
        if axis == "v":
            if by - 4 <= hi and lo <= by + bh + 4:
                for bxx in (bx, bx + bw):
                    if bxx <= coord:
                        neg = min(neg, coord - bxx - BORDER_CLEAR)
                    else:
                        pos = min(pos, bxx - coord - BORDER_CLEAR)
        else:
            if bx - 4 <= hi and lo <= bx + bw + 4:
                for byy in (by, by + bh):
                    if byy <= coord:
                        neg = min(neg, coord - byy - BORDER_CLEAR)
                    else:
                        pos = min(pos, byy - coord - BORDER_CLEAR)
    return max(neg, 0.0), max(pos, 0.0)


def assign_lanes(lay: Layout, node_edges: list[dict],
                 routes: dict[str, NodeRoute],
                 demand_out: dict | None = None) -> dict[str, dict[int, float]]:
    """回廊を共有する中間 Run にレーン(平行オフセット)を割り当てる。

    同じ回廊線を使う Run を「接続元・接続先の位置」でソートし、左(上)から
    来るものほど左(上)のレーンに置く。順序が揃うため回廊内での交差・重走を
    防げる。オフセット幅は障害物までの余地に合わせて圧縮する。
    返り値: eid → {run index → オフセット px}。
    """
    groups: dict[tuple, list[tuple[str, int, float, float, float]]] = {}
    for e in node_edges:
        r = routes.get(e["id"])
        if not isinstance(r, NodeRoute):
            continue
        sp, ep, coords = pinned_coords(lay, e, r)
        for i in range(1, len(coords) - 1):
            axis = r.runs[i].axis
            # 隣接 Run の先の接続座標(なければ端点)を平均し、並び順のキーにする
            term = sp[0] if axis == "v" else sp[1]
            prev_c = coords[i - 2] if i - 2 >= 0 else term
            term = ep[0] if axis == "v" else ep[1]
            next_c = coords[i + 2] if i + 2 < len(coords) else term
            key = (prev_c + next_c) / 2
            lo, hi = min(coords[i - 1], coords[i + 1]), max(coords[i - 1], coords[i + 1])
            # key が同点(同一ノード発のファン等)のときのネスト順: 抜けて
            # いく方向(next_c 側)に対して深く進む Run ほど内側のレーンに
            # 置くと、同方向へ折れる線同士が編み込まずに入れ子になる
            nest = -hi if next_c > coords[i] else hi
            groups.setdefault((axis, round(coords[i], 1)), []).append(
                (e["id"], i, key, lo, hi, nest, e["src"], e["dst"]))
    offsets: dict[str, dict[int, float]] = {}
    for (axis, coord), members in groups.items():
        if len(members) <= 1:
            continue
        members.sort(key=lambda m: (m[2], m[5]))
        # 同一 src または同一 dst で区間が重ならない(隙間 12px 以上)Run
        # 同士は、1 本のレーンを共有する対称ユニットにまとめる — 上下対称
        # ファンアウト/ファンインが ±7px のレーン分離で「階段状」に崩れる
        # のを防ぐ(FB第3R 指摘3 / SEM-7-5)。無関係なエッジ同士は従来
        # どおりオフセットで分離する(同 指摘1。ユニット化を端点共有エッジに
        # 限るのは、無関係エッジの共有が dense 系でレーン順序の意味
        # (交差防止)を崩し交差を増やすため — 実測 4→6)
        units: list[list] = []
        by_end: dict[tuple[str, str], list[list]] = {}
        for m in members:
            unit = next((u for end in (("s", m[6]), ("d", m[7]))
                         for u in by_end.get(end, ())
                         if all(m[3] >= um[4] + 12.0 or um[3] >= m[4] + 12.0
                                for um in u)), None)
            if unit is None:
                unit = [m]
                units.append(unit)
            else:
                unit.append(m)
            for end in (("s", m[6]), ("d", m[7])):
                lst = by_end.setdefault(end, [])
                if not any(u is unit for u in lst):
                    lst.append(unit)
        k = len(units)
        if k <= 1:
            continue    # 全員が 1 対称ユニット = 回廊線を共有(オフセット不要)
        ext_lo = min(m[3] for m in members)
        ext_hi = max(m[4] for m in members)
        cap = max(28.0, (k - 1) * LANE_STEP / 2 + 4.0)
        neg, pos = lane_room(lay, axis, coord, ext_lo, ext_hi, cap)
        step = LANE_STEP
        if (k - 1) * step > neg + pos:
            step = (neg + pos) / (k - 1)
        if demand_out is not None and step < LANE_MIN:
            # 過負荷: E7(6px 未満の重走)を出さずに並べるのに足りない幅
            need = (k - 1) * LANE_MIN + 4.0 - (neg + pos)
            key = (axis, coord)
            demand_out[key] = max(demand_out.get(key, 0.0), need)
        offs = [(i - (k - 1) / 2) * step for i in range(k)]
        shift = 0.0
        if offs[0] + shift < -neg:
            shift = -neg - offs[0]
        if offs[-1] + shift > pos:
            shift = pos - offs[-1]
        for idx, unit in enumerate(units):
            for eid, i, _key, _lo, _hi, _nest, _src, _dst in unit:
                offsets.setdefault(eid, {})[i] = offs[idx] + shift
    return offsets


def node_geometries(lay: Layout, node_edges: list[dict],
                    routes: dict[str, NodeRoute]
                    ) -> dict[str, tuple[Point, Point, list[list[float]]]]:
    """fan-out 済みルート集合の最終ジオメトリ(レーン適用済み)を返す。"""
    lanes = assign_lanes(lay, node_edges, routes)
    geo = {}
    for e in node_edges:
        r = routes.get(e["id"])
        if isinstance(r, NodeRoute):
            geo[e["id"]] = route_geometry(lay, e, r, lanes.get(e["id"]))
    return geo


def cont_route(lay: Layout, e: dict, node_frac: float = .5) -> dict:
    """コンテナを端点に含むエッジの配線(中心同士を結ぶ L/Z 字)。

    node_frac はノード側端点の辺上の位置。他エッジと重走するときに
    0.5 からずらして呼び直す。
    """
    def clampf(f):
        return min(0.92, max(0.08, f))

    s, d = e["src"], e["dst"]
    sb, db = lay.boxes[s], lay.boxes[d]
    scx, scy = lay.center(s)
    dcx, dcy = lay.center(d)
    cmap = lay.cmap
    vertical = abs(dcy - scy) >= abs(dcx - scx)
    wps = []
    if vertical:
        down = dcy > scy
        if s in cmap and d not in cmap and down:
            # コンテナ → 下のノード: ノード上辺の位置を先に決め、真上から降ろす
            en = ("T", node_frac)
            en_x = db[0] + node_frac * db[2]
            fx = clampf((en_x - sb[0]) / sb[2])
            ex = ("B", fx)
            ex_x = sb[0] + fx * sb[2]
        else:
            if s in cmap:
                fx = clampf((dcx - sb[0]) / sb[2])
                ex = ("B" if down else "T", fx)
                ex_x = sb[0] + fx * sb[2]
            else:  # ノード: 下辺は使わない
                ex = ("T", node_frac) if not down else (("R" if dcx >= scx else "L"), .75)
                ex_x = (sb[0] + node_frac * sb[2]) if not down \
                    else (sb[0] + sb[2] if dcx >= scx else sb[0])
            if d in cmap:
                fy_ = clampf((ex_x - db[0]) / db[2])
                en = ("T" if down else "B", fy_)
                en_x = db[0] + fy_ * db[2]
            else:  # ノード: 上からは top、下からは側面
                en = ("T", node_frac) if down else (("L" if ex_x <= dcx else "R"), node_frac)
                en_x = (db[0] + node_frac * db[2]) if down \
                    else (db[0] if ex_x <= dcx else db[0] + db[2])
        if abs(ex_x - en_x) > 1:
            midy = (sb[1] + sb[3] + db[1]) / 2 if down else (db[1] + db[3] + sb[1]) / 2
            wps = [[ex_x, midy], [en_x, midy]]
    else:
        right = dcx > scx
        if s in cmap and d not in cmap:
            # コンテナ → ノード: ノード側辺の位置を先に決め、同じ高さで一直線に狙う
            en = ("L" if right else "R", node_frac)
            en_y = db[1] + node_frac * db[3]
            fy = clampf((en_y - sb[1]) / sb[3])
            ex = ("R" if right else "L", fy)
            ex_y = sb[1] + fy * sb[3]
        else:
            if s in cmap:
                fy = clampf((dcy - sb[1]) / sb[3])
                ex = ("R" if right else "L", fy)
                ex_y = sb[1] + fy * sb[3]
            else:
                ex = (("R" if right else "L"), node_frac)
                ex_y = sb[1] + node_frac * sb[3]
            if d in cmap:
                fy2 = clampf((ex_y - db[1]) / db[3])
                en = ("L" if right else "R", fy2)
                en_y = db[1] + fy2 * db[3]
            else:
                en = ("L" if right else "R", node_frac)
                en_y = db[1] + node_frac * db[3]
        if abs(ex_y - en_y) > 1:
            midx = (sb[0] + sb[2] + db[0]) / 2 if right else (db[0] + db[2] + sb[0]) / 2
            wps = [[midx, ex_y], [midx, en_y]]
    return {"exit": ex, "entry": en, "wps": wps}


def fixed_route_poly(lay: Layout, e: dict, r: dict | None) -> list[Point]:
    """手動/コンテナ端点エッジの折れ線(交差評価・登録用)。"""
    if r is None:  # 手動: spec の exit/entry/points
        bx, by, bw, bh = lay.boxes[e["src"]]
        sp = (bx + e["exit"][0] * bw, by + e["exit"][1] * bh)
        bx, by, bw, bh = lay.boxes[e["dst"]]
        ep = (bx + e["entry"][0] * bw, by + e["entry"][1] * bh)
        return [sp] + [tuple(p) for p in e.get("points", [])] + [ep]
    sp = lay.side_point(e["src"], *r["exit"])
    ep = lay.side_point(e["dst"], *r["entry"])
    return [sp] + [tuple(p) for p in r["wps"]] + [ep]


def finalize_polys(lay: Layout, node_edges: list[dict],
                   routes: dict[str, NodeRoute]) -> dict[str, list[Point]]:
    """fan-out とレーンを適用した最終折れ線を eid → poly で返す(routes は変更しない)。"""
    work = {eid: replace(r) for eid, r in routes.items()}
    fan_out(lay, node_edges, work)
    geo = node_geometries(lay, node_edges, work)
    return {eid: [sp] + [tuple(p) for p in wps] + [ep]
            for eid, (sp, ep, wps) in geo.items()}


def crossing_pairs(items: list[tuple[str | None, list[Point]]]) -> list[tuple]:
    """折れ線同士の交差ペア [(id_a, id_b), ...] を返す(交差 1 箇所につき 1 件)。

    折れ線単位のバウンディングボックスで先に棄却する。
    """
    boxes = []
    for _, p in items:
        xs = [q[0] for q in p]
        ys = [q[1] for q in p]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    pairs = []
    for i in range(len(items)):
        ia, pa = items[i]
        bx1, by1, bx2, by2 = boxes[i]
        for j in range(i + 1, len(items)):
            ob = boxes[j]
            if bx1 > ob[2] or ob[0] > bx2 or by1 > ob[3] or ob[1] > by2:
                continue
            ib, pb = items[j]
            for k in range(len(pa) - 1):
                for m in range(len(pb) - 1):
                    if seg_cross(pa[k], pa[k + 1], pb[m], pb[m + 1]):
                        pairs.append((ia, ib))
    return pairs


def poly_len(poly: list[Point]) -> float:
    return sum(math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1))


DETOUR_REPAIR_MIN = 380.0  # 迂回修復の対象とする余分な経路長(px)
# 迂回修復での交差 1 つの換算値(px)。通常配線の CROSS=400 より安いのは、
# 修復対象が「既に大回りで見た目を損ねているエッジ」に限られるため
# (実例: コンテナ間の直角交差 3 本の追加 < 図を半周する迂回の解消)
DETOUR_TRADE = 150.0


def is_detour(plen: float, manh: float) -> bool:
    """直線距離 manh に対して plen が「大回り」といえるか(HINT/最適化の共通閾値)。

    比率条件だけだと長いエッジの絶対量の大きい迂回(例: 直線 800px に対し
    +700px)がすり抜けるため、絶対量単独の条件を OR で持つ。"""
    return manh > 1 and ((plen > 2.2 * manh and plen - manh > 320)
                         or plen - manh > 600)


def _rect_hits(a: Rect, b: Rect) -> bool:
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
            and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])


CHECK_DELTA = os.environ.get("AWSDIAG_CHECK") == "1"  # 差分スコアの検算(回帰用)
_NO_ASTAR = os.environ.get("AWSDIAG_NO_ASTAR") == "1"      # 切り分け用(通常は A*)


def cross_between(pa: list[Point], pb: list[Point]) -> int:
    """2 本の折れ線間の交差数。"""
    n = 0
    for k in range(len(pa) - 1):
        a, b = pa[k], pa[k + 1]
        for m in range(len(pb) - 1):
            if seg_cross(a, b, pb[m], pb[m + 1]):
                n += 1
    return n


def container_borders(lay: Layout) -> tuple[list, list]:
    """コンテナ境界線(水平線・垂直線)を返す: ([(y,x1,x2)..], [(x,y1,y2)..])。"""
    hb, vb = [], []
    for cid in lay.cmap:
        x, y, w, h = lay.boxes[cid]
        hb += [(y, x, x + w), (y + h, x, x + w)]
        vb += [(x, y, y + h), (x + w, y, y + h)]
    return hb, vb


def title_pen(lay: Layout, a: Point, b: Point) -> float:
    """線分がコンテナタイトル文字帯を横切るときのペナルティ(スタブ用)。"""
    lo_x, hi_x = min(a[0], b[0]), max(a[0], b[0])
    lo_y, hi_y = min(a[1], b[1]), max(a[1], b[1])
    for x, y, w, h in lay.title_bands:
        if lo_x < x + w and x < hi_x and lo_y < y + h and y < hi_y:
            return 1800.0
    return 0.0


def icon_degree_map(lay: Layout, edges) -> dict[str, int]:
    """アイコンノード端点の次数(交差目安のハブ補正と配置原則6 HINT 用)。

    コンテナ端点と entity・フロー図形の箱は数えない。
    """
    deg: dict[str, int] = {}
    for e in edges:
        for t in (e["src"], e["dst"]):
            if t in lay.cell and t not in lay.box_nodes:
                deg[t] = deg.get(t, 0) + 1
    return deg


def icon_degrees(lay: Layout, edges) -> list[int]:
    return sorted(icon_degree_map(lay, edges).values(), reverse=True)


# R5-C: 近傍サブレーン修復の定数。回廊格子だけでは、終端手前の登りが他エッジの
# 縦レーンと重走/交差する図で「横→短い段差→横」の二段ステップが最適解になる
# (理想の一本登りが探索空間に無い)。回廊±SUBLANE_OFF のサブレーンを足した
# 拡張格子を、二段ステップ検出時の該当エッジ引き直しに限って使う — 全エッジを
# 拡張格子で探索すると dense 実測 2.4 倍(格子 27x17→53x33)で性能ゲート超過
SUBLANE_OFF = 18.0   # 回廊からのサブレーン距離(外部実験の実証値。±14〜20 が有効域)
_STEP_MAX = 40.0     # 「短い段差」とみなす中間区間の上限 px
_STEP_NEAR = 120.0   # 段差から終端までの距離上限 px


def _two_step_ends(poly: list[Point]) -> int:
    """終端 3 区間が「直進→短い段差→終端直進」を成す端の数(0〜2)。

    二段ステップ = 交差回避のスレッディングで縦(横)の登りが 2 本に割れ、
    終端手前に小段差が残った形。中間の短い区間と同軸の区間が他にもあること
    (登りが割れた証拠)を条件にし、端点差を 1 回で吸収する正常な Z 字
    (3 区間)は対象にしない。
    """
    segs: list[tuple[str, float]] = []
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        dx, dy = abs(x1 - x2), abs(y1 - y2)
        if dx < 0.5 and dy < 0.5:
            continue
        if dx >= 0.5 and dy >= 0.5:
            return 0            # 斜め区間を含む折れ線は対象外(安全側)
        segs.append(("h" if dx > dy else "v", dx + dy))
    if len(segs) < 4:
        return 0
    axes = [a for a, _ in segs]
    n = 0
    for at_dst in (True, False):
        (a1, l1), (a2, l2), (a3, l3) = segs[-3:] if at_dst else segs[:3]
        term = l3 if at_dst else l1
        rest = axes[:-3] if at_dst else axes[3:]
        if (a1 == a3 and a2 != a1 and l2 <= _STEP_MAX
                and term <= _STEP_NEAR and a2 in rest):
            n += 1
    return n


def _with_sublanes(vals: list[float], corr: list[int]) -> list[float]:
    """格子線 vals に回廊±SUBLANE_OFF のサブレーンを加えた座標列を返す。

    既存線の座標は動かさない(既存線と 6px 未満に近づくサブレーンは追加
    しない — dedupe 方式で既存線を吸収するとスタブ格子点の座標がずれる)。
    """
    out = list(vals)
    for i in corr:
        for v in (vals[i] - SUBLANE_OFF, vals[i] + SUBLANE_OFF):
            if all(abs(v - u) > 6.0 for u in out):
                out.append(v)
    out.sort()
    return out


def _mark_share(router: Router, poly: list[Point]) -> None:
    """確定済み折れ線の重走コスト(SHARE)を router の帳簿に写す。

    register_poly は直進通過(CROSS)しか写さないため、サブレーン修復の
    引き直しが既存ルートと同一レーンを無償で共有し重走(E7 の種)を
    作るのを防ぐ。
    """
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        if abs(y1 - y2) <= 1 and abs(x1 - x2) > 1:        # 水平区間
            lo, hi = min(x1, x2), max(x1, x2)
            for j, y in enumerate(router.ys):
                if abs(y - y1) >= 3:
                    continue
                for i in range(len(router.xs) - 1):
                    if router.xs[i] >= lo - 1 and router.xs[i + 1] <= hi + 1:
                        key = ("h", i, j)
                        router.share[key] = router.share.get(key, 0) + 1
        elif abs(x1 - x2) <= 1 and abs(y1 - y2) > 1:      # 垂直区間
            lo, hi = min(y1, y2), max(y1, y2)
            for i, x in enumerate(router.xs):
                if abs(x - x1) >= 3:
                    continue
                for j in range(len(router.ys) - 1):
                    if router.ys[j] >= lo - 1 and router.ys[j + 1] <= hi + 1:
                        key = ("v", i, j)
                        router.share[key] = router.share.get(key, 0) + 1


def _tight_coruns(poly: list[Point], others: list[list[Point]]) -> int:
    """poly が他の折れ線と 6〜7px の間隔で 12px 以上並走する区間数。

    サブレーン(回廊±18px)は他エッジのレーンオフセット(±14px 等)と
    数 px 差になり得る。6px 未満は E7 監査(separate_corun_runs)が
    分離してくれる(fc109 実測: 4px → 14px)ので任せ、どの機構も救わない
    「E7 未満・レーン分離検査(≥7px)違反」のデッドゾーンだけを
    採用ゲートで弾く。
    """
    n = 0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        horiz = abs(y1 - y2) <= 1 and abs(x1 - x2) > 1
        vert = abs(x1 - x2) <= 1 and abs(y1 - y2) > 1
        if not (horiz or vert):
            continue
        lo, hi = (sorted((x1, x2)) if horiz else sorted((y1, y2)))
        line = y1 if horiz else x1
        for op in others:
            for (ox1, oy1), (ox2, oy2) in zip(op, op[1:]):
                if horiz and abs(oy1 - oy2) <= 1 and abs(ox1 - ox2) > 1:
                    d, s1, s2 = abs(oy1 - line), *sorted((ox1, ox2))
                elif vert and abs(ox1 - ox2) <= 1 and abs(oy1 - oy2) > 1:
                    d, s1, s2 = abs(ox1 - line), *sorted((oy1, oy2))
                else:
                    continue
                if 6.0 <= d < 7.0 and min(hi, s2) - max(lo, s1) >= 12.0:
                    n += 1
    return n


def _sublane_context(lay: Layout) -> tuple[Layout, Router]:
    """サブレーン入り拡張格子の Layout(浅いコピー)と Router を作る。"""
    fine = replace(lay)
    fine.xs = _with_sublanes(lay.xs, lay.xi_corr)
    fine.ys = _with_sublanes(lay.ys, lay.yi_corr)
    ix = {v: i for i, v in enumerate(fine.xs)}   # 既存線の座標は保存されている
    iy = {v: j for j, v in enumerate(fine.ys)}
    fine.xi_corr = [ix[lay.xs[i]] for i in lay.xi_corr]
    fine.xi_band = [ix[lay.xs[i]] for i in lay.xi_band]
    fine.yi_corr = [iy[lay.ys[j]] for j in lay.yi_corr]
    fine.yi_band = [iy[lay.ys[j]] for j in lay.yi_band]
    router = Router(fine.xs, fine.ys, lay.obstacles,
                    borders=[lay.boxes[cid] for cid in lay.cmap],
                    title_bands=lay.title_bands)
    return fine, router


def _seed_geometry_ok(lay: Layout, e: dict, route: NodeRoute) -> bool:
    """R5-D: キャッシュ経路が現在の配置でまだ幾何的に成立しているかを検査する。

    見るのはハード制約のみ — 直交性・LCA 境界(内部通信が境界外を走ると
    誤読される)・障害物(アイコン+ラベル箱)・他コンテナ通過(transit)。
    交差・題字帯・anti 端点・折れ・長さといった品質はここでは判定しない
    (route_all の慣性ゲートがタブ全体のスコアで新旧比較する)。
    """
    src, dst = e["src"], e["dst"]
    if src not in lay.boxes or dst not in lay.boxes:
        return False
    # R7-15/16: diamond の頂点規約もハード制約(旧世代キャッシュの
    # 辺上 frac・規約違反の辺は無効として引き直させる)
    dban = lay.diamond_bans.get(e["id"], frozenset())
    if (src, route.exit[0]) in dban or (dst, route.entry[0]) in dban:
        return False
    if (src in lay.diamond and abs(route.exit[1] - 0.5) > 1e-6) or \
            (dst in lay.diamond and abs(route.entry[1] - 0.5) > 1e-6):
        return False
    sp, ep, wps = route_geometry(lay, e, route)
    poly = [sp] + [tuple(p) for p in wps] + [ep]
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        if abs(x1 - x2) > 0.01 and abs(y1 - y2) > 0.01:
            return False    # 斜め区間 = Run 列と端点辺の不整合(壊れたキャッシュ)
    lca = lca_container(lay, src, dst)
    if lca is not None:
        # route_edge と同じ規律: トップレベル境界はリングなし、入れ子は
        # すぐ外の回廊(リング 30px)まで正常な経路
        ring = 0.0 if lay.parents.get(lca) is None else 30.0
        bx, by, bw, bh = lay.boxes[lca]
        for x, y in poly:
            if not (bx - ring - 0.5 <= x <= bx + bw + ring + 0.5
                    and by - ring - 0.5 <= y <= by + bh + ring + 0.5):
                return False
    sb, db = lay.boxes[src], lay.boxes[dst]

    def touches(a: Rect, b: Rect) -> bool:
        return (a[0] < b[0] + b[2] + 1 and b[0] - 1 < a[0] + a[2]
                and a[1] < b[1] + b[3] + 1 and b[1] - 1 < a[1] + a[3])

    # 自端点の箱に接する障害物はスタブが必然的に接するため除外
    # (_direct_axis_route と同じ扱い)。マージンは CLEARANCE-1: 元経路は
    # CLEARANCE ちょうどの距離を通り得るため、数値誤差ぶんだけ緩める
    margin = CLEARANCE - 1.0
    obs = [ob for ob in lay.obstacles
           if not (touches(ob, sb) or touches(ob, db))]
    hard = [(ox - margin, oy - margin, ox + ow + margin, oy + oh + margin)
            for ox, oy, ow, oh in obs]
    hard += [(ax + 2, ay + 2, ax + aw - 2, ay + ah - 2)
             for ax, ay, aw, ah in transit_avoid(lay, src, dst)]
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        lx, hx = min(x1, x2), max(x1, x2)
        ly, hy = min(y1, y2), max(y1, y2)
        for rx1, ry1, rx2, ry2 in hard:
            if lx < rx2 and rx1 < hx and ly < ry2 and ry1 < hy:
                return False
    return True


# SEM-6: 対ファンの鏡像対称化で使う辺の写像。
_MIRROR_V = {"L": "L", "R": "R", "T": "B", "B": "T"}   # 上下対 = y 反転
_MIRROR_H = {"T": "T", "B": "B", "L": "R", "R": "L"}   # 左右対 = x 反転


def _mirror_runs(runs: list[Run], flip_axis: str, mid: float) -> list[Run]:
    """Run 列を src 中心線で鏡像する(flip_axis="h" なら y 座標を反転)。"""
    return [Run(r.axis, 2 * mid - r.coord if r.axis == flip_axis else r.coord)
            for r in runs]


def _mirror_runs_clear(lay: Layout, e: dict, route: NodeRoute) -> bool:
    """鏡像候補の中間 Run がコンテナ境界線に並走(HUG/W13 相当)しないか。

    _seed_geometry_ok はハード障害物・境界しか見ないため、鏡像で新たに
    作るレーンが境界貼り付きを生まないよう Router._hug_segments と同じ
    距離基準(11px 未満・境界の両端 10px は除外)で検査する。端の Run は
    端点に固定され従来経路と同じ帯を走るので対象外。
    """
    sp, ep, wps = route_geometry(lay, e, route)
    poly = [sp] + [tuple(p) for p in wps] + [ep]
    for (x1, y1), (x2, y2) in list(zip(poly, poly[1:]))[1:-1]:
        horiz = abs(y1 - y2) <= 0.01
        lo, hi = (min(x1, x2), max(x1, x2)) if horiz \
            else (min(y1, y2), max(y1, y2))
        coord = y1 if horiz else x1
        for cid in lay.cmap:
            bx, by, bw, bh = lay.boxes[cid]
            if horiz:
                if any(abs(coord - b) < 11.0 for b in (by, by + bh)) \
                        and lo < bx + bw - 10 and bx + 10 < hi:
                    return False
            else:
                if any(abs(coord - b) < 11.0 for b in (bx, bx + bw)) \
                        and lo < by + bh - 10 and by + 10 < hi:
                    return False
    return True


def _fan_pairs(lay: Layout, node_edges: list[dict],
               routes: dict[str, NodeRoute], shared: str
               ) -> list[tuple[bool, float, tuple, tuple]]:
    """鏡像対称化の対象になる対ファンを列挙する(SEM-6/SEM-7-5 共通)。

    shared="src" は同一 src・同一出射辺のファンアウト、"dst" は同一 dst・
    同一出射辺文字のファンイン。共有ノードの中心線を挟んで反対側の端点が
    1 本ずつのものだけを対とする。返り値: (vert, mid, (ea, ra), (eb, rb))。
    vert=True は上下対(y 反転)、mid は鏡像軸の座標。ea/ra が上(左)。
    """
    other = "dst" if shared == "src" else "src"
    groups: dict[tuple[str, str], list[tuple[dict, NodeRoute]]] = {}
    for e in node_edges:
        r = routes.get(e["id"])
        if not isinstance(r, NodeRoute) or e["src"] == e["dst"]:
            continue
        if e[shared] in lay.cmap or e["src"] in lay.diamond \
                or e["dst"] in lay.diamond:
            continue
        groups.setdefault((e[shared], r.exit[0]), []).append((e, r))
    out: list[tuple[bool, float, tuple, tuple]] = []
    for (hub, side), members in sorted(groups.items()):
        vert = side in "LR"      # 横辺の出射対 → 上下の鏡像(y 反転)
        mid = lay.center(hub)[1] if vert else lay.center(hub)[0]
        lo_m = [m for m in members
                if lay.center(m[0][other])[1 if vert else 0] < mid - 4.0]
        hi_m = [m for m in members
                if lay.center(m[0][other])[1 if vert else 0] > mid + 4.0]
        if len(lo_m) != 1 or len(hi_m) != 1:
            continue             # 対にならないファンは従来動作
        out.append((vert, mid, lo_m[0], hi_m[0]))
    return out


def _mirror_fan_candidates(lay: Layout, node_edges: list[dict],
                           routes: dict[str, NodeRoute],
                           shared: str = "src"
                           ) -> list[list[tuple[dict, NodeRoute]]]:
    """SEM-6/SEM-7-5: 対ファンの「折れ構造を鏡像に揃える」差し替え候補を列挙する。

    shared="src"(SEM-6)は同一 src・同一出射辺から上下(左右)へ分かれる
    ファンアウト対、shared="dst"(SEM-7-5)は同一 dst へ上下(左右)から
    集まるファンイン対(src 側の出射辺が同一文字)を対象にする。
    v1.6.0 の対称ユニット(assign_lanes)と _fan_slots は端点とレーン
    共有までを対称化するが、探索の SHARE/CROSS ペナルティが後着の対枝を
    別回廊の階段状経路(折れ +2)や別の入射辺(構成図03 の NAT→ECR 実測:
    上枝 = ECR 上辺・下枝 = ECR 左辺)へ追いやるのは防げない。ここでは
    Run 数が少ない枝を鋳型に、共有ノード中心線で鏡像した Run 列をもう一方の
    候補として返す。ファンインで入射辺そのものが不整合の対は、長い枝を
    鋳型にする候補(折れ増を許す整合化。差 2 Run まで)も併せて返す。
    採用可否(ハード幾何・境界並走・スコア非悪化)は route_all が判定する。
    対にならないファン(片側 0 本・複数本)・ひし形端点・既に鏡像の対は
    対象外(過剰一般化しない)。返り値: 対ごとの候補リスト(優先順)。

    ファンインを src 側出射辺の同一文字で群化する理由: 共有ノード側の辺
    (entry)は当の不整合量なので鍵に使えない。軸鏡像で自分自身に写る辺
    (縦対なら L/R、横対なら T/B)だけが鏡像対の出射辺になり得る。
    """
    out: list[list[tuple[dict, NodeRoute]]] = []
    for vert, mid, (ea, ra), (eb, rb) in _fan_pairs(lay, node_edges,
                                                    routes, shared):
        flip = "h" if vert else "v"
        mside = _MIRROR_V if vert else _MIRROR_H

        def cand(tr: NodeRoute, fe: dict, fr: NodeRoute) -> NodeRoute | None:
            runs = _mirror_runs(tr.runs, flip, mid)
            en = mside[tr.entry[0]]
            if en == "B" and fe["dst"] in lay.cell \
                    and fe["dst"] not in lay.box_nodes:
                return None      # アイコン下辺はキャプションがあり入射不可
                                 # (node_stubs と同じ規律)— この対は従来経路
            if fr.entry[0] == en:
                entry = fr.entry     # 既存の入射端点(fan スロット互換)を維持
            else:
                ef = tr.entry[1]
                entry = (en, 1.0 - ef if (en in "LR") == vert else ef)
            return NodeRoute(exit=fr.exit, entry=entry, runs=runs,
                             direct=len(runs) == 1)

        # 入射辺の鏡像整合(ファンインの群では共有 dst 上の同一辺 or 対面辺)
        aligned = mside[ra.entry[0]] == rb.entry[0]
        if len(ra.runs) == len(rb.runs):
            mir = _mirror_runs(ra.runs, flip, mid)
            if (shared == "src" or aligned) \
                    and all(abs(m.coord - r.coord) <= 2.0
                            for m, r in list(zip(mir, rb.runs))[1:-1]):
                continue         # 既に鏡像 — 触らない
            alts = [(eb, cand(ra, eb, rb)), (ea, cand(rb, ea, ra))]
        elif len(ra.runs) < len(rb.runs):
            alts = [(eb, cand(ra, eb, rb))]
            if shared == "dst" and not aligned \
                    and len(rb.runs) - len(ra.runs) <= 2:
                alts.append((ea, cand(rb, ea, ra)))
        else:
            alts = [(ea, cand(rb, ea, ra))]
            if shared == "dst" and not aligned \
                    and len(ra.runs) - len(rb.runs) <= 2:
                alts.append((eb, cand(ra, eb, rb)))
        alts = [(e, c) for e, c in alts if c is not None]
        if alts:
            out.append(alts)
    return out


def route_all(router: Router, lay: Layout, node_edges: list[dict],
              fixed_polys: list[list[Point]], kinds: dict | None = None,
              draft: bool = False,
              seed_routes: dict[str, NodeRoute] | None = None
              ) -> dict[str, NodeRoute]:
    """複数の配線順序を試し、最終形(fan-out・レーン適用後)の交差が最少の割り当てを返す。

    各順序で配線 → 交差が残れば競合エッジだけリップアップ再配線 → さらに残れば
    交差相手を高コスト化した狙い撃ち再配線。交差 0 に達した時点で打ち切る。
    draft=True は探索ループ用の高速モード(1 順序・再配線なし)。
    seed_routes は前回ビルドの経路(R5-D 経路の慣性)。幾何的に有効で、かつ
    タブ全体のスコアが悪化しない限り、新規経路より優先して維持される。
    """
    def manh(e):
        (sx, sy), (dx_, dy_) = lay.center(e["src"]), lay.center(e["dst"])
        return (abs(sx - dx_) + abs(sy - dy_)) / (CELLW + GAPX)

    fixed_items = [(f"__fixed{i}", p) for i, p in enumerate(fixed_polys)]
    fixed_len = sum(poly_len(p) for p in fixed_polys)

    def total_crossings(polys: dict[str, list[Point]]) -> int:
        return len(crossing_pairs(list(polys.items()) + fixed_items))

    def count_involving(polys: dict[str, list[Point]], changed: list[str]) -> int:
        """changed の折れ線が絡む交差数(changed 同士は 1 回だけ数える)。"""
        pos = {cid: i for i, cid in enumerate(changed)}
        allp = dict(fixed_items)
        allp.update(polys)
        boxes = {}
        for k, p in allp.items():
            xs = [q[0] for q in p]
            ys = [q[1] for q in p]
            boxes[k] = (min(xs), min(ys), max(xs), max(ys))
        n = 0
        for idx, cid in enumerate(changed):
            pa = allp[cid]
            ax1, ay1, ax2, ay2 = boxes[cid]
            for k, pb in allp.items():
                if k == cid or pos.get(k, idx) < idx:
                    continue
                b = boxes[k]
                if ax1 > b[2] or b[0] > ax2 or ay1 > b[3] or b[1] > ay2:
                    continue
                n += cross_between(pa, pb)
        return n

    def title_hits(polys) -> int:
        """折れ線がコンテナ題字帯を横切るセグメント数(W5 相当)。

        anti 修復・引き直しが「回り込みは消えたが題字の上を走る」解へ
        流れないよう、交差数の次・anti 端点より前の採点キーにする
        (題字貫通は文字が潰れる分、回り込みより実害が大きい)。
        """
        n = 0
        for p in polys.values():
            for (x1, y1), (x2, y2) in zip(p, p[1:]):
                for bx, by, bw, bh in lay.title_bands:
                    if (min(x1, x2) < bx + bw and bx < max(x1, x2)
                            and min(y1, y2) < by + bh and by < max(y1, y2)):
                        n += 1
        return n

    def anti_ends(routes) -> int:
        """行き先(出発点)と逆を向いた端点の数(視認 NG の「回り込み」)。

        交差数が辞書式に支配する採点では、探索コスト(_dir_penalty)だけ
        では交差最適解に埋め込まれた anti 端点を除去できない(ANTI_ALIGN を
        200 まで上げると dense の交差が 4→8 に退行する実測)。第 2 キーに
        して「交差が同数なら行き先を向いた辺の解を採る」(実使用FB第4R
        指摘A。優先原則: 交差 > 接続して見える > 折れ点最少)。
        """
        n = 0
        for eid, r in routes.items():
            e = by_id.get(eid)
            if e is None:
                continue
            (sx, sy), (dx_, dy_) = lay.center(e["src"]), lay.center(e["dst"])
            vx, vy = dx_ - sx, dy_ - sy
            d = math.hypot(vx, vy)
            if d < 1e-9:
                continue
            for (side, _f), flip in ((r.exit, 1.0), (r.entry, -1.0)):
                nx_, ny_ = _SIDE_NORMAL[side]
                if (nx_ * vx + ny_ * vy) * flip / d < -0.3:
                    n += 1
        return n

    def fan_fixes(routes) -> tuple[int, list[tuple[dict, frozenset]]]:
        """同一 src ノードから片側方向(全 dst が左または右)へ出るエッジ群で、
        出射辺が dst 側を向く辺と違う・コンテナ宛の入射辺が src 側を向く辺と
        違うものを数え、揃えるための ban 集合を列挙する(外部FB A-1)。
        対のエッジは同じ流儀で引く — 個々は正しい L 字でも、出射辺・入射辺が
        対で不揃いだと並べたときに不統一に見えるため。"""
        groups: dict[str, list] = {}
        for eid, r in routes.items():
            e = by_id.get(eid)
            if e is None or e["src"] in lay.cmap:
                continue
            groups.setdefault(e["src"], []).append((e, r))
        n, fixes = 0, []
        for src, members in groups.items():
            if len(members) < 2:
                continue
            sx = lay.center(src)[0]
            vxs = [lay.center(e["dst"])[0] - sx for e, _ in members]
            if all(v > 1e-9 for v in vxs):
                ex_side, en_side = "R", "L"
            elif all(v < -1e-9 for v in vxs):
                ex_side, en_side = "L", "R"
            else:
                continue    # 上下混在・同座標は対象外(縦ファンは辺の制約が別)
            # コンテナ宛の入射は 2 つの正統な流儀を許す: h=src 側を向く横辺 /
            # v=src の行を向く上下の対面辺(鏡映対称ファン)。群内でどちらかに
            # 統一されていればよく、混在だけを不一致と数える(多数派に揃える)
            sy = lay.center(src)[1]
            infos, n_h, n_v = [], 0, 0
            for e, r in members:
                if e["dst"] not in lay.cmap:
                    infos.append((e, r, None, None))
                    continue
                vface = "T" if lay.center(e["dst"])[1] > sy else "B"
                oks = (r.entry[0] == en_side, r.entry[0] == vface)
                n_h += oks[0]
                n_v += oks[1]
                infos.append((e, r, vface, oks))
            cat_v = n_v >= n_h
            for e, r, vface, oks in infos:
                bad_exit = r.exit[0] != ex_side
                bad_entry = oks is not None and not (oks[1] if cat_v else oks[0])
                if not (bad_exit or bad_entry):
                    continue
                n += int(bad_exit) + int(bad_entry)
                ban = {(e["src"], s) for s in "LRTB" if s != ex_side}
                if oks is not None:
                    want = vface if cat_v else en_side
                    ban |= {(e["dst"], s) for s in "LRTB" if s != want}
                fixes.append((e, frozenset(ban)))
        return n, fixes

    def full_score(routes, polys) -> tuple:
        return (total_crossings(polys), title_hits(polys), anti_ends(routes),
                fan_fixes(routes)[0],
                sum(len(r.runs) for r in routes.values()),
                sum(poly_len(p) for p in polys.values()) + fixed_len)

    orders = [
        list(node_edges),
        sorted(node_edges, key=manh),
        sorted(node_edges, key=lambda e: (kind_base(e, kinds) != "main", manh(e))),
    ]
    if draft:
        orders = orders[1:2]
    by_id = {e["id"]: e for e in node_edges}
    # R7-15/A3: decision の頂点規約+フロー箱の上辺入射規約。
    # route_edge が全ての(再)配線でマージする
    lay.diamond_bans = entry_conventions(lay, node_edges, kinds)

    def run_order(order: list[dict], mono: bool) -> tuple:
        """1 つの配線順序を最後まで実行して (score, routes, recs) を返す。

        mono=False は従来どおりの盲目リップアップ(引き直しを無条件採用)、
        mono=True は最終形スコアが改善したときだけ採用する単調版。
        どちらが勝つかはスペック依存なので呼び出し側で両方式を比較する。
        """
        router.reset()
        for poly in fixed_polys:
            router.register_poly(poly)
        routes: dict[str, NodeRoute] = {}
        recs: dict[str, tuple] = {}   # eid → (commit レコード, 格子経路)
        for e in order:
            found = route_edge(router, lay, e)
            if found is None:
                continue
            routes[e["id"]], (path, stub_marks) = found
            recs[e["id"]] = (router.commit(path, stub_marks), path)
        polys = finalize_polys(lay, node_edges, routes)
        score = full_score(routes, polys)

        def try_replace(e, boost: list | None = None, weight: int = 3,
                        ban: frozenset = frozenset()) -> bool:
            """エッジを引き直し、最終形スコアが改善したら採用する。"""
            nonlocal score, polys
            eid = e["id"]
            old_route, (old_rec, old_path) = routes[eid], recs[eid]
            router.uncommit(old_rec)
            undo = [router.register_poly(p, weight) for p in (boost or [])]
            found = route_edge(router, lay, e, ban)
            for u in undo:
                router.unregister(u)
            if found is None:
                recs[eid] = (router.recommit(old_rec), old_path)
                return False
            routes[eid], (npath, marks) = found
            recs[eid] = (router.commit(npath, marks), npath)
            new_polys = finalize_polys(lay, node_edges, routes)
            changed = [k for k in new_polys if new_polys[k] != polys.get(k)]
            new_total = (score[0] - count_involving(polys, changed)
                         + count_involving(new_polys, changed))
            if CHECK_DELTA:
                assert new_total == total_crossings(new_polys), \
                    f"差分交差数の不一致: edge {eid}"
            new_score = (new_total, title_hits(new_polys), anti_ends(routes),
                         fan_fixes(routes)[0],
                         sum(len(r.runs) for r in routes.values()),
                         sum(poly_len(p) for p in new_polys.values()) + fixed_len)
            if new_score < score:
                score, polys = new_score, new_polys
                return True
            router.uncommit(recs[eid][0])
            routes[eid] = old_route
            recs[eid] = (router.recommit(old_rec), old_path)
            return False

        # リップアップ再配線
        if score[0] > 0 and not draft:
            if mono:
                for _rip in range(4):
                    if not any(try_replace(e) for e in order if e["id"] in recs):
                        break
                    if score[0] == 0:
                        break
            else:
                for e in order:
                    eid = e["id"]
                    if eid not in recs:
                        continue
                    rec, path = recs[eid]
                    if not router.contested(path, rec):
                        continue  # 未競合は引き直しても変わらない
                    router.uncommit(rec)
                    found = route_edge(router, lay, e)
                    if found is None:
                        recs[eid] = (router.recommit(rec), path)
                        continue
                    routes[eid], (npath, marks) = found
                    recs[eid] = (router.commit(npath, marks), npath)
                polys = finalize_polys(lay, node_edges, routes)
                score = full_score(routes, polys)

        # 狙い撃ち再配線(交差相手を高コスト化して引き直し、改善のみ採用)
        rounds = 0 if draft else 3
        for _round in range(rounds):
            if score[0] == 0:
                break
            items = list(polys.items()) + fixed_items
            poly_by_id = dict(items)
            hot: dict[str, list[list[Point]]] = {}
            for ia, ib in crossing_pairs(items):
                for me, other in ((ia, ib), (ib, ia)):
                    if me in recs:
                        hot.setdefault(me, []).append(poly_by_id[other])
            improved = False
            for eid in sorted(hot, key=lambda k: -len(hot[k])):
                if try_replace(by_id[eid], hot[eid], weight=3 * len(hot[eid])):
                    improved = True
            if not improved:
                break

        # anti 端点の修復: 行き先(出発点)と逆を向いた辺を禁止して引き直し、
        # 最終形スコア(交差 → 題字貫通 → anti 端点 → 折れ点 → 長さ)が改善したときだけ
        # 採用する。探索コストの ANTI_ALIGN だけでは、交差最適解に埋まった
        # 回り込み端点(dense の実測 fc=-0.99 等)を除去できないための追い撃ち。
        # 交差はスコア第 1 キーのままなので、交差を増やす修復は棄却される
        if not draft and score[2] > 0:
            for e in order:
                eid = e["id"]
                r = routes.get(eid)
                if eid not in recs or not isinstance(r, NodeRoute):
                    continue
                (sx_, sy_), (tx_, ty_) = lay.center(e["src"]), lay.center(e["dst"])
                vx_, vy_ = tx_ - sx_, ty_ - sy_
                d_ = math.hypot(vx_, vy_)
                if d_ < 1e-9:
                    continue
                ban = set()
                for (side, _f), flip, term in ((r.exit, 1.0, e["src"]),
                                               (r.entry, -1.0, e["dst"])):
                    nx_, ny_ = _SIDE_NORMAL[side]
                    if (nx_ * vx_ + ny_ * vy_) * flip / d_ < -0.3:
                        ban.add((term, side))
                if ban:
                    try_replace(e, ban=frozenset(ban))
                if score[2] == 0:
                    break

        # ファンアウト辺の一貫性修復(外部FB A-1): 同一 src から片側方向へ出る
        # 対エッジ群の出射辺(コンテナ宛は入射辺も)を揃えて引き直す。fan 不一致は
        # スコア第 4 キーなので、交差・題字・anti 端点を悪化させる修復は
        # try_replace が棄却する(折れ点・長さの増加は対の一貫性を優先して許容する)
        if not draft and score[3] > 0:
            for e, ban in fan_fixes(routes)[1]:
                if e["id"] in recs:
                    try_replace(e, ban=ban)
                if score[3] == 0:
                    break

        # 磨きパス(外部FB A-2): 折れ点 3 つ以上のエッジを、全エッジ確定後の
        # 文脈でもう一度引き直す。初期の配線順の巡り合わせで残る「不要な折れ・
        # 出射直後のマイクロジョグ」は、混雑が確定した最終状態でなら素直な経路が
        # 見つかることが多い(リップアップは交差に関与したエッジしか引き直さない
        # ため、交差ゼロの折れ多エッジはここでしか救えない)。採用はスコアゲート付き
        if not draft:
            bendy = [(len(pl), by_id[eid_]) for eid_, pl in polys.items()
                     if eid_ in recs and eid_ in by_id and len(pl) >= 5]
            for _, be in sorted(bendy, key=lambda t: -t[0]):
                try_replace(be)

        # R7-16: diamond 同一辺の端点重なりを辺の専有で解消(スコアゲート
        # なしの強制パス — ひし形は fan 系の辺上分散が使えないため、頂点の
        # 重なり解消は交差の増加より優先する)
        if not draft and _dedupe_diamond_sides(router, lay, node_edges,
                                               routes, recs, kinds):
            polys = finalize_polys(lay, node_edges, routes)
            score = full_score(routes, polys)
        return score, routes, recs

    best: tuple | None = None
    budget = max(2, round(len(lay.cell) / 10))
    for order in orders:
        res = run_order(order, mono=False)
        if res[0][0] > budget and not draft:
            alt = run_order(order, mono=True)   # 方式の優劣はスペック依存
            if alt[0] < res[0]:
                res = alt
        if best is None or res[0] < best[0]:
            best = res
        if best[0][0] <= budget:  # バリデータの目安以内なら残りの順序は不要
            break
    assert best is not None
    score, routes, recs = best

    # 迂回修復: 交差・共有ペナルティが招いた極端な大回りを、短縮量と交差の
    # 増分を天秤にかけて引き直す(交差 1 つ ≈ DETOUR_TRADE px と換算)。
    # 通常探索のスコアは交差数が辞書式に支配するため、ここでしか救えない。
    if not draft and routes:
        router.reset()
        for poly in fixed_polys:
            router.register_poly(poly)
        for eid, (rec, path) in list(recs.items()):
            recs[eid] = (router.recommit(rec), path)
        polys = finalize_polys(lay, node_edges, routes)
        crossings = total_crossings(polys)
        # ゲートはバリデータ I1 と同じハブ補正付きの目安(早期終了は従来式)
        # ゲートは密度補正なしの厳しい式のまま(緩めると探索が早く諦める)
        budget, _, _, _ = crossing_budget(len(lay.cell),
                                          icon_degrees(lay, by_id.values()))

        def extra(eid: str, ps: dict[str, list[Point]]) -> float:
            e = by_id[eid]
            (sx, sy), (dx_, dy_) = lay.center(e["src"]), lay.center(e["dst"])
            return poly_len(ps[eid]) - (abs(sx - dx_) + abs(sy - dy_))

        for eid in sorted(routes, key=lambda k: -extra(k, polys)):
            old_extra = extra(eid, polys)
            if old_extra <= DETOUR_REPAIR_MIN:
                continue  # 先行修復でレーンが動き境界を割ることがある
            old_route, (old_rec, old_path) = routes[eid], recs[eid]
            router.uncommit(old_rec)
            router.SHARE, router.CROSS = Router.RELAX_SHARE, Router.RELAX_CROSS
            try:
                found = route_edge(router, lay, by_id[eid])
            finally:
                del router.SHARE, router.CROSS   # 上書きを外してクラス既定へ
            if found is None:
                recs[eid] = (router.recommit(old_rec), old_path)
                continue
            routes[eid], (npath, marks) = found
            recs[eid] = (router.commit(npath, marks), npath)
            new_polys = finalize_polys(lay, node_edges, routes)
            changed = [k for k in new_polys if new_polys[k] != polys.get(k)]
            new_crossings = (crossings - count_involving(polys, changed)
                            + count_involving(new_polys, changed))
            if CHECK_DELTA:
                assert new_crossings == total_crossings(new_polys), \
                    f"迂回修復の差分交差数の不一致: edge {eid}"
            saved = old_extra - extra(eid, new_polys)
            added = max(0, new_crossings - crossings)
            # 交差の目安(バリデータと同式)を守れている図では、目安を壊してまで
            # 短縮しない。既に目安超過の図では短さ・素直さを優先する
            gate_ok = new_crossings <= budget or \
                (crossings > budget and new_crossings <= crossings)
            if gate_ok and saved > added * DETOUR_TRADE + 60 and saved > 350:
                if added:
                    print(f"INFO: 迂回修復: edge '{eid}' の大回りを解消"
                          f"(経路 -{saved:.0f}px、交差 {crossings}→{new_crossings})")
                crossings, polys = new_crossings, new_polys
            else:  # 割に合わなければ元に戻す
                router.uncommit(recs[eid][0])
                routes[eid] = old_route
                recs[eid] = (router.recommit(old_rec), old_path)

    # R5-C: 終端二段ステップの修復。該当エッジだけを、回廊±SUBLANE_OFF の
    # サブレーンを足した拡張格子で引き直す(磨きパスは回廊格子上の経路しか
    # 返せないため、レーン競合由来の段差はここでしか救えない)。他エッジの
    # 確定経路は register_poly(交差)+ _mark_share(重走)で拡張格子に写し、
    # 採用は「段差が減り、最終形スコアが悪化しない」ときだけ
    if not draft and routes:
        polys = finalize_polys(lay, node_edges, routes)
        offenders = [eid for eid, p in polys.items()
                     if eid in recs and eid in by_id and _two_step_ends(p)]
        if offenders:
            fine_lay, fine_router = _sublane_context(lay)
            for eid in offenders:
                fine_router.reset()
                for p in fixed_polys:
                    fine_router.register_poly(p)
                for oid, op in polys.items():
                    if oid != eid:
                        fine_router.register_poly(op)
                        _mark_share(fine_router, op)
                found = route_edge(fine_router, fine_lay, by_id[eid])
                if found is None:
                    continue
                old_route = routes[eid]
                old_polys = polys
                old_score = full_score(routes, polys)
                routes[eid] = found[0]
                polys = finalize_polys(lay, node_edges, routes)

                def corun(ps: dict[str, list[Point]]) -> int:
                    others = [p for oid, p in ps.items() if oid != eid]
                    return _tight_coruns(ps[eid], others + fixed_polys)

                if (_two_step_ends(polys[eid])
                        < _two_step_ends(old_polys[eid])
                        and full_score(routes, polys) <= old_score
                        and corun(polys) <= corun(old_polys)):
                    continue    # 採用(recs の格子経路はここ以降使われない)
                routes[eid] = old_route
                polys = old_polys

    # R5-D: 経路の慣性。前回ビルドの経路(seed_routes)を初期解として扱い、
    # (a) 幾何的にまだ有効(障害物・境界・直交性)かつ (b) タブ全体のスコア
    # (交差→題字→anti→fan→折れ→長さ)が新規経路と比べ悪化しないものは
    # 旧経路を維持する。悪化するなら引き直す — 慣性は品質に劣後する。
    # まず有効な旧経路を一括適用して比較する(旧経路同士は前回ビルドで
    # 整合済みのため、1 本ずつでは互いの新旧混在に阻まれて戻れない解も
    # 丸ごとなら戻れる)。一括で悪化する場合のみ 1 本ずつスコアゲートで試す
    if not draft and seed_routes and routes:
        cands: dict[str, NodeRoute] = {}
        for e in node_edges:
            eid = e["id"]
            sr = seed_routes.get(eid)
            if (sr is None or routes.get(eid) is None or routes[eid] == sr
                    or not _seed_geometry_ok(lay, e, sr)):
                continue
            cands[eid] = sr
        if cands:
            polys = finalize_polys(lay, node_edges, routes)
            score = full_score(routes, polys)
            whole = dict(routes)
            whole.update(cands)
            if full_score(whole, finalize_polys(lay, node_edges, whole)) <= score:
                routes = whole
            else:
                for e in node_edges:    # spec 順で決定論に
                    eid = e["id"]
                    if eid not in cands:
                        continue
                    trial = dict(routes)
                    trial[eid] = cands[eid]
                    tpolys = finalize_polys(lay, node_edges, trial)
                    tscore = full_score(trial, tpolys)
                    if tscore <= score:
                        routes, score = trial, tscore

    # SEM-6/SEM-7-5: 対ファンの折れ構造を鏡像に揃える(shared="src" =
    # 同一 src のファンアウト対、shared="dst" = 同一 dst のファンイン対)。
    # 対称ユニット(assign_lanes)と fan スロットは端点・レーン共有までしか
    # 対称化できず、探索の SHARE/CROSS が後着の枝を階段状経路や別の入射辺へ
    # 追いやった場合の非対称はここで直す。ハード幾何(_seed_geometry_ok)・
    # 境界並走ガード・タブ全体スコア(交差→題字→anti→fan→折れ→長さ)の
    # 非悪化・密着並走の非増加を全て満たす候補だけ採用する(満たせない対は
    # 従来経路のまま = 交差増・迂回を作らない)。例外: ファンインの入射辺
    # そのものを整合させる候補(SEM-7-5)は、鏡像化の対価である折れ・長さの
    # 増加を許し、上位成分(交差→題字→anti→fan)の非悪化だけを要求する
    if not draft and routes:
        polys = finalize_polys(lay, node_edges, routes)
        score = full_score(routes, polys)
        for role in ("src", "dst"):
            for alts in _mirror_fan_candidates(lay, node_edges, routes, role):
                for e, cand in alts:
                    eid = e["id"]
                    if eid not in polys or not _seed_geometry_ok(lay, e, cand) \
                            or not _mirror_runs_clear(lay, e, cand):
                        continue
                    trial = dict(routes)
                    trial[eid] = cand
                    tpolys = finalize_polys(lay, node_edges, trial)
                    tscore = full_score(trial, tpolys)
                    others_old = [p for k, p in polys.items() if k != eid]
                    others_new = [p for k, p in tpolys.items() if k != eid]
                    align = role == "dst" \
                        and cand.entry[0] != routes[eid].entry[0]
                    ok = tscore[:4] <= score[:4] if align \
                        else tscore <= score
                    if ok and \
                            _tight_coruns(tpolys[eid], others_new + fixed_polys) \
                            <= _tight_coruns(polys[eid], others_old + fixed_polys):
                        routes, polys, score = trial, tpolys, tscore
                        break

    # SEM-7-5: 鏡像が成立しているファンイン対の端点辺を、後段の直線化
    # (straighten_polys の辺付け替えリシェイプ)から保護する。リシェイプは
    # 対を知らないため、片枝だけ折れを 1 つ減らす付け替え(実測: 構成図03 の
    # NAT→ECR 上枝 Z 字 → ECR 上辺 L 字)で入射辺の整合を再び崩す。
    # 流入辺規約(R7-15/A3)と同じ ban 機構に固定する — straighten_polys は
    # ban された辺への付け替えを行わない。対象は「入射辺が鏡像整合かつ折れ
    # 構造も鏡像」の対だけ(整合していない対は従来どおりリシェイプに委ねる)
    if not draft and routes:
        for vert, mid, (ea, ra), (eb, rb) in \
                _fan_pairs(lay, node_edges, routes, "dst"):
            flip = "h" if vert else "v"
            mside = _MIRROR_V if vert else _MIRROR_H
            if mside[ra.entry[0]] != rb.entry[0] \
                    or len(ra.runs) != len(rb.runs):
                continue
            mir = _mirror_runs(ra.runs, flip, mid)
            if not all(abs(m.coord - r.coord) <= 2.0
                       for m, r in list(zip(mir, rb.runs))[1:-1]):
                continue
            for e2, r2 in ((ea, ra), (eb, rb)):
                keep = {(e2["src"], r2.exit[0]), (e2["dst"], r2.entry[0])}
                ban = {(t, s) for t in (e2["src"], e2["dst"])
                       for s in "LRTB"} - keep
                lay.diamond_bans[e2["id"]] = \
                    lay.diamond_bans.get(e2["id"], frozenset()) | frozenset(ban)

    # 後段の修復(迂回・R5-C・経路の慣性)が diamond の辺占有を崩して
    # いないか最終確認する(run_order 内の dedupe と同じ強制パス)
    if not draft and routes:
        _dedupe_diamond_sides(router, lay, node_edges, routes, recs, kinds)

    return routes


# ---- スペック要素の型(ドキュメント用。実検証は validate_spec が行う)----
class NodeSpec(TypedDict, total=False):
    id: str
    label: str
    icon: str
    col: int
    row: int
    parent: str
    on_boundary: str  # left/right/top/bottom: 親コンテナの枠線上センターまたぎ
    step: int
    pin: bool
    shape: str
    title: str
    rows: list[str]
    rows2: list[str]
    w: float
    h: float
    style_extra: str


class EdgeSpec(TypedDict, total=False):
    id: str
    src: str
    dst: str
    kind: str
    label: str
    bidir: bool
    exit: list[float]
    entry: list[float]
    points: list[list[float]]
    style_extra: str


class ContainerSpec(TypedDict, total=False):
    id: str
    label: str
    type: str
    parent: str
    style_extra: str


def fan_out(lay: Layout, edges: list[EdgeSpec],
            routes: dict[str, NodeRoute]) -> None:
    """同一ノード同一辺に集まる端点の重なりを 3 段階で防ぐ。

    1. _fan_slots: 同一辺の端点をスロットに割り当てる(直行便は 0.5 固定)
    2. _fan_deconflict_runs: 端点から伸びる直線同士の同一線上重なりを分離
    3. _fan_container_endpoints: コンテナ端点の同一位置重複を 20px 刻みでずらす
    コンテナ端点は格子探索が外周上の位置(frac)を決めているため、
    スロット再割り当てはせず末尾の重複解消(spread)だけを行う。
    """
    _fan_slots(lay, edges, routes)
    _fan_deconflict_runs(lay, edges, routes)
    _fan_container_endpoints(lay, edges, routes)


def _fan_slots(lay: Layout, edges: list[EdgeSpec],
               routes: dict[str, NodeRoute]) -> None:
    """同一ノード同一辺に集まる端点をスロットへ割り当てる。"""
    groups: dict[tuple, list] = {}
    for e in edges:
        r = routes.get(e["id"])
        if not isinstance(r, NodeRoute):
            continue
        if e["src"] not in lay.cmap:
            groups.setdefault((e["src"], r.exit[0]), []).append(("exit", e))
        if e["dst"] not in lay.cmap:
            groups.setdefault((e["dst"], r.entry[0]), []).append(("entry", e))
    pinned_all = getattr(lay, "pinned_ports", {}) or {}
    for (nid, side), members in groups.items():
        if nid in lay.diamond:
            continue   # ひし形は頂点固定(R7-16)— 辺上のスロット分散をしない
        pins = pinned_all.get((nid, side), [])
        if len(members) + len(pins) <= 1:
            continue

        def far(m):
            kind, e = m
            other = e["dst"] if kind == "exit" else e["src"]
            ox, oy = lay.center(other)
            return oy if side in "LR" else ox

        members.sort(key=far)
        directs = [m for m in members if routes[m[1]["id"]].direct]
        movers = [m for m in members if not routes[m[1]["id"]].direct]
        fracs: dict[tuple, float] = {}
        for kind, e in directs:  # 直行便は現在の frac を維持(斜め防止。
            # 題字帯回避で中心からずれた直行線も直線のまま保つ)
            fracs[(id(e), kind)] = getattr(routes[e["id"]], kind)[1]
        if directs or pins:
            # 0.5 の直行線をまたがないよう、相手が上(左)の線は上半分、
            # 下(右)の線は下半分のスロットに割り当てる。スロットは辺中心
            # 0.5 に対する対称ラダー(0.5 ± i*step)から取る: 上下同数なら
            # 完全対称、異なっても直行線を含め等間隔の扇形になる(指摘6)。
            # pin 済みポート (外部FB A-3) も固定スロットとして数え、最寄りスロットを
            # 除外することで pin と同一点への割り当てを防ぐ
            mid = lay.center(nid)[1] if side in "LR" else lay.center(nid)[0]
            above = [m for m in movers if far(m) < mid]
            below = [m for m in movers if far(m) >= mid]
            pa = [p for p in pins if p < 0.5]
            pb = [p for p in pins if p >= 0.5]
            step = min(0.215, 0.35 / max(len(above) + len(pa),
                                         len(below) + len(pb), 1))
            for grp, sign, gp in ((above, -1, pa), (below, 1, pb)):
                k = len(grp) + len(gp)
                if len(grp) == 0:
                    continue
                # 遠い相手ほど外側の段(ポート直近での交差を防ぐ既存の並び)
                slots = [0.5 - step * (k - i) for i in range(k)] if sign < 0 \
                    else [0.5 + step * (i + 1) for i in range(k)]
                for p in gp:    # pin の最寄りスロットは使わない
                    slots.remove(min(slots, key=lambda s: abs(s - p)))
                for m, f in zip(grp, slots):
                    fracs[(id(m[1]), m[0])] = f
        else:
            k = len(movers)
            # 5 本以上は帯を 0.05〜0.95 へ広げる(78px 辺で 7 本 ≈ 11.7px 間隔。
            # 0.15〜0.85 のままだと 9.1px 間隔になり deconflict が衝突連鎖する)
            lo_f = max(0.05, 0.5 - 0.075 * k)
            mslots = FRAC_SLOTS.get(k) or [
                lo_f + (1 - 2 * lo_f) * i / (k - 1) for i in range(k)]
            for m, f in zip(movers, mslots):
                fracs[(id(m[1]), m[0])] = f
        for kind, e in members:
            r = routes[e["id"]]
            cur = getattr(r, kind)
            setattr(r, kind, (cur[0], fracs.get((id(e), kind), cur[1])))


def _fan_deconflict_runs(lay: Layout, edges: list[EdgeSpec],
                         routes: dict[str, NodeRoute]) -> None:
    """端点から伸びる直線同士が同一線上(近接含む)で重なる場合、端点位置を
    ずらして平行に分離する。直行便(単一直線)は両端を同量ずらし、かつ
    優先的に元位置を守る。"""
    # (ノード id, 辺) → 端点数。単独ポートの判定用(R4-4): LANE_STEP=14px
    # のずらしは 78px アイコンで frac 0.6795 になり「接続して見えない」
    # 端点を作るため、単独ポートは辺中心 ±NEAR_FRAC 内へクランプする。
    # 同一辺に複数付くポート群は対称ラダー(〜0.05/0.95)が正当で対象外
    port_n: dict[tuple[str, str], int] = {}
    for e in edges:
        r = routes.get(e["id"])
        if not isinstance(r, NodeRoute):
            continue
        for term, attr in (("src", "exit"), ("dst", "entry")):
            if e[term] not in lay.cmap:
                key = (e[term], getattr(r, attr)[0])
                port_n[key] = port_n.get(key, 0) + 1

    runs_list: list[tuple] = []  # (axis, coord, span, direct, e, r, attr)
    for e in edges:
        r = routes.get(e["id"])
        if not isinstance(r, NodeRoute):
            continue
        sp, ep, coords = pinned_coords(lay, e, r)
        if r.direct:
            axis = r.runs[0].axis
            span = tuple(sorted((sp[0], ep[0]) if axis == "h" else (sp[1], ep[1])))
            runs_list.append((axis, coords[0], span, True, e, r, "both"))
            continue
        for idx, attr, tp in ((0, "exit", sp), (-1, "entry", ep)):
            axis = r.runs[idx].axis
            corner = coords[1] if idx == 0 else coords[-2]
            t = tp[0] if axis == "h" else tp[1]
            runs_list.append((axis, coords[idx], tuple(sorted((t, corner))),
                              False, e, r, attr))

    def deconflict(cluster: list[tuple]) -> None:
        # 直行便を先に固定し、他はシフト後の最終座標同士で衝突判定する。
        # frac のクランプ(0.05〜0.95)後の「実際に置かれる座標」で判定・
        # 記録しないと、クランプで同じ端に潰れた線同士を分離済みと誤認する
        cluster.sort(key=lambda t: (not t[3], t[1]))
        placed: list[tuple[tuple, float]] = []
        for axis, coord, span, direct, e, r, attr in cluster:
            targets = (("src", "exit"), ("dst", "entry")) if attr == "both" \
                else ((("src", "exit"),) if attr == "exit" else (("dst", "entry"),))
            # ひし形端点は頂点固定(R7-16)— ずらさず現在位置を占有として
            # 記録だけする(直行便は両端が連動するため片端でも対象外)
            movable = not any(e[t] in lay.diamond for t, _a in targets)
            # 直行直線(both)は端点そのものが動く — 辺中心 ±NEAR_FRAC を
            # 超えるずらしは「浮いた線」になるため許さない(FB第3R 指摘2)。
            # 折れ線のスタブ側も、単独ポートのノード端点は同じ帯へクランプ
            # (R4-4)。ラダー(同一辺 2 本以上)とコンテナ端点は従来どおり
            # 0.05〜0.95
            if attr == "both":
                f_lo, f_hi = .5 - NEAR_FRAC, .5 + NEAR_FRAC
            else:
                term0 = "src" if attr == "exit" else "dst"
                sd0 = getattr(r, attr)[0]
                if (e[term0] not in lay.cmap
                        and port_n.get((e[term0], sd0), 0) <= 1):
                    f_lo, f_hi = .5 - NEAR_FRAC, .5 + NEAR_FRAC
                else:
                    f_lo, f_hi = .05, .95

            def landing(delta: float) -> float:
                term, at = targets[0]
                side, f = getattr(r, at)
                box = lay.boxes[e[term]]
                dim = box[3] if side in "LR" else box[2]
                base = box[1] if side in "LR" else box[0]
                return base + min(f_hi, max(f_lo, f + delta / dim)) * dim

            def free(fc: float) -> bool:
                # 7px = バリデータ E7(6px 未満)の直上。10px にすると
                # fan-out スロット(高次数で 8〜12px 間隔)と喧嘩する
                return not any(abs(fc - other) < 7
                               and span[0] < s[1] + 2 and s[0] < span[1] + 2
                               for s, other in placed)

            delta, fc_new = 0.0, landing(0.0)
            if movable and not free(fc_new):
                for k in range(1, 40):
                    d_ = LANE_STEP * ((k + 1) // 2) * (1 if k % 2 else -1)
                    f_ = landing(d_)
                    if free(f_):
                        delta, fc_new = d_, f_
                        break
                else:
                    # 空きなし: 元位置に留まる(巨大 delta のクランプ落ちで
                    # 全員が同じ端に潰れるのが最悪)
                    delta, fc_new = 0.0, landing(0.0)
            if delta:
                for term, at in targets:
                    side, f = getattr(r, at)
                    box = lay.boxes[e[term]]
                    dim = box[3] if side in "LR" else box[2]
                    setattr(r, at, (side, min(f_hi, max(f_lo, f + delta / dim))))
            placed.append((span, fc_new))

    for axis in ("h", "v"):
        items = sorted((t for t in runs_list if t[0] == axis), key=lambda t: t[1])
        cluster: list[tuple] = []
        for t in items:
            if cluster and t[1] - cluster[-1][1] > 20:
                deconflict(cluster)
                cluster = []
            cluster.append(t)
        if cluster:
            deconflict(cluster)


def _fan_container_endpoints(lay: Layout, edges: list[EdgeSpec],
                             routes: dict[str, NodeRoute]) -> None:
    """コンテナ側端点: 同一辺・同一位置に重なったら 20px 刻みでずらす。"""
    used: dict[tuple, list[float]] = {}
    for e in edges:
        r = routes.get(e["id"])
        if not isinstance(r, NodeRoute):
            continue
        for term, attr in (("src", "exit"), ("dst", "entry")):
            tid = e[term]
            if tid not in lay.cmap:
                continue
            side, f = getattr(r, attr)
            _x, _y, w, h = lay.boxes[tid]
            step = 20.0 / (h if side in "LR" else w)
            fs = used.setdefault((tid, side), [])
            g = f
            while any(abs(g - u) < step * 0.75 for u in fs) and g + step < 0.96:
                g += step
            setattr(r, attr, (side, g))
            fs.append(g)


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
RESERVED_IDS = frozenset({"0", "1"})

# コンテナ階層の慣例は _common.CONTAINER_PARENTS に一本化(W9。
# ビルド時=type 名で直接判定 / バリデータ=スタイル署名から型を推定して判定)


GRID_MAX = 500  # col/row の上限。配線の計算量が最大添字に約 O(C×R) で効くため

# ビルド段の納品ブロッカー WARN(バリデータのサマリ集計外)。_build が最後に通知する
BUILD_WARNS: list[str] = []

# abs スペックの id(生成器内部の _meta 等を許すため、先頭アンダースコアも可)
ABS_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*\Z")


def _finite_num(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _num_pair(v) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 2
            and all(_finite_num(x) for x in v))


def check_abs_basics(spec: dict) -> None:
    """abs スペック(validate_spec を通らない経路)の最小検証。

    id は XML 属性へ、座標は width= 等の属性値へそのまま入るため、ここで
    弾かないと壊れた XML の沈黙生成につながる(特に --no-validate 時)。
    """
    for kindname in ("nodes", "containers", "edges"):
        for item in spec.get(kindname) or []:
            iid = item.get("id")
            if not isinstance(iid, str) or not iid:
                die(f"id のない {kindname[:-1]} があります: {item!r}")
            if not ABS_ID_RE.match(iid):
                die(f"{kindname[:-1]} '{iid}' の id に使えない文字があります"
                    "(英数字・_ . - のみ)")
            if kindname == "edges":
                # フィールド単位の検証(grid の validate_spec 相当。欠けると
                # 型ミスが build_diagram 内の generic TypeError に落ちる)
                for k in ("src", "dst", "kind"):
                    if k in item and not isinstance(item[k], str):
                        die(f"edge '{iid}' の {k} は文字列で書いてください"
                            f"({item[k]!r})")
                for k in ("src_label", "dst_label"):
                    if k in item and (not isinstance(item[k], str) or not item[k]):
                        die(f"edge '{iid}' の {k} はラベル文字列で"
                            f"書いてください({item[k]!r})")
                for key in ("exit", "entry"):
                    if key in item and (not _num_pair(item[key]) or not all(
                            0 <= x <= 1 for x in item[key])):
                        die(f"edge '{iid}' の {key} は [fx, fy](0〜1 の数値)で"
                            f"書いてください({item[key]!r})")
                for key in ("label_at", "src_at", "dst_at",
                            "src_label_at", "dst_label_at"):
                    if key in item and not _num_pair(item[key]):
                        die(f"edge '{iid}' の {key} は [数値, 数値] で"
                            f"書いてください({item[key]!r})")
                for key in ("exit_dy", "entry_dy"):
                    if key in item and not _finite_num(item[key]):
                        die(f"edge '{iid}' の {key} は有限な数値で"
                            f"書いてください({item[key]!r})")
                if "points" in item:  # 値ベースだと null がすり抜ける(キー存在で見る)
                    pts = item["points"]
                    if (not isinstance(pts, list)
                            or not all(_num_pair(p) for p in pts)):
                        die(f"edge '{iid}' の points は [[x, y], ...] の有限な数値で"
                            f"書いてください({pts!r})")
                continue
            parent = item.get("parent")
            if parent is not None and not isinstance(parent, str):
                die(f"{kindname[:-1]} '{iid}' の parent はコンテナ id の文字列で"
                    f"書いてください({parent!r})")
            if kindname == "containers":
                missing = [k for k in ("x", "y", "w", "h") if k not in item]
                if missing:
                    die(f"container '{iid}': abs スペックには x/y/w/h が必要です"
                        f"(不足: {missing})。グリッドで書くなら nodes に col/row を")
            elif not (("cx" in item and "cy" in item)
                      or ("x" in item and "y" in item)):
                die(f"node '{iid}': abs スペックには cx/cy(または x/y)が必要です。"
                    "グリッドで書くなら col/row を")
            for k in ("x", "y", "cx", "cy", "w", "h"):
                if k in item:
                    v = item[k]
                    bad = (isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v))
                    if k in ("w", "h"):
                        bad = bad or v <= 0
                    if bad:
                        die(f"{kindname[:-1]} '{iid}' の {k} は"
                            f"{'正の' if k in ('w', 'h') else ''}数値で"
                            f"書いてください({v!r})")
            if kindname == "nodes":
                if "on_boundary" in item:
                    die(f"node '{iid}': on_boundary はグリッド経路(col/row)"
                        "専用です。abs スペックでは cx/cy を親コンテナの枠線上に"
                        "置き、style_extra に 'awsdiagBoundary=1;' を足して"
                        "ください(バリデータの E2/E8 例外マーカー)")
                if "icon" in item and not isinstance(item["icon"], str):
                    die(f"node '{iid}' の icon はアイコン名の文字列で"
                        f"書いてください({item['icon']!r})")
                shape = item.get("shape")
                if shape is not None and not isinstance(shape, str):
                    die(f"node '{iid}' の shape は文字列で書いてください({shape!r})")
                for key in ("rows", "rows2"):
                    v = item.get(key)
                    if v is not None and (not isinstance(v, list) or not all(
                            isinstance(s, str) for s in v)):
                        die(f"node '{iid}' の {key} は文字列の配列で"
                            f"書いてください({v!r})")
                if is_entity(item) and (not isinstance(item.get("title"), str)
                                        or not item["title"]):
                    die(f"node '{iid}': shape=entity には title(文字列)が必要です")
                if "link" in item:
                    link = item["link"]
                    if not isinstance(link, str) or not link.strip():
                        die(f"node '{iid}' の link は空でない URL/相対パス文字列で"
                            f"書いてください({link!r})")
                    if item.get("shape") != "subprocess":
                        die(f"node '{iid}': link は shape=subprocess 専用です")
                st = item.get("stereotype")
                if st is not None:
                    if not isinstance(st, str) or not st:
                        die(f"node '{iid}' の stereotype は文字列で"
                            f"書いてください({st!r})")
                    if not is_entity(item):
                        die(f"node '{iid}': stereotype は shape=entity 専用です"
                            "(interface / abstract / 任意文字列)")
                    if "«" in str(item.get("title", "")):
                        print(f"WARN: node '{iid}': title に «...» がありますが "
                              f"stereotype='{st}' も指定されています。二重表示に"
                              "なるため title からは «...» を外してください"
                              "(stereotype 指定が正)")
                if "text" in item and not ("x" in item and "y" in item):
                    die(f"node '{iid}': text ノードには x/y が必要です")

    endpoint_ids = {
        item.get("id")
        for kindname in ("nodes", "containers")
        for item in (spec.get(kindname) or [])
    }
    for edge in spec.get("edges") or []:
        for term in ("src", "dst"):
            endpoint = edge.get(term)
            if endpoint is None and f"{term}_at" in edge:
                # 固定座標端点(src_at/dst_at。--emit-abs の凡例 _lg_e* 等)は
                # 図形参照を持たないのが正
                continue
            if not isinstance(endpoint, str):
                die(f"edge '{edge['id']}' に {term} がありません")
            if endpoint not in endpoint_ids:
                die(f"edge '{edge['id']}' の {term} '{endpoint}' が "
                    "nodes/containers にありません")


def check_structure(spec: dict) -> None:
    """nodes/containers/edges の器(null・非配列・非 dict 要素)を検証して即時 die。

    validate_spec の先頭のほか、_build の grid/abs 分岐(is_grid/is_abs)の前でも
    呼ぶ。分岐前に検証しないと "nodes": null 等がここへ届かず、親切なメッセージの
    代わりに generic な TypeError で落ちる。
    """
    for name in ("nodes", "containers", "edges"):
        v = spec.get(name)
        if v is None:
            if name in spec:
                die(f"{name} が null です(配列で書くか、キーごと省略してください)")
            continue
        if not isinstance(v, list):
            die(f"{name} は配列で書いてください({type(v).__name__} になっています)")
        for item in v:
            if not isinstance(item, dict):
                die(f"{name} の要素が dict ではありません: {item!r}")


def validate_spec(spec: dict) -> None:
    """グリッドスペックの前段検証。違反は全件集めて 1 回の SpecError で報告する。

    ここで落とすことで、後段の無限ループ(parent 循環)・KeyError・
    壊れた XML の沈黙生成を防ぐ。構造が壊れていて続行できないものだけ即時終了。
    """
    # 構造(ここが壊れていると以降の検査が安全に続かないので即時 die)
    check_structure(spec)
    nodes = spec.get("nodes") or []
    conts = spec.get("containers") or []
    edges = spec.get("edges") or []

    errs: list[str] = []
    err = errs.append

    # id: 必須・文字種・予約・全体で一意(id 欠落だけは以降の照合に必要なので即時)
    seen: dict[str, str] = {}
    for kindname, lst in (("node", nodes), ("container", conts), ("edge", edges)):
        for item in lst:
            iid = item.get("id")
            if not isinstance(iid, str) or not iid:
                die(f"id のない {kindname} があります: {item!r}")
            if iid in RESERVED_IDS or iid.startswith("_"):
                err(f"id '{iid}' は予約されています(\"0\"/\"1\"/先頭アンダースコアは不可)")
            elif not ID_RE.match(iid):
                err(f"id '{iid}' に使えない文字があります(英数字・_ . - のみ、先頭は英数字)")
            if iid in seen:
                err(f"id '{iid}' が重複しています({seen[iid]} と {kindname}。"
                    "nodes/containers/edges 全体で一意にしてください)")
            seen[iid] = kindname

    # containers: type・parent 実在・循環(parent "1" はルート扱い)
    cmap = {c["id"]: c for c in conts}

    def is_root(parent) -> bool:
        return parent in (None, "1")

    for c in conts:
        ctype = c.get("type")
        if ctype is not None and not isinstance(ctype, str):
            err(f"container '{c['id']}' の type は文字列で書いてください({ctype!r})")
        elif not c.get("style") and ctype not in CONTAINER_STYLES:
            err(f"container '{c['id']}': type '{ctype}' は未知です。"
                f"候補: {sorted(CONTAINER_STYLES)}")
        parent = c.get("parent")
        if parent is not None and not isinstance(parent, str):
            err(f"container '{c['id']}' の parent はコンテナ id の文字列で"
                f"書いてください({parent!r})")
        elif not is_root(parent) and parent not in cmap:
            err(f"container '{c['id']}' の parent '{parent}' が containers にありません")
    for c in conts:
        path: list[str] = []
        cur: str | None = c["id"]
        while cur is not None and cur in cmap:
            if cur in path:
                cycle = path[path.index(cur):] + [cur]
                err(f"containers の parent が循環しています: {' → '.join(cycle)}")
                break
            path.append(cur)
            nxt = cmap[cur].get("parent")
            if nxt is not None and not isinstance(nxt, str):
                break  # 型違いは上の parent 検査で err 済み
            cur = None if is_root(nxt) else nxt
        # W9: 階層の慣例チェック(誤解を招く入れ子は警告のみ)
        ctype = c.get("type")
        allowed = CONTAINER_PARENTS.get(ctype) if isinstance(ctype, str) else None
        if allowed is not None:
            parent = c.get("parent")
            ptype = (cmap[parent].get("type")
                     if isinstance(parent, str) and parent in cmap else None)
            if ptype not in allowed:
                print(f"WARN: W9: コンテナ階層が AWS の慣例と合いません: "
                      f"{c.get('type')} '{c['id']}' の親が "
                      f"{ptype or 'トップレベル'}(慣例: {sorted(x or 'トップ' for x in allowed)}。"
                      "根拠: サブネット⊂AZ = docs.aws.amazon.com/vpc/latest/userguide/"
                      "configure-subnets.html / ルート→OU→アカウント = docs.aws.amazon.com/"
                      "organizations/latest/userguide/orgs_getting-started_concepts.html)")

    # nodes: parent 実在・col/row の型・icon(grid では text ノード不可)
    for n in nodes:
        parent = n.get("parent")
        if parent is not None and not isinstance(parent, str):
            err(f"node '{n['id']}' の parent はコンテナ id の文字列で"
                f"書いてください({parent!r})")
        elif not is_root(parent) and parent not in cmap:
            err(f"node '{n['id']}' の parent '{parent}' が containers にありません")
        ob = n.get("on_boundary")
        if ob is not None:
            if ob not in ("left", "right", "top", "bottom"):
                err(f"node '{n['id']}' の on_boundary は left / right / top / "
                    f"bottom のいずれかで書いてください({ob!r})")
            elif not (isinstance(parent, str) and parent in cmap):
                err(f"node '{n['id']}': on_boundary には parent(枠線をまたぐ"
                    "コンテナ)の指定が必要です。col/row は親の内側・指定辺に"
                    "隣接するセルに置いてください")
        if "icon" in n and not isinstance(n["icon"], str):
            err(f"node '{n['id']}' の icon はアイコン名の文字列で"
                f"書いてください({n['icon']!r})")
        if ("col" in n) != ("row" in n):
            err(f"node '{n['id']}' は col/row の片方だけです(両方書くか両方省略)")
        for k in ("col", "row"):
            if k in n:
                v = n[k]
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    err(f"node '{n['id']}' の {k} は非負の整数で書いてください({v!r})")
                elif v > GRID_MAX:
                    err(f"node '{n['id']}' の {k}={v} が大きすぎます(上限 {GRID_MAX})。"
                        "col/row はピクセル座標ではなくマス目の添字です")
        for k in ("w", "h"):
            if k in n:
                v = n[k]
                if (isinstance(v, bool) or not isinstance(v, (int, float))
                        or not math.isfinite(v) or v <= 0):
                    err(f"node '{n['id']}' の {k} は正の数値で書いてください({v!r})")
        shape = n.get("shape")
        if shape is not None and not isinstance(shape, str):
            err(f"node '{n['id']}' の shape は文字列で書いてください({shape!r})")
        elif "text" in n:
            err(f"node '{n['id']}': text ノードはグリッドスペックでは使えません"
                "(説明書きは meta キーで、凡例は legend で)")
        elif is_entity(n):
            if not isinstance(n.get("title"), str) or not n["title"]:
                err(f"node '{n['id']}': shape=entity には title が必須です")
            for key in ("rows", "rows2"):
                v = n.get(key)
                if v is not None and (not isinstance(v, list)
                                      or not all(isinstance(x, str) for x in v)):
                    err(f"node '{n['id']}' の {key} は文字列の配列で({v!r})")
        elif is_flow(n):
            # label は任意(無ラベルの分岐点も許す)。gateway は 64x64 固定で
            # 「+」マーカーがラベルと重なるため無ラベル推奨(R7 REV-7)
            if shape == "gateway" and str(n.get("label") or "").strip():
                print(f"WARN: node '{n['id']}': gateway のラベル "
                      f"{n['label']!r} は「+」マーカーと重なります。無ラベルにして "
                      "補足は流入エッジの label か隣の注記に置いてください")
        elif n.get("shape") is not None:
            err(f"node '{n['id']}': shape '{n['shape']}' は未知です"
                f"(entity / {' / '.join(FLOW_STYLES)})")
        elif "icon" not in n:
            err(f"node '{n['id']}' に icon がありません"
                "(ER/UML は shape=entity、フロー図は shape=process 等)")
        if "link" in n:
            link = n["link"]
            if not isinstance(link, str) or not link.strip():
                err(f"node '{n['id']}' の link は空でない URL/相対パス文字列で"
                    f"書いてください({link!r})")
            elif n.get("shape") != "subprocess":
                err(f"node '{n['id']}': link は shape=subprocess 専用です")
        if "pin" in n:
            if not isinstance(n["pin"], bool):
                err(f"node '{n['id']}' の pin は true/false で書いてください"
                    f"({n['pin']!r})")
            elif n["pin"] and "col" not in n:
                err(f"node '{n['id']}': pin には col/row の指定が必要です"
                    "(自動配置のノードは固定できません)")
        st = n.get("stereotype")
        if st is not None:
            # R7-6: «...» 行の自動生成。abstract は UML 慣例でタイトル斜体
            if not isinstance(st, str) or not st:
                err(f"node '{n['id']}' の stereotype は文字列で書いてください"
                    f"({st!r})")
            elif not is_entity(n):
                err(f"node '{n['id']}': stereotype は shape=entity 専用です"
                    "(interface / abstract / 任意文字列)")
            elif "«" in str(n.get("title", "")):
                print(f"WARN: node '{n['id']}': title に «...» がありますが "
                      f"stereotype='{st}' も指定されています。二重表示になるため "
                      "title からは «...» を外してください(stereotype 指定が正)")
    placed = ["col" in n for n in nodes]
    if any(placed) and not all(placed):
        missing = [n["id"] for n in nodes if "col" not in n][:5]
        err(f"col/row が一部のノードにしかありません(例: {missing})。"
            "全ノードに書くか、全ノードで省略(自動配置)にしてください")

    # W14: ゲートウェイ/アタッチメント系ノードの配置規約(表は _common.
    # GATEWAY_PLACEMENT に一本化。バリデータ側 W14 と同じ判定)。祖先を近い順に
    # たどり、最初に当たったネットワーク境界(vpc / public_subnet /
    # private_subnet。無ければ None = VPC 外)が許容集合に無ければ警告。
    # on_boundary ノードは親の枠線上 = 親直下として扱う(parent 連鎖そのまま)。
    # サブネットを 1 つも描いていない VPC(抽象度の高い図。実例: マルチ
    # アカウント図の Egress VPC 直下の NAT)では、subnet 配置を要求する規約は
    # 発火しない — W10 と同じ抽象度ルール
    vpcs_with_subnet: set[str] = set()
    for c in conts:
        if c.get("type") not in ("public_subnet", "private_subnet"):
            continue
        seen_p: set[str] = set()
        cur = c.get("parent")
        while isinstance(cur, str) and cur in cmap and cur not in seen_p:
            seen_p.add(cur)
            if cmap[cur].get("type") == "vpc":
                vpcs_with_subnet.add(cur)
            cur = cmap[cur].get("parent")
    for n in nodes:
        icon = n.get("icon")
        if not isinstance(icon, str):
            continue
        nm = icon[4:] if icon.startswith("aws:") else icon
        nm = ICON_ALIASES.get(nm, nm)
        rule = GATEWAY_PLACEMENT.get(nm)
        if rule is None:
            continue
        allowed, hint, url = rule
        ctx = None
        seen_p: set[str] = set()
        cur = n.get("parent")
        while isinstance(cur, str) and cur in cmap and cur not in seen_p:
            seen_p.add(cur)
            t = cmap[cur].get("type")
            if t in ("vpc", "public_subnet", "private_subnet"):
                ctx = (t, cur)
                break
            cur = cmap[cur].get("parent")
        if (ctx[0] if ctx else None) in allowed:
            continue
        if (ctx and ctx[0] == "vpc" and ctx[1] not in vpcs_with_subnet
                and {"public_subnet", "private_subnet"} & allowed):
            continue  # サブネット未描画の VPC 直下は抽象表現として許容
        place = f"{ctx[0]} '{ctx[1]}' 内" if ctx else "VPC の外"
        print(f"WARN: W14: ゲートウェイ系ノードの配置が AWS の慣例と合いません: "
              f"{nm} '{n['id']}' が {place}にあります。{hint}(出典: {url})")

    # ---- W16〜W21: アーキテクチャ・アンチパターン検査(SEM-3)----
    # 語彙(icon 集合・テキスト署名)は _common に一本化。バリデータ側
    # (validate_drawio)は生成後/手編集の .drawio に同じ検査を行う。
    # W17/W18/W19 は境界・到達性の事実誤り = error(ビルド拒否)、
    # W16/W20/W21 は略図の意図があり得るため warning から運用する。
    def _res_icon(n: dict) -> str | None:
        ic = n.get("icon")
        if not isinstance(ic, str):
            return None
        nm = ic[4:] if ic.startswith("aws:") else ic
        return ICON_ALIASES.get(nm, nm)

    def _anc_types(n: dict) -> list[str]:
        """祖先コンテナの type を近い順に返す(循環・欠落は打ち切り)。"""
        out: list[str] = []
        seen_p: set[str] = set()
        cur = n.get("parent")
        while isinstance(cur, str) and cur in cmap and cur not in seen_p:
            seen_p.add(cur)
            t = cmap[cur].get("type")
            if isinstance(t, str):
                out.append(t)
            cur = cmap[cur].get("parent")
        return out

    def _nearest_subnet(n: dict) -> str | None:
        for t in _anc_types(n):
            if t in ("public_subnet", "private_subnet"):
                return t
        return None

    nmap = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}

    def _end(e: dict, key: str) -> dict | None:
        """エッジ端のノード dict(型違いの src/dst は先行検査が err 済み)。"""
        v = e.get(key)
        return nmap.get(v) if isinstance(v, str) else None

    # W17(AP2): グローバルエッジサービスが region/VPC 内 — error。
    # CloudFront/Route 53 は無条件、WAF は CloudFront に関連付くもの
    # (cloudfront ノードとエッジで接続)のみ対象(ALB/API GW 用の
    # リージョナル WAF は region 内が正当のため対象外 = 誤検知ゼロ優先)
    cf_ids = {i for i, n in nmap.items() if _res_icon(n) == "cloudfront"}
    waf_ids = {i for i, n in nmap.items() if _res_icon(n) == "waf"}
    waf_cf: set[str] = set()
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if not isinstance(s, str) or not isinstance(d, str):
            continue
        if s in cf_ids and d in waf_ids:
            waf_cf.add(d)
        if d in cf_ids and s in waf_ids:
            waf_cf.add(s)
    _W17_REGIONAL = ("region", "vpc", "az", "public_subnet", "private_subnet")
    for i, n in nmap.items():
        ic = _res_icon(n)
        if ic not in ("cloudfront", "route_53") and not (
                ic == "waf" and i in waf_cf):
            continue
        hit = next((t for t in _anc_types(n) if t in _W17_REGIONAL), None)
        if hit:
            err(f"W17: {ic} '{i}' が {hit} コンテナ内にあります。CloudFront/"
                "Route 53(および CloudFront に関連付ける WAF = us-east-1 の"
                "グローバル web ACL)はグローバルサービスで、リージョン障害の"
                "切替対象ではありません — aws_cloud 直下に置き、切替はオリジン"
                "(LB)側で表現してください(出典: docs.aws.amazon.com/"
                "AmazonCloudFront/latest/DeveloperGuide/"
                "restrict-access-to-load-balancer.html / docs.aws.amazon.com/"
                "waf/latest/developerguide/web-acl-associating-aws-resource.html)")

    # W16(AP1): failover 線が CDN/WAF をバイパスして DR の LB/コンピュートへ
    # 直行(平常時 main 経路は CloudFront/WAF 前段)— 非対称な DR 経路
    _fo_targets = LB_ICONS | COMPUTE_ICONS
    front_main = any(  # 平常時経路(kind 省略=main)が CDN/WAF 前段か
        e2.get("kind", "main") == "main"
        and _res_icon(_end(e2, "src") or {}) in EDGE_STACK_ICONS
        and _res_icon(_end(e2, "dst") or {}) in _fo_targets
        for e2 in edges)
    for e in edges:
        if e.get("kind") != "failover" or not front_main:
            continue
        s = _end(e, "src")
        d = _end(e, "dst")
        if s is None or d is None or _res_icon(d) not in _fo_targets:
            continue
        if _res_icon(s) in EDGE_STACK_ICONS:
            continue  # cf/waf 起点 = オリジン切替の対称経路(正しい形)
        anc = _anc_types(d)
        if "region" not in anc and "vpc" not in anc:
            continue
        print(f"WARN: W16: フェイルオーバー経路がプライマリと非対称です: "
              f"edge '{e['id']}'({e.get('src')}→{e.get('dst')})が CloudFront/"
              "WAF をバイパスして DR の LB/コンピュートへ直行しています。切替"
              "はオリジンだけにし、エッジスタックは共通で通してください(例: "
              "cf→DR の LB を kind=failover で。バイパス経路は WAF 検査ゼロ、"
              "ALB を CloudFront 限定に保護する推奨構成では 403 で DR 不能。"
              "出典: docs.aws.amazon.com/wellarchitected/latest/"
              "reliability-pillar/rel_planning_for_recovery_config_drift.html"
              " / docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/"
              "restrict-access-to-load-balancer.html)")

    # W18(AP6a): DB/キャッシュが public subnet 内 — error
    for i, n in nmap.items():
        ic = _res_icon(n)
        if ic in DB_SUBNET_ICONS and _nearest_subnet(n) == "public_subnet":
            err(f"W18: DB/キャッシュ {ic} '{i}' が public subnet 内にあります。"
                "RDS/Aurora/ElastiCache は private subnet に置き、インターネット"
                "から隠すのが公式推奨です(DB サブネットグループは 2AZ 以上。"
                "出典: docs.aws.amazon.com/AmazonRDS/latest/UserGuide/"
                "USER_VPC.WorkingWithRDSInstanceinaVPC.html)")

    # W19(AP6b): 外部クライアント → DB の直接エッジ — error
    for e in edges:
        s = _end(e, "src")
        d = _end(e, "dst")
        if (s is not None and d is not None
                and _res_icon(s) in EXTERNAL_CLIENT_ICONS
                and _res_icon(d) in DB_ICONS):
            err(f"W19: edge '{e['id']}': 外部({e.get('src')})から DB"
                f"({e.get('dst')})への直接線です。DB へのアクセスはアプリ層"
                "からのみ描きます(公式シナリオ: Web 層 public・DB 層 private、"
                "Web だけが DB にアクセス。出典: docs.aws.amazon.com/AmazonRDS/"
                "latest/UserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html)")

    # W20(AP3): HA/Multi-AZ/冗長の表記があるのに AZ コンテナが 1 つ以下。
    # 対象テキストはタブ名+ラベル(meta は情報源の記述が混ざるため見ない)
    _w20_text = "\n".join(
        [str(spec.get("name") or "")]
        + [str(x.get("label") or "") for x in conts + nodes + edges])
    m = HA_TEXT_RE.search(_w20_text)
    if m:
        az_n = sum(1 for c in conts if c.get("type") == "az")
        if az_n <= 1:
            print(f"WARN: W20: ラベルに「{m.group(0)}」とありますが AZ コンテナ"
                  f"が {az_n} 個です。本番の HA は 2AZ 以上に展開して描いて"
                  "ください(compute を両 AZ、RDS は primary/standby を別 AZ。"
                  "意図的な略図なら表記側を見直す。出典: docs.aws.amazon.com/"
                  "wellarchitected/latest/reliability-pillar/"
                  "rel_fault_isolation_multiaz_region_system.html)")

    # W21(AP5): private subnet 内ノード → 外部クライアントへの直行エッジ
    # (経路に NAT/IGW/エンドポイントが無い)。経由省略の略図があり得るため warning
    for e in edges:
        s = _end(e, "src")
        d = _end(e, "dst")
        if s is None or d is None:
            continue
        if _res_icon(d) not in EXTERNAL_CLIENT_ICONS:
            continue
        if _nearest_subnet(s) != "private_subnet" or _anc_types(d):
            continue
        print(f"WARN: W21: edge '{e['id']}': private subnet 内の "
              f"'{e.get('src')}' から外部 '{e.get('dst')}' への直行線です。"
              "private subnet は IGW への直接ルートを持たないため、外向きは "
              "NAT Gateway(public subnet)→IGW 経由で描いてください(AWS "
              "サービス宛なら VPC エンドポイントで NAT 不要。出典: "
              "docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html)")

    # step(リファレンスアーキテクチャ図の番号バッジ)/ steps(説明パネル)
    seen_steps: dict[int, str] = {}
    for kindname, lst in (("node", nodes), ("edge", edges)):
        for item in lst:
            if "step" in item:
                v = item["step"]
                if (isinstance(v, bool) or not isinstance(v, int)
                        or not 1 <= v <= 99):
                    err(f"{kindname} '{item['id']}' の step は 1〜99 の整数で"
                        f"書いてください({v!r})")
                elif v in seen_steps:
                    err(f"step {v} が重複しています({seen_steps[v]} と "
                        f"{item['id']}。番号は図内で一意にしてください)")
                else:
                    seen_steps[v] = item["id"]
    stp = spec.get("steps")
    if stp is not None and (not isinstance(stp, list) or not all(
            isinstance(s, str) for s in stp)):
        err("steps は説明文字列の配列で書いてください"
            "(番号は図中の step バッジと対応)")
    bs = spec.get("badge_style")
    if bs is not None and bs not in BADGE_STYLES:
        err(f"badge_style '{bs}' は未知です(候補: "
            f"{' / '.join(sorted(BADGE_STYLES))}。dark=濃紺+白数字が既定)")
    eq = spec.get("equalize_containers")
    if eq is not None and not isinstance(eq, bool):
        err(f"equalize_containers は true / false で書いてください"
            f"({eq!r} になっています。既定 true = 同じ親・同じ type の"
            "兄弟コンテナの寸法を揃える)")

    # meta / legend(型間違いは下流で generic な TypeError になるためここで捕捉)
    meta = spec.get("meta")
    if meta is not None and not isinstance(meta, dict):
        err('meta は {"purpose": ...} の dict で書いてください'
            f"({type(meta).__name__} になっています)")
    legend = spec.get("legend")
    if legend is not None and not isinstance(legend, (dict, list)):
        err('legend は {"kind名": "説明"} の dict か'
            ' [{"kind": .., "label": ..}] の配列で書いてください'
            f"({type(legend).__name__} になっています)")
    elif isinstance(legend, list):
        for item in legend:
            if (not isinstance(item, dict) or not isinstance(item.get("kind"), str)
                    or not isinstance(item.get("label"), str)):
                err('legend の要素は {"kind": .., "label": ..} の dict で'
                    f"書いてください({item!r})")

    # kinds
    kinds = spec.get("kinds")
    if kinds is not None and not isinstance(kinds, dict):
        err('kinds は {"名前": {"base": ..., "color": ...}} の形式で書いてください')
    elif kinds:
        for kname, kdef in kinds.items():
            if not isinstance(kdef, dict):
                err(f"kinds '{kname}' は dict で定義してください({kdef!r})")
                continue
            unknown = set(kdef) - {"base", "color", "style_extra"}
            if unknown:
                err(f"kinds '{kname}' の未知キー: {sorted(unknown)}"
                    "(base / color / style_extra)")
            base = kdef.get("base", "sub")
            if not isinstance(base, str) or base not in EDGE_STYLES:
                err(f"kinds '{kname}': base '{kdef.get('base')}' は "
                    f"{sorted(EDGE_STYLES)} から選んでください")
            color = kdef.get("color")
            if color is not None and not HEX_RE.match(str(color)):
                err(f"kinds '{kname}': color '{color}' は #RRGGBB 形式で")

    cont_ids = {c.get("id") for c in conts if isinstance(c, dict)}
    node_ids = {n.get("id") for n in nodes if isinstance(n, dict)}
    endpoint_ids = cont_ids | node_ids
    # edges: src/dst 必須・自己ループ・手動配線の値域
    for e in edges:
        for k in ("src", "dst"):
            if not isinstance(e.get(k), str):
                err(f"edge '{e['id']}' に {k} がありません")
            elif e[k] not in endpoint_ids:
                err(f"edge '{e['id']}' の {k} '{e[k]}' が nodes/containers に"
                    "ありません")
        if "kind" in e and not isinstance(e["kind"], str):
            err(f"edge '{e['id']}' の kind は文字列で書いてください({e['kind']!r})")
        if e.get("src") and e.get("src") == e.get("dst") \
                and e.get("src") in cont_ids:
            err(f"edge '{e['id']}': コンテナへの自己ループは描けません"
                "(ノードの自己参照のみ対応)")
        for key in ("exit", "entry"):
            if key in e:
                v = e[key]
                if (not isinstance(v, (list, tuple)) or len(v) != 2
                        or not all(isinstance(x, (int, float))
                                   and not isinstance(x, bool)
                                   and 0 <= x <= 1 for x in v)):
                    err(f"edge '{e['id']}' の {key} は [fx, fy](0〜1 の数値)で"
                        f"書いてください({v!r})")
        if "points" in e:
            v = e["points"]
            if not isinstance(v, list) or not all(_num_pair(pt) for pt in v):
                err(f"edge '{e['id']}' の points は [[x, y], ...] の有限な数値で"
                    f"書いてください({v!r})")
        for key in ("label_at", "src_at", "dst_at",
                    "src_label_at", "dst_label_at"):
            if key in e and not _num_pair(e[key]):
                err(f"edge '{e['id']}' の {key} は [数値, 数値] で"
                    f"書いてください({e[key]!r})")
        # R7-4: エッジ端ラベル(全 kind で使用可。UML 多重度・ER 端別表示等)
        for key in ("src_label", "dst_label"):
            if key in e and (not isinstance(e[key], str) or not e[key]):
                err(f"edge '{e['id']}' の {key} はラベル文字列で"
                    f"書いてください({e[key]!r})")

    if errs:
        shown = errs[:12]
        more = f"\n  … 他 {len(errs) - 12} 件" if len(errs) > 12 else ""
        die(f"スペックに {len(errs)} 件の問題があります:\n  - "
            + "\n  - ".join(shown) + more)

def classify_edges(lay: Layout, edges: list[dict]
                   ) -> tuple[list, list, dict, list]:
    """エッジを (手動, 配線対象, 固定ルート, 固定折れ線) に分類する。

    内包ペア(cloud→内部ノード等)も格子探索で配線する。以前は L/Z の
    簡易配線(cont_route)に固定していたが、障害物を見ないため密な図で
    アイコンを貫通した。container_stubs が相手の内側にいるコンテナには
    スタブを内向きに立てるので、通常の探索で障害物を避けられる。
    cont_route は探索不能時の代替配線(WARN 付き)としてのみ残る。
    """
    manual = [e for e in edges if "exit" in e and "entry" in e]
    # pin 端点 (ノードのみ) を台帳化。スロット割当 (_fan_slots) が pin 済みポートを
    # 固定スロットとして避けられるようにする (外部FB A-3: pin とスロットの相互不可視バグ)
    lay.pinned_ports = {}
    for e in manual:
        for term, key in (("src", "exit"), ("dst", "entry")):
            nid, v = e.get(term), e.get(key)
            if not v or nid in lay.cmap or nid not in lay.boxes:
                continue
            px, py = float(v[0]), float(v[1])
            if px <= 0.0:
                side, frac = "L", py
            elif px >= 1.0:
                side, frac = "R", py
            elif py <= 0.0:
                side, frac = "T", px
            else:
                side, frac = "B", px
            lay.pinned_ports.setdefault((nid, side), []).append(frac)
    routable = [e for e in edges
                if e not in manual and e["src"] != e["dst"]]
    fixed_routes: dict[str, dict | None] = {e["id"]: None for e in manual}
    fixed_polys = [fixed_route_poly(lay, e, None) for e in manual]
    return manual, routable, fixed_routes, fixed_polys


FORK_GAP = 8.0    # fork トランク・脚とコンテナ枠の最小間隔(px)
FORK_PAD = 12.0   # レーン x とコンテナ縦枠の最小距離・トランクの最小長(px)


def _fork_seg_conflict(segs: list[tuple[Point, Point]],
                       polys: list[list[Point]]) -> bool:
    """fork の線分群が既存の固定折れ線(手動配線・先行 fork)と衝突するか。

    fork は固定配線で後から避けられないため、交差または 7px 未満の
    同軸並走(重なり 8px 超)があれば検出段で棄却する(安全側)。
    """
    for a, b in segs:
        for poly in polys:
            for c, d in zip(poly, poly[1:]):
                if seg_cross(a, b, c, d):
                    return True
                for ax in (0, 1):
                    o = 1 - ax
                    if (abs(a[ax] - b[ax]) < 0.75 and abs(c[ax] - d[ax]) < 0.75
                            and abs(a[ax] - c[ax]) < 7.0):
                        lo = max(min(a[o], b[o]), min(c[o], d[o]))
                        hi = min(max(a[o], b[o]), max(c[o], d[o]))
                        if hi - lo > 8.0:
                            return True
    return False


def _fork_lane_clear(lay: Layout, segs: list[tuple[Point, Point]],
                     src: str) -> bool:
    """fork のトランク・脚(軸平行線分)が空きレーンに置けるか(R5-B)。

    障害物(src 自身の箱は除く)に CLEARANCE 未満で接近しない・題字帯に
    触れない・コンテナ枠を横断しない・枠と FORK_GAP 未満で並走しない。
    宛先コンテナへの入射端点は枠上でちょうど終わるため、開区間判定に
    より横断・並走には数えない。
    """
    own = lay.fullb.get(src)
    for a, b in segs:
        lo_x, hi_x = min(a[0], b[0]), max(a[0], b[0])
        lo_y, hi_y = min(a[1], b[1]), max(a[1], b[1])
        for ob in lay.obstacles:
            if ob == own:
                continue
            if (lo_x < ob[0] + ob[2] + CLEARANCE
                    and ob[0] - CLEARANCE < hi_x
                    and lo_y < ob[1] + ob[3] + CLEARANCE
                    and ob[1] - CLEARANCE < hi_y):
                return False
        for tb in lay.title_bands:
            if (lo_x < tb[0] + tb[2] and tb[0] < hi_x
                    and lo_y < tb[1] + tb[3] and tb[1] < hi_y):
                return False
        horiz = hi_y - lo_y < 0.75
        for cid in lay.cmap:
            bx, by, bw, bh = lay.boxes[cid]
            if horiz:
                if by < a[1] < by + bh and (lo_x < bx < hi_x
                                            or lo_x < bx + bw < hi_x):
                    return False        # コンテナ縦枠の横断
                if (lo_x < bx + bw and bx < hi_x
                        and min(abs(a[1] - by),
                                abs(a[1] - by - bh)) < FORK_GAP):
                    return False        # コンテナ横枠との並走・接触
            else:
                if bx < a[0] < bx + bw and (lo_y < by < hi_y
                                            or lo_y < by + bh < hi_y):
                    return False        # コンテナ横枠の横断
                if (lo_y < by + bh and by < hi_y
                        and min(abs(a[0] - bx),
                                abs(a[0] - bx - bw)) < FORK_GAP):
                    return False        # コンテナ縦枠との並走・接触
    return True


def detect_center_forks(lay: Layout, edges: list[dict],
                        routable: list[dict],
                        fixed_polys: list[list[Point]] = ()) -> dict[str, dict]:
    """fork(中心からの二股)を検出し、固定配線として返す(R5-B)。

    外部フィードバックが手動 pin で実証した形状仕様に忠実:
      1. 出射は同一辺の対称スロット(FRAC_SLOTS[2] = 0.35 / 0.65)—
         2 本が見える平行トランク
      2. 2 本は同じレーン x で同時に折れて上下に分かれる。レーン x の
         アンカーは宛先コンテナ内の先頭(src 寄り)の直下子ボックス中心
         (コンテナ中心だと奥まで走りすぎる)
      3. 宛先の対面辺(上コンテナ=下辺 / 下コンテナ=上辺)へレーン x と
         同じ位置で入射(entry frac = レーン x の正規化値)
    棄却済み 2 案は実装しない: トランク完全共有(exit 0.5 共有)は両端
    矢印の双方向線に誤読される / レーン x=コンテナ中心は走りすぎに見える。

    検出は安全側に限定し、外れる形は現行ルータ(+fan_fixes)に委ねる:
      - src はアイコンノードで、出エッジがちょうど 2 本・宛先は共に
        コンテナ(ノード宛は「下辺入射禁止」と衝突するため対象外)
      - 宛先は 1 上 1 下・共に src と同じ横方向側・x 範囲が重なる
      - トランク回廊(コンテナ間の隙間)に FORK_GAP 以上の余白がある
      - レーン(トランク 2 本+脚 2 本)が空いている(_fork_lane_clear)
      - src の fork 側に他エッジの端点・手動 pin が来ない
        (対称スロット 0.35/0.65 の専有が前提)
      - 宛先コンテナに他エッジのコンテナ端点が付かない(固定配線は
        _fan_container_endpoints の重複解消から不可視のため)
      - 既存の固定折れ線(手動配線・先行 fork)と交差・7px 未満並走
        しない(fork は固定配線で後から避けられない)
      - 下コンテナ上辺の題字文字にレーンが載る場合は、上辺スタブと同じ
        _title_blocks/_nearest_free で最小シフト(空きが無ければ不発動)
    戻り値: eid → {"exit": (辺, frac), "entry": (辺, frac), "wps": [[x, y]]}
    (cont_route と同形式。fixed_route_poly・出力段の固定配線経路に乗る)。
    座標は全てレイアウト確定後の内部値で完結する(外部入力不要)。
    """
    routable_ids = {e["id"] for e in routable}
    by_src: dict[str, list[dict]] = {}
    for e in edges:
        by_src.setdefault(e.get("src"), []).append(e)
    out: dict[str, dict] = {}
    used_dst: set[str] = set()
    fixed = [list(map(tuple, p)) for p in fixed_polys]
    f_up, f_dn = FRAC_SLOTS[2]
    for e in routable:
        s = e["src"]
        if e["id"] in out:
            continue
        outgoing = by_src.get(s, ())
        if len(outgoing) != 2:
            continue
        if s not in lay.cell or s in lay.box_nodes or s in lay.diamond:
            continue
        e1, e2 = outgoing
        if not all(o["id"] in routable_ids and o["dst"] in lay.cmap
                   and o["dst"] not in used_dst for o in (e1, e2)):
            continue
        if e1["dst"] == e2["dst"] or \
                set(ancestors(lay, s)) & {e1["dst"], e2["dst"]}:
            continue
        sx, sy, sw, sh = lay.boxes[s]
        scx, scy = sx + sw / 2, sy + sh / 2
        dxs = [lay.center(o["dst"])[0] - scx for o in (e1, e2)]
        if all(d > 1.0 for d in dxs):
            side, sgn = "R", 1.0
        elif all(d < -1.0 for d in dxs):
            side, sgn = "L", -1.0
        else:
            continue    # 左右混在・真上下(縦 fork)は対象外 = 安全側
        eu, ed = sorted((e1, e2), key=lambda o: lay.center(o["dst"])[1])
        if not (lay.center(eu["dst"])[1] < scy < lay.center(ed["dst"])[1]):
            continue    # 1 上 1 下でない
        ub, db = lay.boxes[eu["dst"]], lay.boxes[ed["dst"]]
        y1, y2 = sy + f_up * sh, sy + f_dn * sh
        if ub[1] + ub[3] > y1 - FORK_GAP or db[1] < y2 + FORK_GAP:
            continue    # src がコンテナ間のトランク回廊に居ない
        if lay.pinned_ports.get((s, side)):
            continue    # fork 側に手動 pin(対称スロットを専有できない)
        blocked = False
        for o in edges:
            if o is e1 or o is e2:
                continue
            if o.get("src") in (eu["dst"], ed["dst"]) \
                    or o.get("dst") in (eu["dst"], ed["dst"]):
                blocked = True    # 宛先コンテナに他のコンテナ端点が付く
                break
            if s in (o.get("src"), o.get("dst")):
                t = o.get("src") if o.get("dst") == s else o.get("dst")
                if t == s or t not in lay.boxes \
                        or (lay.center(t)[0] - scx) * sgn > -1.0:
                    blocked = True    # fork 側から出入りする他エッジ
                    break
        if blocked:
            continue
        lo = max(ub[0], db[0]) + FORK_PAD
        hi = min(ub[0] + ub[2], db[0] + db[2]) - FORK_PAD
        if lo > hi:
            continue    # 宛先の x 範囲が(余白込みで)重ならない
        anchors = []
        for dst in (eu["dst"], ed["dst"]):
            cs = [lay.boxes[t][0] + lay.boxes[t][2] / 2
                  for t, p in lay.parents.items() if p == dst]
            if cs:
                anchors.append(min(cs) if sgn > 0 else max(cs))
        if len(anchors) < 2:
            continue    # 直下の子ボックスが無く先頭アンカーを取れない
        lane_x = min(max(min(anchors) if sgn > 0 else max(anchors), lo), hi)
        # 下コンテナ上辺の題字文字にレーンが載るなら最小シフト(R4-2 の
        # 上辺スタブと同じ規約: 矢先が題字の上に載るのは視認 NG)
        fx = _nearest_free(lane_x, lo, hi,
                           _title_blocks(lay, ed["dst"], y2) or [])
        if fx is None:
            continue    # 上辺が題字帯で覆い尽くされている
        lane_x = fx
        x0 = sx + sw if sgn > 0 else sx
        if (lane_x - x0) * sgn < FORK_PAD:
            continue    # トランク長を確保できない
        segs = [((x0, y1), (lane_x, y1)), ((x0, y2), (lane_x, y2)),
                ((lane_x, ub[1] + ub[3]), (lane_x, y1)),
                ((lane_x, y2), (lane_x, db[1]))]
        if not _fork_lane_clear(lay, segs, s):
            continue    # レーンが空いていない
        if _fork_seg_conflict(segs, fixed):
            continue    # 手動配線・先行 fork の固定折れ線と衝突
        fixed.extend([a, b] for a, b in segs)
        used_dst.update((eu["dst"], ed["dst"]))
        out[eu["id"]] = {"exit": (side, f_up),
                         "entry": ("B", (lane_x - ub[0]) / ub[2]),
                         "wps": [[lane_x, y1]]}
        out[ed["id"]] = {"exit": (side, f_dn),
                         "entry": ("T", (lane_x - db[0]) / db[2]),
                         "wps": [[lane_x, y2]]}
        print(f"INFO: fork 配線: '{s}' → '{eu['dst']}'(上)/'{ed['dst']}'"
              f"(下)を同一レーン x={lane_x:.0f} で二股化")
    return out


def validate_spec_edges(lay: Layout, edges: list[dict], kinds: dict | None) -> None:
    for e in edges:
        eid = e.get("id")
        if not eid:
            die(f"id のないエッジがあります: {e}")
        if edge_style(e, kinds) is None:
            die(f"edge '{eid}': kind '{e.get('kind')}' は未知です"
                f"(組み込み: {' / '.join(EDGE_STYLES)} か spec の kinds で定義)")
        for t in (e.get("src"), e.get("dst")):
            if t not in lay.boxes:
                die(f"edge '{eid}': 端点 '{t}' が未定義です")
        if (e["src"] != e["dst"] and e["src"] in lay.cell
                and e["dst"] in lay.cell
                and lay.cell[e["src"]] == lay.cell[e["dst"]]):
            die(f"edge '{eid}' の両端が同一セルです")


def _stretch_fn(jumps: dict[float, float]):
    """回廊座標→追加幅 の集合から単調な座標リマップ関数を作る。

    回廊線上の点(±0.5px)は広がった回廊の新しい中央へ、回廊より先の
    点は追加幅ぶんだけ平行移動する(区分線形・単調)。"""
    pts = sorted(jumps.items())

    def f(v: float) -> float:
        off = 0.0
        for c, d in pts:
            if v > c + 0.5:
                off += d
            elif abs(v - c) <= 0.5:
                off += d / 2
        return v + off
    return f


def _stretch_layout(lay: Layout, fx, fy) -> None:
    """レイアウト全体を座標リマップで引き伸ばす(構造・格子本数は不変)。"""
    def rect(b: Rect) -> Rect:
        x2, y2 = fx(b[0] + b[2]), fy(b[1] + b[3])
        x1, y1 = fx(b[0]), fy(b[1])
        return (x1, y1, x2 - x1, y2 - y1)
    lay.xs = [fx(x) for x in lay.xs]
    lay.ys = [fy(y) for y in lay.ys]
    lay.boxes = {k: rect(v) for k, v in lay.boxes.items()}
    lay.obstacles[:] = [rect(o) for o in lay.obstacles]
    lay.title_bands[:] = [rect(t) for t in lay.title_bands]
    lay.fullb = {k: rect(v) for k, v in lay.fullb.items()}


# ---- R5-D: 経路キャッシュ(慣性) ----
# 出力 .drawio と併置の <name>.routes.json に、タブごとの構成ハッシュと
# fan-out・伸長前の正準経路(route_all の出力)を保存する。次回ビルドは
# 同じ座標系(route_all は伸長前)で初期解として比較できる。
# 読み: ファイルが存在する場合のみ。書き: --route-cache 指定時、または
# 既存キャッシュの更新時のみ(テンプレ再生成・CI・eval の「同一 spec →
# バイト一致」検証に、キャッシュ無しの経路が混入しない安全側の既定)。

ROUTE_CACHE_VERSION = 2


def route_cache_path(out: Path) -> Path:
    return out.with_name(out.name.removesuffix(".drawio") + ".routes.json")


def route_cache_tab_key(spec: dict) -> str:
    """タブ名を型込みで安定 ID 化する。タブ順は ID に含めない。"""
    import hashlib
    raw = json.dumps(spec.get("name"), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def routes_struct_hash(spec: dict) -> str:
    """タブ構成(ノード/エッジ集合)のハッシュ。一致しないキャッシュは全体無効。

    含めるのは配置を決める集合だけ: ノードの id・col/row・parent・on_boundary、
    コンテナの id・parent、エッジの id・src/dst。pin(exit/entry/points)・
    ラベル・kind は含めない — pin 追加やラベル修正で無関係なエッジの経路が
    変わらないようにするのが慣性の目的(幾何のずれは _seed_geometry_ok と
    スコアゲートが安全側に落とす)。
    """
    import hashlib   # キャッシュ利用時のみ(起動 ~7ms を既定経路に乗せない)
    rows = []
    for n in spec.get("nodes") or []:
        rows.append(["n", n.get("id"), n.get("col"), n.get("row"),
                     n.get("parent"), n.get("on_boundary")])
    for c in spec.get("containers") or []:
        rows.append(["c", c.get("id"), c.get("parent")])
    for e in spec.get("edges") or []:
        rows.append(["e", e.get("id"), e.get("src"), e.get("dst")])
    blob = "\n".join(sorted(
        json.dumps(r, ensure_ascii=False, default=str) for r in rows))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_route_cache(path: Path) -> dict | None:
    """<name>.routes.json を読む。壊れていれば WARN してキャッシュ無し扱い。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARN: 経路キャッシュ {path.name} が読めないため無視します({exc})")
        return None
    if (not isinstance(data, dict) or data.get("version") != ROUTE_CACHE_VERSION
            or not isinstance(data.get("tabs"), list)):
        print(f"WARN: 経路キャッシュ {path.name} の形式が不明のため無視します"
              "(削除すれば次回ビルドで再生成されます)")
        return None
    return data


def _decode_route(obj) -> NodeRoute | None:
    """キャッシュ 1 エッジぶんを NodeRoute へ復元する。形が崩れていれば None。"""
    if not isinstance(obj, dict):
        return None
    ends = []
    for key in ("exit", "entry"):
        v = obj.get(key)
        if (not isinstance(v, (list, tuple)) or len(v) != 2
                or v[0] not in ("L", "R", "T", "B") or not _finite_num(v[1])
                or not 0.0 <= float(v[1]) <= 1.0):
            return None
        ends.append((v[0], float(v[1])))
    runs_in = obj.get("runs")
    if not isinstance(runs_in, list) or not runs_in:
        return None
    runs: list[Run] = []
    for rv in runs_in:
        if (not isinstance(rv, (list, tuple)) or len(rv) != 2
                or rv[0] not in ("h", "v") or not _finite_num(rv[1])):
            return None
        if runs and runs[-1].axis == rv[0]:
            return None    # 同軸の連続 Run は route_edge が作らない形
        runs.append(Run(rv[0], float(rv[1])))
    if (runs[0].axis != ("h" if ends[0][0] in "LR" else "v")
            or runs[-1].axis != ("h" if ends[1][0] in "LR" else "v")):
        return None
    direct = obj.get("direct", len(runs) == 1)
    if not isinstance(direct, bool) or (direct and len(runs) != 1):
        return None
    return NodeRoute(exit=ends[0], entry=ends[1], runs=runs, direct=direct)


def seed_routes_from_cache(cache: dict | None, idx: int, spec: dict,
                           current_keys: list[str] | None = None
                           ) -> tuple[dict[str, NodeRoute], bool] | None:
    """キャッシュからタブ名で対応付けた初期解を復元する。

    構成ハッシュ不一致(ノード/エッジ集合の変更)はタブ全体を無効化する。
    タブ名が現行 spec またはキャッシュ内で重複する場合も、安全側に無効化する。
    これによりタブの挿入・削除・並べ替えで別タブの経路を混入させない。
    壊れたエッジ項目は個別にスキップする(残りの慣性は生かす)。
    返り値: (シード, 前回ビルドの等化適用フラグ)。等化フラグは grid_to_abs が
    照合する — 等化ロールバック(R4-6)で非等化になったタブのシードを
    等化レイアウトに注入すると、ロールバック判定が変わり再ビルドが
    非冪等になるため(実測: multiaccount CI/CD タブ)。
    """
    if cache is None or not 0 <= idx:
        return None
    key = route_cache_tab_key(spec)
    if current_keys is not None and current_keys.count(key) != 1:
        return None
    matches = [tab for tab in cache["tabs"]
               if isinstance(tab, dict) and tab.get("key") == key]
    if len(matches) != 1:
        return None
    tab = matches[0]
    if tab.get("hash") != routes_struct_hash(spec):
        return None
    edges = tab.get("edges")
    if not isinstance(edges, dict):
        return None
    seeds: dict[str, NodeRoute] = {}
    for eid, obj in edges.items():
        route = _decode_route(obj)
        if route is not None:
            seeds[eid] = route
    if not seeds:
        return None
    return seeds, bool(tab.get("equalized"))


def unique_route_cache_tabs(cache: dict) -> dict[str, dict]:
    """一意な tab key だけを O(n) で索引化する。重複 key は除外する。"""
    indexed: dict[str, dict] = {}
    duplicates: set[str] = set()
    for tab in cache.get("tabs") or []:
        if not isinstance(tab, dict) or not isinstance(tab.get("key"), str):
            continue
        key = tab["key"]
        if key in indexed:
            duplicates.add(key)
        else:
            indexed[key] = tab
    for key in duplicates:
        indexed.pop(key, None)
    return indexed


def encode_route_snapshot(routes: dict[str, NodeRoute]) -> dict:
    """route_all 直後(fan-out・伸長前)の経路をキャッシュ形式へ直列化する。"""
    return {eid: {"exit": [r.exit[0], r.exit[1]],
                  "entry": [r.entry[0], r.entry[1]],
                  "runs": [[run.axis, run.coord] for run in r.runs],
                  "direct": r.direct}
            for eid, r in sorted(routes.items()) if isinstance(r, NodeRoute)}


def grid_to_abs(spec: dict, icons: dict,
                seed_routes: dict[str, NodeRoute] | None = None,
                seed_equalized: bool = False) -> dict:
    """グリッドスペック 1 タブぶんを絶対座標スペックへ変換する。

    seed_routes は前回ビルドの経路(R5-D)。route_all がスコア非悪化の範囲で
    維持する。seed_equalized(前回の等化適用状態)が今回と食い違う場合、
    シードは座標系が別物なので使わない。返り値には次回ビルド用
    スナップショット "_routes_out" が付く(呼び出し側 _build が pop して
    .routes.json へ保存する)。
    """
    validate_spec(spec)
    edges = spec.get("edges", [])
    kinds = spec.get("kinds")
    # 手動配線(exit+entry+points 直書き)の座標は描画後の最終座標として扱う
    manual_ids = {e["id"] for e in edges if "exit" in e and "entry" in e}

    # legend の網羅チェック(規約を暗黙にしない)
    used_kinds = {e.get("kind", "main") for e in edges}
    legend = spec.get("legend")
    if legend:
        listed = set(legend) if isinstance(legend, dict) \
            else {d.get("kind") for d in legend}
        missing = sorted(used_kinds - listed)
        if missing:
            print(f"WARN: 使用中の線種が legend に載っていません: {missing}")
            BUILD_WARNS.append("legend 未掲載")
    elif len(used_kinds) > 1:
        print(f"WARN: 線種を {len(used_kinds)} 種使っていますが legend がありません"
              "(意味の規約を明示してください)")
        BUILD_WARNS.append("legend なし")
    lay, out_conts, out_nodes = place(spec, icons)
    if seed_routes is not None and lay.equalized != seed_equalized:
        # R5-D: 等化ロールバック(R4-6)の境界をまたぐシードは座標系が別物。
        # 使うとロールバック判定が変わり、再ビルドが非冪等になる
        seed_routes = None
    validate_spec_edges(lay, edges, kinds)
    manual_edges, routable, fixed_routes, fixed_polys = classify_edges(lay, edges)

    # R5-B: fork(中心からの二股)を固定配線として生成。他エッジは手動 pin と
    # 同様にこれを避けて配線される(register_poly+交差カウント)。fixed_routes
    # に入るため回廊過負荷の引き伸ばしは自動的に見送られる(固定配線の絶対
    # 座標が伸長でずれるのを防ぐ既存の安全条件と同じ理由)
    forks = detect_center_forks(lay, edges, routable, fixed_polys)
    if forks:
        routable = [e for e in routable if e["id"] not in forks]
        by_eid = {e2["id"]: e2 for e2 in edges}
        for eid, fr in forks.items():
            fixed_routes[eid] = fr
            fixed_polys.append(fixed_route_poly(lay, by_eid[eid], fr))

    router = Router(lay.xs, lay.ys, lay.obstacles,
                    borders=[lay.boxes[cid] for cid in lay.cmap],
                    title_bands=lay.title_bands)
    routes = route_all(router, lay, routable, fixed_polys, kinds,
                       seed_routes=seed_routes)

    # 到達不能エッジ: クリアランスを緩めて再探索(貫通する単純配線は最後の砦)
    relaxed: Router | None = None
    for e in routable:
        eid = e["id"]
        if eid in routes:
            continue
        if relaxed is None:
            icon_only = [lay.boxes[nid] for nid in lay.cell]
            relaxed = Router(lay.xs, lay.ys, icon_only, clearance=2)
        found = route_edge(relaxed, lay, e)
        if found is not None:
            routes[eid] = found[0]
            print(f"WARN: edge '{eid}' は過密のためクリアランスを縮めて配線しました"
                  "(ラベルに近接する可能性)")
            BUILD_WARNS.append(f"クリアランス縮小配線({eid})")
        else:
            fixed_routes[eid] = cont_route(lay, e)
            print(f"WARN: edge '{eid}' の自動配線に失敗し直線的な代替配線にしました"
                  "(貫通の可能性)。src/dst を相手の隣接列に移すか、"
                  "コンテナ端点への集約を検討してください")
            BUILD_WARNS.append(f"代替配線({eid})")

    # R5-D: 経路キャッシュ用スナップショット(fan-out・伸長で経路が変異する
    # 前に取る。route_all は伸長前の座標系で動くため、次回もこの形で比較できる)
    routes_snapshot = encode_route_snapshot(routes)

    fan_out(lay, routable, routes)
    geo = node_geometries(lay, routable, routes)

    # 回廊の過負荷検出 → レイアウトを引き伸ばして幅を作る(再ルーティング
    # なし)。粗いトポロジでは 1 本の回廊に 10 本超のランが集まり、レーン
    # 圧縮が E7(6px 未満の重走)を量産する。物理的に幅が足りないのだから
    # 図の方を広げるのが正しい。ルートの組合せ構造(回廊割当・交差)は
    # 保ったまま座標だけ動かすので、再収束の劣化も追加の探索時間もない。
    # 手動配線・固定配線があるときは絶対座標がずれるため安全側で見送る
    if not manual_edges and not fixed_routes:
        def _inside_icon(axis_: str, coord_: float) -> bool:
            # 崩壊レイアウト(未使用列の潰し)では回廊線がノード箱の内部と
            # 同座標になり得る。そこで伸長すると箱の片側だけがジャンプを
            # またいでアイコンが横に伸び、線(d/2 移動)と端点(d 移動)の
            # 不整合で斜め線も生む — その回廊は広げない(残 E7 は許容)
            for nid_ in lay.cell:
                bx_, by_, bw_, bh_ = lay.boxes[nid_]
                if axis_ == "v":
                    if bx_ + 1 < coord_ < bx_ + bw_ - 1:
                        return True
                elif by_ + 1 < coord_ < by_ + bh_ - 1:
                    return True
            return False

        for _pass in range(3):   # 伸長で群が組み替わるため残需要を反復解消
            demand: dict[tuple, float] = {}
            assign_lanes(lay, routable, routes, demand_out=demand)
            xjumps: dict[float, float] = {}
            yjumps: dict[float, float] = {}
            top_ids = [cid for cid in lay.cmap
                       if lay.parents.get(cid) is None]
            for (axis, coord), need in demand.items():
                if _inside_icon(axis, coord):
                    continue
                need = min(need, 240.0)
                jumps = xjumps if axis == "v" else yjumps
                matched = False
                # b=0 / C+1(R+1)はページ外周道路 — コンテナのない図の
                # 過負荷はここに集まる。同じジャンプで余白帯ごと太らせる
                if axis == "v":  # 縦ラン → x 方向の余地 → 縦回廊を広げる
                    for b in range(0, lay.C + 2):
                        xj = lay.xs[lay.xi_corr[b]]
                        if abs(xj - coord) < 0.6:
                            jumps[xj] = max(jumps.get(xj, 0.0), need)
                            matched = True
                            break
                else:            # 横ラン → y 方向の余地 → 横回廊を広げる
                    for b in range(0, lay.R + 2):
                        yj = lay.ys[lay.yi_corr[b]]
                        if abs(yj - coord) < 0.6:
                            jumps[yj] = max(jumps.get(yj, 0.0), need)
                            matched = True
                            break
                if matched:
                    continue
                # 内周ガター(トップレベルコンテナの枠線から 12px 内側)の
                # 過負荷: ガター線上にジャンプを置くと、枠線は動かず中身が
                # 離れて帯が太る(ガター線自体は d/2 移動して帯の中央に残る)。
                # 上辺は題字帯が同じ帯に居るため対象外(需要は残 E7 として許容)
                for cid in top_ids:
                    bx_, by_, bw_, bh_ = lay.boxes[cid]
                    cands = ((bx_ + 12.0, bx_ + bw_ - 12.0) if axis == "v"
                             else (by_ + bh_ - 12.0,))
                    hit = next((g_ for g_ in cands
                                if abs(g_ - coord) < 0.6), None)
                    if hit is not None:
                        jumps[hit] = max(jumps.get(hit, 0.0), need)
                        break
            if not xjumps and not yjumps:
                break
            fx_, fy_ = _stretch_fn(xjumps), _stretch_fn(yjumps)
            old_boxes = dict(lay.boxes)
            _stretch_layout(lay, fx_, fy_)
            for r in routes.values():
                for run in r.runs:
                    run.coord = (fx_(run.coord) if run.axis == "v"
                                 else fy_(run.coord))
            # frac は箱に対する比例位置 — 箱の幅が伸びると絶対位置がずれる
            # (コンテナ端点で顕在化)。旧絶対点を座標変換して frac を取り直す
            def _side_pt(b_: Rect, side_: str, f_: float) -> Point:
                x_, y_, w_, h_ = b_
                return {"L": (x_, y_ + f_ * h_), "R": (x_ + w_, y_ + f_ * h_),
                        "T": (x_ + f_ * w_, y_), "B": (x_ + f_ * w_, y_ + h_)}[side_]
            for e_ in routable:
                r_ = routes.get(e_["id"])
                if not isinstance(r_, NodeRoute):
                    continue
                for term_, at_ in (("src", "exit"), ("dst", "entry")):
                    tid_ = e_[term_]
                    if tid_ not in old_boxes:
                        continue
                    side_, f_ = getattr(r_, at_)
                    opx, opy = _side_pt(old_boxes[tid_], side_, f_)
                    npx, npy = fx_(opx), fy_(opy)
                    nx_, ny_, nw_, nh_ = lay.boxes[tid_]
                    nf_ = ((npy - ny_) / nh_ if side_ in "LR"
                           else (npx - nx_) / nw_)
                    setattr(r_, at_, (side_, nf_))
            for oc in out_conts:
                x2, y2 = fx_(oc["x"] + oc["w"]), fy_(oc["y"] + oc["h"])
                x1, y1 = fx_(oc["x"]), fy_(oc["y"])
                oc.update({"x": g0(x1), "y": g0(y1),
                           "w": g0(x2 - x1), "h": g0(y2 - y1)})
            for on in out_nodes:
                on["cx"], on["cy"] = g0(fx_(on["cx"])), g0(fy_(on["cy"]))
            geo = node_geometries(lay, routable, routes)

    # 大回りしたエッジを報告(配置改善の手掛かり。ルータは黙って迂回を選ぶため)
    detours = []
    for e in routable:
        g = geo.get(e["id"])
        if g is None:
            continue
        sp, ep, wps = g
        plen = poly_len([sp] + [tuple(p) for p in wps] + [ep])
        (sx, sy), (dx_, dy_) = lay.center(e["src"]), lay.center(e["dst"])
        manh = abs(sx - dx_) + abs(sy - dy_)
        if is_detour(plen, manh):
            bx1, bx2 = sorted((sx, dx_))
            by1, by2 = sorted((sy, dy_))
            blockers = [nid for nid, (c, r) in lay.cell.items()
                        if nid not in (e["src"], e["dst"])
                        and _rect_hits(lay.boxes[nid],
                                       (bx1 - 10, by1 - 10,
                                        bx2 - bx1 + 20, by2 - by1 + 20))]
            note = f"(直線帯上のノード: {', '.join(blockers[:4])})" if blockers else ""
            detours.append((plen / manh,
                            f"HINT: edge '{e['id']}' は直線距離の "
                            f"{plen / manh:.1f} 倍に迂回 {note}"))
    detours.sort(reverse=True)
    for _, msg in detours[:5]:
        print(msg)

    # ハブ次数の HINT(配置原則6): 次数7以上はグリッド配線で原理的に交差が増える
    for nid, d in sorted(icon_degree_map(lay, edges).items(),
                         key=lambda kv: -kv[1]):
        if d >= 7:
            print(f"HINT: '{nid}' の次数が {d}。接続相手を8近傍リングに配置するか"
                  f"コンテナ端点への集約を検討(配置原則6)")

    # 端点座標化 → 直線化(ジョグ潰し)→ ラベル確定
    out_edges = []
    pending = []   # 格子配線エッジ: (oe, e, poly)。直線化後に points を確定
    for e in edges:
        oe = dict(e)
        eid = e["id"]
        sp = ep = None
        if e["src"] == e["dst"] and "exit" not in e:
            # 自己参照(ER の社員→上司など): 側面のコの字ループで描く。
            # 他エッジの少ない側を優先する。ラベルはループ縦線セグメントの
            # 外側に置き、ノード・題字と重ならない y を探索。収まらなければ
            # 反対辺へ切り替える(R7-2: 旧来のブラケット内配置は高い entity
            # 箱+隣接密集で必ず E5 になった)
            bx, by, bw, bh = lay.boxes[e["src"]]
            off = 28.0
            side_use = {"L": 0, "R": 0}
            for e2 in edges:
                r2_ = routes.get(e2["id"])
                if not isinstance(r2_, NodeRoute):
                    continue
                if e2["src"] == e["src"] and r2_.exit[0] in side_use:
                    side_use[r2_.exit[0]] += 1
                if e2["dst"] == e["src"] and r2_.entry[0] in side_use:
                    side_use[r2_.entry[0]] += 1

            def strip_clear(x0: float) -> bool:
                for ox, oy, ow, oh in lay.obstacles:
                    if (x0 < ox + ow and ox < x0 + off + 6
                            and by < oy + oh and oy < by + bh):
                        return False
                return True
            pick_r = (side_use["R"], not strip_clear(bx + bw + 2))
            pick_l = (side_use["L"], not strip_clear(bx - off - 4))
            side = "R" if pick_r <= pick_l else "L"
            lbl_at = None
            if e.get("label"):
                lw_, lh_ = text_size(str(e["label"]), 11)

                def label_slot(s2: str) -> Point | None:
                    """縦線の外側で障害物・題字と重ならないラベル中心を探す。"""
                    xo2 = bx + bw + off if s2 == "R" else bx - off
                    sgn = 1.0 if s2 == "R" else -1.0
                    lx = xo2 + sgn * (lw_ / 2 + 5)
                    ymid = by + 0.5 * bh   # 縦線セグメント(0.3h〜0.7h)の中点
                    lo, hi = by, by + bh + lh_ + 12
                    cands = [ymid]
                    k = 8.0
                    while ymid + k <= hi or ymid - k >= lo:
                        if ymid + k <= hi:
                            cands.append(ymid + k)
                        if ymid - k >= lo:
                            cands.append(ymid - k)
                        k += 8.0
                    obs = list(lay.obstacles) + list(lay.title_bands)
                    for ly in cands:
                        box = (lx - lw_ / 2 - 2, ly - lh_ / 2 - 2,
                               lw_ + 4, lh_ + 4)
                        if not any(_rect_hits(box, ob) for ob in obs):
                            return lx, ly
                    return None

                for s2 in (("R", "L") if pick_r <= pick_l else ("L", "R")):
                    pos = label_slot(s2)
                    if pos is not None:
                        side, lbl_at = s2, pos
                        break
            if side == "R":
                xw, xo = bx + bw, bx + bw + off
            else:
                xw, xo = bx, bx - off
            sp = (xw, by + 0.3 * bh)
            ep = (xw, by + 0.7 * bh)
            oe["exit"] = to_frac(side, 0.3)
            oe["entry"] = to_frac(side, 0.7)
            oe["points"] = [[g0(xo), g0(sp[1])], [g0(xo), g0(ep[1])]]
            if e.get("label"):
                if lbl_at is None:   # 両辺とも塞がっている: 旧来位置で最善努力
                    lbl_at = ((xw + xo) / 2, ep[1] + lh_ / 2 + 7)
                oe["label_at"] = [g0(lbl_at[0]), g0(lbl_at[1])]
            pending.append((oe, e, None,
                            [sp, (xo, sp[1]), (xo, ep[1]), ep]))
            out_edges.append(oe)
            continue
        if eid in geo:
            r = routes[eid]
            sp, ep, wps = geo[eid]
            oe["exit"] = to_frac(r.exit[0], round(r.exit[1], 4))
            oe["entry"] = to_frac(r.entry[0], round(r.entry[1], 4))
            pending.append((oe, e, r, [sp] + [tuple(p) for p in wps] + [ep]))
        elif fixed_routes.get(eid) is not None:
            r2 = fixed_routes[eid]
            sp = lay.side_point(e["src"], *r2["exit"])
            ep = lay.side_point(e["dst"], *r2["entry"])
            wps = r2["wps"]
            oe["exit"] = to_frac(r2["exit"][0], round(r2["exit"][1], 4))
            oe["entry"] = to_frac(r2["entry"][0], round(r2["entry"][1], 4))
            oe["points"] = [[g0(p[0]), g0(p[1])] for p in wps]
            pending.append((oe, e, None,
                            [sp] + [tuple(p) for p in wps] + [ep]))
        out_edges.append(oe)
    all_polys = [poly for _, _, _, poly in pending]
    edge_bounds = {e["id"]: lca_bounds(lay, e["src"], e["dst"])
                   for _, e, r, poly in pending if r is not None}
    def _anc(tid: str) -> set:
        out: set[str] = set()
        t: str | None = tid
        while t is not None:
            out.add(t)
            t = lay.parents.get(t)
        return out

    straighten_polys(lay, [
        (poly, lay.boxes[e["src"]], e["src"] not in lay.diamond,
         lay.boxes[e["dst"]], e["dst"] not in lay.diamond,
         edge_bounds[e["id"]], (e["src"], e["dst"]),
         _anc(e["src"]) | _anc(e["dst"]),
         lay.diamond_bans.get(e["id"], frozenset()))
        for _, e, r, poly in pending if r is not None])
    separate_terminals(lay, pending, edge_bounds)
    dodge_title_bands(lay, pending, edge_bounds)
    separate_corun_runs(lay, pending, edge_bounds)
    snap_diamond_ends(lay, pending)   # R7-16: 頂点固定の最終安全網
    borders = container_borders(lay)

    def side_frac(box: Rect, side: str, pt: Point) -> float:
        x, y, w, h = box
        return (pt[1] - y) / h if side in "LR" else (pt[0] - x) / w

    placed: list[tuple] = []
    for oe, e, r, poly in pending:
        if r is not None:
            # 直線化・端点分離で端点が辺上を動き(リシェイプでは辺の
            # 付け替えもあり)得るため、辺と frac を座標から再計算する
            sbx = lay.boxes[e["src"]]
            s_side = point_side(sbx, poly[0], r.exit[0])
            d_side = point_side(lay.boxes[e["dst"]], poly[-1], r.entry[0])
            oe["exit"] = to_frac(s_side, round(
                side_frac(sbx, s_side, poly[0]), 4))
            oe["entry"] = to_frac(d_side, round(
                side_frac(lay.boxes[e["dst"]], d_side, poly[-1]), 4))
            if s_side == "B" and poly[0][1] > sbx[1] + sbx[3] + 1:
                # キャプション下アンカー: 実端点はアイコン下辺から exit_dy
                # だけ下(AWS 公式の「キャプションの真下から出る」流儀)
                oe["exit_dy"] = g0(poly[0][1] - (sbx[1] + sbx[3]))
            oe["points"] = [[g0(x), g0(y)] for x, y in poly[1:-1]]
        if e.get("label"):
            if "label_at" not in oe:
                oe["label_at"] = pick_label_at(lay, e["label"], poly,
                                               all_polys, placed, borders)
            lw, lh = text_size(str(e["label"]), 11)
            lx, ly = oe["label_at"]
            placed.append((lx - lw / 2, ly - lh / 2, lx + lw / 2, ly + lh / 2))
        for label_key, at_end in (("src_label", False), ("dst_label", True)):
            if not e.get(label_key):
                continue
            at_key = label_key + "_at"
            if at_key not in oe:
                oe[at_key] = pick_end_label_at(
                    lay, e[label_key], poly, at_end, all_polys, placed, borders)
            lw, lh = text_size(str(e[label_key]), 11)
            lx, ly = oe[at_key]
            placed.append((lx - lw / 2, ly - lh / 2,
                           lx + lw / 2, ly + lh / 2))

    # リファレンスアーキテクチャ図: 番号バッジ(step)を実体化する。
    # ノードのバッジはアイコン右上角に重ねる(AWS 公式一頁物の流儀)。
    # エッジのバッジはラベルと同じ衝突回避で経路上に置く(Guidance 系の変種)
    step_nums = []
    for e in manual_edges:
        if isinstance(e.get("step"), int):  # 座標系が混在し自動配置できない
            print(f"WARN: edge '{e['id']}' は手動配線(exit/entry 直書き)のため "
                  "step バッジを自動配置できません。番号は src/dst ノード側に"
                  "振ってください(バッジは描画されません)")
            BUILD_WARNS.append(f"step バッジ未描画({e['id']})")
    for oe, e, r, poly in pending:
        st = e.get("step")
        if isinstance(st, bool) or not isinstance(st, int):
            continue
        step_nums.append(st)
        bx, by = pick_label_at(lay, str(st), poly, all_polys, placed, borders)
        out_nodes.append({"id": f"_step_{e['id']}", "badge": st,
                          "x": g0(bx - 11), "y": g0(by - 11), "w": 22, "h": 22})
        placed.append((bx - 11, by - 11, bx + 11, by + 11))
    for n in spec.get("nodes") or []:
        st = n.get("step")
        if isinstance(st, bool) or not isinstance(st, int):
            continue
        step_nums.append(st)
        nx, ny, nw_, _nh = lay.boxes[n["id"]]
        out_nodes.append({"id": f"_step_{n['id']}", "badge": st,
                          "x": g0(nx + nw_ - 12), "y": g0(ny - 10),
                          "w": 22, "h": 22})
    steps_list = spec.get("steps") or []
    if step_nums or steps_list:
        missing = sorted(set(range(1, max(step_nums, default=0) + 1))
                         - set(step_nums))
        msgs = []
        if missing:
            msgs.append(f"番号に欠番があります: {missing}")
        if steps_list and step_nums and len(steps_list) != max(step_nums):
            msgs.append(f"steps の説明が {len(steps_list)} 件に対し"
                        f"図中の最大番号が {max(step_nums)}")
        if steps_list and not step_nums:
            msgs.append("steps の説明だけがあり、図中に step バッジがありません")
        if step_nums and not steps_list:
            msgs.append("step バッジだけがあり、steps の説明パネルがありません")
        for m in msgs:
            print(f"WARN: {m}(step は 1 から連番で、steps と 1:1 に対応させる)")
            BUILD_WARNS.append("step 不整合")

    maxx = max(b[0] + b[2] for b in lay.boxes.values())
    maxy = max(b[1] + b[3] for b in lay.boxes.values())
    # 凡例・ページ寸法はエッジの経路とラベルも含めて算出する
    # (経路の下を凡例が塞ぐと、枠線とエッジが同一直線で融合して見える)
    for _, _, _, poly in pending:
        for px_, py_ in poly:
            maxx = max(maxx, px_ + 12)
            maxy = max(maxy, py_ + 12)
    for pb in placed:
        maxx = max(maxx, pb[2] + 8)
        maxy = max(maxy, pb[3] + 8)

    if steps_list:  # 公式一頁物の型: 図の右側に薄グレーの縦パネル
        snode, s_w, s_h = build_steps(steps_list, maxx + 30, 0.0)
        out_nodes.append(snode)
        maxx += 30 + s_w
        maxy = max(maxy, s_h)

    if spec.get("legend"):
        cont, lg_nodes, lg_edges, lg_h = build_legend(spec["legend"], kinds,
                                                      MARGIN, maxy + 30)
        out_conts.append(cont)
        out_nodes.extend(lg_nodes)
        out_edges.extend(lg_edges)
        maxy += 30 + lg_h

    if spec.get("meta"):
        mnode, dy = build_meta(spec["meta"])
        tnode = None
        if steps_list and spec.get("name"):  # 公式の型: 左上に大きなタイトル
            tnode = {"id": "_title", "text": str(spec["name"]),
                     "x": MARGIN, "y": 6,
                     "w": g0(text_width(str(spec["name"]), 20) + 12), "h": 30,
                     "style_extra": "fontSize=20;fontStyle=1;fontColor=#232F3E;"}
            mnode["y"] = g0(mnode["y"] + 34)
            dy += 34
        for c in out_conts:
            c["y"] = g0(c["y"] + dy)
        for n in out_nodes:
            if "cy" in n:
                n["cy"] = g0(n["cy"] + dy)
            else:
                n["y"] = g0(n["y"] + dy)
        for e in out_edges:
            if e["id"] in manual_ids:
                continue  # 手動配線の points/label_at は描画後の最終座標として扱う
            if e.get("points"):
                e["points"] = [[p[0], g0(p[1] + dy)] for p in e["points"]]
            if e.get("label_at"):
                e["label_at"] = [e["label_at"][0], g0(e["label_at"][1] + dy)]
            for key in ("src_at", "dst_at", "src_label_at", "dst_label_at"):
                if e.get(key):
                    e[key] = [e[key][0], g0(e[key][1] + dy)]
        out_nodes.insert(0, mnode)
        if tnode is not None:
            out_nodes.insert(0, tnode)
        maxy += dy
    else:
        print("WARN: meta(目的/読者/スコープ/抽象度/前提)が未指定です。"
              '"meta": {"purpose": ...} を必ず書いてください(図の冒頭に描画されます)')
        BUILD_WARNS.append("meta 未指定")

    out = {"name": spec.get("name"),
           "page": spec.get("page") or [int(maxx + 80), int(maxy + 120)],
           "containers": out_conts, "nodes": out_nodes, "edges": out_edges}
    if spec.get("kinds"):
        out["kinds"] = spec["kinds"]
    if spec.get("badge_style"):
        out["badge_style"] = spec["badge_style"]
    if lay.equalized:   # R4-6: _build の結果ロールバック用の内部マーカー
        out["_equalized"] = True
    # R5-D: _build が pop して .routes.json へ保存する(等化状態も照合用に記録)
    out["_routes_out"] = {"equalized": lay.equalized, "edges": routes_snapshot}
    return out


META_KEYS = (("purpose", "目的"), ("audience", "読者"), ("scope", "スコープ"),
             ("abstraction", "抽象度"), ("updated", "更新日"),
             ("assumptions", "前提"))


def build_meta(meta: dict) -> tuple[dict, float]:
    """図の冒頭に置くメタ情報パネル(テキストノード)と、図全体を下げる量を返す。

    updated が無ければ生成日を自動で入れる。
    """
    import datetime
    vals = dict(meta)
    vals.setdefault("updated", datetime.date.today().isoformat())
    unknown = sorted(set(vals) - {k for k, _ in META_KEYS})
    if unknown:
        die(f"meta の未知キー: {unknown}(使えるキー: {[k for k, _ in META_KEYS]})")
    lines = [f"{jp}: {vals[k]}" for k, jp in META_KEYS if vals.get(k)]
    w = min(1200.0, max(text_width(ln, 11) for ln in lines) + 12)
    h = 18.0 * len(lines)
    node = {"id": "_meta", "text": "<br>".join(lines),
            "x": MARGIN, "y": 26, "w": g0(w), "h": g0(h)}
    return node, h + 30


def build_steps(steps: list, x0: float, y0: float) -> tuple[dict, float, float]:
    """リファレンスアーキテクチャ図のステップ説明パネル(図の右側の縦パネル)。

    AWS 公式一頁物の型: 薄グレー背景に「番号+説明 1〜3 文」を縦に並べる。
    番号は図中の step バッジと対応する。
    """
    W = 360.0
    lines = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    # whiteSpace=wrap で draw.io 側が折り返すぶんの高さを見積もる
    inner = W - 24.0
    rows = sum(max(1, math.ceil(text_width(ln, 11) / inner)) for ln in lines)
    h = rows * 17.0 + len(lines) * 8.0 + 16.0
    node = {"id": "_steps", "text": "<br><br>".join(lines),
            "x": g0(x0), "y": g0(y0), "w": g0(W), "h": g0(h),
            "style_extra": ("fillColor=#F2F3F3;strokeColor=#D5DBDB;"
                            "fontColor=#232F3E;verticalAlign=top;spacing=8;"
                            "spacingLeft=10;spacingRight=10;")}
    return node, W, h


def build_legend(legend, kinds: dict | None, x0: float,
                 y0: float) -> tuple[dict, list, list, float]:
    """凡例ボックス(線種サンプル+説明)を絶対座標で生成する。

    legend: {"main": "同期呼び出し", ...} または [{"kind":..,"label":..}, ...]。
    kind はカスタム線種(spec.kinds)も使える。
    """
    if isinstance(legend, dict):
        items = list(legend.items())
    else:
        items = [(d["kind"], d["label"]) for d in legend]
    if not items:
        die("legend が空です")
    for kind, _ in items:
        if edge_style({"kind": kind}, kinds) is None:
            die(f"legend: kind '{kind}' は未知です"
                f"({sorted(EDGE_STYLES)} か spec の kinds で定義)")
    maxw = max(text_size(lbl, 11)[0] for _, lbl in items)
    w = 110 + maxw + 30
    h = 85.0 + (len(items) - 1) * 40
    cont = {"id": "_legend", "label": "凡例", "type": "generic",
            "x": g0(x0), "y": g0(y0), "w": g0(w), "h": g0(h)}
    nodes, edges = [], []
    for i, (kind, label) in enumerate(items):
        y = y0 + 55 + i * 40
        edges.append({"id": f"_lg_e{i}", "kind": kind,
                      "src_at": [g0(x0 + 15), g0(y)], "dst_at": [g0(x0 + 75), g0(y)]})
        nodes.append({"id": f"_lg_t{i}", "text": label, "parent": "_legend",
                      "x": g0(x0 + 95), "y": g0(y - 10),
                      "w": g0(text_size(label, 11)[0] + 4), "h": 20})
    return cont, nodes, edges, h


# ====================================================================
# 絶対座標スペック → 簡易プレビュー SVG(--emit-svg)
# ====================================================================

def _sv(style: str, key: str, default: str) -> str:
    # style は後勝ち(カスタム kinds が base の色を上書きする)ため最後の値を採る
    m = re.findall(rf"{key}=([^;]+)", style)
    return m[-1] if m else default


def _wrap_text_px(s: str, max_w: float, size: float) -> str:
    """whiteSpace=wrap の draw.io 描画を近似: 各行を max_w px で折り返す。

    実 .drawio はパネル内で折り返すのに簡易 SVG がはみ出して見え、
    エージェントが「見切れ?」の偽疑いを踏む問題への対処。空白があれば
    語境界で、無ければ(和文)文字単位で折る。"""
    if max_w <= 0:
        return str(s)
    out_lines: list[str] = []
    for ln in str(s).replace("<br>", "\n").split("\n"):
        while text_width(ln, size) > max_w and len(ln) > 1:
            # max_w に収まる最長の切り出し位置を二分探索
            lo, hi = 1, len(ln)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if text_width(ln[:mid], size) <= max_w:
                    lo = mid
                else:
                    hi = mid - 1
            cut = lo
            sp = ln.rfind(" ", 0, cut + 1)
            if sp > 0 and text_width(ln[:sp], size) <= max_w:
                cut = sp
                out_lines.append(ln[:cut])
                ln = ln[cut + 1:]          # 語境界: 空白は捨てる
            else:
                out_lines.append(ln[:cut])
                ln = ln[cut:]
        out_lines.append(ln)
    return "\n".join(out_lines)


def _svg_text(x: float, y: float, s, size: float = 12, color: str = "#232F3E",
              anchor: str = "middle", bold: bool = False,
              italic: bool = False) -> str:
    lines = str(s).replace("<br>", "\n").split("\n")
    fw = ' font-weight="bold"' if bold else ""
    fs = ' font-style="italic"' if italic else ""
    spans = "".join(
        f'<tspan x="{x:.0f}" dy="{0 if i == 0 else size + 4:.0f}">{esc(ln)}</tspan>'
        for i, ln in enumerate(lines))
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}"{fw}{fs}>{spans}</text>')


def _svg_marker(p1: Point, p2: Point, color: str, arrow: str,
                fill: bool) -> str:
    """終端 p2 に向かうマーカーを描く(.drawio の startArrow/endArrow を再現)。

    open=シェブロン / block=三角(fill で塗り)/ diamondThin=ひし形 /
    ERone=直交バー / ERzeroToOne=円+バー / ERmandOne=二重バー /
    ERmany=クロウズフット / ERzeroToMany=クロウズフット+円 /
    none=なし。プレビューでも記法(継承・コンポジション・多重度)を判別
    できるようにする(実利用 QA: ER/UML の凡例が全部同じに見えた)。
    """
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    ln = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux            # 直交方向
    def pt(back: float, side: float) -> str:
        return f"{x2 - ux * back + px * side:.1f},{y2 - uy * back + py * side:.1f}"
    if arrow == "none":
        return ""
    if arrow == "block":
        f = color if fill else "#FFFFFF"
        return (f'<polygon points="{pt(0, 0)} {pt(12, 5.5)} {pt(12, -5.5)}" '
                f'fill="{f}" stroke="{color}"/>')
    if arrow == "diamondThin":
        f = color if fill else "#FFFFFF"
        return (f'<polygon points="{pt(0, 0)} {pt(8, 4.5)} {pt(16, 0)} '
                f'{pt(8, -4.5)}" fill="{f}" stroke="{color}"/>')
    if arrow == "ERone":
        return (f'<path d="M {pt(8, 6)} L {pt(8, -6)}" fill="none" '
                f'stroke="{color}"/>')
    if arrow == "ERzeroToOne":
        cx = x2 - ux * 14
        cy = y2 - uy * 14
        return (f'<path d="M {pt(5, 6)} L {pt(5, -6)}" fill="none" '
                f'stroke="{color}"/><circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" '
                f'fill="#FFFFFF" stroke="{color}"/>')
    if arrow == "ERmandOne":
        return (f'<path d="M {pt(4, 6)} L {pt(4, -6)} M {pt(10, 6)} '
                f'L {pt(10, -6)}" fill="none" stroke="{color}"/>')
    if arrow in ("ERmany", "ERzeroToMany"):
        crow = (f'<path d="M {pt(10, 0)} L {pt(0, 6)} M {pt(10, 0)} L '
                f'{pt(0, 0)} M {pt(10, 0)} L {pt(0, -6)}" fill="none" '
                f'stroke="{color}"/>')
        if arrow == "ERzeroToMany":
            cx = x2 - ux * 15
            cy = y2 - uy * 15
            crow += (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" '
                     f'fill="#FFFFFF" stroke="{color}"/>')
        return crow
    # 既定: open シェブロン
    a = (x2 - ux * 8 - uy * 4.5, y2 - uy * 8 + ux * 4.5)
    b = (x2 - ux * 8 + uy * 4.5, y2 - uy * 8 - ux * 4.5)
    return (f'<path d="M {a[0]:.1f} {a[1]:.1f} L {x2:.1f} {y2:.1f} '
            f'L {b[0]:.1f} {b[1]:.1f}" fill="none" stroke="{color}"/>')


def emit_svg(spec: dict, icons: dict) -> str:
    """絶対座標スペックから自己確認用の簡易 SVG を描く(--emit-svg)。

    アイコンは公式アイコン色の矩形で代用する。幾何(配置・配線・ラベル)は
    本番 XML と同じ内部データから描くので、迂回・重なり・バランスの
    目視確認に足りる。外部リソース参照なしの自己完結 SVG。
    """
    kinds = spec.get("kinds")
    diamond_ids = {n["id"] for n in spec.get("nodes", [])
                   if n.get("shape") in ("decision", "gateway")}
    pw, ph = spec.get("page", [1654, 1169])
    # qlmanage 等のサムネイラが正方形に切り抜いても全体が写るよう、
    # キャンバスは常に長辺の正方形にする(図は左上、余白は白)
    size = max(pw, ph)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
           f'viewBox="0 0 {size} {size}" font-family="Arial, Helvetica, sans-serif">',
           f'<rect width="{size}" height="{size}" fill="#FFFFFF"/>']
    geo: dict[str, Rect] = {}

    for c in spec.get("containers", []):
        style = c.get("style") or CONTAINER_STYLES.get(c.get("type"), "")
        x, y, w, h = c["x"], c["y"], c["w"], c["h"]
        geo[c["id"]] = (x, y, w, h)
        dash = ' stroke-dasharray="6 4"' if "dashed=1" in style else ""
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
                   f'fill="{_sv(style, "fillColor", "none")}" '
                   f'stroke="{_sv(style, "strokeColor", "#5A6C86")}"{dash}/>')
        if c.get("label"):
            out.append(_svg_text(x + 8, y + 18, c["label"], 12,
                                 _sv(style, "fontColor", "#5A6C86"), "start", True))

    for n in spec.get("nodes", []):
        if "badge" in n:
            continue  # エッジの後で描画(z 順: バッジを線の上に載せる)
        if "text" in n:
            x, y = n["x"], n["y"]
            w, h = n.get("w", 300), n.get("h", 20)
            geo[n["id"]] = (x, y, w, h)
            extra = n.get("style_extra", "")
            pad = 0.0
            m_ = re.search(r"fillColor=([^;]+)", extra)
            if m_:  # 背景付きパネル(ステップ説明等)
                out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
                           f'height="{h:.0f}" fill="{m_.group(1)}" '
                           f'stroke="#D5DBDB"/>')
                pad = 10.0
            size = 20 if "fontSize=20" in extra else 11
            # TEXT 基底スタイルは whiteSpace=wrap — 実描画と同じく箱幅で折り返す
            body_text = _wrap_text_px(n["text"], w - 2 * pad, size)
            out.append(_svg_text(x + pad, y + pad + size, body_text, size,
                                 "#232F3E", "start",
                                 bold="fontStyle=1" in extra))
            continue
        if is_entity(n):
            _, iw, ih = entity_geometry(n)
            style = ""
        elif is_flow(n):
            iw, ih = flow_geometry(n)
            style = ""
        else:
            style, iw, ih = node_icon(icons, n)
        w, h = n.get("w", iw), n.get("h", ih)
        x, y = ((n["cx"] - w / 2, n["cy"] - h / 2) if "cx" in n
                else (n["x"], n["y"]))
        geo[n["id"]] = (x, y, w, h)
        cx = x + w / 2
        if is_entity(n):
            out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
                       f'height="{h:.0f}" fill="#FFFFFF" stroke="#232F3E"/>')
            st = n.get("stereotype")
            if st:
                out.append(_svg_text(cx, y + 16, f"«{st}»", 11))
            title_y = y + (33 if st else 18)
            out.append(_svg_text(
                cx, title_y, n.get("title", n["id"]), 12, bold=True,
                italic=st in ("interface", "abstract")))
            body = list(n.get("rows") or []) + list(n.get("rows2") or [])
            if body:
                body_y = y + (57 if st else 42)
                out.append(_svg_text(x + 8, body_y, "\n".join(body), 10.5,
                                     "#232F3E", "start"))
        elif is_flow(n):
            sh = n["shape"]
            if sh in ("decision", "gateway"):
                pts = (f"{cx:.0f},{y:.0f} {x + w:.0f},{y + h / 2:.0f} "
                       f"{cx:.0f},{y + h:.0f} {x:.0f},{y + h / 2:.0f}")
                out.append(f'<polygon points="{pts}" fill="#FFFFFF" stroke="#232F3E"/>')
                if sh == "gateway":
                    arm = min(w, h) * 0.20
                    out.append(
                        f'<path d="M {cx - arm:.0f} {y + h / 2:.0f} '
                        f'L {cx + arm:.0f} {y + h / 2:.0f} '
                        f'M {cx:.0f} {y + h / 2 - arm:.0f} '
                        f'L {cx:.0f} {y + h / 2 + arm:.0f}" '
                        f'fill="none" stroke="#232F3E" stroke-width="5"/>')
            elif sh == "delay":
                r = h / 2
                out.append(
                    f'<path d="M {x:.0f} {y:.0f} H {x + w - r:.0f} '
                    f'A {r:.0f} {r:.0f} 0 0 1 {x + w - r:.0f} {y + h:.0f} '
                    f'H {x:.0f} Z" fill="#FFFFFF" stroke="#232F3E"/>')
            elif sh == "preparation":
                inset = min(w * 0.18, h * 0.45)
                pts = (f"{x + inset:.0f},{y:.0f} {x + w - inset:.0f},{y:.0f} "
                       f"{x + w:.0f},{y + h / 2:.0f} "
                       f"{x + w - inset:.0f},{y + h:.0f} "
                       f"{x + inset:.0f},{y + h:.0f} {x:.0f},{y + h / 2:.0f}")
                out.append(f'<polygon points="{pts}" fill="#FFFFFF" stroke="#232F3E"/>')
            elif sh in ("junction", "connector"):
                out.append(f'<ellipse cx="{cx:.0f}" cy="{y + h / 2:.0f}" '
                           f'rx="{w / 2:.0f}" ry="{h / 2:.0f}" '
                           f'fill="#FFFFFF" stroke="#232F3E"/>')
            else:
                dark = sh == "terminator"
                rx = ' rx="18"' if dark else ""
                out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
                           f'height="{h:.0f}"{rx} '
                           f'fill="{"#232F3E" if dark else "#FFFFFF"}" stroke="#232F3E"/>')
            if n.get("label"):
                out.append(_svg_text(cx, y + h / 2 + 4, n["label"], 11,
                                     "#FFFFFF" if sh == "terminator" else "#232F3E"))
        else:
            fill = _sv(style, "fillColor", "")
            if not fill.startswith("#"):  # Azure(画像)/GCP はブランド色で代用
                fill = ("#0078D4" if "azure2" in style
                        else "#4285F4" if "gcp3" in style else "#232F3E")
            op = ' opacity="0.4"' if n.get("ref") else ""
            out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
                       f'height="{h:.0f}" fill="{fill}" rx="6"{op}/>')
            if n.get("label"):
                out.append(_svg_text(cx, y + h + 14, n["label"], 11))

    for e in spec.get("edges", []):
        style = edge_style(e, kinds) or ""
        color = _sv(style, "strokeColor", "#232F3E")
        dash = (f' stroke-dasharray="{_sv(style, "dashPattern", "4 4")}"'
                if "dashed=1" in style else "")
        pts: list[Point] = []
        for term, at, frac_key in (("src", "src_at", "exit"),
                                   ("dst", "dst_at", "entry")):
            if term in e:
                x, y, w, h = geo[e[term]]
                fx, fy = e[frac_key]
                pt = (x + fx * w,
                      y + fy * h + float(e.get(f"{frac_key}_dy") or 0))
                if e[term] in diamond_ids:  # ひし形輪郭へ射影(本体と同じ)
                    cx_, cy_ = x + w / 2, y + h / 2
                    dx_, dy_ = pt[0] - cx_, pt[1] - cy_
                    den = (abs(dx_) / (w / 2) + abs(dy_) / (h / 2)) or 1.0
                    pt = (cx_ + dx_ / den, cy_ + dy_ / den)
            else:
                pt = tuple(e[at])
            if term == "dst":
                pts.extend(tuple(p) for p in e.get("points", []))
            pts.append(pt)
        pstr = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        out.append(f'<polyline points="{pstr}" fill="none" stroke="{color}" '
                   f'stroke-width="{_sv(style, "strokeWidth", "1")}"{dash}/>')
        end_arrow = _sv(style, "endArrow", "open")
        start_arrow = _sv(style, "startArrow", "none")
        if e.get("bidir") and start_arrow == "none":
            start_arrow = "open"
        out.append(_svg_marker(pts[-2], pts[-1], color, end_arrow,
                               _sv(style, "endFill", "0") == "1"))
        if start_arrow != "none":
            out.append(_svg_marker(pts[1], pts[0], color, start_arrow,
                                   _sv(style, "startFill", "0") == "1"))
        if e.get("label"):
            lx, ly = e.get("label_at") or ((pts[0][0] + pts[-1][0]) / 2,
                                           (pts[0][1] + pts[-1][1]) / 2)
            tw, th = text_size(str(e["label"]), 11)
            th = max(th, 16.0)
            out.append(f'<rect x="{lx - tw / 2:.0f}" y="{ly - th / 2:.0f}" '
                       f'width="{tw:.0f}" height="{th:.0f}" fill="#FFFFFF"/>')
            out.append(_svg_text(lx, ly - th / 2 + 12, e["label"], 11, color))
        for label_key, at_end in (("src_label", False), ("dst_label", True)):
            if not e.get(label_key):
                continue
            at_key = label_key + "_at"
            base = pts[-1] if at_end else pts[0]
            if e.get(at_key):
                lx, ly = e[at_key]
            else:
                off_x, off_y = _end_label_offset(pts, at_end, e[label_key])
                lx, ly = base[0] + off_x, base[1] + off_y
            tw, th = text_size(str(e[label_key]), 11)
            th = max(th, 16.0)
            out.append(f'<rect x="{lx - tw / 2:.0f}" y="{ly - th / 2:.0f}" '
                       f'width="{tw:.0f}" height="{th:.0f}" fill="#FFFFFF"/>')
            out.append(_svg_text(lx, ly - th / 2 + 12,
                                 e[label_key], 11, color))

    bstyle = resolve_badge_style(spec)  # 本番 XML と同じ配色に追随
    for n in spec.get("nodes", []):
        if "badge" not in n:
            continue  # 番号バッジ(最前面: 線の上に載せる)
        x, y = n["x"], n["y"]
        w, h = n.get("w", 22), n.get("h", 22)
        out.append(f'<circle cx="{x + w / 2:.0f}" cy="{y + h / 2:.0f}" '
                   f'r="{w / 2:.0f}" fill="{_sv(bstyle, "fillColor", "#232F3E")}" '
                   f'stroke="{_sv(bstyle, "strokeColor", "#FFFFFF")}"/>')
        out.append(_svg_text(x + w / 2, y + h / 2 + 4, str(n["badge"]),
                             12, _sv(bstyle, "fontColor", "#FFFFFF"), bold=True))
    out.append("</svg>")
    return "\n".join(out)


# ====================================================================
# 絶対座標スペック → drawio XML
# ====================================================================

# R7-1: draw.io デスクトップ/CLI(v30.3.11 実測)は mxCell の id を JS の
# 配列ベースのテーブルで引くため、Array.prototype / Object.prototype の
# プロパティ名と同名の id は PNG/SVG エクスポートを全フォーマットで
# 「Export failed」(詳細なし)にする。バリデータは通るのに成果物が出せない
# 沈黙破損になるため、XML 上の id だけ末尾 "_" へ退避する(spec は不変)。
# 集合は id スイープの実測(61 検体中 49 失敗)で確定したもの。Function 系
# (apply/call/bind/name/prototype/caller/arguments)は失敗しないため含めない。
# validate_drawio.py の JS_UNSAFE_IDS と同一内容を保つこと(tests で照合)。
JS_UNSAFE_IDS = frozenset((
    # Array.prototype(実測: 全て Export failed)
    "at", "concat", "constructor", "copyWithin", "entries", "every", "fill",
    "filter", "find", "findIndex", "findLast", "findLastIndex", "flat",
    "flatMap", "forEach", "includes", "indexOf", "join", "keys", "lastIndexOf",
    "length", "map", "pop", "push", "reduce", "reduceRight", "reverse",
    "shift", "slice", "some", "sort", "splice", "toLocaleString", "toReversed",
    "toSorted", "toSpliced", "toString", "unshift", "values", "with",
    # Object.prototype(実測: 全て Export failed)
    "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "valueOf",
    "__defineGetter__", "__defineSetter__", "__lookupGetter__",
    "__lookupSetter__", "__proto__",
))


def xml_id_map(spec: dict) -> dict[str, str]:
    """XML に書けない予約語 id → 退避後 id の対応表(R7-1)。

    退避は末尾 "_" 付与(既存 id と衝突するなら "_" を追加)。決定的かつ
    スペック内で単射。危険 id が無ければ空 dict(既存出力はバイト不変)。
    """
    ids = [item["id"] for key in ("containers", "nodes", "edges")
           for item in spec.get(key) or []]
    taken = set(ids)
    m: dict[str, str] = {}
    for i in ids:
        if i in JS_UNSAFE_IDS:
            cand = i + "_"
            while cand in taken:
                cand += "_"
            m[i] = cand
            taken.add(cand)
    return m


def build_diagram(spec: dict, icons: dict, idx: int) -> str:
    cells = []
    kinds = spec.get("kinds")
    abs_geo: dict[str, Rect] = {}
    diamond_ids = {n["id"] for n in spec.get("nodes", [])
                   if n.get("shape") in ("decision", "gateway")}
    idmap = xml_id_map(spec)
    for orig in sorted(idmap):
        print(f"NOTE: id '{orig}' は draw.io の予約語(JS プロパティ名)のため "
              f"XML 上は '{idmap[orig]}' に改名しました(spec はそのまま使えます)")

    def xid(t: str) -> str:
        return idmap.get(t, t)

    used_xml_ids = {"0", "1"} | {
        xid(item["id"])
        for key in ("containers", "nodes", "edges")
        for item in spec.get(key) or []
    }

    def child_cell_id(edge_id: str, end: str) -> str:
        """端ラベルの mxCell id を既存/生成 id と衝突しない形で割り当てる。"""
        cand = f"{xid(edge_id)}_{end}_label"
        while cand in used_xml_ids:
            cand += "_"
        used_xml_ids.add(cand)
        return cand

    def parent_origin(pid):
        if not pid or pid == "1":
            return 0.0, 0.0
        if pid not in abs_geo:
            die(f"parent '{pid}' が未定義です(containers は親→子の順)")
        return abs_geo[pid][0], abs_geo[pid][1]

    for c in spec.get("containers", []):
        cid = c["id"]
        style = c.get("style") or CONTAINER_STYLES.get(c.get("type"))
        if not style:
            die(f"container '{cid}': type '{c.get('type')}' は未知です。"
                f"候補: {sorted(CONTAINER_STYLES)}")
        style += c.get("style_extra", "")
        x, y, w, h = c["x"], c["y"], c["w"], c["h"]
        px, py = parent_origin(c.get("parent"))
        abs_geo[cid] = (x, y, w, h)
        cells.append(
            f'        <mxCell id="{xid(cid)}" value="{esc_label(c.get("label", ""))}" style="{esc(style)}" '
            f'vertex="1" parent="{xid(c.get("parent") or "1")}">\n'
            f'          <mxGeometry x="{g0(x - px)}" y="{g0(y - py)}" width="{g0(w)}" height="{g0(h)}" as="geometry" />\n'
            f'        </mxCell>')

    # バッジは最後に描く(draw.io の z 順は文書順。線の上にバッジを載せる)
    badge_nodes = [n for n in spec.get("nodes", []) if "badge" in n]

    for n in spec.get("nodes", []):
        nid = n["id"]
        if "badge" in n:
            continue  # エッジの後で描画(z 順)
        if "text" in n:
            style = TEXT + n.get("style_extra", "")
            x, y = n["x"], n["y"]
            w, h = n.get("w", 300), n.get("h", 20)
            value = n["text"]
        elif is_entity(n):
            value, iw, ih = entity_geometry(n)
            style = ENTITY_STYLE + n.get("style_extra", "")
            if n.get("stereotype") in ("interface", "abstract"):
                style += "fontStyle=3;"
            w, h = n.get("w", iw), n.get("h", ih)
            if "cx" in n:
                x, y = n["cx"] - w / 2, n["cy"] - h / 2
            else:
                x, y = n["x"], n["y"]
        elif is_flow(n):
            value = n.get("label", "")
            style = FLOW_STYLES[n["shape"]] + n.get("style_extra", "")
            iw, ih = flow_geometry(n)
            w, h = n.get("w", iw), n.get("h", ih)
            if "cx" in n:
                x, y = n["cx"] - w / 2, n["cy"] - h / 2
            else:
                x, y = n["x"], n["y"]
        else:
            style, iw, ih = node_icon(icons, n)
            w, h = n.get("w", iw), n.get("h", ih)
            if n.get("ref"):
                style += "opacity=40;"
            style += n.get("style_extra", "")
            if "cx" in n:
                x, y = n["cx"] - w / 2, n["cy"] - h / 2
            else:
                x, y = n["x"], n["y"]
            value = n.get("label", "")
        px, py = parent_origin(n.get("parent"))
        abs_geo[nid] = (x, y, w, h)
        geometry = (f'          <mxGeometry x="{g0(x - px)}" y="{g0(y - py)}" '
                    f'width="{g0(w)}" height="{g0(h)}" as="geometry" />')
        if n.get("link"):
            cells.append(
                f'        <UserObject id="{xid(nid)}" label="{esc_label(value)}" '
                f'link="{esc(n["link"])}">\n'
                f'          <mxCell style="{esc(style)}" vertex="1" '
                f'parent="{xid(n.get("parent") or "1")}">\n'
                f'{geometry}\n'
                f'          </mxCell>\n'
                f'        </UserObject>')
        else:
            cells.append(
                f'        <mxCell id="{xid(nid)}" value="{esc_label(value)}" '
                f'style="{esc(style)}" vertex="1" '
                f'parent="{xid(n.get("parent") or "1")}">\n'
                f'{geometry}\n'
                f'        </mxCell>')

    for e in spec.get("edges", []):
        eid = e["id"]

        def pt2(term, fx, fy):
            x, y, w, h = abs_geo[term]
            return (x + fx * w, y + fy * h)

        # 端点: 図形接続(src/dst + exit/entry)または固定座標(src_at/dst_at。凡例用)
        style = edge_style(e, kinds)
        if style is None:
            die(f"edge '{eid}': kind '{e.get('kind')}' は未知です"
                f"(組み込み: {' / '.join(EDGE_STYLES)} か spec の kinds で定義)")
        if e.get("bidir"):
            if str(e.get("kind", "")).startswith(("er_", "uml_")):
                print(f"WARN: edge '{eid}': {e['kind']} と bidir の併用は"
                      "矢じり記法を壊します(多対多は er_nn を使う)")
            style += "startArrow=open;startFill=0;"
        term_attr = ""
        end_pts = {}
        for term, at, frac_key, prefix, pname in (
                ("src", "src_at", "exit", "exit", "sourcePoint"),
                ("dst", "dst_at", "entry", "entry", "targetPoint")):
            if term in e:
                if frac_key not in e:
                    die(f"edge '{eid}' に {frac_key} がありません")
                if e[term] not in abs_geo:
                    die(f"edge '{eid}': {term}='{e[term]}' が未定義です")
                fx, fy = e[frac_key]
                dyo = float(e.get(f"{frac_key}_dy") or 0)
                style += (f"{prefix}X={fx};{prefix}Y={fy};"
                          f"{prefix}Dx=0;{prefix}Dy={g0(dyo)};")
                if dyo:
                    # mxGraph は既定(exitPerimeter=true)で接続点を図形輪郭へ
                    # 射影し Dy を破棄する(RectanglePerimeter は方向のみ使用)。
                    # キャプション下アンカーを実 draw.io で効かせるには射影を
                    # 無効化する必要がある
                    style += prefix + "Perimeter=0;"
                if e[term] in diamond_ids:
                    # bbox 固定点をひし形の実輪郭へ射影(浮く矢印の防止)
                    style += prefix + "Perimeter=1;"

                attr = "source" if term == "src" else "target"
                term_attr += f'{attr}="{xid(e[term])}" '
                px_, py_ = pt2(e[term], fx, fy)
                end_pts[pname] = (px_, py_ + dyo)
            elif at in e:
                end_pts[pname] = (e[at][0], e[at][1], "emit")
            else:
                die(f"edge '{eid}' に {term} か {at} がありません")
        style = dedupe_style(style + e.get("style_extra", ""))

        wps = [tuple(p) for p in e.get("points", [])]
        poly = ([end_pts["sourcePoint"][:2]] + wps + [end_pts["targetPoint"][:2]])
        gx, off = "0", None
        if e.get("label"):
            if e.get("label_at"):
                p, off = project_label(poly, tuple(e["label_at"]))
                gx = f"{p:.4f}"
            else:
                off = (0, 0)
        geo = ""
        if wps:
            pts = "".join(f'<mxPoint x="{g0(x)}" y="{g0(y)}" />' for x, y in wps)
            geo += f'\n            <Array as="points">{pts}</Array>'
        if off:
            geo += f'\n            <mxPoint as="offset" x="{off[0]:.1f}" y="{off[1]:.1f}" />'
        for pname, pt in end_pts.items():
            if len(pt) == 3:  # 固定座標端点は sourcePoint/targetPoint で表す
                geo += (f'\n            <mxPoint x="{g0(pt[0])}" y="{g0(pt[1])}" '
                        f'as="{pname}" />')
        cells.append(
            f'        <mxCell id="{xid(eid)}" value="{esc_label(e.get("label", ""))}" '
            f'awsdiagKind="{esc(str(e.get("kind", "main")))}" style="{esc(style)}" '
            f'edge="1" parent="1" {term_attr}>\n'
            f'          <mxGeometry x="{gx}" relative="1" as="geometry">{geo}\n'
            f'          </mxGeometry>\n'
            f'        </mxCell>')
        for label_key, end, at_end, xp in (
                ("src_label", "src", False, -1),
                ("dst_label", "dst", True, 1)):
            if not e.get(label_key):
                continue
            at_key = label_key + "_at"
            base = poly[-1] if at_end else poly[0]
            if e.get(at_key):
                lx, ly = e[at_key]
                off_x, off_y = lx - base[0], ly - base[1]
            else:
                off_x, off_y = _end_label_offset(poly, at_end, e[label_key])
            cells.append(
                f'        <mxCell id="{child_cell_id(eid, end)}" '
                f'value="{esc_label(e[label_key])}" style="{esc(END_LABEL_STYLE)}" '
                f'vertex="1" connectable="0" parent="{xid(eid)}">\n'
                f'          <mxGeometry x="{xp}" relative="1" as="geometry">\n'
                f'            <mxPoint x="{g0(off_x)}" y="{g0(off_y)}" as="offset" />\n'
                f'          </mxGeometry>\n'
                f'        </mxCell>')

    badge_base = resolve_badge_style(spec)  # 不正値はバッジ有無に関わらず拒否
    for n in badge_nodes:  # 番号バッジ(エッジより後=最前面)
        style = badge_base + n.get("style_extra", "")
        w, h = n.get("w", 22), n.get("h", 22)
        cells.append(
            f'        <mxCell id="{xid(n["id"])}" value="{esc_label(str(n["badge"]))}" '
            f'style="{esc(style)}" vertex="1" parent="1">\n'
            f'          <mxGeometry x="{g0(n["x"])}" y="{g0(n["y"])}" '
            f'width="{g0(w)}" height="{g0(h)}" as="geometry" />\n'
            f'        </mxCell>')

    pw, ph = spec.get("page", [1654, 1169])
    name = spec.get("name") or f"図{idx + 1}"
    return (f'  <diagram id="d{idx}" name="{esc(name)}">\n'
            f'    <mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" '
            f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{pw}" '
            f'pageHeight="{ph}" math="0" shadow="0">\n'
            f'      <root>\n'
            f'        <mxCell id="0" />\n'
            f'        <mxCell id="1" parent="0" />\n'
            + "\n".join(cells) + "\n"
            f'      </root>\n'
            f'    </mxGraphModel>\n'
            f'  </diagram>')


# ====================================================================
# 配置の自動化(ドラフト評価・ローカルサーチ・自動グリッド)
# ====================================================================

def count_node_overlaps(rects: list[Rect]) -> int:
    """ノード矩形(アイコン+ラベル)同士の重なりペア数(バリデータ E1 相当)。

    place() は lay.obstacles の先頭にノード順で矩形を積むため、
    先頭 len(nodes) 件を渡せばノード分だけを数えられる。
    """
    cnt = 0
    for i, (ax, ay, aw, ah) in enumerate(rects):
        for bx, by, bw, bh in rects[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                cnt += 1
    return cnt


def convention_penalties(spec: dict, lay: Layout) -> tuple[int, int, list[str]]:
    """図種の向き慣例の違反数 (terminator逆流, ER親右置き, 関与ノードid列)。

    フロー図(R7-3・監査1): 終了系 terminator(流入をもつ)が流入元ノード
    より上の row にあると下→上の逆流に見える。1 違反 = 交差 4 個分として
    第2キーへ合算する(交差 3 個と引き換えでも terminator は下に保つ。
    交差 4 個を増やしてまでは守らない)。係数は監査1の実配置で校正 —
    R7-A3 の上辺入射規約により下部 terminator への合流は側辺退避が
    できず正当配置の交差が +1 構造化したため、旧係数 3(交差 2 個分まで
    保護)では同配置が吊り上げと同点になり、3→4 に再校正した。
    開始 terminator は流入が無いので自然に対象外になる。
    ER(監査4): er_1n/er_0n の src(親)が dst(子)より右の col にあると
    親→子=左→右の読み順が壊れる。こちらは第3キー(交差より弱い
    タイブレーク)— 交差同数の解の中でのみ慣例準拠を選ぶ。
    """
    nodes = {n["id"]: n for n in spec.get("nodes", [])}
    term = er = 0
    ids: list[str] = []
    for e in spec.get("edges", []):
        s, t = e.get("src"), e.get("dst")
        if s == t or s not in lay.cell or t not in lay.cell:
            continue
        if (nodes.get(t, {}).get("shape") == "terminator"
                and lay.cell[t][1] < lay.cell[s][1]):
            term += 1
            ids += [t, s]
        if (e.get("kind") in ("er_1n", "er_0n")
                and lay.cell[s][0] > lay.cell[t][0]):
            er += 1
            ids += [s, t]
    return term, er, ids


def eval_layout(spec: dict, icons: dict,
                draft: bool = True) -> tuple[tuple, list[str]] | None:
    """配線して (スコア, 交差に絡むノード id 列) を返す。

    スコア = (ノード重なり数, 交差数 + 未配線 + terminator 逆流ペナルティ,
    ER 慣例違反数, 総延長)。
    第一キーの重なり数は、交差を減らす代わりにラベル込み矩形の重なり(E1)を
    作る手を辞書順比較で必ず弾くためのガード(重なりゼロ同士の比較は従来の
    (交差, 総延長) と一致する)。第2・第3キーの慣例ペナルティは
    convention_penalties を参照(R7-3)。SpecError(不正配置)なら None。
    draft=True は候補の粗選別用、False は採否確定用(本番と同じ品質)。
    """
    try:
        lay, _c, _n = place(spec, icons)
        edges = spec.get("edges", [])
        _fixed, routable, _fr, fixed_polys = classify_edges(lay, edges)
        router = Router(lay.xs, lay.ys, lay.obstacles,
                    borders=[lay.boxes[cid] for cid in lay.cmap],
                    title_bands=lay.title_bands)
        routes = route_all(router, lay, routable, fixed_polys,
                           spec.get("kinds"), draft=draft)
        polys = finalize_polys(lay, routable, routes)
        items = list(polys.items()) + [(f"__f{i}", p)
                                       for i, p in enumerate(fixed_polys)]
        pairs = crossing_pairs(items)
        unrouted = sum(1 for e in routable if e["id"] not in routes)
        by_id = {e["id"]: e for e in routable}
        freq: dict[str, int] = {}
        for ia, ib in pairs:
            for x in (ia, ib):
                e = by_id.get(x)
                if e:
                    for t in (e["src"], e["dst"]):
                        if t in lay.cell:
                            freq[t] = freq.get(t, 0) + 1
        prob = sorted(freq, key=lambda k: -freq[k])
        # 大回りしているエッジの端点も問題ノードに加える(交差ゼロでも改善余地)
        for e in routable:
            p = polys.get(e["id"])
            if p is None:
                continue
            (sx, sy), (ex, ey) = p[0], p[-1]
            manh = abs(sx - ex) + abs(sy - ey)
            plen = poly_len(p)
            if is_detour(plen, manh):
                for t in (e["src"], e["dst"]):
                    if t in lay.cell and t not in freq:
                        prob.append(t)
        term_viol, er_viol, conv_ids = convention_penalties(spec, lay)
        for t in conv_ids:   # 違反の当事者も改善候補に載せる
            if t not in prob:
                prob.append(t)
        score = (count_node_overlaps(lay.obstacles[:len(spec.get("nodes", ()))]),
                 len(pairs) + 5 * unrouted + 4 * term_viol,
                 er_viol,
                 sum(poly_len(p) for p in polys.values()))
        return score, prob
    except SpecError:
        return None


def optimize_placement(spec: dict, icons: dict, budget_s: float) -> list[str]:
    """交差に絡むノードを近傍の空きセルへ動かす山登りで col/row を改善する。

    スコアの第一キーはラベル込みノード矩形の重なり数(eval_layout 参照)。
    交差が減ってもラベル重なり(E1)を新規に作る手は採用しない。
    向き慣例(R7-3): terminator を流入元より上へ吊り上げる手は交差 3 個の
    削減より重いペナルティで弾き、ER の親→子=左→右は交差同数解の
    タイブレークとして保つ(convention_penalties 参照)。
    候補はドラフト品質で粗く絞り、採否は本番品質のスコアで確定する
    (ドラフトと本番では交差数の傾向が異なるため)。候補の列挙・評価順は
    決定的(同一入力なら同一結果。時間切れで途中終了した場合を除く)。
    draft 評価のプロセス並列化は 2026-07-07 に実測で不採用: draft は
    ~26ms/回まで高速化済みで、予算の大半は直列必須の本番品質確定が占める
    ため、プール生成と pickle 往復が利得を上回った(直列 1,065 回/交差 8 vs
    並列 761 回/交差 11 @30 秒)。改善が止まるか時間切れで終了。
    spec を直接更新し、移動ログを返す。
    """
    deadline = time.monotonic() + budget_s
    base = eval_layout(spec, icons, draft=False)
    if base is None:
        return []
    score, prob = base
    nodes_by_id = {n["id"]: n for n in spec.get("nodes", [])}
    # グラフ隣接(テレポート候補 = 「流入元は流入先の隣接列に」の機械化)
    partners: dict[str, set[str]] = {}
    for e in spec.get("edges", []):
        s, t = e.get("src"), e.get("dst")
        if s in nodes_by_id and t in nodes_by_id:
            partners.setdefault(s, set()).add(t)
            partners.setdefault(t, set()).add(s)
    moves: list[str] = []
    n_draft = n_batch = 0
    # 重なり(第一キー)か交差が残る限り探索(重なりゼロなら従来と同じ条件)
    while score[0] + score[1] > 0 and time.monotonic() < deadline:
        occupied = {(n["col"], n["row"]) for n in spec["nodes"]}
        # 1) 候補列挙(prob 順 × セルの整列順 → 順序は決定的)
        tasks: list[tuple[str, tuple[int, int]]] = []
        for nid in prob[:8]:
            n = nodes_by_id.get(nid)
            if n is None or n.get("pin"):   # pin: true は動かさない
                continue
            c0, r0 = n["col"], n["row"]
            cells = {(c0 + dc, r0 + dr) for dc in (-2, -1, 0, 1, 2)
                     for dr in (-2, -1, 0, 1, 2) if 0 < abs(dc) + abs(dr) <= 2}
            cells |= {(c0 - 3, r0), (c0 + 3, r0)}  # 同一行の長スライド
            for pid in partners.get(nid, ()):    # 接続相手の隣へテレポート
                p = nodes_by_id[pid]
                pc, pr = p["col"], p["row"]
                cells |= {(pc - 1, pr), (pc + 1, pr),
                          (pc, pr - 1), (pc, pr + 1)}
            tasks.extend((nid, cell) for cell in sorted(cells)
                         if cell[0] >= 0 and cell[1] >= 0
                         and cell not in occupied)
        if not tasks:
            break
        # 2) draft 品質の粗選別
        n_draft += len(tasks)
        n_batch += 1
        cands: list[tuple[tuple, str, tuple[int, int]]] = []
        for nid, cell in tasks:
            if time.monotonic() >= deadline:
                break
            n = nodes_by_id[nid]
            old = (n["col"], n["row"])
            n["col"], n["row"] = cell
            res = eval_layout(spec, icons, draft=True)
            n["col"], n["row"] = old
            if res is not None:
                cands.append((res[0], nid, cell))
        cands.sort(key=lambda t: t[0])
        # 3) 候補をドラフト順に本番品質で確定評価(改善する最初の 1 手を採用)
        accepted = False
        for _draft_score, nid, cell in cands:
            if time.monotonic() >= deadline:
                break
            n = nodes_by_id[nid]
            old = (n["col"], n["row"])
            n["col"], n["row"] = cell
            res = eval_layout(spec, icons, draft=False)
            if res is not None and res[0] < score:
                lap = (f"、重なり {score[0]} → {res[0][0]}"
                       if res[0][0] != score[0] else "")
                if res[0][2] != score[2]:
                    lap += f"、ER慣例違反 {score[2]} → {res[0][2]}"
                moves.append(f"OPT: '{nid}' {old} → {cell} "
                             f"(交差スコア {score[1]} → {res[0][1]}{lap})")
                score, prob = res
                accepted = True
                break
            n["col"], n["row"] = old
        if not accepted:
            break
    if os.environ.get("AWSDIAG_OPT_STATS") == "1":
        print(f"OPT-STATS: draft {n_draft} 回 / {n_batch} バッチ")
    return moves


def auto_grid(spec: dict) -> None:
    """col/row のないスペックに自動でマス目を割り当てる(ドラフト品質)。

    列 = エッジの最長経路層(左→右の流れ)。行 = コンテナツリーを DFS し、
    各コンテナ・トップレベルのノード群に排他的な行バンドを割り当てる
    (兄弟コンテナの矩形が重ならないことを構造的に保証する)。
    """
    nodes = spec.get("nodes", [])
    conts = spec.get("containers", [])
    edges = spec.get("edges", [])
    ids = {n["id"] for n in nodes}

    pinned = [n["id"] for n in nodes if n.get("pin")]
    if pinned:
        die(f"pin は col/row を書いたノードにだけ使えます(自動配置では固定でき"
            f"ません): {pinned[:3]}")

    preds: dict[str, list[str]] = {}
    for e in edges:
        s, t = e.get("src"), e.get("dst")
        if s in ids and t in ids:
            preds.setdefault(t, []).append(s)
    memo: dict[str, int] = {}
    onstack: set[str] = set()

    def layer(u: str) -> int:
        if u in memo:
            return memo[u]
        if u in onstack:
            return 0  # 閉路はここで断つ
        onstack.add(u)
        v = 0
        for p in preds.get(u, []):
            v = max(v, layer(p) + 1)
        onstack.discard(u)
        memo[u] = v
        return v

    cmap = {c["id"]: c for c in conts}
    kids: dict[str | None, list[str]] = {}
    for c in conts:
        p = c.get("parent")
        kids.setdefault(p if p in cmap else None, []).append(c["id"])
    members: dict[str | None, list[dict]] = {}
    for n in nodes:
        p = n.get("parent")
        members.setdefault(p if p in cmap else None, []).append(n)

    def min_layer(cid: str) -> int:
        vals = [layer(n["id"]) for n in members.get(cid, [])]
        vals += [min_layer(k) for k in kids.get(cid, [])]
        return min(vals) if vals else 10 ** 6

    occupied: set[tuple[int, int]] = set()
    next_row = [0]

    def place_band(band_nodes: list[dict]) -> None:
        if not band_nodes:
            return
        base = next_row[0]
        height = 1
        for n in sorted(band_nodes, key=lambda n: (layer(n["id"]), n["id"])):
            c = layer(n["id"])
            r = base
            while (c, r) in occupied:
                r += 1
            n["col"], n["row"] = c, r
            occupied.add((c, r))
            height = max(height, r - base + 1)
        next_row[0] = base + height

    def walk(cid: str | None) -> None:
        for k in sorted(kids.get(cid, []), key=min_layer):
            walk(k)
        place_band(members.get(cid, []))

    for top in sorted(kids.get(None, []), key=min_layer):
        walk(top)
    place_band(members.get(None, []))


ONE_LINE_LISTS = ("containers", "nodes", "edges")


def dump_spec(spec: dict, path: Path) -> None:
    """スペックを「containers/nodes/edges は 1 オブジェクト 1 行」で保存する。

    テンプレートや --optimize の書き戻しに使う。Read のトークン量と diff の
    読みやすさのための形式で、内容は通常の JSON と等価。
    """
    def fmt_tab(tab: dict, pad: str) -> str:
        parts = []
        for k, v in tab.items():
            if k in ONE_LINE_LISTS and isinstance(v, list):
                rows = ",\n".join(
                    pad + "  " + json.dumps(x, ensure_ascii=False,
                                            separators=(", ", ": "))
                    for x in v)
                parts.append(f'{pad}"{k}": [\n{rows}\n{pad}]')
            else:
                parts.append(f'{pad}"{k}": '
                             + json.dumps(v, ensure_ascii=False,
                                          separators=(", ", ": ")))
        open_pad = pad[:-1]
        return open_pad + "{\n" + ",\n".join(parts) + "\n" + open_pad + "}"

    if "diagrams" in spec:
        tabs = ",\n".join(fmt_tab(t, "   ") for t in spec["diagrams"])
        text = '{\n "diagrams": [\n' + tabs + "\n ]\n}\n"
    else:
        text = fmt_tab(spec, " ") + "\n"
    assert json.loads(text) == spec, "dump_spec の整形結果が元データと不一致"
    path.write_text(text, encoding="utf-8")


def is_abs(spec: dict) -> bool:
    """絶対座標スペック(--emit-abs の出力等)か。auto_grid の対象外。"""
    return any("cx" in n or "x" in n for n in spec.get("nodes") or [])


def is_grid(spec: dict) -> bool:
    return any("col" in n for n in spec.get("nodes") or [])


def parse_args(argv: list[str] | None) -> SimpleNamespace | int:
    """argv を解釈する(argparse は起動コストが高いため手書き)。

    正常時は SimpleNamespace、ヘルプ表示や引数エラー時は終了コードを返す。
    """
    args = SimpleNamespace(spec=None, out=None, no_validate=False,
                           emit_abs=False, emit_svg=False, emit_png=False,
                           optimize=None, route_cache=False)
    argv = list(sys.argv[1:] if argv is None else argv)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a in ("-o", "--out"):
            i += 1
            if i >= len(argv):
                print("ERROR: -o の後に出力パスが必要です", file=sys.stderr)
                return 2
            args.out = argv[i]
        elif a == "--no-validate":
            args.no_validate = True
        elif a == "--emit-abs":
            args.emit_abs = True
        elif a == "--emit-svg":
            args.emit_svg = True
        elif a == "--emit-png":
            args.emit_png = True
        elif a == "--route-cache":
            args.route_cache = True
        elif a == "--optimize":
            args.optimize = 30.0
            if i + 1 < len(argv):
                try:
                    args.optimize = float(argv[i + 1])
                    i += 1
                except ValueError:
                    pass  # 次の引数は秒数ではない(spec パス等)
        elif a.startswith("-"):
            print(f"ERROR: 不明なオプション: {a}(--help で使い方)", file=sys.stderr)
            return 2
        elif args.spec is None:
            args.spec = a
        else:
            print(f"ERROR: 引数が多すぎます: {a}", file=sys.stderr)
            return 2
        i += 1
    if args.spec is None:
        print(__doc__)
        return 2
    return args


def find_drawio_cli() -> str | None:
    """draw.io CLI の実体を探す(PATH → macOS アプリの順)。"""
    import shutil as _shutil
    for cand in ("drawio", "draw.io"):
        p = _shutil.which(cand)
        if p:
            return p
    mac = "/Applications/draw.io.app/Contents/MacOS/draw.io"
    if Path(mac).exists():
        return mac
    return None


def export_png(cli: str, drawio_path: Path, diagrams: list[dict]) -> list[Path]:
    """draw.io CLI で実描画 PNG を書き出す(タブごと)。失敗タブは飛ばす。"""
    import subprocess
    outs: list[Path] = []
    stem = drawio_path.name.removesuffix(".drawio")
    for i, d in enumerate(diagrams):
        tab = preview_tab_suffix(diagrams, i, d)
        png = drawio_path.with_name(f"{stem}{tab}.png")
        # drawio CLI の --page-index は 1-based(30.3.11 実測: -p 0 と -p 1 が同一出力)
        cmd = [cli, "-x", "-f", "png", "-s", "2", "-p", str(i + 1),
               "-o", str(png), str(drawio_path)]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=120)
            if cp.returncode == 0 and png.exists():
                outs.append(png)
            else:
                print(f"WARN: PNG 書き出し失敗(タブ {i}): "
                      f"{(cp.stderr or cp.stdout).strip()[:200]}")
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"WARN: PNG 書き出し失敗(タブ {i}): {exc}")
    return outs


def preview_tab_suffix(diagrams: list[dict], index: int, diagram: dict) -> str:
    """プレビュー名の安全な suffix。連番で正規化後の衝突を防ぐ。"""
    if len(diagrams) == 1:
        return ""
    slug = re.sub(r"[^\w\-]+", "_",
                  str(diagram.get("name") or f"tab{index + 1}"))
    slug = slug.strip("_.-")[:80].rstrip("_.-") or f"tab{index + 1}"
    return f".{index + 1:02d}-{slug}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if isinstance(args, int):
        return args
    try:
        return _build(args)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: スペックの JSON が壊れています: {exc}"
              "(カンマ・引用符・括弧の対応を確認)", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: ファイルにアクセスできません: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # 想定外はスペック起因が大半。指示付きで返す
        if os.environ.get("AWSDIAG_TRACE") == "1":
            raise
        print(f"ERROR: スペック処理中に想定外のエラー"
              f"({type(exc).__name__}: {exc})。スペックの構造"
              "(nodes/containers/edges は dict の配列、diagrams はタブの配列)を"
              "確認してください。詳細は AWSDIAG_TRACE=1 で再実行", file=sys.stderr)
        return 2


def _rollback_bad_equalization(diagrams: list[dict], originals: list[dict],
                               icons: dict) -> list[dict]:
    """R4-6: 寸法等化が新たな ERROR/WARN を生んだタブだけ等化なしで戻す。

    等化はレイアウト後の箱拡張なので、回廊・レーンの前提と稀にずれて
    W1/W3(クリアランス)等を誘発する(実測: multiaccount の CI/CD タブで
    W3 7px)。等化を適用したタブを単体で検証し、ERROR/WARN があれば
    等化なしビルドと比較して少ない方を採用する —「壊れるケースでは
    そのコンテナ群のみ等化を諦める」の実装(粒度はタブ単位。1 タブに
    複数グループがある場合は道連れになる)。--no-validate 時は呼ばれない。
    """
    import tempfile
    import validate_drawio

    def ew_count(d: dict, idx: int) -> int:
        saved = list(BUILD_WARNS)   # 検証用の再ビルドで二重計上しない
        try:
            xml = ('<mxfile host="app.diagrams.net" agent="claude '
                   'tech-diagram" version="24.0.0">\n'
                   + build_diagram(d, icons, idx) + "\n</mxfile>\n")
        finally:
            BUILD_WARNS[:] = saved
        fd, path = tempfile.mkstemp(suffix=".drawio")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(xml)
            findings, _cross = validate_drawio.validate(path)
        finally:
            os.unlink(path)
        return sum(1 for x in findings if x["level"] in ("ERROR", "WARN"))

    out = []
    for i, d in enumerate(diagrams):
        if not d.pop("_equalized", False):
            out.append(d)
            continue
        n_eq = ew_count(d, i)
        if n_eq == 0:
            out.append(d)
            continue
        alt_spec = dict(originals[i])
        alt_spec["equalize_containers"] = False
        saved = list(BUILD_WARNS)
        alt = grid_to_abs(alt_spec, icons)
        BUILD_WARNS[:] = saved
        alt.pop("_equalized", None)
        if ew_count(alt, i) < n_eq:
            print(f"INFO: タブ '{d.get('name') or i}' はコンテナ寸法等化で"
                  " ERROR/WARN が増えるため、このタブのみ等化を見送りました"
                  '(固定したい場合は "equalize_containers": false)')
            out.append(alt)
        else:
            out.append(d)
    return out


def _build(args) -> int:
    BUILD_WARNS.clear()  # in-process で複数回呼ばれても前回分を持ち越さない
    spec_path = Path(args.spec)
    out = Path(args.out) if args.out else None
    if out is None:
        base = spec_path.name
        for suf in (".spec.json", ".json"):
            if base.endswith(suf):
                base = base[: -len(suf)]
                break
        out = spec_path.with_name(base + ".drawio")

    with spec_path.open(encoding="utf-8") as f:
        spec = json.load(f)
    if not isinstance(spec, dict):
        die("スペックのトップレベルは JSON オブジェクトで書いてください")
    diagrams = spec["diagrams"] if "diagrams" in spec else [spec]
    if not isinstance(diagrams, list):
        die(f"diagrams はタブ定義の配列で書いてください"
            f"({type(diagrams).__name__} になっています)")
    if not diagrams:
        die("diagrams が空です(タブ定義を 1 つ以上入れてください)")
    icons = load_icons()

    # 器の検証を grid/abs 分岐より前に(null 等を親切なメッセージで落とす)
    for d in diagrams:
        if not isinstance(d, dict):
            die(f"diagrams の要素が dict ではありません: {d!r}")
        check_structure(d)
        page = d.get("page")
        if page is not None and (
                not isinstance(page, (list, tuple)) or len(page) != 2
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                           and math.isfinite(x) and x > 0 for x in page)):
            die(f"page は [幅, 高さ](正の数値 2 つ)で書いてください({page!r})")

    # 自動配置(col/row 未指定)と配置ローカルサーチ
    changed = False
    for d in diagrams:
        if d.get("nodes") and not is_grid(d) and not is_abs(d):
            auto_grid(d)
            changed = True
            print(f"AUTO: '{d.get('name', '')}' の col/row を自動配置しました(ドラフト品質)")
    if args.optimize is not None:
        budget = args.optimize / max(1, len([d for d in diagrams if is_grid(d)]))
        for d in diagrams:
            if is_grid(d):
                moves = optimize_placement(d, icons, budget)
                for msg in moves:
                    print(msg)
                changed = changed or bool(moves)
    for d in diagrams:
        if not is_grid(d):  # abs 経路は validate_spec を通らないため最小検証
            check_abs_basics(d)
    originals = list(diagrams)
    tab_keys = [route_cache_tab_key(d) for d in originals]

    # R5-D: 経路キャッシュ。読みは <out>.routes.json が存在する場合のみ、
    # 書きは --route-cache 指定時か既存ファイルの更新時のみ(既定挙動は不変)
    cache_path = route_cache_path(out)
    cache_exists = cache_path.exists()
    old_cache = load_route_cache(cache_path) if cache_exists else None
    write_cache = args.route_cache or cache_exists
    seeds_by_tab: dict[int, tuple] = {}
    if old_cache is not None:
        key_counts: dict[str, int] = {}
        for key in tab_keys:
            key_counts[key] = key_counts.get(key, 0) + 1
        cache_tabs = unique_route_cache_tabs(old_cache)
        for i, d in enumerate(diagrams):
            if is_grid(d):
                key = tab_keys[i]
                cached = cache_tabs.get(key) if key_counts[key] == 1 else None
                seeds = (seed_routes_from_cache(
                    {"tabs": [cached]}, i, d) if cached is not None else None)
                if seeds is not None:
                    seeds_by_tab[i] = seeds

    diagrams = [grid_to_abs(d, icons,
                            seed_routes=seeds_by_tab.get(i, (None, False))[0],
                            seed_equalized=seeds_by_tab.get(i, (None, False))[1])
                if is_grid(d) else d for i, d in enumerate(diagrams)]
    # R4-6: 等化を適用したタブに ERROR/WARN が出た場合、等化なしと比較して
    # 悪化していればそのタブだけ等化を見送る(結果ベースの安全弁)
    if not args.no_validate:
        diagrams = _rollback_bad_equalization(diagrams, originals, icons)
    else:
        for d in diagrams:
            d.pop("_equalized", None)
    # R5-D: 次回ビルド用スナップショットを回収(タブ順に整列。abs タブは None)
    cache_tabs = []
    for orig, d in zip(originals, diagrams):
        snap = d.pop("_routes_out", None)
        if write_cache:
            cache_tabs.append(None if snap is None else {
                "name": orig.get("name"), "key": route_cache_tab_key(orig),
                "hash": routes_struct_hash(orig),
                "equalized": snap["equalized"], "edges": snap["edges"]})
    if args.emit_abs:
        abs_path = out.with_name(
            out.name.removesuffix(".drawio") + ".abs.json")
        with abs_path.open("w", encoding="utf-8") as f:
            json.dump({"diagrams": diagrams}, f, ensure_ascii=False, indent=1)
        print(f"絶対座標スペック: {abs_path}")

    body = "\n".join(build_diagram(d, icons, i) for i, d in enumerate(diagrams))
    xml = ('<mxfile host="app.diagrams.net" agent="claude tech-diagram" version="24.0.0">\n'
           + body + "\n</mxfile>\n")
    # 沈黙不良の最終防衛線: 整形式でない XML は書き出さない(--no-validate 時も)
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(xml)
    except ET.ParseError as exc:
        die(f"内部エラー: 生成した XML が整形式ではありません({exc})。"
            "スペックの文字列値に XML を壊す値が混入していないか確認してください")
    out.write_text(xml, encoding="utf-8")
    print(f"生成: {out}({len(diagrams)} タブ)")
    if write_cache:   # 生成が成功したビルドの経路だけをキャッシュする
        cache = {"_comment": "tech-diagram 経路キャッシュ: 前回ビルドの経路を"
                             "初期解として保持し、品質スコアが悪化しない限り"
                             "維持する(R5-D)。無効化はこのファイルを削除",
                 "version": ROUTE_CACHE_VERSION, "tabs": cache_tabs}
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True)
            + "\n", encoding="utf-8")
        print(f"経路キャッシュ: {cache_path}")
    want_svg = args.emit_svg
    if args.emit_png:
        cli = find_drawio_cli()
        pngs = export_png(cli, out, diagrams) if cli else []
        if pngs:
            for p in pngs:
                print(f"PNG プレビュー(実描画・公式アイコン): {p}")
        else:
            if cli is None:
                print("draw.io CLI 不在 — SVG プレビューにフォールバック"
                      "(qlmanage -t -s 2000 <svg> -o . で PNG 化可)")
            want_svg = True
    if want_svg:
        stem = out.name.removesuffix(".drawio")
        for i, d in enumerate(diagrams):
            tab = preview_tab_suffix(diagrams, i, d)
            svg_path = out.with_name(f"{stem}{tab}.svg")
            svg_path.write_text(emit_svg(d, icons), encoding="utf-8")
            print(f"SVG プレビュー: {svg_path}")
    if changed:  # 書き戻しは生成が成功してから(失敗時に入力を汚さない)
        dump_spec(spec, spec_path)
        print(f"スペックを更新: {spec_path}")

    if not args.no_validate:
        import validate_drawio
        rc = validate_drawio.main([str(out)])
        if BUILD_WARNS:
            print(f"注意: 上のサマリ集計に入らないビルド段 WARN が "
                  f"{len(BUILD_WARNS)} 件({', '.join(BUILD_WARNS)})。"
                  "納品前に解消すること")
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())

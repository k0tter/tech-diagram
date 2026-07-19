#!/usr/bin/env python3
"""draw.io AWS アーキテクチャ図バリデータ。

図の「見やすさ」を機械的に検証する。チェック項目:

  E1  アイコン同士(ラベル込みバウンディングボックス)の重なり
  E2  子要素が親コンテナからはみ出している / パディング不足
  E3  エッジのセグメントがアイコン(ラベル込み)を貫通している
  E4  エッジのセグメントが斜め(直交していない)
  E5  エッジラベルがアイコンと重なっている
  E6  エッジに exitX/exitY または entryX/entryY が未指定(描画が非決定的になる)
  E7  2本のエッジが同一直線上で重なって走っている
  E8  アイコンがコンテナの境界線をまたいでいる(中途半端に重なっている)。
      style に awsdiagBoundary=1 を持つアイコンは意図的なまたぎ(IGW 等の
      公式流ゲートウェイ描画)として E2/E8 の対象外
  E9  圧縮された XML(検証不能。非圧縮で保存し直すこと)
  E10 id の重複(同一タブ内で mxCell の id が衝突)
  E11 mxCell の id が draw.io の予約語(JS の Array/Object プロパティ名。
      join/map/filter/length/toString 等)— PNG/SVG エクスポートが
      「Export failed」で沈黙破損する(CLI v30.3.11 実測)。ジェネレータは
      自動で末尾 "_" に退避するため、手編集 XML でのみ発生する
  E12 geometry/edge port の数値が NaN/Inf、または vertex の幅/高さが 0 以下
  W4  エッジラベル同士が重なっている(ごく小さな接触は無視)
  W8  マネージドサービス(S3/DynamoDB/SQS 等)が VPC/VNet・サブネットの内側にある
  W10 サブネット常駐サービス(EC2/RDS/ALB 等)が、サブネットを持つ VPC 内なのに
      サブネット外にある(LB 系の VPC 直下「またぎ表現」は許容)
  W11 グローバルサービス(CloudFront/Route 53/IAM/Organizations 等)が
      リージョンコンテナの内側にある(グローバルは region 外・aws_cloud 直下)
  W12 リファレンスアーキテクチャ図の番号バッジの整合(重複・欠番・説明パネル
      との件数不一致。バッジ自体は E1/E3 等の対象外)
  W13 エッジがコンテナ枠線の 10px 未満を 40px 以上並走(枠線と二重に見える)
  W14 ゲートウェイ/アタッチメント系ノードの配置規約違反(IGW/VGW=VPC 直下、
      NAT GW=パブリックサブネット内、TGW/Direct Connect=VPC 外。
      規約表は _common.GATEWAY_PLACEMENT — ビルド段の検査と共有)
  W16 フェイルオーバー線(awsdiagKind=failover。手編集図はラベルの
      failover/フェイルオーバーも後方互換で認識)が CloudFront/
      WAF をバイパスして DR の LB/コンピュートへ直行(平常時経路は CDN/WAF
      前段なのに非対称。ビルド段は kind=failover で同判定)— WARN
  W17 CloudFront/Route 53/WAF(CloudFront 接続)が region/VPC/サブネットの
      内側にある(グローバルサービスの境界誤り。W8/W11 の該当報告はこちらに
      集約)— ERROR
  W18 RDS/Aurora/ElastiCache 系がパブリックサブネット内にある — ERROR
  W19 外部クライアント(ユーザー/インターネット系)から DB への直接エッジ — ERROR
  W20 ラベルに Multi-AZ/HA/冗長とあるのに AZ コンテナ相当が 1 つ以下 — WARN
  W21 プライベートサブネット内ノードから外部クライアントへの直行エッジ
      (NAT/IGW/エンドポイント非経由)— WARN
      (W16〜W21 の語彙は _common — ビルド段 validate_spec の検査と共有)
  W*  同種の軽微な違反(クリアランス不足など)は WARN
  W5  エッジがコンテナのタイトル文字帯を貫通
  W6  矢じりの視認性(同一辺の端点が 10px 未満 / 矢じり延長線上に他エッジ)
  W7  両端が同一コンテナ内のエッジが、そのコンテナの外側を走行
  W15 フロー図形への上方からの流入が上辺以外に入射(フローチャート規約
      「上=入、左右下=出」。decision/gateway は上頂点 (0.5,0) — 1 本のみで、
      別の上方流入が上頂点を取っていれば側頂点の 2 本目は警告しない。
      process 等の箱は上方 src からの流入すべてが上辺 entryY=0 へ)
  I1  エッジ交差(交差したエッジの組と交点座標を列挙。目安 = 基本(ノード数
      連動)+ハブ次数補正。内訳は I1 メッセージに表示)

複数タブ(<diagram>)がある場合は全タブを検証する。
--json 出力の型: errors/warnings は件数(int)、findings は
[{level,code,message}] 配列、crossings は [{tab,a,b,x,y}] 配列。

単体適用時の守備範囲: E1 はアイコン同士、E8 はアイコン×コンテナの「またぎ」のみ。
コンテナ同士の重なり・親ではないコンテナへの完全内包・ラベルの左右はみ出しは
検出しない(ジェネレータ経由ならビルド時の container_extents 検査と列幅自動
拡張が防ぐため通常フローでは発生しない)。エンジンを介さず手編集した XML を
検証する場合は、その分を目視で補うこと。

使い方:
  python3 validate_drawio.py <file.drawio> [--json | --graph]

--graph は検証せず構成(vertex/edge の集合)をソート済みテキストで出力する。
スペック起こし直し前後の 2 ファイルを diff すれば「構成 1:1 不変」を機械照合できる。

終了コード: ERROR があれば 1、なければ 0。
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
import xml.etree.ElementTree as ET

from _common import AZ_LABEL_RE, COMPUTE_ICONS, CONTAINER_PARENTS, DB_ICONS, \
    DB_SUBNET_ICONS, EDGE_STACK_ICONS, EXTERNAL_CLIENT_ICONS, \
    FAILOVER_LABEL_RE, GATEWAY_PLACEMENT, HA_TEXT_RE, LB_ICONS, \
    crossing_budget, seg_intersect, text_width

# ---- しきい値(px) ----
ICON_GAP_WARN = 20      # アイコン(ラベル込み)同士の最小推奨間隔
EDGE_CLEAR_WARN = 8     # エッジとアイコンの最小推奨クリアランス
PAD_TOP_MIN = 25        # コンテナ上端の最小パディング(ラベル帯)
PAD_TOP_RECO = 34       # ラベル帯直下に子がある場合の推奨パディング(エンジン TOPB=34 と対)
PAD_SIDE_MIN = 10      # コンテナ左右・下端の最小パディング
FONT_DEFAULT = 12
MAX_SHOWN_PER_CODE = 8  # テキスト出力で同一コードの表示上限(--json は全件)
EDGE_LABEL_OVERLAP_MIN = 4  # エッジラベル同士: 両軸ともこれ以上食い込んだら W4(未満は接触扱い)

# E11: draw.io CLI/デスクトップの予約語 id(JS の Array/Object プロパティ名)。
# この id を持つ mxCell があると PNG/SVG エクスポートが「Export failed」で
# 沈黙破損する(v30.3.11 の id スイープで実測)。build_drawio.py の
# JS_UNSAFE_IDS と同一内容を保つこと(tests で照合)
JS_UNSAFE_IDS = frozenset((
    "at", "concat", "constructor", "copyWithin", "entries", "every", "fill",
    "filter", "find", "findIndex", "findLast", "findLastIndex", "flat",
    "flatMap", "forEach", "includes", "indexOf", "join", "keys", "lastIndexOf",
    "length", "map", "pop", "push", "reduce", "reduceRight", "reverse",
    "shift", "slice", "some", "sort", "splice", "toLocaleString", "toReversed",
    "toSorted", "toSpliced", "toString", "unshift", "values", "with",
    "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "valueOf",
    "__defineGetter__", "__defineSetter__", "__lookupGetter__",
    "__lookupSetter__", "__proto__",
))

# VPC/サブネットの内側に描くと不正確なマネージドサービス(W8)。
# RDS/Aurora/ElastiCache/Redshift/MSK/EC2/ALB 等の「サブネットに実在する」ものは含めない
MANAGED_OUTSIDE_VPC = frozenset({
    "s3", "dynamodb", "sqs", "sns", "eventbridge", "step_functions",
    "cloudfront", "route_53", "waf", "shield", "api_gateway",
    "cloudwatch_2", "cloudtrail", "config", "organizations", "control_tower",
    "athena", "glue", "quicksight", "kinesis", "kinesis_data_streams",
    "kinesis_data_firehose", "cognito", "simple_email_service", "backup",
    "secrets_manager", "key_management_service", "identity_and_access_management",
})

# Azure 版(azure2 の SVG ファイル名 snake)。VNet/サブネット内に描くと不正確な PaaS
AZURE_MANAGED_OUTSIDE_VNET = frozenset({
    "storage_accounts", "azure_cosmos_db", "service_bus", "event_hubs",
    "event_hub_clusters", "sql_database", "api_management_services",
    "log_analytics_workspaces", "application_insights",
    "azure_active_directory", "cdn_profiles", "blob_block", "storage_queue",
    "entra_id_protection", "entra_managed_identities", "key_vaults",
    "event_grid_topics", "event_grid_domains", "logic_apps", "monitor",
    "front_doors",
})
# GCP 版(gcp3 シェイプ名。同梱は 45 種のみなので該当も少数)
GCP_MANAGED_OUTSIDE_VPC = frozenset({
    "cloud_storage", "bigquery", "cloudspanner", "apigee", "vertexai",
    "looker", "securitycommandcenter",
})

# W8 の逆リスト(W10): サブネットに実在するサービス(AWS)。
# サブネットを持つ VPC 内に置かれているのにサブネットの外にあると境界が不正確
SUBNET_RESIDENT_AWS = frozenset({
    "ec2", "rds", "rds_instance", "aurora", "aurora_instance",
    "elasticache", "elasticache_for_redis", "elasticache_for_memcached",
    "memorydb_for_redis", "redshift", "managed_streaming_for_kafka",
    "elastic_load_balancing", "application_load_balancer",
    "network_load_balancer", "gateway_load_balancer", "classic_load_balancer",
})
# ロードバランサーは複数サブネットをまたいで実在するため、VPC 直下に置く
# 「またぎ表現」(同梱 3tier テンプレの流儀)は W10 の対象外にする
SUBNET_SPAN_OK = frozenset({
    "elastic_load_balancing", "application_load_balancer",
    "network_load_balancer", "gateway_load_balancer", "classic_load_balancer",
})

# リージョンの内側に描くと不正確なグローバルサービス(W11)。
# WAF(CloudFront 用/ALB 用)・ACM・Direct Connect 等の文脈依存は誤検知を
# 避けるため含めない(棲み分けの指針は SKILL.md 側に記載)
GLOBAL_SERVICES_AWS = frozenset({
    "cloudfront", "route_53", "global_accelerator", "organizations",
    "identity_and_access_management", "shield",
})


def strip_html(v):
    if not v:
        return ""
    v = re.sub(r"<br\s*/?>", "\n", v, flags=re.I)
    v = re.sub(r"</div>|</p>", "\n", v, flags=re.I)
    v = re.sub(r"<[^>]+>", "", v)
    return html.unescape(v).strip()


def parse_style(style):
    d = {}
    for part in (style or "").split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            d[k] = v
        elif part:
            d[part] = None
    return d


class Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def x2(self):
        return self.x + self.w

    @property
    def y2(self):
        return self.y + self.h

    def union(self, o):
        x1, y1 = min(self.x, o.x), min(self.y, o.y)
        x2, y2 = max(self.x2, o.x2), max(self.y2, o.y2)
        return Box(x1, y1, x2 - x1, y2 - y1)

    def inflate(self, m):
        return Box(self.x - m, self.y - m, self.w + 2 * m, self.h + 2 * m)

    def overlaps(self, o):
        return self.x < o.x2 and o.x < self.x2 and self.y < o.y2 and o.y < self.y2

    def contains(self, o):
        return self.x <= o.x and self.y <= o.y and self.x2 >= o.x2 and self.y2 >= o.y2

    def gap(self, o):
        dx = max(o.x - self.x2, self.x - o.x2, 0)
        dy = max(o.y - self.y2, self.y - o.y2, 0)
        return math.hypot(dx, dy) if (dx and dy) else max(dx, dy)

    def __repr__(self):
        return f"({self.x:.0f},{self.y:.0f} {self.w:.0f}x{self.h:.0f})"


class Cell:
    def __init__(self, el, user_object=None):
        self.el = el
        self.user_object = user_object
        attrs = user_object if user_object is not None else el
        self.id = attrs.get("id")
        self.value = (attrs.get("label", attrs.get("value", ""))
                      if user_object is not None else el.get("value", ""))
        self.link = attrs.get("link")
        self.kind = attrs.get("awsdiagKind") or el.get("awsdiagKind")
        self.style = parse_style(el.get("style", ""))
        self.parent = el.get("parent")
        self.source = el.get("source")
        self.target = el.get("target")
        self.is_vertex = el.get("vertex") == "1"
        self.is_edge = el.get("edge") == "1"
        g = el.find("mxGeometry")
        self.geo = g
        self.children = []

    def geo_f(self, attr, default=0.0):
        if self.geo is None:
            return default
        v = self.geo.get(attr)
        return float(v) if v is not None else default


class Diagram:
    def __init__(self, root_el):
        self.cells = {}
        wrapped = {}
        # draw.io はビルダー出力の UserObject に加え、UI でリンク等を編集した
        # セルを <object label link id> に直列化する。両方を包みとして扱わないと
        # リンク付きセルが cells から消える(E1/E2/E10/E11・graph の盲点。REV-5)
        for tag in ("UserObject", "object"):
            for obj in root_el.iter(tag):
                child = obj.find("mxCell")
                if child is not None:
                    wrapped[id(child)] = obj
        for el in root_el.iter("mxCell"):
            c = Cell(el, wrapped.get(id(el)))
            if c.id:
                self.cells[c.id] = c
        for c in self.cells.values():
            p = self.cells.get(c.parent)
            if p:
                p.children.append(c)

    def abs_origin(self, cell):
        """親チェーンをたどって絶対座標のオフセットを返す(循環はそこで打ち切り)。"""
        ox = oy = 0.0
        visited = {cell.id}
        p = self.cells.get(cell.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            if p.is_vertex:
                ox += p.geo_f("x")
                oy += p.geo_f("y")
            p = self.cells.get(p.parent)
        return ox, oy

    def abs_box(self, cell):
        ox, oy = self.abs_origin(cell)
        return Box(ox + cell.geo_f("x"), oy + cell.geo_f("y"),
                   cell.geo_f("width"), cell.geo_f("height"))

    def is_container(self, cell):
        if not cell.is_vertex:
            return False
        s = cell.style
        if s.get("container") == "1" or "grIcon" in s:
            return True
        if any(ch.is_vertex for ch in cell.children):
            return True
        # 塗りなし枠のみの矩形(AZ / Security group / 汎用グループ)。
        # image スタイル(Azure アイコン等)はアイコンでありコンテナではない
        if "shape" not in s and "image" not in s \
                and s.get("fillColor", "").lower() in ("none", "") \
                and s.get("verticalAlign") == "top":
            return True
        return False

    def label_lines(self, cell):
        txt = strip_html(cell.value)
        return [ln for ln in txt.split("\n") if ln.strip()]

    def icon_label_box(self, cell, box):
        """verticalLabelPosition=bottom のアイコンのラベル推定ボックス。"""
        lines = self.label_lines(cell)
        if not lines:
            return None
        font = float(cell.style.get("fontSize", FONT_DEFAULT))
        if cell.style.get("verticalLabelPosition") == "bottom":
            w = max(text_width(ln, font) for ln in lines)
            # ビルダーの実寸(text_size の line_h=16)に合わせる。大フォントは比例
            h = max(16.0, 1.3 * font) * len(lines)
            cx = box.x + box.w / 2
            return Box(cx - w / 2, box.y2 + 2, w, h)
        return None  # コンテナ等(内側ラベル)は E2 のパディング規則で担保

    def full_box(self, cell):
        cached = getattr(self, "_fb_cache", None)
        if cached is None:
            cached = self._fb_cache = {}
        if cell.id in cached:
            return cached[cell.id]
        b = self.abs_box(cell)
        lb = self.icon_label_box(cell, b)
        r = b.union(lb) if lb else b
        cached[cell.id] = r
        return r

    def is_ancestor(self, a, b):
        """a が b の祖先か(循環はそこで打ち切り)。"""
        visited = {b.id}
        p = self.cells.get(b.parent)
        while p is not None and p.id not in visited:
            if p.id == a.id:
                return True
            visited.add(p.id)
            p = self.cells.get(p.parent)
        return False


# ---- エッジ幾何 ----

def flow_shape_kind(cell):
    """フロー図形のスタイル署名から種別を推定する(W15 の一般化用)。

    返り値: "diamond"(decision/gateway — 端点が頂点固定)/ "box"
    (四角いフロー図形)/ None(フロー図形と断定できない)。
    ビルダー FLOW_STYLES の識別的な署名だけを見る — 手編集・独自スタイルは
    保守的に None(W9 と同じ誤検知ゼロ方針)。素の白矩形(process)は
    ENTITY_STYLE(align=left)・コンテナ類と紛れるため、追加の消極条件で
    絞る。
    """
    s = cell.style
    if "awsdiagBadge" in s:
        return None
    if "rhombus" in s or s.get("shape") == "mxgraph.bpmn.gateway2":
        return "diamond"
    if s.get("shape") in ("parallelogram", "document", "cylinder3",
                          "process", "delay", "hexagon"):
        return "box"
    if s.get("rounded") == "1" and s.get("arcSize") == "50":
        return "box"    # terminator
    if "ellipse" in s and s.get("aspect") == "fixed":
        return "box"    # junction / connector
    if (s.get("rounded") == "0" and "whiteSpace" in s and "shape" not in s
            and "image" not in s and s.get("align") != "left"
            and s.get("verticalAlign") != "top"):
        return "box"    # process(素の白矩形)
    return None


def terminal_point(diag, edge, term_id, prefix):
    cell = diag.cells.get(term_id) if term_id else None
    s = edge.style
    fx, fy = s.get(prefix + "X"), s.get(prefix + "Y")
    if cell is not None and cell.is_vertex:
        b = diag.abs_box(cell)
        if fx is not None and fy is not None:
            dx = float(s.get(prefix + "Dx", 0) or 0)
            dy = float(s.get(prefix + "Dy", 0) or 0)
            return (b.x + float(fx) * b.w + dx, b.y + float(fy) * b.h + dy), True
        return (b.x + b.w / 2, b.y + b.h / 2), False
    # 端点が図形に接続されていない場合は sourcePoint/targetPoint
    if edge.geo is not None:
        name = "sourcePoint" if prefix == "exit" else "targetPoint"
        for pt in edge.geo.findall("mxPoint"):
            if pt.get("as") == name:
                return (float(pt.get("x", 0)), float(pt.get("y", 0))), True
    return None, False


def edge_polyline(diag, edge):
    """エッジの折れ線(絶対座標)と exit/entry 指定の有無を返す。"""
    p0, has_exit = terminal_point(diag, edge, edge.source, "exit")
    pn, has_entry = terminal_point(diag, edge, edge.target, "entry")
    ox, oy = diag.abs_origin(edge)
    pts = []
    if edge.geo is not None:
        arr = edge.geo.find("Array[@as='points']")
        if arr is not None:
            for pt in arr.findall("mxPoint"):
                pts.append((float(pt.get("x", 0)) + ox, float(pt.get("y", 0)) + oy))
    poly = ([p0] if p0 else []) + pts + ([pn] if pn else [])
    return poly, has_exit, has_entry


def shared_trunk_len(pa, pb, tol=2.0):
    """同一始点から出る 2 折れ線が分岐点まで共有する経路(トランク)の長さ。

    fork 配線(1 点から出て途中まで同走し、分岐点から別方向へ分かれる)の
    トランクは意図的な同走なので、E7(重走)の対象から外すために使う。
    始点が tol を超えて離れていれば共有なし(0.0)。長さは直交線分前提の
    マンハッタン長(E7 判定側の弧長と同じ物差し)。
    """
    if abs(pa[0][0] - pb[0][0]) > tol or abs(pa[0][1] - pb[0][1]) > tol:
        return 0.0

    def step(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        if abs(dx) <= 0.75 and abs(dy) <= 0.75:
            return None  # 実質ゼロ長
        return (0, dx > 0) if abs(dx) >= abs(dy) else (1, dy > 0)

    total = 0.0
    i, j, ca, cb = 1, 1, pa[0], pb[0]
    while i < len(pa) and j < len(pb):
        da = step(ca, pa[i])
        if da is None:
            ca, i = pa[i], i + 1
            continue
        db = step(cb, pb[j])
        if db is None:
            cb, j = pb[j], j + 1
            continue
        ax = da[0]
        if da != db or abs(ca[1 - ax] - cb[1 - ax]) > tol:
            break  # 方向が割れた / レーンがずれた = 分岐点
        la = abs(pa[i][ax] - ca[ax])
        lb = abs(pb[j][ax] - cb[ax])
        adv = min(la, lb)
        total += adv
        sgn = 1.0 if da[1] else -1.0
        if ax == 0:
            ca, cb = (ca[0] + sgn * adv, ca[1]), (cb[0] + sgn * adv, cb[1])
        else:
            ca, cb = (ca[0], ca[1] + sgn * adv), (cb[0], cb[1] + sgn * adv)
        if la - adv <= 0.75:
            ca, i = pa[i], i + 1
        if lb - adv <= 0.75:
            cb, j = pb[j], j + 1
    return total


def clip_to_border(box, inside, outside):
    """inside(中心)から outside へ向かう線と box 境界の交点。"""
    x0, y0 = inside
    x1, y1 = outside
    dx, dy = x1 - x0, y1 - y0
    ts = []
    if dx:
        ts += [(box.x - x0) / dx, (box.x2 - x0) / dx]
    if dy:
        ts += [(box.y - y0) / dy, (box.y2 - y0) / dy]
    ts = [t for t in ts if 0 < t <= 1
          and box.x - 1e-6 <= x0 + t * dx <= box.x2 + 1e-6
          and box.y - 1e-6 <= y0 + t * dy <= box.y2 + 1e-6]
    if not ts:
        return outside
    t = min(ts)
    return (x0 + t * dx, y0 + t * dy)


def seg_box_clearance(a, b, box):
    """線分 ab と矩形の距離。交差していれば 0。軸平行前提の近似。"""
    (x1, y1), (x2, y2) = a, b
    sx1, sx2 = min(x1, x2), max(x1, x2)
    sy1, sy2 = min(y1, y2), max(y1, y2)
    dx = max(box.x - sx2, sx1 - box.x2, 0)
    dy = max(box.y - sy2, sy1 - box.y2, 0)
    return math.hypot(dx, dy)


def point_along(poly, x_param, offset, y_perp=0.0):
    """エッジラベル位置: geometry x(-1..1)+offset から座標を推定。"""
    if len(poly) < 2:
        return None
    lens = [math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
    total = sum(lens)
    if total == 0:
        return None
    d = (x_param + 1) / 2 * total
    acc = 0.0
    for i, ln in enumerate(lens):
        if acc + ln >= d or i == len(lens) - 1:
            t = (d - acc) / ln if ln else 0
            px = poly[i][0] + t * (poly[i + 1][0] - poly[i][0])
            py = poly[i][1] + t * (poly[i + 1][1] - poly[i][1])
            if y_perp and ln:
                ux = (poly[i + 1][0] - poly[i][0]) / ln
                uy = (poly[i + 1][1] - poly[i][1]) / ln
                px += -uy * y_perp
                py += ux * y_perp
            return (px + offset[0], py + offset[1])
        acc += ln
    return None


# ---- メイン検証 ----

def load_models(path):
    """[(タブ名, mxGraphModel | None)] を返す。None は圧縮タブ。"""
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag == "mxGraphModel":
        return [("", root)]
    out = []
    for i, d in enumerate(root.findall(".//diagram")):
        model = d.find("mxGraphModel")
        if model is None and (d.text or "").strip():
            model = None  # 圧縮されている
        out.append((d.get("name", f"tab{i}"), model))
    if not out:
        model = root.find(".//mxGraphModel")
        if model is not None:
            return [("", model)]
        raise SystemExit(f"mxGraphModel が見つかりません: {path}")
    return out


def validate(path):
    findings = []
    all_crossings = []
    models = load_models(path)
    multi = len(models) > 1
    tab_icons: dict[str, int] = {}
    tab_degs: dict[str, list[int]] = {}
    tab_edges: dict[str, int] = {}
    for tab_name, model in models:
        prefix = f"[{tab_name}] " if multi else ""
        if model is None:
            findings.append({"level": "ERROR", "code": "E9", "message":
                             prefix + "diagram が圧縮(base64)されています。非圧縮 XML で保存してください。"})
            continue
        f, c, n_icons, hub_degs, n_edges = validate_model(model)
        tab_icons[tab_name] = n_icons
        tab_degs[tab_name] = hub_degs
        tab_edges[tab_name] = n_edges
        for item in f:
            item["message"] = prefix + item["message"]
            findings.append(item)
        for cr in c:
            cr["tab"] = tab_name
            all_crossings.append(cr)
    if all_crossings:
        per_tab = {}
        for cr in all_crossings:
            per_tab[cr["tab"]] = per_tab.get(cr["tab"], 0) + 1
        # 交差の許容目安 = 基本(ノード数比例)+ ハブ次数補正(_common.crossing_budget)
        over = False
        details = []
        for t, cnt in per_tab.items():
            budget, base, corr, dens = crossing_budget(
                tab_icons.get(t, 0), tab_degs.get(t, ()),
                tab_edges.get(t))
            parts = [f"基本{base}"]
            if corr:
                parts.append(f"ハブ補正{corr}")
            if dens:
                parts.append(f"密度補正{dens}")
            detail = (f"目安 ≤{budget}={'+'.join(parts)}"
                      if len(parts) > 1 else f"目安 ≤{budget}")
            details.append(f"{t or '図'}: {cnt}({detail})")
            if cnt > budget:
                over = True
        findings.append({"level": "WARN" if over else "INFO", "code": "I1",
                         "message": f"エッジ交差 計 {len(all_crossings)} 箇所"
                         f"({', '.join(details)})。目安内なら微調整は不要"})
    if any(f["code"] == "E3" for f in findings):
        findings.append({"level": "INFO", "code": "H1", "message":
                         "E3(貫通)は密度の症状: 流入元を流入先の隣接列へ移す / "
                         "横断的な線はコンテナ端点に集約 / タブ分割、のどれかが効きます"})
    return findings, all_crossings


def validate_model(model):
    findings = []

    def add(level, code, msg):
        findings.append({"level": level, "code": code, "message": msg})

    ids = [el.get("id") for tag in ("mxCell", "UserObject", "object")
           for el in model.iter(tag) if el.get("id")]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        add("ERROR", "E10", f"mxCell の id が重複しています: {dup[:6]}"
            "(後勝ちで解釈されるため図が壊れます)")
    unsafe = sorted({i for i in ids if i in JS_UNSAFE_IDS})
    for uid in unsafe:
        add("ERROR", "E11", f"mxCell の id '{uid}' は draw.io の予約語"
            f"(JS の Array/Object プロパティ名)です — PNG/SVG エクスポートが"
            f"「Export failed」になります。'{uid}_' 等へ改名してください"
            "(ジェネレータ経由なら自動退避されます)")
    diag = Diagram(model)
    geometry_bad = False

    def check_number(cell, field, raw, *, positive=False):
        nonlocal geometry_bad
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = None
        if value is None or not math.isfinite(value):
            add("ERROR", "E12", f"cell '{cell.id}' の {field}={raw!r} は"
                "有限な数値ではありません")
            geometry_bad = True
        elif positive and value <= 0:
            add("ERROR", "E12", f"cell '{cell.id}' の {field}={raw!r} は"
                "正の数値である必要があります")
            geometry_bad = True

    # NaN/Inf は大小比較を全て偽にして幾何検査を静かにすり抜けるため、
    # 座標を使う前の信頼境界で一括拒否する。
    for c in diag.cells.values():
        if c.geo is not None:
            for attr in ("x", "y", "width", "height"):
                raw = c.geo.get(attr)
                if raw is not None:
                    check_number(c, f"mxGeometry.{attr}", raw,
                                 positive=c.is_vertex and attr in ("width", "height"))
            for point in c.geo.iter("mxPoint"):
                for attr in ("x", "y"):
                    raw = point.get(attr)
                    if raw is not None:
                        check_number(c, f"mxPoint.{attr}", raw)
        for attr in ("exitX", "exitY", "entryX", "entryY",
                     "exitDx", "exitDy", "entryDx", "entryDy"):
            raw = c.style.get(attr)
            if raw is not None:
                check_number(c, f"style.{attr}", raw)
    if geometry_bad:
        n_edges = sum(1 for c in diag.cells.values() if c.is_edge)
        return findings, [], 0, [], n_edges

    vertices = [c for c in diag.cells.values() if c.is_vertex and c.geo is not None
                and not (diag.cells.get(c.parent) or Cell(ET.Element("mxCell"))).is_edge]
    edges = [c for c in diag.cells.values() if c.is_edge]
    containers = [v for v in vertices if diag.is_container(v)]
    # 番号バッジ(awsdiagBadge)は意図的にエッジ上・アイコン角に載る注釈なので
    # icons(E1/E3/E5 等の対象)から除外し、W12 で番号の整合だけ検査する
    badges = [v for v in vertices
              if not diag.is_container(v) and "awsdiagBadge" in v.style]
    icons = [v for v in vertices
             if not diag.is_container(v) and "awsdiagBadge" not in v.style]

    def name(c):
        lbl = strip_html(c.value).replace("\n", " ")
        return f"'{lbl}'({c.id})" if lbl else f"({c.id})"

    # E1: アイコン同士の重なり / 間隔不足
    for i in range(len(icons)):
        for j in range(i + 1, len(icons)):
            a, b = icons[i], icons[j]
            ba, bb = diag.full_box(a), diag.full_box(b)
            if ba.overlaps(bb):
                add("ERROR", "E1", f"アイコン(ラベル込み)が重なっています: {name(a)} {ba} と {name(b)} {bb}")
            elif ba.gap(bb) < ICON_GAP_WARN:
                add("WARN", "W1", f"アイコン間隔が {ba.gap(bb):.0f}px しかありません(推奨 {ICON_GAP_WARN}px 以上): {name(a)} と {name(b)}")

    # E2: 親コンテナへの収まりとパディング
    for v in vertices:
        p = diag.cells.get(v.parent)
        if p is None or not p.is_vertex or not diag.is_container(p):
            continue
        if v.style.get("awsdiagBoundary") == "1":
            continue  # 意図的な境界またぎ(IGW 等)— 収まり・パディング対象外
        pb, vb = diag.abs_box(p), diag.abs_box(v)
        fb = diag.full_box(v)
        if not pb.contains(vb):
            add("ERROR", "E2", f"{name(v)} {vb} が親コンテナ {name(p)} {pb} からはみ出しています")
            continue
        pad_top = vb.y - pb.y
        pad = min(vb.x - pb.x, pb.x2 - vb.x2, pb.y2 - fb.y2)
        if pad_top < PAD_TOP_MIN:
            add("ERROR", "E2", f"{name(v)} の上パディングが {pad_top:.0f}px(最低 {PAD_TOP_MIN}px。コンテナのラベル帯と重なります)")
        if pad < PAD_SIDE_MIN:
            add("ERROR", "E2", f"{name(v)} と親 {name(p)} の左右/下の余白が {pad:.0f}px(最低 {PAD_SIDE_MIN}px)")
        # ラベル帯(左上)直下の子は 40px 空ける
        label_zone_w = 40 + text_width(strip_html(p.value)) + 20
        if pad_top < PAD_TOP_RECO and vb.x < pb.x + label_zone_w:
            add("WARN", "W2", f"{name(v)} が {name(p)} のラベル帯に近すぎます(上 {pad_top:.0f}px。ラベル下は {PAD_TOP_RECO}px 推奨)")

    # E8: コンテナ境界をまたぐアイコン
    for v in icons:
        if v.style.get("awsdiagBoundary") == "1":
            continue  # 意図的な境界またぎマーカー(手編集の公式流配置も対象)
        vb = diag.abs_box(v)
        for c in containers:
            if diag.is_ancestor(c, v) or diag.is_ancestor(v, c):
                continue
            cb = diag.abs_box(c)
            if vb.overlaps(cb) and not cb.contains(vb):
                add("ERROR", "E8", f"{name(v)} がコンテナ {name(c)} の境界線をまたいでいます")

    # W8: マネージドサービス(VPC/VNet 外のサービス)がサブネット等の内側にある
    def managed_service_name(v):
        img = v.style.get("image") or ""
        if "img/lib/azure2/" in img:  # Azure は SVG ファイル名から
            base = img.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
            return "azure", re.sub(r"[^a-z0-9]+", "_", base).strip("_")
        s = v.style.get("resIcon") or v.style.get("shape") or ""
        if ".gcp3." in s:
            return "gcp", s.rsplit(".", 1)[-1]
        return "aws", s.rsplit(".", 1)[-1]

    MANAGED = {"aws": MANAGED_OUTSIDE_VPC,
               "azure": AZURE_MANAGED_OUTSIDE_VNET,
               "gcp": GCP_MANAGED_OUTSIDE_VPC}

    # ネットワーク境界コンテナの署名(W8/W10/W14/W16〜W21 で共有)
    def subnet_like(cell):
        return (cell.style.get("grIcon", "").endswith("group_security_group")
                or cell.style.get("tdb") == "subnet")

    def vpc_like(cell):
        return (cell.style.get("grIcon", "").endswith("group_vpc2")
                or cell.style.get("tdb") == "vpc")

    def region_like(cell):
        return cell.style.get("grIcon", "").endswith("group_region")

    def subnet_kind(cell):
        """サブネットの public/private(エンジン既定の枠色)。不明は None。"""
        return {"#7AA116": "public_subnet",
                "#00A4A6": "private_subnet"}.get(
                    cell.style.get("strokeColor", ""))

    def ancestors(v):
        """親チェーンのセルを近い順に返す(循環はそこで打ち切り)。"""
        out = []
        visited = {v.id}
        p = diag.cells.get(v.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            out.append(p)
            p = diag.cells.get(p.parent)
        return out

    # ---- W16〜W21: アーキテクチャ・アンチパターン検査(SEM-3)----
    # 語彙(icon 集合・テキスト署名)は _common に一本化し、ビルド段
    # (build_drawio.validate_spec)と同じ判定を .drawio 側でも行う。
    # W17/W18/W19 は境界・到達性の事実誤り = ERROR、W16/W20/W21 は
    # 略図の意図があり得るため WARN。判別できない独自スタイルは
    # 保守的にスキップ(W9/W14 と同じ誤検知ゼロ方針)。
    def aws_icon(v):
        prov, svc = managed_service_name(v)
        return svc if prov == "aws" else None

    # W17(AP2): グローバルエッジサービスが region/VPC/サブネット内。
    # CloudFront/Route 53 は無条件、WAF は cloudfront ノードとエッジで
    # 接続されたもの(CloudFront スコープ)のみ対象 — ALB/API GW 用の
    # リージョナル WAF は region 内が正当のため。検出したノードは
    # W8/W11 の重複報告をスキップする(こちらの ERROR に集約)
    cf_cell_ids = {v.id for v in icons if aws_icon(v) == "cloudfront"}
    waf_cf_ids: set[str] = set()
    for e in edges:
        for a, b in ((e.source, e.target), (e.target, e.source)):
            if a in cf_cell_ids and b:
                other = diag.cells.get(b)
                if other is not None and other.is_vertex \
                        and aws_icon(other) == "waf":
                    waf_cf_ids.add(b)
    w17_nodes: set[str] = set()
    for v in icons:
        svc = aws_icon(v)
        if svc not in ("cloudfront", "route_53") and not (
                svc == "waf" and v.id in waf_cf_ids):
            continue
        hit = next((p for p in ancestors(v)
                    if region_like(p) or vpc_like(p) or subnet_like(p)), None)
        if hit is not None:
            w17_nodes.add(v.id)
            where = ("リージョン" if region_like(hit)
                     else "サブネット" if subnet_like(hit) else "VPC")
            add("ERROR", "W17",
                f"{name(v)} が {where} {name(hit)} 内にあります。CloudFront/"
                "Route 53(および CloudFront に関連付ける WAF = us-east-1 の"
                "グローバル web ACL)はグローバルサービスで、リージョン障害の"
                "切替対象ではありません — aws_cloud 直下に置き、切替はオリジン"
                "(LB)側で表現してください(出典: docs.aws.amazon.com/"
                "AmazonCloudFront/latest/DeveloperGuide/"
                "restrict-access-to-load-balancer.html / docs.aws.amazon.com/"
                "waf/latest/developerguide/web-acl-associating-aws-resource.html)")

    # W16(AP1): failover 線(ラベル署名で判定。ビルド段は kind=failover)が
    # CDN/WAF をバイパスして DR の LB/コンピュートへ直行。凡例の見本線
    # ("_" 始まり id)は対象外
    _fo_targets = LB_ICONS | COMPUTE_ICONS
    front_edge = any(
        e.source and e.target
        and (sc := diag.cells.get(e.source)) is not None and sc.is_vertex
        and (tc := diag.cells.get(e.target)) is not None and tc.is_vertex
        and aws_icon(sc) in EDGE_STACK_ICONS and aws_icon(tc) in _fo_targets
        for e in edges if not (e.id or "").startswith("_"))
    for e in edges:
        if (e.id or "").startswith("_") or not front_edge:
            continue
        if (e.kind != "failover"
                and not FAILOVER_LABEL_RE.search(strip_html(e.value))):
            continue
        s = diag.cells.get(e.source)
        t = diag.cells.get(e.target)
        if s is None or t is None or not s.is_vertex or not t.is_vertex:
            continue
        if aws_icon(t) not in _fo_targets or aws_icon(s) in EDGE_STACK_ICONS:
            continue
        if not any(region_like(p) or vpc_like(p) for p in ancestors(t)):
            continue
        add("WARN", "W16",
            f"フェイルオーバー経路がプライマリと非対称です: エッジ {name(e)}"
            f"({name(s)}→{name(t)})が CloudFront/WAF をバイパスして DR の "
            "LB/コンピュートへ直行しています。切替はオリジンだけにし、エッジ"
            "スタックは共通で通してください(バイパス経路は WAF 検査ゼロ、"
            "ALB を CloudFront 限定に保護する推奨構成では 403 で DR 不能。"
            "出典: docs.aws.amazon.com/wellarchitected/latest/"
            "reliability-pillar/rel_planning_for_recovery_config_drift.html"
            " / docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/"
            "restrict-access-to-load-balancer.html)")

    # W18(AP6a): DB/キャッシュがパブリックサブネット内(最寄りのサブネット
    # 祖先が public。枠色で判別できないサブネットは保守的にスキップ)
    for v in icons:
        if aws_icon(v) not in DB_SUBNET_ICONS:
            continue
        for p in ancestors(v):
            if subnet_like(p):
                if subnet_kind(p) == "public_subnet":
                    add("ERROR", "W18",
                        f"{name(v)} がパブリックサブネット {name(p)} 内に"
                        "あります。RDS/Aurora/ElastiCache は private subnet "
                        "に置き、インターネットから隠すのが公式推奨です"
                        "(DB サブネットグループは 2AZ 以上。出典: "
                        "docs.aws.amazon.com/AmazonRDS/latest/UserGuide/"
                        "USER_VPC.WorkingWithRDSInstanceinaVPC.html)")
                break
            if vpc_like(p):
                break

    # W19(AP6b): 外部クライアント → DB の直接エッジ
    for e in edges:
        s = diag.cells.get(e.source)
        t = diag.cells.get(e.target)
        if (s is not None and t is not None and s.is_vertex and t.is_vertex
                and aws_icon(s) in EXTERNAL_CLIENT_ICONS
                and aws_icon(t) in DB_ICONS):
            add("ERROR", "W19",
                f"エッジ {name(e)} は外部 {name(s)} から DB {name(t)} への"
                "直接線です。DB へのアクセスはアプリ層からのみ描きます"
                "(公式シナリオ: Web 層 public・DB 層 private、Web だけが "
                "DB にアクセス。出典: docs.aws.amazon.com/AmazonRDS/latest/"
                "UserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html)")

    # W20(AP3): HA/Multi-AZ/冗長の表記があるのに AZ コンテナ相当が 1 つ以下。
    # 生成物("_" 始まり id = 凡例・メタパネル)のテキストは対象外
    _w20_text = "\n".join(
        strip_html(c.value) for c in diag.cells.values()
        if c.value and c.id and not c.id.startswith("_"))
    _w20_m = HA_TEXT_RE.search(_w20_text)
    if _w20_m:
        az_n = sum(1 for c in containers
                   if (c.style.get("strokeColor") == "#147EBA"
                       and c.style.get("dashed") == "1")
                   or AZ_LABEL_RE.search(strip_html(c.value)))
        if az_n <= 1:
            add("WARN", "W20",
                f"ラベルに「{_w20_m.group(0)}」とありますが AZ コンテナ相当が "
                f"{az_n} 個です。本番の HA は 2AZ 以上に展開して描いてください"
                "(compute を両 AZ、RDS は primary/standby を別 AZ。意図的な"
                "略図なら表記側を見直す。出典: docs.aws.amazon.com/"
                "wellarchitected/latest/reliability-pillar/"
                "rel_fault_isolation_multiaz_region_system.html)")

    # W21(AP5): private subnet 内ノード → 外部クライアントへの直行エッジ
    # (NAT/IGW/エンドポイント非経由。経由省略の略図があり得るため WARN)
    for e in edges:
        s = diag.cells.get(e.source)
        t = diag.cells.get(e.target)
        if (s is None or t is None or not s.is_vertex or not t.is_vertex
                or aws_icon(t) not in EXTERNAL_CLIENT_ICONS):
            continue
        if any(diag.is_container(p) for p in ancestors(t)):
            continue  # 外部ノードが何かのコンテナ内 = 外部直行の形ではない
        src_subnet = None
        for p in ancestors(s):
            if subnet_like(p):
                src_subnet = subnet_kind(p)
                break
            if vpc_like(p):
                break
        if src_subnet != "private_subnet":
            continue
        add("WARN", "W21",
            f"エッジ {name(e)} はプライベートサブネット内の {name(s)} から"
            f"外部 {name(t)} への直行線です。private subnet は IGW への直接"
            "ルートを持たないため、外向きは NAT Gateway(public subnet)→"
            "IGW 経由で描いてください(AWS サービス宛なら VPC エンドポイント"
            "で NAT 不要。出典: docs.aws.amazon.com/vpc/latest/userguide/"
            "vpc-nat-gateway.html)")

    for v in icons:
        prov, svc = managed_service_name(v)
        if svc not in MANAGED[prov] or v.id in w17_nodes:
            continue  # w17_nodes は W17(ERROR)で報告済み — 重複させない
        visited = {v.id}
        p = diag.cells.get(v.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            ps = p.style
            gr = ps.get("grIcon", "")
            tdb = ps.get("tdb", "")
            if (gr.endswith("group_security_group") or gr.endswith("group_vpc2")
                    or tdb in ("subnet", "vpc")):
                where = ("サブネット" if gr.endswith("group_security_group")
                         or tdb == "subnet" else "VPC/VNet")
                add("WARN", "W8",
                    f"{name(v)} は {where} {name(p)} 内に置かれていますが、"
                    "マネージドサービスは VPC/VNet 外が正確です(私設アクセスは "
                    "エンドポイント系アイコンで表現。根拠: docs.aws.amazon.com"
                    "/vpc/latest/privatelink/gateway-endpoints.html)")
                break
            p = diag.cells.get(p.parent)

    # W10: サブネット常駐サービスが VPC 内なのにサブネット外にある(W8 の逆)。
    # 祖先を近い順にたどり、サブネット系に先に当たれば正常、VPC 系に先に
    # 当たれば警告。どちらも無い(クラウド外の演出ノード等)は対象外。
    # サブネットを 1 つも描いていない VPC(抽象度の高い図)では発火しない。
    # subnet_like / vpc_like は W8 の前(W16〜W21 ブロックの冒頭)で定義済み
    vpcs_with_subnet = set()  # 配下にサブネットを持つ VPC の id
    for c in vertices:
        if not subnet_like(c):
            continue
        visited = {c.id}
        p = diag.cells.get(c.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            if vpc_like(p):
                vpcs_with_subnet.add(p.id)
            p = diag.cells.get(p.parent)
    for v in icons:
        prov, svc = managed_service_name(v)
        if prov != "aws" or svc not in SUBNET_RESIDENT_AWS:
            continue
        visited = {v.id}
        p = diag.cells.get(v.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            if subnet_like(p):
                break  # サブネット(相当)の内側にいる: 正しい配置
            if vpc_like(p):
                if p.id in vpcs_with_subnet and not (
                        svc in SUBNET_SPAN_OK and v.parent == p.id):
                    add("WARN", "W10",
                        f"{name(v)} は VPC {name(p)} 内に置かれていますが、サブネットの"
                        "外です(EC2/RDS/ALB 等はサブネット内が正確。SG がサブネットを"
                        "またぐ場合は AZ ごとに SG を複製)")
                break
            p = diag.cells.get(p.parent)

    # W9: コンテナ階層の慣例(ビルド時検査の移植 — 手編集した既存 .drawio を
    # validate だけ通す経路でも階層違反(VPC 二重入れ子等)を検出する)。
    # スタイル署名から本スキルのコンテナ型を推定し、判別できない独自スタイルは
    # 保守的にスキップ(偽陽性を出さない)。
    _GRICON_TYPES = {
        "group_aws_cloud_alt": "aws_cloud", "group_region": "region",
        "group_vpc2": "vpc", "group_security_group": "_subnet",
        "group_account": "account",
        "group_ec2_instance_contents": "ec2_contents",
        "group_corporate_data_center": "corporate_dc",
        "group_auto_scaling_group": "auto_scaling",
    }
    _TDB_TYPES = {("vpc", "#0078D4"): "vnet", ("vpc", "#4285F4"): "gcp_vpc",
                  ("subnet", "#7FBAE3"): "az_subnet",
                  ("subnet", "#669DF6"): "gcp_subnet"}
    # (strokeColor, dashed("1"/None), 追加キー=値, 型)— PLAIN 系の判別
    _PLAIN_TYPES = (
        ("#CD2264", "1", None, "ou"), ("#147EBA", "1", None, "az"),
        ("#DD3522", None, None, "security_group"),
        ("#5C2D91", "1", None, "mgmt_group"),
        ("#0078D4", "1", None, "subscription"),
        ("#8A8886", "1", None, "resource_group"),
        ("#F9AB00", "1", None, "folder"),
        ("#DADCE0", None, None, "project"),
        ("#BDC1C6", "1", None, "gcp_zone"),
        ("#5A6C86", "1", ("spacingLeft", "10"), "generic"),
    )

    def conv_type(cell) -> str | None:
        s = cell.style
        gr = s.get("grIcon", "")
        for suffix, t in _GRICON_TYPES.items():   # grIcon が最優先
            if gr.endswith(suffix):               # (基底 GRP は
                return t                          #  shape=mxgraph.aws4.group)
        if "resIcon" in s or s.get("shape", "").startswith("mxgraph."):
            return None                       # アイコン・図形はコンテナでない
        t = _TDB_TYPES.get((s.get("tdb", ""), s.get("strokeColor", "")))
        if t:
            return t
        if not diag.is_container(cell):
            return None
        stroke, dashed = s.get("strokeColor", ""), s.get("dashed")
        for want_stroke, want_dash, extra, t in _PLAIN_TYPES:
            if stroke != want_stroke or dashed != want_dash:
                continue
            if extra and s.get(extra[0]) != extra[1]:
                continue
            return t
        return None

    def parents_ok(ctype: str, ptype: str | None) -> bool:
        key = "public_subnet" if ctype == "_subnet" else ctype
        allowed = CONTAINER_PARENTS.get(key)
        if allowed is None:
            return True
        if ptype == "_subnet":
            return bool({"public_subnet", "private_subnet"} & allowed)
        return ptype in allowed

    for v in diag.cells.values():
        if not v.is_vertex:
            continue
        ctype = conv_type(v)
        if ctype is None:
            continue
        visited = {v.id}
        p = diag.cells.get(v.parent)
        ptype = None
        while p is not None and p.id not in visited:
            visited.add(p.id)
            pt = conv_type(p)
            if pt is not None:
                ptype = pt
                break
            p = diag.cells.get(p.parent)
        if not parents_ok(ctype, ptype):
            shown = "public/private_subnet" if ctype == "_subnet" else ctype
            add("WARN", "W9",
                f"コンテナ階層が慣例と合いません: {shown} {name(v)} の親が "
                f"{ptype or 'トップレベル'}(根拠: サブネット⊂AZ = "
                "docs.aws.amazon.com/vpc/latest/userguide/configure-subnets.html"
                " / ルート→OU→アカウント = docs.aws.amazon.com/organizations/"
                "latest/userguide/orgs_getting-started_concepts.html)")

    # W11: グローバルサービスがリージョンコンテナの内側にある
    # (cloudfront/route_53 は W17 が ERROR で報告済みならスキップ)
    for v in icons:
        prov, svc = managed_service_name(v)
        if prov != "aws" or svc not in GLOBAL_SERVICES_AWS \
                or v.id in w17_nodes:
            continue
        visited = {v.id}
        p = diag.cells.get(v.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            if p.style.get("grIcon", "").endswith("group_region"):
                add("WARN", "W11",
                    f"{name(v)} はリージョン {name(p)} 内に置かれていますが、"
                    "グローバルサービスです(region の外・aws_cloud 直下が正確。"
                    "マルチリージョン図では region の真上の行に置く。根拠: "
                    "docs.aws.amazon.com/whitepapers/latest/"
                    "aws-fault-isolation-boundaries/global-services.html)")
                break
            p = diag.cells.get(p.parent)

    # W14: ゲートウェイ/アタッチメント系ノードの配置規約(ビルド時検査の対。
    # 表は _common.GATEWAY_PLACEMENT に一本化)。祖先を近い順にたどり、最初に
    # 当たったネットワーク境界(vpc 系 / subnet 系。無ければ None = VPC 外)が
    # 許容集合に無ければ警告。public/private の別はサブネットの strokeColor
    # (エンジン既定 #7AA116/#00A4A6)で判定し、判別できない subnet は
    # public/private のどちらかが許される規約なら保守的にスキップ(誤検知回避)。
    # awsdiagBoundary=1(on_boundary)は親の枠線上 = 親直下扱い(E2/E8 と同じ)。
    # 親が全て root のフラットな手編集ファイルはアイコン中心の幾何包含で判定。
    # サブネットを 1 つも描いていない VPC(抽象度の高い図。実例: マルチ
    # アカウント図の Egress VPC 直下の NAT)では、subnet 配置を要求する規約は
    # 発火しない — W10 と同じ抽象度ルール(vpcs_with_subnet を共有)
    def w14_boundary(cell):
        if subnet_like(cell):
            return {"#7AA116": "public_subnet",
                    "#00A4A6": "private_subnet"}.get(
                        cell.style.get("strokeColor", ""), "subnet")
        if vpc_like(cell):
            return "vpc"
        return None

    for v in icons:
        prov, svc = managed_service_name(v)
        rule = GATEWAY_PLACEMENT.get(svc) if prov == "aws" else None
        if rule is None:
            continue
        allowed, hint, url = rule
        ctx = where = None
        found_container = False
        visited = {v.id}
        p = diag.cells.get(v.parent)
        while p is not None and p.id not in visited:
            visited.add(p.id)
            if diag.is_container(p):
                found_container = True
                b = w14_boundary(p)
                if b:
                    ctx, where = b, p
                    break
            p = diag.cells.get(p.parent)
        if not found_container:
            vb = diag.abs_box(v)
            cx, cy = vb.x + vb.w / 2, vb.y + vb.h / 2
            best = None
            for c in containers:
                b = w14_boundary(c)
                if b is None:
                    continue
                cb = diag.abs_box(c)
                if cb.x <= cx <= cb.x2 and cb.y <= cy <= cb.y2 and (
                        best is None or cb.w * cb.h < best[0]):
                    best = (cb.w * cb.h, b, c)
            if best is not None:
                ctx, where = best[1], best[2]
        if ctx in allowed or (ctx == "subnet"
                              and {"public_subnet", "private_subnet"} & allowed):
            continue
        if (ctx == "vpc" and where is not None
                and where.id not in vpcs_with_subnet
                and {"public_subnet", "private_subnet"} & allowed):
            continue  # サブネット未描画の VPC 直下は抽象表現として許容
        place = (f"{'VPC/VNet' if ctx == 'vpc' else 'サブネット'} "
                 f"{name(where)} 内" if where is not None else "VPC の外")
        add("WARN", "W14",
            f"{name(v)} は {place}にあります。{hint}(出典: {url})")

    # エッジ検証
    polylines = {}
    edge_labels = []  # W4 用: (エッジ, テキスト, ラベル推定ボックス)
    for e in edges:
        poly, has_exit, has_entry = edge_polyline(diag, e)
        src, tgt = diag.cells.get(e.source), diag.cells.get(e.target)
        if src is not None and not has_exit:
            add("WARN", "E6", f"エッジ {name(e)} に exitX/exitY がありません(始点の位置が非決定的になります)")
            if len(poly) >= 2:
                poly[0] = clip_to_border(diag.abs_box(src), poly[0], poly[1])
        if tgt is not None and not has_entry:
            add("WARN", "E6", f"エッジ {name(e)} に entryX/entryY がありません(終点の位置が非決定的になります)")
            if len(poly) >= 2:
                poly[-1] = clip_to_border(diag.abs_box(tgt), poly[-1], poly[-2])
        polylines[e.id] = poly

        # E4: 直交チェック
        for k in range(len(poly) - 1):
            (x1, y1), (x2, y2) = poly[k], poly[k + 1]
            if abs(x1 - x2) > 0.75 and abs(y1 - y2) > 0.75:
                hint = ""
                s_, t_ = diag.cells.get(e.source), diag.cells.get(e.target)
                if (s_ and diag.is_container(s_)) or (t_ and diag.is_container(t_)):
                    hint = "(端点がコンテナ: 境界セル不足の可能性 → 実ノードの直指定も検討)"
                add("ERROR", "E4", f"エッジ {name(e)} の区間 ({x1:.0f},{y1:.0f})→({x2:.0f},{y2:.0f}) が斜めです。waypoint を追加して直交させてください{hint}")

        # E3: アイコン貫通
        for v in icons:
            if v.id in (e.source, e.target):
                continue
            fb = diag.full_box(v)
            for k in range(len(poly) - 1):
                cl = seg_box_clearance(poly[k], poly[k + 1], fb)
                if cl == 0:
                    add("ERROR", "E3", f"エッジ {name(e)} がアイコン {name(v)} {fb} を貫通しています")
                    break
                elif cl < EDGE_CLEAR_WARN:
                    add("WARN", "W3", f"エッジ {name(e)} とアイコン {name(v)} のクリアランスが {cl:.0f}px(推奨 {EDGE_CLEAR_WARN}px 以上)")
                    break

        # E5: エッジ自身のラベル位置
        label_pts = []
        if strip_html(e.value) and e.geo is not None:
            xp = float(e.geo.get("x", 0) or 0)
            yp = float(e.geo.get("y", 0) or 0)
            off = (0.0, 0.0)
            op = e.geo.find("mxPoint[@as='offset']")
            if op is not None:
                off = (float(op.get("x", 0) or 0), float(op.get("y", 0) or 0))
            pt = point_along(poly, xp, off, yp)
            if pt:
                label_pts.append((e, strip_html(e.value), pt, e))
        # 子ラベルセル
        for ch in e.children:
            if ch.is_vertex and strip_html(ch.value):
                xp = ch.geo_f("x")
                op = ch.geo.find("mxPoint[@as='offset']") if ch.geo is not None else None
                off = (float(op.get("x", 0) or 0), float(op.get("y", 0) or 0)) if op is not None else (0, 0)
                pt = point_along(poly, xp, off)
                if pt:
                    label_pts.append((e, strip_html(ch.value), pt, ch))
        for _, txt, (lx, ly), label_cell in label_pts:
            font = float(label_cell.style.get("fontSize", 11) or 11)
            lines = txt.split("\n")
            w = max(text_width(ln, font) for ln in lines)
            # ビルダーの実寸(text_size の line_h=16)に合わせる。大フォントは比例
            h = max(16.0, 1.3 * font) * len(lines)
            lbox = Box(lx - w / 2, ly - h / 2, w, h)
            edge_labels.append((e, txt, lbox))
            for v in icons:
                vb = diag.full_box(v)
                if v.id in (e.source, e.target):
                    # 端点アイコンは 4px 以上の食い込みのみ(かすりは許容)
                    ib = diag.abs_box(v)
                    ox = min(lbox.x2, ib.x2) - max(lbox.x, ib.x)
                    oy = min(lbox.y2, ib.y2) - max(lbox.y, ib.y)
                    if ox >= 4 and oy >= 4:
                        add("ERROR", "E5", f"エッジラベル '{txt}' が端点アイコン {name(v)} を {ox:.0f}x{oy:.0f}px 欠けさせています")
                    continue
                if lbox.overlaps(vb):
                    add("ERROR", "E5", f"エッジラベル '{txt}' {lbox} がアイコン {name(v)} と重なっています")

    # W5: エッジ × コンテナタイトル文字帯(題字の上を線が走ると文字が潰れる)
    bands = []
    for c in containers:
        if not strip_html(c.value):
            continue
        cb = diag.abs_box(c)
        # 実テキストは spacingLeft=30 から(左の空白は帯に含めない)。
        # 幅がコンテナに収まらない題字は draw.io が折り返すため、帯の高さも
        # 行数ぶんに広げる(ビルダー側の title_bands モデルと同じ規約)
        full_tw = text_width(strip_html(c.value).split("\n")[0], 12) + 12
        tw = min(full_tw, cb.w - 28)
        if tw <= 0:
            continue
        lines_ = max(1, math.ceil(full_tw / max(tw, 1.0)))
        bands.append((c, Box(cb.x + 28, cb.y + 3, tw, 16 * lines_)))
    for e in edges:
        poly, _hx, _he = edge_polyline(diag, e)
        if not poly:
            continue
        hit = None
        for a, b in zip(poly, poly[1:]):
            for c, band in bands:
                if (min(a[0], b[0]) < band.x2 and band.x < max(a[0], b[0])
                        and min(a[1], b[1]) < band.y2
                        and band.y < max(a[1], b[1])):
                    hit = (c, a, b)
                    break
            if hit:
                break
        if hit:
            add("WARN", "W5", f"エッジ {name(e)} がコンテナ {name(hit[0])} の"
                f"タイトル文字帯を貫通しています({hit[1][0]:.0f},{hit[1][1]:.0f} 付近)")

    # W6: 矢じりの視認性
    tips = []   # (端点, 逆側点, ノードid, 辺, edge, is_entry)
    for e in edges:
        poly, _hx, _he = edge_polyline(diag, e)
        if len(poly) < 2:
            continue
        st = e.style
        for is_entry, term, fx_k, fy_k in ((False, e.source, "exitX", "exitY"),
                                           (True, e.target, "entryX", "entryY")):
            if not term or fx_k not in st:
                continue
            tip = poly[-1] if is_entry else poly[0]
            nxt = poly[-2] if is_entry else poly[1]
            fx = round(float(st[fx_k]), 2)
            fy = round(float(st.get(fy_k.replace("X", "Y"), 0.5) or 0.5), 2)
            side = "L" if fx == 0 else "R" if fx == 1 else \
                   "T" if fy == 0 else "B" if fy == 1 else "?"
            tips.append((tip, nxt, term, side, e, is_entry))
    seen_pairs = set()
    for i in range(len(tips)):
        for j in range(i + 1, len(tips)):
            a, b = tips[i], tips[j]
            if a[2] != b[2] or a[3] != b[3] or a[2] is None:
                continue
            if not (a[5] or b[5]):
                continue   # exit 同士(矢じりなし)は無害
            v = diag.cells.get(a[2])
            if v is not None and v.style.get("rhombus") is None \
                    and "rhombus" not in (v.style or {}):
                d = math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1])
                if d < 10 and (a[4].id, b[4].id) not in seen_pairs:
                    seen_pairs.add((a[4].id, b[4].id))
                    add("WARN", "W6", f"エッジ {name(a[4])} と {name(b[4])} の"
                        f"端点が同一辺で {d:.0f}px しか離れていません"
                        "(矢じりが重なって見えます)")
    edge_polys = [(e, edge_polyline(diag, e)[0]) for e in edges]
    for tip, nxt, term, side, e, is_entry in tips:
        if not is_entry:
            continue   # 矢じりは entry 側
        horiz = abs(tip[1] - nxt[1]) < 1
        for oe, opoly in edge_polys:
            if oe is e or not opoly:
                continue
            fused = False
            for c, d in zip(opoly, opoly[1:]):
                o_h = abs(c[1] - d[1]) < 1
                if o_h != horiz:
                    continue
                if horiz and abs(c[1] - tip[1]) < 5:
                    near = min(abs(c[0] - tip[0]), abs(d[0] - tip[0]))
                    inside = min(c[0], d[0]) - 2 <= tip[0] <= max(c[0], d[0]) + 2
                    if near < 16 or inside:
                        fused = True
                if not horiz and abs(c[0] - tip[0]) < 5:
                    near = min(abs(c[1] - tip[1]), abs(d[1] - tip[1]))
                    inside = min(c[1], d[1]) - 2 <= tip[1] <= max(c[1], d[1]) + 2
                    if near < 16 or inside:
                        fused = True
                if fused:
                    break
            if fused:
                add("WARN", "W6", f"エッジ {name(e)} の矢じり"
                    f"({tip[0]:.0f},{tip[1]:.0f})の延長線上を {name(oe)} が"
                    "走っており 1 本の線に見えます")
                break

    # W15: フロー図形への上方からの流入は上辺へ(R7-15 decision / R7-A3 で
    # 全フロー図形に一般化。フローチャート規約「上=入、左右下=出」)。
    # decision/gateway は端点が頂点固定のため上頂点 (0.5,0) を取れるのは
    # 1 本 — 上方流入のどれかが既に上頂点に入っていれば、残りの上方流入は
    # 側頂点で正当(2 本目の救済)として警告しない。四角い箱(process 等)は
    # 辺上に複数ポートを並べられるため、上方 src(src 下端 ≤ dst 上端)からの
    # 流入は全て上辺(entryY=0。辺内の x ずれは fan スロットとして正当)。
    # entry 未指定は自動アタッチとしてスキップ(decision は E6 が別途検出)
    flow_in = {}
    for e in edges:
        tgt = diag.cells.get(e.target)
        src = diag.cells.get(e.source)
        if (tgt is None or src is None or not tgt.is_vertex
                or e.source == e.target or diag.is_container(tgt)):
            continue
        fkind = flow_shape_kind(tgt)
        if fkind is None:
            continue
        st = e.style
        try:
            fx = round(float(st["entryX"]), 3)
            fy = round(float(st["entryY"]), 3)
        except (KeyError, TypeError, ValueError):
            continue
        db = diag.abs_box(tgt)
        sb = diag.abs_box(src)
        if fkind == "diamond":
            above = sb.y + sb.h / 2 < db.y      # R7-15 と同じ基準(中心 y)
        else:
            above = sb.y2 <= db.y + 0.5         # R7-A3: src 下端 ≤ dst 上端
        flow_in.setdefault(tgt.id, []).append((e, above, fx, fy, fkind))
    for tid, ins in sorted(flow_in.items()):
        above_ins = [it for it in ins if it[1]]
        if not above_ins:
            continue
        t_ = diag.cells[tid]
        if ins[0][4] == "diamond":
            if any((fx, fy) == (0.5, 0.0) for _e, _a, fx, fy, _k in above_ins):
                continue
            for e, _a, fx, fy, _k in above_ins:
                add("WARN", "W15",
                    f"エッジ {name(e)} は上方から decision {name(t_)} へ入るのに"
                    f"上頂点 (0.5,0) でなく ({fx:g},{fy:g}) へ入射しています"
                    "(フローチャート規約: 上方からの主フロー流入は上頂点)")
        else:
            for e, _a, fx, fy, _k in above_ins:
                if fy != 0.0:
                    add("WARN", "W15",
                        f"エッジ {name(e)} は上方からフロー図形 {name(t_)} へ"
                        f"入るのに上辺でなく ({fx:g},{fy:g}) へ入射しています"
                        "(フローチャート規約: 上方からの流入は上辺へ)")

    # W7: 両端が同一コンテナ内なのに、その外側を走るエッジ(外周迂回の誤読)
    for e in edges:
        s_ = diag.cells.get(e.source)
        t_ = diag.cells.get(e.target)
        if s_ is None or t_ is None or diag.is_container(s_) \
                or diag.is_container(t_):
            continue
        sb, tb = diag.abs_box(s_), diag.abs_box(t_)
        best = None
        for c in containers:
            cb = diag.abs_box(c)
            if cb.contains(sb) and cb.contains(tb):
                if best is None or cb.w * cb.h < best[1].w * best[1].h:
                    best = (c, cb)
        if best is None:
            continue
        c, cb = best
        # トップレベルコンテナ(AWS Cloud 等)は網の境界 — 猶予 8px。
        # 入れ子コンテナはすぐ外の回廊が正常経路のため従来の 30px
        tol = 8 if c.parent in (None, "1") else 30
        poly, _hx, _he = edge_polyline(diag, e)
        out_pt = next(((px, py) for px, py in poly
                       if px < cb.x - tol or px > cb.x2 + tol
                       or py < cb.y - tol or py > cb.y2 + tol), None)
        if out_pt:
            add("WARN", "W7", f"エッジ {name(e)} は両端が {name(c)} 内なのに"
                f"外側({out_pt[0]:.0f},{out_pt[1]:.0f})を走っています")

    # W12: リファレンスアーキテクチャ図の番号バッジの整合
    # (重複・欠番・ステップ説明パネルとの件数不一致)
    if badges:
        nums = []
        for b in badges:
            t = strip_html(b.value)
            if t.isdigit():
                nums.append(int(t))
        dups = sorted({n for n in nums if nums.count(n) > 1})
        if dups:
            add("WARN", "W12", f"番号バッジが重複しています: {dups}")
        if nums and max(nums) > 999:  # 巨大値で range を実体化しない(ハング防止)
            add("WARN", "W12", f"番号バッジの値が大きすぎます(最大 {max(nums)}。"
                "step は 1 からの連番)")
            nums = []
        if nums:
            missing = sorted(set(range(1, max(nums) + 1)) - set(nums))
            if missing:
                add("WARN", "W12", f"番号バッジに欠番があります: {missing}"
                    "(step は 1 から連番)")
        panel = diag.cells.get("_steps")
        if panel is not None:
            plines = [ln for ln in strip_html(panel.value).splitlines()
                      if re.match(r"\d+\.", ln.strip())]
            if nums and len(plines) != max(nums):
                add("WARN", "W12",
                    f"ステップ説明が {len(plines)} 件に対し図中の最大番号が "
                    f"{max(nums)} です(1:1 に対応させる)")
        elif nums:
            add("WARN", "W12", "番号バッジがあるのにステップ説明パネル"
                "(steps)がありません")

    # W13: エッジがコンテナ枠線と並走(枠に貼り付き、二重境界に見える)。
    # 横切るのは正常。並走のみを、エッジごとに最悪 1 件だけ報告する
    W13_DIST, W13_LEN = 10.0, 40.0
    for e in edges:
        poly = polylines.get(e.id) or []
        worst = None  # (dist, run, コンテナ名, x, y)
        for c in containers:
            cb = diag.abs_box(c)
            for k in range(len(poly) - 1):
                (x1, y1), (x2, y2) = poly[k], poly[k + 1]
                if abs(y1 - y2) <= 0.75:      # 水平区間 × 上下辺
                    lo, hi = min(x1, x2), max(x1, x2)
                    run = min(hi, cb.x2) - max(lo, cb.x)
                    if run < W13_LEN:
                        continue
                    for by in (cb.y, cb.y2):
                        d = abs(y1 - by)
                        if d < W13_DIST and (worst is None or run > worst[1]):
                            worst = (d, run, name(c),
                                     (max(lo, cb.x) + min(hi, cb.x2)) / 2, y1)
                elif abs(x1 - x2) <= 0.75:    # 垂直区間 × 左右辺
                    lo, hi = min(y1, y2), max(y1, y2)
                    run = min(hi, cb.y2) - max(lo, cb.y)
                    if run < W13_LEN:
                        continue
                    for bx in (cb.x, cb.x2):
                        d = abs(x1 - bx)
                        if d < W13_DIST and (worst is None or run > worst[1]):
                            worst = (d, run, name(c), x1,
                                     (max(lo, cb.y) + min(hi, cb.y2)) / 2)
        if worst:
            d, run, cname, wx, wy = worst
            add("WARN", "W13",
                f"エッジ {name(e)} が {cname} の枠線の {d:.0f}px 隣を "
                f"{run:.0f}px 並走しています(({wx:.0f},{wy:.0f}) 付近)。"
                "枠線と二重に見えるため、配置替え・--optimize・exit/entry 指定で"
                "回廊の中央へ離してください")

    # W4: エッジラベル同士の重なり(E5 と同じ推定ボックスのペア総当たり)。
    # 両軸とも EDGE_LABEL_OVERLAP_MIN px 以上食い込んだ場合のみ警告し、
    # かすった程度の接触は無視して誤検知を抑える
    for i in range(len(edge_labels)):
        for j in range(i + 1, len(edge_labels)):
            ea, ta, ba = edge_labels[i]
            eb, tb, bb = edge_labels[j]
            if ea.id == eb.id:
                continue  # 同一エッジ内の複数ラベルは位置指定で意図的に並べることがある
            ox = min(ba.x2, bb.x2) - max(ba.x, bb.x)
            oy = min(ba.y2, bb.y2) - max(ba.y, bb.y)
            if ox >= EDGE_LABEL_OVERLAP_MIN and oy >= EDGE_LABEL_OVERLAP_MIN:
                add("WARN", "W4",
                    f"エッジラベル '{ta}' {ba} と '{tb}' {bb} が重なっています"
                    f"(食い込み {ox:.0f}x{oy:.0f}px)")

    # E7: エッジ同士の重走 / I1: 交差(組と交点座標を列挙)
    def manhattan_cum(poly):
        out = [0.0]
        for k in range(len(poly) - 1):
            out.append(out[-1] + abs(poly[k + 1][0] - poly[k][0])
                       + abs(poly[k + 1][1] - poly[k][1]))
        return out

    crossings = []
    eids = list(polylines)
    for i in range(len(eids)):
        for j in range(i + 1, len(eids)):
            pa, pb = polylines[eids[i]], polylines[eids[j]]
            ea, eb = diag.cells[eids[i]], diag.cells[eids[j]]
            # fork(同一 source から同一始点 ±2px で出るエッジ群)が分岐点まで
            # 共有するトランクは意図的な同走 → その区間だけ E7 の対象外にする。
            # fan-in(同一 target へ同一終点 ±2px で収束するエッジ群)の合流点
            # 以降のトランクも対称に免除する(R4-5)。誤免除ガードも対称:
            # 終点がずれた平行同走は免除しない(shared_trunk_len の ±2px)・
            # 経路全長が一致する完全重複はただの二重線として E7 に残す
            trunk_s = trunk_d = 0.0
            cum_a = cum_b = None
            if pa and pb and ea.source and ea.source == eb.source:
                trunk_s = shared_trunk_len(pa, pb)
            if pa and pb and ea.target and ea.target == eb.target:
                trunk_d = shared_trunk_len(pa[::-1], pb[::-1])
            if trunk_s > 0.0 or trunk_d > 0.0:
                cum_a, cum_b = manhattan_cum(pa), manhattan_cum(pb)
                if (trunk_s >= cum_a[-1] - 2.0 and trunk_s >= cum_b[-1] - 2.0):
                    trunk_s = 0.0  # 全長一致 = 分岐しない重複エッジ(fork ではない)
                if (trunk_d >= cum_a[-1] - 2.0 and trunk_d >= cum_b[-1] - 2.0):
                    trunk_d = 0.0  # 同上(合流しない重複エッジ)
            for k in range(len(pa) - 1):
                for m in range(len(pb) - 1):
                    a1, a2, b1, b2 = pa[k], pa[k + 1], pb[m], pb[m + 1]
                    ip = seg_intersect(a1, a2, b1, b2)
                    if ip:
                        crossings.append({"a": ea.id, "b": eb.id, "x": round(ip[0]), "y": round(ip[1])})
                        add("INFO", "I1", f"交差: {name(ea)} × {name(eb)} @ ({ip[0]:.0f},{ip[1]:.0f})")
                    # 平行重走(同軸で近接し、区間が重なる)
                    for axis in (0, 1):
                        o = 1 - axis
                        if (abs(a1[axis] - a2[axis]) < 0.75 and abs(b1[axis] - b2[axis]) < 0.75
                                and abs(a1[axis] - b1[axis]) < 6):
                            lo = max(min(a1[o], a2[o]), min(b1[o], b2[o]))
                            hi = min(max(a1[o], a2[o]), max(b1[o], b2[o]))
                            if hi - lo > 20:
                                if trunk_s > 0.0:
                                    # 重なり区間の遠端(始点から見て)の弧長が
                                    # 両エッジともトランク内 → 共有区間なので免除
                                    end_a = cum_a[k] + max(abs(lo - a1[o]),
                                                           abs(hi - a1[o]))
                                    end_b = cum_b[m] + max(abs(lo - b1[o]),
                                                           abs(hi - b1[o]))
                                    if (end_a <= trunk_s + 2.0
                                            and end_b <= trunk_s + 2.0):
                                        continue
                                if trunk_d > 0.0:
                                    # fan-in: 終点から測った遠端の弧長が両エッジ
                                    # とも終点側トランク内 → 合流区間なので免除
                                    beg_a = cum_a[-1] - (cum_a[k]
                                                         + min(abs(lo - a1[o]),
                                                               abs(hi - a1[o])))
                                    beg_b = cum_b[-1] - (cum_b[m]
                                                         + min(abs(lo - b1[o]),
                                                               abs(hi - b1[o])))
                                    if (beg_a <= trunk_d + 2.0
                                            and beg_b <= trunk_d + 2.0):
                                        continue
                                add("WARN", "E7", f"エッジ {name(ea)} と {name(eb)} が {hi - lo:.0f}px にわたり重なって走っています")

    # 交差予算の分母はテキストセル(凡例・メタ情報)を除いた実アイコン数
    n_real = sum(1 for v in icons
                 if "shape" in v.style or "resIcon" in v.style
                 or "image" in v.style)  # image = Azure(azure2 は画像スタイル)
    # ハブ次数(交差目安の補正用)。公式アイコンのノードだけ数える —
    # entity・フロー図形は関連が多くても交差ゼロが普通なので対象外
    iconish = {v.id for v in icons
               if "resIcon" in v.style or "image" in v.style
               or v.style.get("shape", "").startswith("mxgraph.")}
    deg: dict[str, int] = {}
    for e in edges:
        for t in (e.source, e.target):
            if t in iconish:
                deg[t] = deg.get(t, 0) + 1
    return (findings, crossings, n_real,
            sorted(deg.values(), reverse=True), len(edges))


def print_findings(findings: list[dict]) -> None:
    """コードごとに表示上限を設けてテキスト出力する(全件は --json で)。"""
    shown: dict[str, int] = {}
    hidden: dict[str, int] = {}
    for f in findings:
        code = f["code"]
        if shown.get(code, 0) < MAX_SHOWN_PER_CODE:
            print(f"[{f['level']}] {code}: {f['message']}")
            shown[code] = shown.get(code, 0) + 1
        else:
            hidden[code] = hidden.get(code, 0) + 1
    for code, n in hidden.items():
        print(f"... {code} は他 {n} 件(全件は --json で確認)")


def _dump_graph(path: str) -> int:
    """構成(vertex/edge 集合)をソート済みで出力する(--graph)。

    凡例・メタ等の生成物("_" 始まりの id)は除外。起こし直しの前後で
    diff すれば構成の 1:1 不変を照合できる。"""
    for tab_name, model in load_models(path):
        diag = Diagram(model)
        lines = []
        for c in diag.cells.values():
            if not c.id or c.id in ("0", "1") or c.id.startswith("_"):
                continue
            label = strip_html(c.value).replace("\n", "␤")
            if c.is_vertex:
                parent = c.parent if c.parent not in ("0", "1") else "-"
                lines.append(f"vertex\t{c.id}\t{label}\t{parent}")
            elif c.is_edge and (c.source or c.target):
                lines.append(f"edge\t{c.source}->{c.target}\t{label}")
        print(f"# tab: {tab_name or '図'}({len(lines)} 要素)")
        for ln in sorted(lines):
            print(ln)
    return 0


def _main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = None
    as_json = as_graph = False
    for a in argv:
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a == "--json":
            as_json = True
        elif a == "--graph":
            as_graph = True
        elif a.startswith("-"):
            print(f"ERROR: 不明なオプション: {a}(--help で使い方)", file=sys.stderr)
            return 2
        elif path is None:
            path = a
        else:
            print(f"ERROR: 引数が多すぎます: {a}", file=sys.stderr)
            return 2
    if path is None:
        print(__doc__)
        return 2
    if as_graph:
        return _dump_graph(path)

    findings, crossings = validate(path)
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: order[f["level"]])
    errors = sum(1 for f in findings if f["level"] == "ERROR")
    warns = sum(1 for f in findings if f["level"] == "WARN")
    if as_json:
        print(json.dumps({"errors": errors, "warnings": warns,
                          "crossings": crossings, "findings": findings},
                         ensure_ascii=False, indent=2))
    else:
        print_findings(findings)
        print(f"\n=== {errors} error(s), {warns} warning(s) ===")
        if errors == 0 and warns == 0:
            print("OK: 重なり・貫通・斜め線は検出されませんでした。")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except FileNotFoundError as exc:
        print(f"ERROR: ファイルが見つかりません: {exc.filename}", file=sys.stderr)
        return 2
    except ET.ParseError as exc:
        print(f"ERROR: XML として読めません: {exc}"
              "(draw.io で非圧縮 XML として保存し直してください)", file=sys.stderr)
        return 2
    except SystemExit:
        raise
    except Exception as exc:
        import os
        if os.environ.get("AWSDIAG_TRACE") == "1":
            raise
        print(f"ERROR: 検証中に想定外のエラー({type(exc).__name__}: {exc})。"
              "ファイルが .drawio(非圧縮 mxGraphModel)か確認してください。"
              "詳細は AWSDIAG_TRACE=1 で再実行", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

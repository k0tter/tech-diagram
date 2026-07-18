"""tech-diagram スキル共通モジュール。

build_drawio.py / validate_drawio.py / find_icon.py が共有する
アイコン解決・テキスト幅見積もり・線分幾何をまとめる。依存は標準ライブラリのみ。
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

_REFS = Path(__file__).resolve().parent.parent / "references"
ICONS_TSV = _REFS / "icons-data.tsv"          # AWS(プレフィックスなし)
PROVIDER_TSVS = {"azure": _REFS / "icons-azure.tsv",
                 "gcp": _REFS / "icons-gcp.tsv"}

# draw.io AWS4 公式スタイル(2021+ フラットカラー版)
SERVICE_STYLE = (
    "sketch=0;points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],"
    "[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],[0,0.25,0],[0,0.5,0],[0,0.75,0],"
    "[1,0.25,0],[1,0.5,0],[1,0.75,0]];outlineConnect=0;fontColor=#232F3E;"
    "fillColor={fill};strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;"
    "verticalAlign=top;align=center;html=1;fontSize=12;fontFamily=Arial;"
    "fontStyle=0;aspect=fixed;"
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{name};"
)
RESOURCE_STYLE = (
    "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;"
    "fillColor={fill};strokeColor=none;dashed=0;verticalLabelPosition=bottom;"
    "verticalAlign=top;align=center;html=1;fontSize=12;fontFamily=Arial;"
    "fontStyle=0;aspect=fixed;"
    "pointerEvents=1;shape=mxgraph.aws4.{name};"
)
# Azure(draw.io 同梱 azure2。SVG 画像参照方式)/ GCP(gcp3 ステンシル)
AZURE_STYLE = (
    "image;aspect=fixed;html=1;points=[];align=center;fontSize=12;fontFamily=Arial;"
    "fontColor=#232F3E;verticalLabelPosition=bottom;verticalAlign=top;"
    "labelBackgroundColor=none;image=img/lib/azure2/{path};"
)
GCP_STYLE = (
    "sketch=0;html=1;fontColor=#232F3E;verticalLabelPosition=bottom;"
    "verticalAlign=top;align=center;fontSize=12;fontFamily=Arial;"
    "fontStyle=0;aspect=fixed;"
    "pointerEvents=1;shape=mxgraph.gcp3.{name};fillColor={fill};"
)

IconRow = dict[str, str]


def load_icons() -> dict[str, list[IconRow]]:
    """全プロバイダのアイコンを name → 候補行リストで返す。

    AWS はプレフィックスなし、Azure/GCP は "azure:name" / "gcp:name"。
    """
    icons: dict[str, list[IconRow]] = {}
    with ICONS_TSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            icons.setdefault(row["name"], []).append(row)
    for prefix, path in PROVIDER_TSVS.items():
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                icons.setdefault(f"{prefix}:{row['name']}", []).append(row)
    for rows in icons.values():
        rows.sort(key=lambda r: r["kind"] != "service")
    return icons


def icon_style(row: IconRow) -> str:
    """アイコン行 1 件から draw.io スタイル文字列を組み立てる。"""
    kind = row["kind"]
    if kind == "azure":   # fillColor 列に SVG 相対パスを収めている
        return AZURE_STYLE.format(path=row["fillColor"])
    if kind == "gcp":
        return GCP_STYLE.format(name=row["name"], fill=row["fillColor"])
    tmpl = SERVICE_STYLE if kind == "service" else RESOURCE_STYLE
    return tmpl.format(fill=row["fillColor"], name=row["name"])


# よく使う略称・現行サービス名 → TSV 上の実名(全て実在を検証済み)
ICON_ALIASES = {
    "cloudwatch": "cloudwatch_2",
    "ses": "simple_email_service",
    "kms": "key_management_service",
    "alb": "application_load_balancer",
    "nlb": "network_load_balancer",
    "msk": "managed_streaming_for_kafka",
    "opensearch": "elasticsearch_service",
    "documentdb": "documentdb_with_mongodb_compatibility",
}


def resolve_icon(icons: dict[str, list[IconRow]], name: str,
                 kind: str | None = None) -> IconRow:
    """name(と任意の kind)からアイコン行を 1 件選ぶ。

    見つからないときは部分一致とあいまい一致の候補を添えて LookupError。
    候補は同じプロバイダに限る(無印=AWS、azure:/gcp: はそのプレフィックス)。
    """
    if name.startswith("aws:"):
        name = name[4:]
    name = ICON_ALIASES.get(name, name)
    rows = icons.get(name)
    if rows:
        if kind:
            rows = [r for r in rows if r["kind"] == kind] or rows
        return rows[0]
    import difflib
    prov = name.split(":", 1)[0] + ":" if ":" in name else None
    pool = [k for k in icons
            if (k.startswith(prov) if prov else ":" not in k)]
    starts = sorted(k for k in pool if k.startswith(name))[:4]
    subs = sorted(k for k in pool
                  if len(name) >= 4 and (name in k or k in name))[:6]
    fuzzy = difflib.get_close_matches(name, pool, n=6, cutoff=0.6)
    cands = list(dict.fromkeys(starts + subs + fuzzy))[:8]
    raise LookupError(
        f"icon '{name}' が見つかりません。候補: {cands or 'なし'}"
        f"(scripts/find_icon.py {name} で検索を)")


# ---- テキスト幅見積もり(CJK=等幅、その他=0.62 倍) ----

CJK_RANGES = ((0x2E80, 0x9FFF), (0x3040, 0x30FF), (0xFF00, 0xFFEF), (0xAC00, 0xD7AF))


def text_width(s: str, font: float = 12.0) -> float:
    """1 行ぶんのおよその描画幅(px)。

    文字数×単価で計算する(float の逐次加算は Python 3.12 の sum() 補償
    加算化でバージョン間の最下位ビット差が出る — 出力のバイト決定性を
    バージョン非依存にするため、整数カウント×乗算の形に固定)。"""
    wide = sum(1 for ch in s if any(a <= ord(ch) <= b for a, b in CJK_RANGES))
    return wide * font + (len(s) - wide) * (font * 0.62)


def text_size(s: str, font: float = 12.0, line_h: float = 16.0) -> tuple[float, float]:
    """複数行テキストの (幅, 高さ) を返す。幅には余白 6px を含む。"""
    lines = str(s).split("\n") or [""]
    return max(text_width(ln, font) for ln in lines) + 6, line_h * len(lines)


# ---- 交差の許容目安 ----

def crossing_budget(n_icons: int, hub_degrees=(),
                    n_edges: int | None = None) -> tuple[int, int, int, int]:
    """エッジ交差数の許容目安。返り値: (目安, 基本, ハブ補正, 密度補正)。

    基本 = max(2, round(アイコン数/10))。ハブ補正 = Σ max(0, 次数−4)
    (次数5以上のノード)+ ハブ(次数6以上)が複数あれば +(ハブ数−1)。
    グリッドのセルは4辺しかないため、5本目以降のスポークは他エッジの
    レーンと競合して交差が原理的に増える。次数はアイコンノード端点の
    エッジ数のみ数える(コンテナ端点・ER/UML の entity・フロー図形は
    数えない — 関連が多くても交差ゼロが普通なため)。

    密度補正 = round(0.7 × max(0, エッジ数 − 1.3 × アイコン数))。
    完全表現の密グラフ(E > 1.3N)は平面性が下がり交差が原理的に増える
    (実測較正: 30〜150 ノード×3 位相の 15 ケース)。n_edges 省略時は 0。
    """
    base = max(2, round(n_icons / 10))
    corr = sum(d - 4 for d in hub_degrees if d >= 5)
    corr += max(0, sum(1 for d in hub_degrees if d >= 6) - 1)
    dens = (round(0.7 * max(0, n_edges - 1.3 * n_icons))
            if n_edges is not None else 0)
    return base + corr + dens, base, corr, dens


# ---- 線分幾何 ----

Point = tuple[float, float]


def _ccw(p: Point, q: Point, r: Point) -> float:
    return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])


def seg_intersect(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    """線分 ab, cd の交点を返す(交差しなければ None。共有端点は交差に数えない)。"""
    for p in (a, b):
        for q in (c, d):
            if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
                return None
    d1, d2 = _ccw(c, d, a), _ccw(c, d, b)
    d3, d4 = _ccw(a, b, c), _ccw(a, b, d)
    if not (((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))):
        return None
    denom = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
    if abs(denom) < 1e-9:
        return None
    t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / denom
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def seg_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """線分 ab, cd が交差するか(共有端点・collinear 接触は除く)。

    真偽判定専用の高速版。バウンディングボックスで先に棄却する
    (直交配線では大半のペアが遠く離れている)。
    """
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    if (ax if ax > bx else bx) < (cx if cx < dx else dx):
        return False
    if (cx if cx > dx else dx) < (ax if ax < bx else bx):
        return False
    if (ay if ay > by else by) < (cy if cy < dy else dy):
        return False
    if (cy if cy > dy else dy) < (ay if ay < by else by):
        return False
    for px, py in ((ax, ay), (bx, by)):
        for qx, qy in ((cx, cy), (dx, dy)):
            if abs(px - qx) < 1e-6 and abs(py - qy) < 1e-6:
                return False
    d1 = (ay - cy) * (dx - cx) - (ax - cx) * (dy - cy)
    d2 = (by - cy) * (dx - cx) - (bx - cx) * (dy - cy)
    if (d1 > 0) == (d2 > 0):
        return False
    d3 = (cy - ay) * (bx - ax) - (cx - ax) * (by - ay)
    d4 = (dy - ay) * (bx - ax) - (dx - ax) * (by - ay)
    return (d3 > 0) != (d4 > 0)


# コンテナ階層の慣例(親として妥当な type。None = トップレベル)。
# ビルド時(build_drawio の validate_spec)とバリデータ(validate_drawio の
# 手編集 .drawio 検査)の両方が W9 判定に使う共有テーブル。
# 根拠: サブネット⊂単一AZ = docs.aws.amazon.com/vpc/latest/userguide/
# configure-subnets.html / ルート→OU→アカウント = docs.aws.amazon.com/
# organizations/latest/userguide/orgs_getting-started_concepts.html
CONTAINER_PARENTS = {
    "aws_cloud": {None, "account"},
    "ou": {None, "aws_cloud", "ou"},
    "account": {None, "aws_cloud", "ou"},
    "region": {None, "aws_cloud", "account"},
    "vpc": {None, "region", "aws_cloud", "account"},
    "az": {"vpc", "region"},
    "public_subnet": {"vpc", "az"},
    "private_subnet": {"vpc", "az"},
    "security_group": {"vpc", "az", "public_subnet", "private_subnet"},
    "auto_scaling": {"vpc", "az", "public_subnet", "private_subnet",
                     "generic"},  # ECS: cluster(generic)>service(auto_scaling)
    # Azure: Management Group > Subscription > Resource Group > VNet > Subnet
    "mgmt_group": {None},
    "subscription": {None, "mgmt_group"},
    "resource_group": {None, "subscription"},
    "vnet": {None, "resource_group", "subscription"},
    "az_subnet": {"vnet"},
    # GCP: Organization/Folder > Project > VPC Network > Subnet(リージョナル)
    "folder": {None},
    "project": {None, "folder"},
    "gcp_vpc": {None, "project"},
    "gcp_subnet": {"gcp_vpc"},
    "gcp_zone": {None, "project", "gcp_vpc", "gcp_subnet", "region"},
}

# ゲートウェイ/アタッチメント系アイコンの配置規約(W14)。
# icon 名(ICON_ALIASES 解決後の TSV 実名)→ (許容配置, 修正ヒント, 出典 URL)。
# 「配置」= 祖先を近い順にたどって最初に当たるネットワーク境界
# (vpc / public_subnet / private_subnet。None = どの境界にも入っていない
# = VPC 外)。ビルド時(build_drawio の validate_spec)は spec の parent 連鎖、
# バリデータ(validate_drawio の W14)はスタイル署名の親探索+幾何包含で
# 同じ表を引く。on_boundary(awsdiagBoundary=1)ノードは「親の枠線上」=
# 親直下として扱う。subnet 配置を要求する規約(NAT)は、サブネットを 1 つも
# 描いていない VPC の直下では発火しない(W10 と同じ抽象度ルール — 実例:
# マルチアカウント図の Egress VPC)。複数配置が実務で正当な icon(ELB 系:
# VPC 直下またぎと subnet 内の両方がある)と Azure/GCP の同型(Azure VPN GW は
# GatewaySubnet=サブネット内が正当等、機械判定に確信が持てない)は載せない
# — 誤検知ゼロ優先。
GATEWAY_PLACEMENT = {
    # IGW は VPC にアタッチする VPC コンポーネント(サブネット内は不正確。
    # VPC を描かない抽象図は対象外 = None 許容)
    "internet_gateway": (
        frozenset({"vpc", None}),
        "IGW は VPC 直下(できれば on_boundary=\"left|top|…\" で枠線上)が正確です",
        "docs.aws.amazon.com/vpc/latest/userguide/VPC_Internet_Gateway.html"),
    # パブリック NAT GW はパブリックサブネット内に作成する
    "nat_gateway": (
        frozenset({"public_subnet"}),
        "NAT Gateway は public subnet 内が正確です(VPC 間・オンプレ向け"
        "プライベート NAT の意図がある場合のみ private subnet も正当)",
        "docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html"),
    # TGW は VPC 間を結ぶリージョナルハブ(VPC の外。VPC とはアタッチメント)
    "transit_gateway": (
        frozenset({None}),
        "Transit Gateway は VPC の外(region/aws_cloud 直下)に置き、"
        "VPC とはエッジで結ぶのが正確です",
        "docs.aws.amazon.com/vpc/latest/tgw/what-is-transit-gateway.html"),
    # VGW は VPC にアタッチ(サブネット内は不正確)
    "vpn_gateway": (
        frozenset({"vpc", None}),
        "VGW は VPC 直下(できれば on_boundary で枠線上)が正確です",
        "docs.aws.amazon.com/vpn/latest/s2svpn/how_it_works.html"),
    # Direct Connect はオンプレ⇔AWS の接続サービス(VPC の外)
    "direct_connect": (
        frozenset({None}),
        "Direct Connect は VPC の外(オンプレとリージョンの接続点)が正確です",
        "docs.aws.amazon.com/directconnect/latest/UserGuide/Welcome.html"),
}


# ---- アーキテクチャ・アンチパターン検査(W16〜W21)の共有語彙 ----
# SEM-3: AWS 一次情報に接地したアンチパターン・カタログのうち、曖昧さゼロで
# 機械判定できる 6 件をビルド段(build_drawio.validate_spec)とバリデータ
# (validate_drawio)の両方で検査する。icon 名は ICON_ALIASES 解決後の TSV 実名。
# 集合に無い icon は検査対象外(W14 と同じ誤検知ゼロ優先の方針)。

# フェイルオーバーの切替先になるリージョン内 LB / コンピュート(W16)
LB_ICONS = frozenset({
    "elastic_load_balancing", "application_load_balancer",
    "network_load_balancer", "gateway_load_balancer", "classic_load_balancer",
})
COMPUTE_ICONS = frozenset({"ec2", "ecs", "eks", "fargate", "ecs_service",
                           "lambda"})
# エッジスタック(CDN/WAF)= 平常時・障害時とも共通に通すべき前段(W16)
EDGE_STACK_ICONS = frozenset({"cloudfront", "waf"})

# サブネット常駐の DB / キャッシュ(W18: public subnet 配置は不正確)。
# S3/DynamoDB 等のマネージド DB は VPC 外が正しく、境界は W8 が検査済み
DB_SUBNET_ICONS = frozenset({
    "rds", "rds_instance", "aurora", "aurora_instance",
    "elasticache", "elasticache_for_redis", "elasticache_for_memcached",
    "memorydb_for_redis",
})
# 外部→DB 直結(W19)の対象はサブネット常駐 DB+マネージド DB
DB_ICONS = DB_SUBNET_ICONS | frozenset({
    "dynamodb", "redshift", "documentdb_with_mongodb_compatibility",
    "neptune", "keyspaces", "timestream",
})
# 外部クライアント(ユーザー/インターネット)系ノード(W19/W21 の端点判定)。
# office_building(オンプレ)は DX/VPN 経由が正当経路のため含めない
EXTERNAL_CLIENT_ICONS = frozenset({
    "users", "user", "client", "mobile_client",
    "internet", "internet_alt1", "internet_alt2", "internet_alt22",
})

# W20: HA 主張のテキスト署名(Multi-AZ / マルチAZ / 冗長 / 高可用 / 単語 HA。
# "HA" は大文字のみ・前後に英字が続く語中一致を除く — CJK 隣接では \b が
# 効かないため lookaround で判定)
HA_TEXT_RE = re.compile(
    r"(?i:multi[-_ ]?az|マルチ\s?az)|冗長|高可用|(?<![A-Za-z])HA(?![A-Za-z])")
# W20: AZ コンテナ相当のラベル署名(AZ-a / AZ 1 / アベイラビリティ(ー)ゾーン)。
# "Multi-AZ" 自体には一致しない(識別子つきの AZ 表記のみ)
AZ_LABEL_RE = re.compile(
    r"(?<![A-Za-z])AZ[ -]?[0-9a-dA-D](?![A-Za-z0-9])"
    r"|アベイラビリティー?\s?ゾーン|Availability\s?Zone", re.IGNORECASE)
# W16(バリデータ側): failover 線のラベル署名(ビルド段は kind で判定)
FAILOVER_LABEL_RE = re.compile(r"failover|フェイルオーバー|フェールオーバー",
                               re.IGNORECASE)

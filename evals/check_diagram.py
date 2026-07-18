#!/usr/bin/env python3
"""tech-diagram の eval 用 grading ヘルパ。生成された .drawio を客観判定する。

evals/evals.json の expectations のうち機械照合できる部分(0 error・0 warning、
交差が目安内か、特定の検査コードが出ていない/出ている、既存構成の 1:1 保持)を
バリデータ経由で自動チェックする。判断・レポート系(Abstraction Notes の質、
縮約の妥当性など)は人手/採点エージェントが成果物とトランスクリプトで見る。

依存: Python 標準ライブラリのみ。同スキルの scripts/validate_drawio.py を呼ぶ。

使い方:
  # 基本(0 error・0 warning を判定。交差数と目安、全 finding コードを表示)
  python3 evals/check_diagram.py <out.drawio>

  # コードの在/不在を要求(例: リファレンス図は W12 が無いこと、AWS 図は W8/W11 が無いこと)
  python3 evals/check_diagram.py <out.drawio> --absent W12 W8 W11

  # スペックからビルドし直して、ビルド段の警告(W9・legend 未掲載・meta 欠落)も含めて判定
  #   validate --json は幾何/境界(E*・W1-W8/W10-W14・I1)のみ。W9・legend・meta は
  #   build_drawio.py の段でしか出ないため、完全な 0 警告判定には --spec を使う。
  python3 evals/check_diagram.py --spec <out.spec.json>

  # 既存図の 1:1 保持(modify eval): baseline の全頂点・辺が残っているか
  python3 evals/check_diagram.py <out.drawio> --graph-superset evals/files/modify/webapp.drawio

  # ルータ回帰チェック(FB第3R: 接続アンカー / ファンアウト対称 / レーン分離、
  # FB第4R: 出射辺の方向 / 垂直ペア中心 / 兄弟コンテナ寸法、
  # FB第5R: ファン辺の流儀統一 / 折れ点上限 / 同一辺ポート分離 / fork 形状、
  # 第7R: decision 頂点 / id / 両端ラベル / ER / stereotype / flow shape / gateway)も判定
  python3 evals/check_diagram.py <out.drawio> --router

  # まとめて JSON で受け取る(採点エージェント向け)
  python3 evals/check_diagram.py <out.drawio> --json
"""
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
VALIDATOR = SCRIPTS / "validate_drawio.py"
BUILDER = SCRIPTS / "build_drawio.py"

sys.path.insert(0, str(SCRIPTS))
import validate_drawio as V  # noqa: E402  幾何(セグメント抽出・座標系)を E7/W5 と共有する


def build_from_spec(spec_path):
    """spec をビルドし (produced_drawio_path, build_warn_lines) を返す。
    ビルド段の警告(W9・legend 未掲載・meta 欠落など)は build stdout の
    'WARN:' 行と '注意:' 行にしか出ないので、それを拾う。"""
    out_dir = Path(tempfile.mkdtemp(prefix="checkdiagram-"))
    out = out_dir / "built.drawio"
    cp = subprocess.run(
        [sys.executable, str(BUILDER), str(spec_path), "-o", str(out)],
        capture_output=True, text=True,
    )
    if not out.exists():
        raise SystemExit(f"ビルド失敗(spec を直して再生成が必要): "
                         f"{cp.stderr.strip() or cp.stdout.strip()}")
    warn_lines = [ln.strip() for ln in cp.stdout.splitlines()
                  if ln.strip().startswith("WARN:") or ln.strip().startswith("注意:")]
    return out, warn_lines


def run_validator(path, extra=()):
    """validate_drawio.py を呼び、(stdout, returncode) を返す。"""
    cp = subprocess.run(
        [sys.executable, str(VALIDATOR), str(path), *extra],
        capture_output=True, text=True,
    )
    return cp.stdout, cp.stderr, cp.returncode


def validate_json(path):
    out, err, rc = run_validator(path, ("--json",))
    if rc == 2:
        raise SystemExit(f"バリデータ実行エラー(rc=2): {err.strip() or out.strip()}")
    return json.loads(out)


def graph_lines(path):
    """--graph の出力から、比較対象になる vertex/edge 行だけを集合で返す。"""
    out, _, rc = run_validator(path, ("--graph",))
    if rc == 2:
        raise SystemExit(f"--graph 実行エラー: {path}")
    lines = set()
    for ln in out.splitlines():
        ln = ln.rstrip()
        if ln.startswith("vertex\t") or ln.startswith("edge\t"):
            lines.add(ln)
    return lines


def budget_from_findings(findings):
    """I1 finding のメッセージから交差の目安(≤N)を取り出す。無ければ None。"""
    for f in findings:
        if f.get("code") == "I1":
            m = re.search(r"目安\s*[≤<]=?\s*(\d+)", f.get("message", ""))
            if m:
                return int(m.group(1))
    return None


# ---- ルータ回帰チェック(FB第3R「接続して見える > 直線 > 折れ点最少」+
#      FB第4R「出射辺の方向 / 垂直ペア中心 0.5 / 兄弟コンテナ寸法等化」)----
# 幾何は validate_drawio.py の E7/W5 と同じ規約で測る: エッジ折れ線は
# edge_polyline(絶対座標)、軸平行判定は 0.75px、同軸近接は端点座標差。
# タイトル帯貫通は既存 W5 が機械検出するため、ここでは重複実装しない。

ANCHOR_LO, ANCHOR_HI = 0.35, 0.65   # scripts/tests.py TestFeedbackRound3 と同じ帯
# 旧 SLIDE_MAX(≤14.5px)免除は R4-4 で撤去した: エンジン側の端点ずらし
# (_fan_deconflict_runs / _slide_end 系)が単独ポートを帯内へクランプする
# ようになり、帯外の単独ポート端点は常に実バグとして検出してよい
LANE_TOL = 2.0                      # レーン共有/対称の許容(±2px、同上)
LANE_NEAR = 28.0                    # 同一回廊とみなす距離(2×LANE_STEP)
CORUN_GAP = 7.0                     # 異 src 並走の最小間隔(LANE_STEP=14 の半分)
CORUN_RUN = 20.0                    # 並走とみなす重なり長(E7 と同じ)

# ---- FB第4R(出射辺の方向 / 垂直ペア中心 / 兄弟コンテナ寸法)の閾値 ----
DIR_COS_MIN = -0.48   # 出射辺の余弦下限。テンプレ10種+実案件2種で実測校正:
#   by-design の最悪値(dense e40 entry -0.455 / multiregion e2 exit -0.379、
#   交差最少が辞書式に勝った正当な辺選択)は通し、R4-1 修正前(v1.6.0)の
#   悪例 complex e10 -0.698 / e23 -0.513(自然な辺が空いているのに反対側
#   から回り込む)は検出する値。マージンは ±0.03 前後と薄い — 変更時は要再校正
DIR_MAX_PTS = 5       # 折れ線 6 点以上は対象外(障害物・混雑の正当な大迂回。
#   by-design の dense e18/e20(6点・余弦 -0.58/-0.987)を免除する実測境界)
ER_HUB_DEGREE = 3     # ER ハブ出射免除の次数下限(A3-#2)。04-saas-er の
#   organizations(次数5)のような多対関係ハブは空き辺が無く、回廊迂回
#   (行き先と逆向きの出射・入射)が正当(実測: r1 余弦 -0.693/-0.721)。
#   免除は「ER マーカー付きエッジ かつ src 次数 >= 3」に限定し、構成図の
#   検出力(r4 fail-before: complex e10 余弦 -0.698)は影響を受けない
PAIR_TOL = 0.02       # 垂直ペア中心 frac 0.5 の許容(R4-3: 旧 0.6484 を検出)
DIM_TOL = 1.0         # 兄弟コンテナ寸法の許容差 px

# ---- FB第5R(ファン流儀統一 / 折れ点上限 / ポート分離 / fork 形状)の閾値 ----
MAX_BENDS = 7         # 全エッジの折れ点(方向転換)数の上限。校正対象12種+
#   フィクスチャ現行ビルドの実測最大 6(dense e36 / multiregion e17 —
#   exit_direction が大迂回として免除するのと同じ by-design の障害物回避)
#   +マージン 1。A-2 磨きパス(折れ点 3 以上の最終再配線)導入後の値で、
#   暴走経路(8 折れ以上)だけを検出するガードレール — 変更時は要再校正
PORT_SEP_MIN = 8.0    # 同一ノード同一辺の端点間最小距離 px。A-3 修正前の
#   実測 = pin 0.4 の 8px 隣(frac 0.5、7.8px)へ自動割当(W6)を検出し、
#   正当な最小値(校正対象の現行ビルド実測 13.0px、ラダー最密の理論値
#   ≈8.8px)は通す。pin が無い図では自動スロットは常にこの間隔を保つ
FORK_LANE_TOL = 1.0   # fork ①: 2 本の折れ x の一致許容(±1px)
FORK_ENTRY_TOL = 0.02  # fork ②: entry frac とレーン x 正規化値の一致許容

# ---- 第7R(A/A2/B/C: decision / id / ER-UML / flow shape)の閾値 ----
DIAMOND_VERTEX_TOL = 0.001  # 4 頂点 fraction との許容差(丸め誤差だけを吸収)
END_LABEL_MAX_DISTANCE = 90.0  # 端点→ラベル箱の最近接点距離の上限。中心距離だと
#   ラベル幅に比例して破綻する(REV-1: builder は端点から線沿い ≤48px+半幅に
#   置くため、幅 210px 級の長ラベルは中心距離 ~113px で恒常発火した)。
#   最近接点なら builder 配置の実測上限 ≈52px で、90 は余裕を持って通す
DIAMOND_VERTICES = ((0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5))

# draw.io CLI で Export failed を起こす Array/Object prototype 名。builder の
# 定数を import せず eval 側に凍結し、実装の退行から独立して検出する。
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

R7_FLOW_STYLE = {
    "gateway": {"shape": "mxgraph.bpmn.gateway2", "gwType": "parallel"},
    "delay": {"shape": "delay"},
    "preparation": {"shape": "hexagon", "perimeter": "hexagonPerimeter2",
                    "fixedSize": "1"},
    "junction": {"ellipse": None, "aspect": "fixed"},
    "connector": {"ellipse": None, "aspect": "fixed"},
}
R7_FLOW_MIN_SIZE = {
    "gateway": (64.0, 64.0),
    "delay": (120.0, 56.0),
    "preparation": (140.0, 56.0),
    "junction": (28.0, 28.0),
    "connector": (42.0, 42.0),
}


def _tabs(path):
    """[(タブ名, Diagram, [エッジ], {eid: 絶対折れ線})] を返す。

    折れ線は E7 と同じ作り: exit/entry 未指定の端点はノード境界へクリップ。
    """
    tabs = []
    for tab, model in V.load_models(str(path)):
        if model is None:
            continue
        diag = V.Diagram(model)
        edges = [c for c in diag.cells.values() if c.is_edge]
        polylines = {}
        for e in edges:
            poly, has_exit, has_entry = V.edge_polyline(diag, e)
            src, tgt = diag.cells.get(e.source), diag.cells.get(e.target)
            if src is not None and not has_exit and len(poly) >= 2:
                poly[0] = V.clip_to_border(diag.abs_box(src), poly[0], poly[1])
            if tgt is not None and not has_entry and len(poly) >= 2:
                poly[-1] = V.clip_to_border(diag.abs_box(tgt), poly[-1], poly[-2])
            polylines[e.id] = poly
        tabs.append((tab, diag, edges, polylines))
    return tabs


def _spec_diagrams(spec_path):
    """spec の各タブを返す。単一図/diagrams 配列の両形式を扱う。"""
    if spec_path is None:
        return []
    data = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    return data.get("diagrams") or [data]


def _tabs_with_spec(path, spec_path=None):
    """出力タブへ同名(無ければ同じ順番)の spec タブを対応付ける。"""
    tabs = _tabs(path)
    specs = _spec_diagrams(spec_path)
    by_name = {str(s.get("name", "")): s for s in specs}
    out = []
    for i, tab_data in enumerate(tabs):
        tab = tab_data[0]
        spec = by_name.get(tab)
        if spec is None and i < len(specs):
            spec = specs[i]
        out.append((*tab_data, spec))
    return out


def _xml_id_map(spec):
    """危険 id の XML 上の決定的な退避名を eval 側で独立に再現する。"""
    ids = [item["id"] for key in ("containers", "nodes", "edges")
           for item in (spec or {}).get(key) or []]
    taken = set(ids)
    out = {}
    for item_id in ids:
        if item_id not in JS_UNSAFE_IDS:
            continue
        candidate = item_id + "_"
        while candidate in taken:
            candidate += "_"
        out[item_id] = candidate
        taken.add(candidate)
    return out


def _spec_xml_id(spec, item_id):
    return _xml_id_map(spec).get(item_id, item_id)


def _is_diamond(cell):
    return ("rhombus" in cell.style
            or cell.style.get("shape") == "mxgraph.bpmn.gateway2")


def _at_diamond_vertex(pair):
    return any(math.dist(pair, vertex) <= DIAMOND_VERTEX_TOL
               for vertex in DIAMOND_VERTICES)


def check_diamond_vertices(path, spec=None):
    """decision/gateway の全端点が4頂点にあり、上方主流入が上頂点か。"""
    out = []
    for tab, diag, edges, _polys, _spec in _tabs_with_spec(path, spec):
        above_by_target = {}
        for edge in edges:
            if edge.source and edge.source == edge.target:
                continue  # 自己ループ(retry 等)は builder/W15 と同じく対象外(REV-2)
            for prefix, term_id, end in (("exit", edge.source, "out"),
                                         ("entry", edge.target, "in")):
                term = diag.cells.get(term_id) if term_id else None
                if term is None or not term.is_vertex or not _is_diamond(term):
                    continue
                pair = _frac_pair(edge, prefix)
                if pair is None:
                    continue  # 端点未指定・不正値は E6 の領分(二重報告しない)
                if not _at_diamond_vertex(pair):
                    out.append({"tab": tab, "edge": edge.id, "end": end,
                                "term": term.id, "frac": pair,
                                "detail": "decision/gateway 端点が4頂点にない"})
                if end != "in" or "rhombus" not in term.style:
                    continue
                source = diag.cells.get(edge.source)
                if source is None or not source.is_vertex:
                    continue
                target_box, source_box = diag.abs_box(term), diag.abs_box(source)
                if source_box.y + source_box.h / 2 < target_box.y:
                    above_by_target.setdefault(term.id, []).append((edge, pair))
        for term_id, incoming in above_by_target.items():
            if any(math.dist(pair, (0.5, 0.0)) <= DIAMOND_VERTEX_TOL
                   for _edge, pair in incoming):
                continue  # W15 と同じく上頂点を取る1本があれば残りは側頂点を許す
            for edge, pair in incoming:
                out.append({"tab": tab, "edge": edge.id, "end": "in",
                            "term": term_id, "frac": pair,
                            "detail": "上方 src からの流入が上頂点 (0.5,0) にない"})
    return out


def check_safe_cell_ids(path, spec=None):
    """draw.io CLI を沈黙破損させる危険な mxCell/UserObject/object id が無いか。

    E10/E11 と同じく XML の生タグを走査する(REV-9: Diagram は UserObject/
    object 包みの外側 id で内側 mxCell の id を上書きするため、内側に残った
    危険 id は cells 経由では見えない)。
    """
    out = []
    for tab, model in V.load_models(str(path)):
        if model is None:
            continue
        ids = {el.get("id") for tag in ("mxCell", "UserObject", "object")
               for el in model.iter(tag) if el.get("id")}
        for cell_id in sorted(ids & JS_UNSAFE_IDS):
            out.append({"tab": tab, "id": cell_id,
                        "detail": "draw.io CLI Export failed を起こす危険 id"})
    return out


def _edge_end_label_children(edge):
    """edgeLabel 子セルを src/dst 別に返す。中央ラベル(x≈0)は対象外。"""
    out = {"src": [], "dst": []}
    for child in edge.children:
        if not child.is_vertex or "edgeLabel" not in child.style or child.geo is None:
            continue
        try:
            relative_x = float(child.geo.get("x", "0"))
        except ValueError:
            continue
        if abs(relative_x + 1.0) <= DIAMOND_VERTEX_TOL:
            out["src"].append(child)
        elif abs(relative_x - 1.0) <= DIAMOND_VERTEX_TOL:
            out["dst"].append(child)
    return out


def _end_label_center(child, endpoint):
    if child.geo is None or child.geo.get("relative") != "1":
        return None
    offset = next((pt for pt in child.geo.findall("mxPoint")
                   if pt.get("as") == "offset"), None)
    if offset is None:
        return None
    try:
        return (endpoint[0] + float(offset.get("x", "0")),
                endpoint[1] + float(offset.get("y", "0")))
    except ValueError:
        return None


def _end_label_box(child, center):
    lines = V.strip_html(child.value).splitlines() or [""]
    try:
        font = float(child.style.get("fontSize", 11) or 11)
    except ValueError:
        font = 11.0
    width = max((V.text_width(line, font) for line in lines), default=0.0)
    height = max(16.0, 1.3 * font) * len(lines)
    return V.Box(center[0] - width / 2, center[1] - height / 2,
                 width, height)


def check_end_labels(path, spec=None):
    """src_label/dst_label が両端近傍にあり、ノード箱と重ならないか。"""
    out = []
    for tab, diag, edges, polys, tab_spec in _tabs_with_spec(path, spec):
        edge_by_id = {edge.id: edge for edge in edges}
        if tab_spec is not None:
            for expected_edge in tab_spec.get("edges") or []:
                expected_id = _spec_xml_id(tab_spec, expected_edge["id"])
                edge = edge_by_id.get(expected_id)
                for key, end in (("src_label", "src"),
                                 ("dst_label", "dst")):
                    if key not in expected_edge:
                        continue
                    children = (_edge_end_label_children(edge)[end]
                                if edge is not None else [])
                    wanted = str(expected_edge[key])
                    if not any(V.strip_html(child.value) == wanted
                               for child in children):
                        out.append({"tab": tab, "edge": expected_id, "end": end,
                                    "detail": f"{key}={wanted!r} の端ラベルセルが無い"})

        node_boxes = [(cell.id, diag.full_box(cell))
                      for cell in diag.cells.values()
                      if cell.is_vertex and not diag.is_container(cell)
                      and "edgeLabel" not in cell.style]
        for edge in edges:
            poly = polys.get(edge.id) or []
            if len(poly) < 2:
                continue
            for end, endpoint in (("src", poly[0]), ("dst", poly[-1])):
                for child in _edge_end_label_children(edge)[end]:
                    center = _end_label_center(child, endpoint)
                    if center is None:
                        out.append({"tab": tab, "edge": edge.id, "end": end,
                                    "detail": "端ラベルの relative geometry/offset が不正"})
                        continue
                    label_box = _end_label_box(child, center)
                    # 端点→ラベル箱の最近接点で測る(REV-1: 中心距離は
                    # ラベル幅に比例して長ラベルで恒常発火する)
                    distance = math.hypot(
                        max(label_box.x - endpoint[0],
                            endpoint[0] - label_box.x2, 0.0),
                        max(label_box.y - endpoint[1],
                            endpoint[1] - label_box.y2, 0.0))
                    if distance > END_LABEL_MAX_DISTANCE:
                        out.append({"tab": tab, "edge": edge.id, "end": end,
                                    "distance": round(distance, 2),
                                    "detail": f"端点からラベル箱まで {distance:.1f}px 離れている"})
                    hits = [cell_id for cell_id, box in node_boxes
                            if label_box.overlaps(box)]
                    if hits:
                        out.append({"tab": tab, "edge": edge.id, "end": end,
                                    "nodes": hits,
                                    "detail": "端ラベルがノード箱と重なる"})
    return out


def check_er_cardinality(path, spec=None):
    """er_01n/er_11n の親側(start)と子側(end)マーカーを照合する。"""
    expected_arrows = {
        "er_01n": ("ERzeroToOne", "ERmany"),
        "er_11n": ("ERmandOne", "ERmany"),
    }
    out = []
    for tab, diag, edges, _polys, tab_spec in _tabs_with_spec(path, spec):
        edge_by_id = {edge.id: edge for edge in edges}
        for edge in edges:
            start = edge.style.get("startArrow")
            end_arrow = str(edge.style.get("endArrow") or "")
            # 汎用則は「子側マーカーの欠落」だけを見る。子側が別の ER マーカー
            # (例: カスタム kind の 0..1 : 1)は意図的な多重度として通す(REV-10)。
            # er_01n/er_11n の厳密な対応は下の spec-aware 側が照合する
            if start in ("ERzeroToOne", "ERmandOne") \
                    and not end_arrow.startswith("ER"):
                out.append({"tab": tab, "edge": edge.id,
                            "detail": f"親側 {start} だが子側に ER マーカーが無い"})
        if tab_spec is None:
            continue
        for expected_edge in tab_spec.get("edges") or []:
            kind = expected_edge.get("kind")
            if kind not in expected_arrows:
                continue
            edge_id = _spec_xml_id(tab_spec, expected_edge["id"])
            edge = edge_by_id.get(edge_id)
            if edge is None:
                out.append({"tab": tab, "edge": edge_id,
                            "detail": f"{kind} の出力エッジが無い"})
                continue
            start, end = expected_arrows[kind]
            source = _spec_xml_id(tab_spec, expected_edge["src"])
            target = _spec_xml_id(tab_spec, expected_edge["dst"])
            if (edge.style.get("startArrow"), edge.style.get("endArrow")) \
                    != (start, end) or (edge.source, edge.target) != (source, target):
                out.append({"tab": tab, "edge": edge_id, "kind": kind,
                            "actual": {"start": edge.style.get("startArrow"),
                                       "end": edge.style.get("endArrow"),
                                       "source": edge.source, "target": edge.target},
                            "detail": f"親側 {start} / 子側 {end} の対応でない"})
    return out


def check_stereotype_italic(path, spec=None):
    """stereotype=interface/abstract のタイトルが italic ビットを持つか。"""
    out = []
    for tab, diag, _edges, _polys, tab_spec in _tabs_with_spec(path, spec):
        if tab_spec is None:
            continue  # legacy の title 直書き «interface» とは XML だけで区別不能
        for expected_node in tab_spec.get("nodes") or []:
            stereotype = expected_node.get("stereotype")
            if stereotype not in ("interface", "abstract"):
                continue
            node_id = _spec_xml_id(tab_spec, expected_node["id"])
            cell = diag.cells.get(node_id)
            try:
                italic = bool(int(cell.style.get("fontStyle", "0")) & 2) if cell else False
            except ValueError:
                italic = False
            if (cell is None or not italic
                    or f"«{stereotype}»" not in cell.value):
                out.append({"tab": tab, "node": node_id,
                            "stereotype": stereotype,
                            "detail": "stereotype 行または fontStyle italic ビットが無い"})
    return out


def _style_has(style, expected):
    return all((key in style if value is None else style.get(key) == value)
               for key, value in expected.items())


def check_flow_shapes_links(path, spec=None):
    """R7 flow shape の native figure と subprocess link 属性を照合する。"""
    out = []
    for tab, diag, _edges, _polys, tab_spec in _tabs_with_spec(path, spec):
        for cell in diag.cells.values():
            if cell.link and cell.style.get("shape") != "process":
                out.append({"tab": tab, "node": cell.id,
                            "detail": "link 付きノードが subprocess(process shape)でない"})
            if cell.style.get("shape") == "mxgraph.bpmn.gateway2" \
                    and cell.style.get("gwType") != "parallel":
                out.append({"tab": tab, "node": cell.id,
                            "detail": "gateway の gwType が parallel でない"})
        if tab_spec is None:
            continue
        for expected_node in tab_spec.get("nodes") or []:
            shape = expected_node.get("shape")
            link = expected_node.get("link")
            if shape not in R7_FLOW_STYLE and link is None:
                continue
            node_id = _spec_xml_id(tab_spec, expected_node["id"])
            cell = diag.cells.get(node_id)
            if cell is None:
                out.append({"tab": tab, "node": node_id,
                            "detail": f"shape={shape} の出力ノードが無い"})
                continue
            if shape in R7_FLOW_STYLE and not _style_has(
                    cell.style, R7_FLOW_STYLE[shape]):
                out.append({"tab": tab, "node": node_id, "shape": shape,
                            "detail": "draw.io native figure の style が不一致"})
            if shape in R7_FLOW_MIN_SIZE:
                box = diag.abs_box(cell)
                min_width, min_height = R7_FLOW_MIN_SIZE[shape]
                expected_width = float(expected_node.get("w", min_width))
                expected_height = float(expected_node.get("h", min_height))
                if box.w < expected_width or box.h < expected_height:
                    out.append({"tab": tab, "node": node_id, "shape": shape,
                                "size": [box.w, box.h],
                                "detail": f"要求最小寸法 {expected_width:g}x"
                                          f"{expected_height:g} を下回る"})
            if link is not None and (cell.link != link
                                     or cell.style.get("shape") != "process"):
                out.append({"tab": tab, "node": node_id,
                            "actual_link": cell.link,
                            "detail": "subprocess の UserObject link 属性が不一致"})
    return out


def check_gateway_topology(path, spec=None):
    """parallel gateway が fork(1→複数)または join(複数→1)を形成するか。"""
    out = []
    for tab, diag, edges, _polys in _tabs(path):
        gateways = [cell for cell in diag.cells.values()
                    if cell.is_vertex
                    and cell.style.get("shape") == "mxgraph.bpmn.gateway2"]
        for gateway in gateways:
            incoming = [edge for edge in edges if edge.target == gateway.id]
            outgoing = [edge for edge in edges if edge.source == gateway.id]
            # 入出とも複数の混合 gateway は fork とみなさない(REV-8:
            # 分割か合流のどちらか一方に分けるのが BPMN の作法)
            is_fork = len(incoming) == 1 and len(outgoing) >= 2
            is_join = len(incoming) >= 2 and len(outgoing) == 1
            if not (is_fork or is_join):
                out.append({"tab": tab, "gateway": gateway.id,
                            "incoming": len(incoming), "outgoing": len(outgoing),
                            "detail": "fork(1→複数) / join(複数→1) になっていない"
                                      "(入出とも複数の混合は fork/join に分割)"})
    return out


def _node_terminal(diag, term_id):
    """端点セルが「ノード」なら返す(コンテナ端点は None = 検査対象外)。"""
    cell = diag.cells.get(term_id) if term_id else None
    if cell is None or not cell.is_vertex or diag.is_container(cell):
        return None
    return cell


def _on_border(f):
    return abs(f) < 1e-6 or abs(f - 1.0) < 1e-6


def _frac_pair(edge, prefix):
    """style の exitX/Y・entryX/Y を (fx, fy) で返す。無ければ None(E6 の領分)。"""
    fx, fy = edge.style.get(prefix + "X"), edge.style.get(prefix + "Y")
    if fx is None or fy is None:
        return None
    try:
        return float(fx), float(fy)
    except ValueError:
        return None  # 不正な style 値は未指定扱い(検査全体を例外で落とさない。REV-11)


def _side(pair):
    """(fx, fy) から辺を ("v", 0/1)(左/右)| ("h", 0/1)(上/下)で返す。

    どちらも 0/1(角)・どちらも中間(浮き)なら None(辺が定まらない)。
    """
    bx, by = _on_border(pair[0]), _on_border(pair[1])
    if bx and not by:
        return ("v", round(pair[0]))
    if by and not bx:
        return ("h", round(pair[1]))
    return None


def _port_counts(diag, edges):
    """(ノードid, 辺) → その辺に付くエッジ端点数。

    同一ノード同一辺に 2 本以上付く場合、fraction は辺中心 0.5 に対して
    対称のラダー(0.15〜0.85 まで正当)になるため、0.35〜0.65 帯の
    検査対象は「その辺の唯一の端点」に限る。
    """
    counts = {}
    for e in edges:
        for prefix, term in (("exit", e.source), ("entry", e.target)):
            if _node_terminal(diag, term) is None:
                continue
            pair = _frac_pair(e, prefix)
            if pair is None:
                continue
            side = _side(pair)
            if side is not None:
                counts[(term, side)] = counts.get((term, side), 0) + 1
    return counts


def check_anchor_fractions(path):
    """ノード端点の「辺に沿う方向」の fraction が 0.35〜0.65 に収まるか。

    exitX/exitY(entryX/entryY)のうち 0/1 の座標が辺を決め、残りが
    辺に沿う fraction。両方 0/1(角)は角刺しなので常に違反。
    対象外: ①コンテナ端点(任意 fraction が正当)②同一ノード同一辺に
    2 本以上付くポート群(辺中心対称のラダーで 0.35〜0.65 の外も正当)
    ③手動配線レシピの分割点 0.25 / 0.75 ちょうど(layout-rules「同一辺から
    複数エッジは exit を 0.25/0.5/0.75 に割る」— 実案件 03 の 3 点セット
    手動配線で実測した正当値。エンジン自動端点は NEAR_FRAC クランプで
    0.35〜0.65 に収まるため、ちょうど 0.25/0.75 に落ちることはない)。
    旧 SLIDE_MAX(≤14.5px)免除は R4-4 で撤去 — エンジンの端点ずらしが
    単独ポートを帯内へクランプするようになったため(frac 0.6795 は絶滅)。
    返り値: 違反のリスト [{tab, edge, end, frac, xy}]。
    """
    out = []
    for tab, diag, edges, _polys in _tabs(path):
        ports = _port_counts(diag, edges)
        for e in edges:
            for prefix, term in (("exit", e.source), ("entry", e.target)):
                cell = _node_terminal(diag, term)
                if cell is None:
                    continue
                pair = _frac_pair(e, prefix)
                if pair is None:
                    continue
                side = _side(pair)
                if side is not None and ports.get((term, side), 0) >= 2:
                    continue  # 多重ポートのラダーは指摘6の対称規約側で正当
                fx, fy = pair
                along = [f for f in (fx, fy) if not _on_border(f)] or [fx, fy]
                for f in along:
                    if ANCHOR_LO - 1e-9 <= f <= ANCHOR_HI + 1e-9:
                        continue
                    if abs(f - 0.25) < 1e-9 or abs(f - 0.75) < 1e-9:
                        continue  # 手動配線レシピの分割点(docstring ③)
                    out.append({"tab": tab, "edge": e.id, "end": prefix,
                                "frac": round(f, 4), "xy": [fx, fy]})
    return out


def _runs(poly):
    """折れ線を軸平行 Run のリスト [(axis, coord, is_middle, lo, hi)] にする。

    axis は固定座標の軸('x'=垂直 Run / 'y'=水平 Run)、lo/hi は進行軸の
    区間。is_middle は両端点セグメント(anchor に接する)以外 = 回廊内の
    中間 Run。斜めセグメントを含む折れ線は None(E4 の領分)。
    """
    runs = []
    n = len(poly) - 1
    for k in range(n):
        (x1, y1), (x2, y2) = poly[k], poly[k + 1]
        if abs(x1 - x2) < 0.75:
            runs.append(("x", (x1 + x2) / 2, 0 < k < n - 1,
                         min(y1, y2), max(y1, y2)))
        elif abs(y1 - y2) < 0.75:
            runs.append(("y", (y1 + y2) / 2, 0 < k < n - 1,
                         min(x1, x2), max(x1, x2)))
        else:
            return None
    return runs


def check_fan_symmetry(path):
    """同一 src ファンアウトの対称性: レーン共有/中心対称と entry の対一致。

    同一ノード source から出るエッジ対ごとに、
      (a) 回廊内の中間 Run 同士が同一回廊(28px 未満)で、かつ区間が
          重ならない(隙間 12px 以上 = エンジンの対称ユニット条件)なら、
          レーン座標が一致(±2px)するか src 中心に対して対称(±2px)で
          あること(修正前の実測: レーン x=223/209 の ±7px 階段割れ)
      (b) 対称ユニット(レーン共有 or 対称、または出射 Run の共有)を成す
          対は、互いの単独ポート同士が同じ辺に入るなら entry の「辺に沿う
          fraction」も対で一致すること(修正前の実測: 0.715/0.5 の不揃い)
    を検査する。コンテナ端点のエッジ・多重ポート(ラダー)は対象外。
    返り値: 違反のリスト [{tab, kind, a, b, detail}]。
    """
    out = []
    for tab, diag, edges, polys in _tabs(path):
        ports = _port_counts(diag, edges)
        by_src = {}
        for e in edges:
            src = _node_terminal(diag, e.source)
            if src is None or _node_terminal(diag, e.target) is None:
                continue
            if _frac_pair(e, "exit") is None:
                continue
            poly = polys.get(e.id) or []
            if len(poly) < 2:
                continue
            runs = _runs(poly)
            if runs is None:
                continue
            by_src.setdefault(src.id, []).append((e, runs))
        for src_id, group in by_src.items():
            if len(group) < 2:
                continue
            sb = diag.abs_box(diag.cells[src_id])
            center = {"x": sb.x + sb.w / 2, "y": sb.y + sb.h / 2}
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    (ea, ra), (eb, rb) = group[i], group[j]
                    unit = False
                    lane_bad = None
                    # 出射直後 Run の共有(上下ファンの縦レーン共有)は
                    # ユニットの証拠として扱う(違反判定はしない — 同一辺
                    # ラダーのポート位置差は指摘6の対称規約側で正当)
                    fa, fb = ra[0], rb[0]
                    if fa[0] == fb[0]:
                        d = abs(fa[1] - fb[1])
                        if d <= LANE_TOL or abs((fa[1] + fb[1]) / 2
                                                - center[fa[0]]) <= LANE_TOL:
                            unit = True
                    # 回廊内の中間 Run 同士(区間が重ならない対 = 対称ユニット)
                    for axa, ca, mida, loa, hia in ra:
                        if not mida:
                            continue
                        for axb, cb, midb, lob, hib in rb:
                            if not midb or axa != axb:
                                continue
                            if abs(ca - cb) >= LANE_NEAR:
                                continue    # 別回廊
                            if not (loa >= hib + 12.0 or lob >= hia + 12.0):
                                continue    # 区間が重なる = レーン分離が正当
                            if (abs(ca - cb) <= LANE_TOL
                                    or abs((ca + cb) / 2
                                           - center[axa]) <= LANE_TOL):
                                unit = True
                            elif lane_bad is None:
                                lane_bad = ("lane", ca, cb)
                    if lane_bad is not None:
                        out.append({"tab": tab, "kind": lane_bad[0],
                                    "a": ea.id, "b": eb.id,
                                    "detail": f"{lane_bad[1]:.1f} / {lane_bad[2]:.1f}"
                                              "(共有でも src 中心対称でもない)"})
                    if not unit:
                        continue
                    # (b) 対称ユニットの entry は同じ辺なら fraction も対で一致
                    pa, pb = _frac_pair(ea, "entry"), _frac_pair(eb, "entry")
                    if pa is None or pb is None:
                        continue
                    sa, sb_ = _side(pa), _side(pb)
                    if sa is None or sa != sb_:
                        continue
                    if (ports.get((ea.target, sa), 0) >= 2
                            or ports.get((eb.target, sb_), 0) >= 2):
                        continue  # 多重ポートのラダーは対一致の対象外
                    along_a = [f for f in pa if not _on_border(f)]
                    along_b = [f for f in pb if not _on_border(f)]
                    if abs(along_a[0] - along_b[0]) > 0.02:
                        out.append({"tab": tab, "kind": "entry",
                                    "a": ea.id, "b": eb.id,
                                    "detail": f"entry {pa} / {pb} が不揃い"})
    return out


def check_corun_separation(path):
    """異 source エッジの同軸並走を幾何で直接測る(E7 の再実装ではない)。

    平行な軸平行セグメント同士が CORUN_GAP(7px)未満の間隔で
    CORUN_RUN(20px)超並走していれば違反。同一 source 対は fork の
    トランク(意図的な同走)なので対象外。
    返り値: 違反のリスト [{tab, a, b, gap, run}](対ごとに最長 1 件)。
    """
    out = []
    for tab, diag, edges, polys in _tabs(path):
        eids = [e.id for e in edges if polys.get(e.id)]
        for i in range(len(eids)):
            for j in range(i + 1, len(eids)):
                ea, eb = diag.cells[eids[i]], diag.cells[eids[j]]
                if ea.source and ea.source == eb.source:
                    continue  # 同一 src = fork トランクの同走は意図的
                pa, pb = polys[eids[i]], polys[eids[j]]
                worst = None
                for k in range(len(pa) - 1):
                    for m in range(len(pb) - 1):
                        a1, a2, b1, b2 = pa[k], pa[k + 1], pb[m], pb[m + 1]
                        for axis in (0, 1):
                            o = 1 - axis
                            if (abs(a1[axis] - a2[axis]) < 0.75
                                    and abs(b1[axis] - b2[axis]) < 0.75
                                    and abs(a1[axis] - b1[axis]) < CORUN_GAP):
                                lo = max(min(a1[o], a2[o]), min(b1[o], b2[o]))
                                hi = min(max(a1[o], a2[o]), max(b1[o], b2[o]))
                                if hi - lo > CORUN_RUN and (
                                        worst is None or hi - lo > worst["run"]):
                                    worst = {"tab": tab, "a": ea.id, "b": eb.id,
                                             "gap": round(abs(a1[axis] - b1[axis]), 1),
                                             "run": round(hi - lo, 1)}
                if worst:
                    out.append(worst)
    return out


# ---- FB第4R ルータ回帰チェック(出射辺の方向 / 垂直ペア中心 / 兄弟寸法)----

_SIDE_NORMALS = {("v", 0): (-1.0, 0.0), ("v", 1): (1.0, 0.0),
                 ("h", 0): (0.0, -1.0), ("h", 1): (0.0, 1.0)}


def _is_er_edge(edge):
    """ER 記法エッジ(startArrow/endArrow が ER 系マーカー)か。"""
    return any(str(edge.style.get(key) or "").startswith("ER")
               for key in ("startArrow", "endArrow"))


def check_exit_direction(path):
    """ノード端点が「行き先に面した辺」から出入りしているか(R4-1)。

    エンジンの _dir_penalty と同じ測り方: 端点辺の外向き法線と、自ノード
    中心→相手ノード中心ベクトルの余弦。DIR_COS_MIN 未満(ほぼ真後ろの辺)
    を違反にする。対象は両端ともノード(非コンテナ)のエッジのみ。
    折れ線 DIR_MAX_PTS+1 点以上は対象外 — 混雑・障害物で反対側へ逃げる
    大迂回は正当(禁止でなくペナルティ、が R4-1 の設計)。
    さらに免除 2 種(A3 校正。r4 fail-before の complex e10(非破線・上向き
    -0.698)/ e23(破線・下向き -0.513)はどちらの免除にも掛からず検出維持):
      ①戻りエッジ: 破線(sub 線種)かつ dst 箱が src 箱より完全に上
        (差し戻しは意図的に逆向きへ出る。実測: 01-approval f10 -0.843)
      ②ER ハブ出射: ER マーカー付きエッジで src 次数 >= ER_HUB_DEGREE
        (実測: 04-saas-er r1 -0.693/-0.721)
    返り値: 違反のリスト [{tab, edge, end, cos}]。
    """
    out = []
    for tab, diag, edges, polys in _tabs(path):
        degree = {}
        for e in edges:
            for term in (e.source, e.target):
                if term:
                    degree[term] = degree.get(term, 0) + 1
        for e in edges:
            if len(polys.get(e.id) or []) > DIR_MAX_PTS:
                continue
            if _is_er_edge(e) and degree.get(e.source, 0) >= ER_HUB_DEGREE:
                continue  # ②ER ハブ出射
            if e.style.get("dashed") == "1":
                src = _node_terminal(diag, e.source)
                tgt = _node_terminal(diag, e.target)
                if src is not None and tgt is not None:
                    src_box, tgt_box = diag.abs_box(src), diag.abs_box(tgt)
                    if tgt_box.y2 <= src_box.y:
                        continue  # ①戻りエッジ(dst が上流 = 行が上)
            for prefix, term, other_id in (("exit", e.source, e.target),
                                           ("entry", e.target, e.source)):
                cell = _node_terminal(diag, term)
                other = _node_terminal(diag, other_id)
                if cell is None or other is None:
                    continue
                pair = _frac_pair(e, prefix)
                side = _side(pair) if pair is not None else None
                if side is None:
                    continue
                sb, ob = diag.abs_box(cell), diag.abs_box(other)
                dx = (ob.x + ob.w / 2) - (sb.x + sb.w / 2)
                dy = (ob.y + ob.h / 2) - (sb.y + sb.h / 2)
                n = math.hypot(dx, dy)
                if n < 1e-9:
                    continue
                nx, ny = _SIDE_NORMALS[side]
                fc = (nx * dx + ny * dy) / n
                if fc < DIR_COS_MIN:
                    out.append({"tab": tab, "edge": e.id, "end": prefix,
                                "cos": round(fc, 3)})
    return out


def check_pair_center(path):
    """直行ノード間の垂直直線が辺中心 0.5 から出入りしているか(R4-3)。

    2 点折れ線(=中間点なし)の垂直直線で、両端がノードの上下辺のもの
    だけを見る。exit/entry の「辺に沿う fraction」が 0.5±PAIR_TOL を
    外れたら違反(R4-3 修正前は 0.6484 の「ずらした直線」が出た)。
    手動 points 凍結エッジは折れ点が入り 3 点以上になるため自然と対象外。
    返り値: 違反のリスト [{tab, edge, exit_frac, entry_frac}]。
    """
    out = []
    for tab, diag, edges, polys in _tabs(path):
        for e in edges:
            poly = polys.get(e.id) or []
            if len(poly) != 2 or abs(poly[0][0] - poly[1][0]) >= 0.75:
                continue
            if (_node_terminal(diag, e.source) is None
                    or _node_terminal(diag, e.target) is None):
                continue
            pe, pn = _frac_pair(e, "exit"), _frac_pair(e, "entry")
            if pe is None or pn is None:
                continue
            se, sn = _side(pe), _side(pn)
            if se is None or sn is None or se[0] != "h" or sn[0] != "h":
                continue
            if abs(pe[0] - .5) > PAIR_TOL or abs(pn[0] - .5) > PAIR_TOL:
                out.append({"tab": tab, "edge": e.id,
                            "exit_frac": round(pe[0], 4),
                            "entry_frac": round(pn[0], 4)})
    return out


def _dims_kind(diag, cell):
    """兄弟寸法検査の対象コンテナ型(subnet 系 / az)。それ以外は None。

    validate_drawio の W9 型推定(スタイル署名)の安全な部分集合に限定する。
    ou / account / generic 等を外すのは、①エンジンの等化ロールバック
    (等化すると別の ERROR/WARN が出るタブは等化なしで再ビルドされる —
    multiaccount テンプレの CI/CD タブで実際に発動)②等化実装前の検証済み
    .drawio(実案件 04 等)の不一致が、XML からは「正当な見送り」と
    「バグ」を区別できないため。subnet / az は両方の全対象で不一致ゼロを
    実測確認済み(README の適用範囲を参照)。
    """
    s = cell.style
    if s.get("grIcon", "").endswith("group_security_group"):
        return "subnet:" + s.get("strokeColor", "")
    if ("grIcon" not in s and "resIcon" not in s
            and not s.get("shape", "").startswith("mxgraph.")
            and s.get("container") == "1"
            and s.get("strokeColor") == "#147EBA" and s.get("dashed") == "1"):
        return "az"
    return None


def check_sibling_dims(path):
    """同一親・同種の兄弟コンテナの寸法が揃っているか(R4-6)。

    エンジンの等化が保証する軸だけを照合する: 縦積み(行が互いに素・
    列が重なる)は幅、横並びは高さ。斜め・格子状の混在配置は対象外
    (等化自体が対象外のため)。許容差 DIM_TOL px。
    返り値: 違反のリスト [{tab, kind, ids, dim, vals}]。
    """
    out = []
    for tab, diag, _edges, _polys in _tabs(path):
        groups = {}
        for cell in diag.cells.values():
            if not cell.is_vertex or not diag.is_container(cell):
                continue
            kind = _dims_kind(diag, cell)
            if kind is not None:
                groups.setdefault((cell.parent, kind), []).append(cell)
        for (_parent, kind), cells in groups.items():
            if len(cells) < 2:
                continue
            boxes = [(c.id, diag.abs_box(c)) for c in cells]
            pairs = [(a, b) for i, (_, a) in enumerate(boxes)
                     for _, b in boxes[i + 1:]]
            if (all(a.y2 < b.y or b.y2 < a.y for a, b in pairs)
                    and all(a.x <= b.x2 and b.x <= a.x2 for a, b in pairs)):
                dim, vals = "w", [round(b.w, 1) for _, b in boxes]
            elif (all(a.x2 < b.x or b.x2 < a.x for a, b in pairs)
                    and all(a.y <= b.y2 and b.y <= a.y2 for a, b in pairs)):
                dim, vals = "h", [round(b.h, 1) for _, b in boxes]
            else:
                continue
            if max(vals) - min(vals) > DIM_TOL:
                out.append({"tab": tab, "kind": kind.split(":")[0],
                            "ids": [i for i, _ in boxes],
                            "dim": dim, "vals": vals})
    return out


# ---- FB第5R ルータ回帰チェック(ファン流儀統一 / 折れ点上限 / ポート分離 /
#      fork 形状)。エンジン側の対応 = A-1 fan_fixes / A-2 磨きパス /
#      A-3 pinned_ports / R5-B detect_center_forks。R5-D(経路の慣性)は
#      <out>.routes.json キャッシュがあるときだけ働く機能で、eval はキャッシュ
#      なしの新規ビルドしか扱わないため検査対象外。


def _lateral_fan_groups(path):
    """同一 src ノードから片側方向(全 dst 中心が右または左)へ出るエッジ群。

    エンジン fan_fixes と同じ群定義を、出力 XML の両端座標から再構成する:
    src はノード(非コンテナ)、dst はノード/コンテナ両方、方向は中心 x の
    厳密な同符号(上下混在・同座標の群は対象外)。手動配線レシピの分割点
    (exit の辺沿い frac が 0.25 / 0.75 ちょうど)は fan_fixes の対象外
    (固定配線)なので群から除く。
    yield: (tab, diag, ex_side, en_side, src_cy, members)
      members = [(edge, exit_side, dst_cell)]、ex_side = dst を向く辺、
      en_side = h 流儀の入射辺(src を向く横辺)。
    """
    for tab, diag, edges, _polys in _tabs(path):
        by_src = {}
        for e in edges:
            src = _node_terminal(diag, e.source)
            tgt = diag.cells.get(e.target) if e.target else None
            if src is None or tgt is None or not tgt.is_vertex:
                continue
            pex = _frac_pair(e, "exit")
            sex = _side(pex) if pex is not None else None
            if sex is None:
                continue
            along = [f for f in pex if not _on_border(f)]
            if along and (abs(along[0] - 0.25) < 1e-9
                          or abs(along[0] - 0.75) < 1e-9):
                continue  # 手動配線レシピ(check_anchor_fractions ③と同じ)
            by_src.setdefault(src.id, []).append((e, sex, tgt))
        for src_id, members in by_src.items():
            if len(members) < 2:
                continue
            sb = diag.abs_box(diag.cells[src_id])
            scx, scy = sb.x + sb.w / 2, sb.y + sb.h / 2
            dxs = []
            for _e, _s, tgt in members:
                tb = diag.abs_box(tgt)
                dxs.append(tb.x + tb.w / 2 - scx)
            if all(d > 1e-6 for d in dxs):
                ex_side, en_side = ("v", 1), ("v", 0)
            elif all(d < -1e-6 for d in dxs):
                ex_side, en_side = ("v", 0), ("v", 1)
            else:
                continue  # 上下混在・同 x は対象外(縦ファンは辺の制約が別)
            yield tab, diag, ex_side, en_side, scy, members


def check_fan_side_consistency(path):
    """同一 src 横方向ファンのコンテナ宛「対」の出射辺・入射辺統一(A-1)。

    エンジンの fan_fixes はスコア第 4 キー+スコアゲート付き修復のため、
    交差・題字・anti 端点を悪化させる統一は正当に見送られる(校正対象の
    現行ビルド 9/15 に by-design の混在が残存する実測)。機械照合は
    エンジンが実際に統一を保証する部分集合 = **コンテナ宛メンバーが
    ちょうど 2 本の対** に限定する(A-1 の再現形状 = test_a1 と同じ)。
    (a) 対の出射辺: 同一辺、または上下鏡映({上,下})のみ正当。
        軸をまたぐ混在(A-1 修正前の実測: m1 右辺 / m2 下辺)は違反
    (b) 対の入射辺: h 流儀(src を向く横辺)か v 流儀(src の行を向く
        上下の対面辺 = 鏡映)のどちらかに対で統一(修正前の実測:
        m1 下辺(v)/ m2 左辺(h)の混在)
    dst がノードの入射・3 本以上の群は _fan_slots・fan_symmetry の領分。
    返り値: 違反のリスト [{tab, kind, src, edges, detail}]。
    """
    out = []
    for tab, diag, ex_side, en_side, scy, members in _lateral_fan_groups(path):
        pair = [(e, sex, tgt) for e, sex, tgt in members
                if diag.is_container(tgt)]
        if len(pair) != 2:
            continue
        src_id = pair[0][0].source
        sides = {sex for _e, sex, _t in pair}
        if len(sides) > 1 and sides != {("h", 0), ("h", 1)}:
            out.append({"tab": tab, "kind": "exit", "src": src_id,
                        "edges": [e.id for e, _s, _t in pair],
                        "detail": f"対の出射辺が混在: {sorted(sides)}"})
        ent = []
        for e, _sex, tgt in pair:
            pen = _frac_pair(e, "entry")
            sen = _side(pen) if pen is not None else None
            if sen is None:
                continue
            tb = diag.abs_box(tgt)
            vface = ("h", 0) if tb.y + tb.h / 2 > scy else ("h", 1)
            ent.append((e.id, sen == en_side, sen == vface, sen))
        if len(ent) == 2 and not (all(h for _, h, _, _ in ent)
                                  or all(v for _, _, v, _ in ent)):
            out.append({"tab": tab, "kind": "entry", "src": src_id,
                        "edges": [i for i, _, _, _ in ent],
                        "detail": "対の入射辺が h/v 流儀で不統一: "
                                  + str([(i, s) for i, _, _, s in ent])})
    return out


def _bend_count(poly):
    """折れ線の方向転換数。斜めセグメントを含めば None(E4 の領分)。"""
    dirs = []
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        dx, dy = x2 - x1, y2 - y1
        if abs(dx) < 0.75 and abs(dy) < 0.75:
            continue  # 長さ 0 の重複点
        if abs(dx) >= 0.75 and abs(dy) >= 0.75:
            return None
        d = ("h", dx > 0) if abs(dx) > abs(dy) else ("v", dy > 0)
        if not dirs or dirs[-1] != d:
            dirs.append(d)
    return max(0, len(dirs) - 1)


def check_max_bends(path):
    """全エッジの折れ点(方向転換)数が MAX_BENDS 以下か(A-2 磨きパス)。

    A-2 は折れ点 3 以上のエッジを全エッジ確定後に再配線する(修正前の
    実測: 交差ゼロなのにリップアップ対象外で 6 折れの大回りが残存)。
    閾値は校正対象12種+フィクスチャの現行ビルドで誤検知ゼロになるよう
    実測校正(MAX_BENDS のコメント参照)。斜め線は対象外。
    返り値: 違反のリスト [{tab, edge, bends}]。
    """
    out = []
    for tab, _diag, edges, polys in _tabs(path):
        for e in edges:
            poly = polys.get(e.id) or []
            if len(poly) < 2:
                continue
            bends = _bend_count(poly)
            if bends is not None and bends > MAX_BENDS:
                out.append({"tab": tab, "edge": e.id, "bends": bends})
    return out


def check_pin_slot_distance(path):
    """同一ノード同一辺の端点同士が PORT_SEP_MIN px 以上離れているか(A-3)。

    A-3 修正前は手動 pin 端点が _fan_slots から不可視で、自動端点が pin の
    同一点・至近(実測: pin frac 0.4 の 7.8px 隣 = W6)へ割り当てられ得た。
    pin は XML からは自動端点と区別できないため「同一辺の全端点対の最小
    距離」で照合する — 正当な最小値(校正実測 13.0px)より下だけを違反に
    する。pin が無い図では自動スロットは常にこの間隔を保つ(自動パス)。
    validate の W6(矢じり重なり)と重なる帯があるが、こちらは exit 側の
    衝突も px 距離で直接測る。
    自己ループ(src=dst)は同一辺の近接端点が正当なので対象外。
    返り値: 違反のリスト [{tab, node, side, a, b, dist_px}]。
    """
    out = []
    for tab, diag, edges, _polys in _tabs(path):
        pts = {}
        for e in edges:
            if e.source and e.source == e.target:
                continue  # 自己ループ
            for prefix, term in (("exit", e.source), ("entry", e.target)):
                cell = _node_terminal(diag, term)
                if cell is None:
                    continue
                pair = _frac_pair(e, prefix)
                side = _side(pair) if pair is not None else None
                if side is None:
                    continue
                b = diag.abs_box(cell)
                length = b.h if side[0] == "v" else b.w
                along = [f for f in pair if not _on_border(f)] or [0.0]
                pts.setdefault((term, side), []).append(
                    (f"{e.id}:{prefix}", along[0], length))
        for (nid, side), lst in pts.items():
            if len(lst) < 2:
                continue
            lst.sort(key=lambda t: t[1])
            for (ka, fa, ln), (kb, fb, _) in zip(lst, lst[1:]):
                d = abs(fb - fa) * ln
                if d < PORT_SEP_MIN - 1e-9:
                    out.append({"tab": tab, "node": nid,
                                "side": f"{side[0]}{side[1]}",
                                "a": ka, "b": kb, "dist_px": round(d, 1)})
    return out


def detect_forks(path):
    """fork(R5-B)署名の対を検出する(check_fork_shape と verify.py 共用)。

    署名 = 同一 src ノードから 2 本が同一の縦辺(左/右)の対称スロット
    0.35 / 0.65 で出て、両方コンテナ宛、かつ上行き(exit 0.35)が宛先の
    下辺・下行き(exit 0.65)が宛先の上辺に入る。旧エンジンには機能自体が
    無く(平行 2 レーン)、この署名にならない。
    返り値: [{tab, up, dn, up_tgt, dn_tgt, polys}](生セル参照を含む内部用)。
    """
    res = []
    for tab, diag, edges, polys in _tabs(path):
        by_src = {}
        for e in edges:
            src = _node_terminal(diag, e.source)
            tgt = diag.cells.get(e.target) if e.target else None
            if src is None or tgt is None or not diag.is_container(tgt):
                continue
            pex, pen = _frac_pair(e, "exit"), _frac_pair(e, "entry")
            sex = _side(pex) if pex is not None else None
            sen = _side(pen) if pen is not None else None
            if sex is None or sen is None or sex[0] != "v" or sen[0] != "h":
                continue
            frac = [f for f in pex if not _on_border(f)][0]
            by_src.setdefault((src.id, sex), []).append((e, frac, sen, tgt))
        for (_src, _sex), lst in by_src.items():
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    pair = sorted((lst[i], lst[j]), key=lambda t: t[1])
                    (eu, fu, senu, tu), (ed, fd, send, td) = pair
                    if abs(fu - 0.35) > 1e-3 or abs(fd - 0.65) > 1e-3:
                        continue
                    if senu != ("h", 1) or send != ("h", 0):
                        continue  # 上行き=下辺・下行き=上辺 でなければ非 fork
                    res.append({"tab": tab, "diag": diag, "up": eu, "dn": ed,
                                "up_tgt": tu, "dn_tgt": td, "polys": polys})
    return res


def check_fork_shape(path):
    """fork 発動図の 3 不変条件(R5-B)。fork 不発動図では自動パス。

    署名(detect_forks)に一致した対だけを検査する:
      ① 2 本の折れ x(トランク終端のレーン)が一致(±FORK_LANE_TOL px)
        (修正前の実測: x=304.4 / 395.4 の平行 2 レーン — ただし旧エンジン
        は署名自体を作らないため、before は「署名にならない」で記録する)
      ② entry frac がレーン x の正規化値(レーン x をコンテナ幅で割った
        位置)と一致(±FORK_ENTRY_TOL)
      ③ 平行トランクが 2 本見える(出射直後の水平トランク y の間隔 > 0)
    返り値: 違反のリスト [{tab, pair, kind, detail}]。
    """
    out = []
    for f in detect_forks(path):
        tab, diag, polys = f["tab"], f["diag"], f["polys"]
        eu, ed = f["up"], f["dn"]
        pair = [eu.id, ed.id]
        pu, pd = polys.get(eu.id) or [], polys.get(ed.id) or []
        if len(pu) < 3 or len(pd) < 3:
            out.append({"tab": tab, "pair": pair, "kind": "bend",
                        "detail": "折れ点が無い(fork 署名なのに直線)"})
            continue
        lane_u, lane_d = pu[1][0], pd[1][0]
        if abs(lane_u - lane_d) > FORK_LANE_TOL:
            out.append({"tab": tab, "pair": pair, "kind": "lane",
                        "detail": f"折れ x が別々: {lane_u:.1f} / {lane_d:.1f}"})
            continue
        lane = (lane_u + lane_d) / 2
        for e, tgt in ((eu, f["up_tgt"]), (ed, f["dn_tgt"])):
            pen = _frac_pair(e, "entry")
            along = [fr for fr in pen if not _on_border(fr)][0]
            tb = diag.abs_box(tgt)
            want = (lane - tb.x) / tb.w if tb.w else 0.0
            if abs(along - want) > FORK_ENTRY_TOL:
                out.append({"tab": tab, "pair": pair, "kind": "entry",
                            "detail": f"{e.id} の entry frac {along:.4f} が"
                                      f"レーン正規化値 {want:.4f} と不一致"})
        if abs(pu[0][1] - pd[0][1]) <= 0.0:
            out.append({"tab": tab, "pair": pair, "kind": "trunk",
                        "detail": "トランク 2 本の間隔が 0(平行に見えない)"})
    return out


def check(path, absent=(), present=(), graph_superset=None, spec=None,
          router=False):
    build_warns = []
    if spec is not None:
        path, build_warns = build_from_spec(spec)  # spec からビルドし直した .drawio を検証
    result = validate_json(path)
    errors = result["errors"]
    warnings = result["warnings"]
    crossings = len(result["crossings"])
    codes = [f["code"] for f in result["findings"]]
    budget = budget_from_findings(result["findings"])

    checks = []
    checks.append(("0 error", errors == 0, f"errors={errors}"))
    checks.append(("0 warning(幾何/境界)", warnings == 0, f"warnings={warnings}"))
    if spec is not None:
        checks.append(("ビルド段の警告なし(W9/legend/meta)", not build_warns,
                       "なし" if not build_warns else f"{len(build_warns)}件: {build_warns[:3]}"))
    if budget is not None:
        checks.append(("交差が目安内", crossings <= budget,
                       f"crossings={crossings} / 目安≤{budget}"))
    else:
        checks.append(("交差(目安表示なし)", True, f"crossings={crossings}"))

    for code in absent:
        checks.append((f"{code} が無い", code not in codes,
                       "検出" if code in codes else "なし"))
    for code in present:
        checks.append((f"{code} がある", code in codes,
                       "あり" if code in codes else "未検出"))

    if graph_superset:
        base = graph_lines(graph_superset)
        cur = graph_lines(path)
        missing = sorted(base - cur)
        checks.append((f"{Path(graph_superset).name} の構成を 1:1 保持",
                       not missing,
                       "全保持" if not missing else f"欠落 {len(missing)}: {missing[:6]}"))

    router_result = None
    if router:
        router_result = {"anchor_fractions": check_anchor_fractions(path),
                         "fan_symmetry": check_fan_symmetry(path),
                         "corun_separation": check_corun_separation(path),
                         "exit_direction": check_exit_direction(path),
                         "pair_center": check_pair_center(path),
                         "sibling_dims": check_sibling_dims(path),
                         "fan_side_consistency": check_fan_side_consistency(path),
                         "max_bends": check_max_bends(path),
                         "pin_slot_distance": check_pin_slot_distance(path),
                         "fork_shape": check_fork_shape(path),
                         "diamond_vertices": check_diamond_vertices(path, spec),
                         "safe_cell_ids": check_safe_cell_ids(path, spec),
                         "end_labels": check_end_labels(path, spec),
                         "er_cardinality": check_er_cardinality(path, spec),
                         "stereotype_italic": check_stereotype_italic(path, spec),
                         "flow_shapes_links": check_flow_shapes_links(path, spec),
                         "gateway_topology": check_gateway_topology(path, spec)}
        for label, key in (("接続アンカー(ノード端点 frac 0.35–0.65)", "anchor_fractions"),
                           ("ファンアウト対称(レーン共有・entry 対一致)", "fan_symmetry"),
                           ("レーン分離(異 src 並走 ≥7px)", "corun_separation"),
                           ("出射辺の方向(行き先への余弦 ≥ -0.48)", "exit_direction"),
                           ("垂直ペア中心(直行垂直直線の frac 0.5±0.02)", "pair_center"),
                           ("兄弟コンテナ寸法(subnet/az の幅・高さ一致)", "sibling_dims"),
                           ("ファン辺の流儀統一(同一 src 横ファンの出射/入射辺)", "fan_side_consistency"),
                           (f"折れ点上限(全エッジ ≤{MAX_BENDS})", "max_bends"),
                           (f"同一辺ポート分離(pin/自動端点 ≥{PORT_SEP_MIN:g}px)", "pin_slot_distance"),
                           ("fork 形状(レーン一致・entry 整合・平行トランク)", "fork_shape"),
                           ("decision/gateway 頂点(4頂点・上方流入は上頂点)", "diamond_vertices"),
                           ("draw.io CLI 安全 id(Array/Object prototype 名なし)", "safe_cell_ids"),
                           (f"両端ラベル(端点→ラベル箱 ≤{END_LABEL_MAX_DISTANCE:g}px・箱と非重複)", "end_labels"),
                           ("ER 端別カーディナリティ(親 0..1/1・子 many)", "er_cardinality"),
                           ("UML stereotype(interface/abstract のタイトル italic)", "stereotype_italic"),
                           ("新 flow shape / subprocess link(native figure/属性)", "flow_shapes_links"),
                           ("parallel gateway topology(fork/join)", "gateway_topology")):
            v = router_result[key]
            checks.append((label, not v,
                           "違反なし" if not v else f"{len(v)}件: {v[:3]}"))

    passed = all(ok for _, ok, _ in checks)
    return {
        "file": str(path),
        "errors": errors, "warnings": warnings,
        "crossings": crossings, "crossing_budget": budget,
        "finding_codes": codes,
        "build_warnings": build_warns,
        "router": router_result,
        "checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in checks],
        "all_pass": passed,
    }


def main(argv):
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    as_json = "--json" in args
    router = "--router" in args
    args = [a for a in args if a not in ("--json", "--router")]

    absent, present, graph_superset, spec, path = [], [], None, None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--absent":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                absent.append(args[i]); i += 1
            continue
        if a == "--present":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                present.append(args[i]); i += 1
            continue
        if a == "--graph-superset":
            graph_superset = args[i + 1]; i += 2; continue
        if a == "--spec":
            spec = args[i + 1]; i += 2; continue
        path = a; i += 1

    if not path and not spec:
        print("ERROR: 対象 .drawio か --spec <spec.json> を指定してください", file=sys.stderr)
        return 2

    res = check(path, absent, present, graph_superset, spec, router)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        mark = "PASS" if res["all_pass"] else "FAIL"
        print(f"[{mark}] {res['file']}  "
              f"(errors={res['errors']} warnings={res['warnings']} "
              f"crossings={res['crossings']}"
              + (f"/目安≤{res['crossing_budget']}" if res['crossing_budget'] is not None else "")
              + ")")
        for c in res["checks"]:
            print(f"  {'✓' if c['pass'] else '✗'} {c['name']}: {c['detail']}")
        if res["finding_codes"]:
            print(f"  finding codes: {res['finding_codes']}")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

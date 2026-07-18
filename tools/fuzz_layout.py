#!/usr/bin/env python3
"""レイアウトエンジンの幾何不変条件ファザー(CI スモーク用)。

ランダムな正当グリッドスペック(縦横スタック・ハブ・コンテナ入れ子)を
生成してビルドし、次を検証する:
  1. ビルドが成功する(正当な入力で die しない)
  2. バリデータの ERROR(E 系)がゼロ(silent-bad の再発防止)
  3. 全エッジ区間が直交(斜め線なし)
  4. exit_dy が付くのは exit の fy=1 のときだけ
シード固定で再現可能。

使い方: python3 tools/fuzz_layout.py [ケース数=60]
終了コード: 問題ゼロなら 0、あれば 1(再現シードを表示)
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD = Path(__file__).resolve().parent.parent / "scripts" / "build_drawio.py"
VALIDATE = (Path(__file__).resolve().parent.parent / "scripts"
            / "validate_drawio.py")

ICONS = ["ec2", "lambda", "s3", "dynamodb", "sqs", "sns", "rds",
         "api_gateway", "cloudfront", "cloudwatch_2", "eventbridge",
         "kinesis_data_streams", "elasticache", "step_functions"]
LABELS = ["", "処理", "注文サービス", "中程度に長い説明ラベル",
          "二行の\nラベル", "A"]


def gen_spec(seed: int) -> dict:
    """正当なスペックを生成する(コンテナ矩形=列域の分割で所属を保証)。"""
    rnd = random.Random(seed)
    rows = rnd.randint(3, 6)
    containers = []
    zones = [("", rnd.randint(1, 3))]          # (parent_id, 列数) の帯
    if rnd.random() < 0.7:
        containers.append({"id": "vpc", "label": "VPC", "type": "vpc"})
        if rnd.random() < 0.5:
            containers.append({"id": "sub", "label": "Subnet",
                               "type": "private_subnet", "parent": "vpc"})
            zones.append(("sub", 1))
        zones.append(("vpc", rnd.randint(1, 2)))
    nodes = []
    col0 = 0
    for parent, width in zones:
        cells = [(c, r) for c in range(col0, col0 + width)
                 for r in range(rows)]
        rnd.shuffle(cells)
        k = rnd.randint(min(2, len(cells)), min(6, len(cells)))
        for _ in range(k):
            c, r = cells.pop()
            n = {"id": f"n{len(nodes)}", "icon": rnd.choice(ICONS),
                 "col": c, "row": r}
            lb = rnd.choice(LABELS)
            if lb:
                n["label"] = lb
            if parent:
                n["parent"] = parent
            nodes.append(n)
        col0 += width
    edges = []
    n_edges = rnd.randint(len(nodes) // 2, min(int(len(nodes) * 1.8), 26))
    hub = rnd.choice(nodes)["id"] if rnd.random() < 0.5 else None
    for i in range(n_edges):
        if hub and rnd.random() < 0.4:
            a, b = hub, rnd.choice(nodes)["id"]
        else:
            a, b = (rnd.choice(nodes)["id"] for _ in range(2))
        if a == b:
            continue
        edges.append({"id": f"e{i}", "src": a, "dst": b,
                      "kind": rnd.choice(["main", "main", "sub", "ops"]),
                      **({"label": "ラベル"} if rnd.random() < 0.25 else {})})
    return {"name": f"fz{seed}",
            "meta": {"purpose": "fuzz", "audience": "ci", "scope": "smoke",
                     "abstraction": "概要", "assumptions": "自動生成"},
            "legend": {"main": "同期", "sub": "非同期", "ops": "監視"},
            "containers": containers, "nodes": nodes, "edges": edges}


def check_geometry(abs_path: Path) -> str | None:
    d = json.loads(abs_path.read_text(encoding="utf-8"))
    for dd in d.get("diagrams", [d]):
        boxes = {}
        for n in dd.get("nodes", []):
            if "cx" in n:
                w, h = n.get("w", 78), n.get("h", 78)
                boxes[n["id"]] = (n["cx"] - w / 2, n["cy"] - h / 2, w, h)
        for c in dd.get("containers", []):
            boxes[c["id"]] = (c["x"], c["y"], c["w"], c["h"])
        for e in dd.get("edges", []):
            if "exit" not in e or e.get("src") not in boxes \
                    or e.get("dst") not in boxes:
                continue
            dy = float(e.get("exit_dy") or 0)
            if dy and e["exit"][1] != 1:
                return f"exit_dy が fy={e['exit'][1]} に付与({e['id']})"

            def pt(t, f, off=0.0):
                x, y, w, h = boxes[e[t]]
                return (x + f[0] * w, y + f[1] * h + off)
            poly = ([pt("src", e["exit"], dy)]
                    + [tuple(p) for p in e.get("points") or []]
                    + [pt("dst", e["entry"])])
            for a, b in zip(poly, poly[1:]):
                if abs(a[0] - b[0]) > 0.75 and abs(a[1] - b[1]) > 0.75:
                    return (f"斜め線 {e['id']}: ({a[0]:.0f},{a[1]:.0f})→"
                            f"({b[0]:.0f},{b[1]:.0f})")
    return None


def run_case(seed: int) -> str | None:
    spec = gen_spec(seed)
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "s.spec.json"
        sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        out = Path(td) / "s.drawio"
        try:
            r = subprocess.run(
                [sys.executable, str(BUILD), str(sp), "-o", str(out),
                 "--emit-abs", "--no-validate"],
                capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return f"HANG seed={seed}"
        if r.returncode != 0:
            out = r.stdout + r.stderr
            # W16–W21 はアーキテクチャのアンチパターン(グローバルサービスをリージョン内へ、
            # DB を public subnet へ、外部→DB 直結 等)を意図的に拒否するビルド段エラー。
            # ランダム生成が偶然踏んだ不正構成の正しい拒否であり、レイアウトの頑健性
            # (この fuzz が見る対象)の失敗ではないので、想定内としてスキップする。
            if re.search(r"\bW(1[6-9]|2[01])\b", out):
                return None
            return f"BUILD_FAIL seed={seed}: {out[-120:]}"
        v = subprocess.run(
            [sys.executable, str(VALIDATE), str(out), "--json"],
            capture_output=True, text=True, timeout=60)
        try:
            j = json.loads(v.stdout)
        except Exception:
            return f"VALIDATE_FAIL seed={seed}"
        if j.get("errors", 0) > 0:
            first = next((f["message"] for f in j.get("findings", [])
                          if f["level"] == "ERROR"), "?")
            return f"E-ERROR seed={seed}: {first[:100]}"
        g = check_geometry(Path(td) / "s.abs.json")
        if g:
            return f"GEOM seed={seed}: {g}"
    return None


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    problems = [p for p in (run_case(s) for s in range(n)) if p]
    print(f"fuzz_layout: {n} cases, problems: {len(problems)}")
    for p in problems[:10]:
        print(" ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

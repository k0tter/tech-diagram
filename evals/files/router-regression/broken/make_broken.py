#!/usr/bin/env python3
"""broken/ 破損フィクスチャの再生成スクリプト(REV-3)。

現行エンジンで r7 スペックをビルドした正しい .drawio を人工的に壊し、
check_diagram の各検査が違反を出すことを実証する固定素材を作る。
フィクスチャは commit 済みで、通常は再実行不要。エンジンの出力形式が
意図的に変わってフィクスチャを作り直すときだけ実行する:

  python3 evals/files/router-regression/broken/make_broken.py

壊し方(verify.py の BROKEN と 1:1 対応):
  broken-er-cardinality.drawio  er_11n の子側 endArrow=ERmany → open
                                (子側マーカー欠落 → er_cardinality)
  broken-flow-shapes.drawio     join_gate の gwType=parallel → exclusive
                                (→ flow_shapes_links)+ fork の出射 e3 を
                                削除で 1→1(→ gateway_topology)+ e6 の
                                exitY=1 → 0.72(→ diamond_vertices)
  broken-subprocess-link.drawio subprocess の link 属性を除去
                                (→ flow_shapes_links)
"""
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../router-regression/broken
RR = HERE.parent                                # .../router-regression
SKILL = RR.parents[2]                           # スキルルート
ENGINE = SKILL / "scripts" / "build_drawio.py"


def build(spec_name: str, td: Path) -> Path:
    out = td / (spec_name.replace(".spec.json", "") + ".drawio")
    cp = subprocess.run(
        [sys.executable, str(ENGINE), str(RR / spec_name), "-o", str(out)],
        capture_output=True, text=True)
    assert out.exists(), cp.stdout + cp.stderr
    return out


def cells_by_id(root):
    out = {}
    for tag in ("mxCell", "UserObject", "object"):
        for el in root.iter(tag):
            if el.get("id"):
                out[el.get("id")] = el
    return out


def style_replace(el, old, new):
    style = el.get("style", "")
    assert old in style, (el.get("id"), style)
    el.set("style", style.replace(old, new))


def write(tree, name):
    path = HERE / name
    tree.write(path, encoding="unicode", xml_declaration=False)
    print("wrote", path)


def main():
    with tempfile.TemporaryDirectory(prefix="make-broken-") as td_str:
        td = Path(td_str)

        tree = ET.parse(build("r7-er-cardinality.spec.json", td))
        cells = cells_by_id(tree.getroot())
        style_replace(cells["required"], "endArrow=ERmany", "endArrow=open")
        write(tree, "broken-er-cardinality.drawio")

        tree = ET.parse(build("r7-flow-shapes.spec.json", td))
        root = tree.getroot()
        cells = cells_by_id(root)
        style_replace(cells["join_gate"], "gwType=parallel", "gwType=exclusive")
        style_replace(cells["e6"], "exitY=1", "exitY=0.72")
        for parent in root.iter("root"):
            for el in list(parent):
                if el.get("id") == "e3":
                    parent.remove(el)
        write(tree, "broken-flow-shapes.drawio")

        tree = ET.parse(build("r7-subprocess-link.spec.json", td))
        cells = cells_by_id(tree.getroot())
        detail = cells["detail"]
        assert detail.get("link"), detail.attrib
        del detail.attrib["link"]
        write(tree, "broken-subprocess-link.drawio")


if __name__ == "__main__":
    main()

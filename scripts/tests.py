#!/usr/bin/env python3
"""tech-diagram 回帰テスト(標準ライブラリのみ)。

  python3 scripts/tests.py            # 全テスト
  python3 scripts/tests.py -v         # 詳細

方針:
  - 敵対的スペックは期待 rc 付き(「traceback が無い」だけでは
    validate_spec を消しても通ってしまうため)
  - フィクスチャは全て tempdir 上で実行し、資材の変異を防ぐ
  - バリデータにも敵対ケース(ハング検体は timeout 付き)
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / "build_drawio.py"
VALIDATE = HERE / "validate_drawio.py"
TEMPLATES = sorted((ROOT / "templates").glob("*.spec.json"))

sys.path.insert(0, str(HERE))
from _common import seg_cross  # noqa: E402
import build_drawio as B  # noqa: E402


def run_build(spec_path: Path, *extra: str,
              cwd: Path | None = None) -> subprocess.CompletedProcess:
    out = (cwd or spec_path.parent) / (spec_path.stem + ".out.drawio")
    env = dict(os.environ, AWSDIAG_CHECK="1")
    return subprocess.run(
        [sys.executable, str(BUILD), str(spec_path), "-o", str(out), *extra],
        capture_output=True, text=True, timeout=60, env=env)


def build_spec(spec, tmp: Path, name: str, *extra: str):
    """dict または生テキストのスペックを tempdir に置いてビルドする。"""
    p = tmp / f"{name}.spec.json"
    if isinstance(spec, str):
        p.write_text(spec, encoding="utf-8")
    else:
        p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return run_build(p, *extra, cwd=tmp)


def base_spec(**over):
    s = {"name": "t", "meta": {"purpose": "test"},
         "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0},
                   {"id": "b", "icon": "s3", "col": 1, "row": 0}],
         "edges": [{"id": "e1", "src": "a", "dst": "b", "kind": "main"}]}
    s.update(over)
    return s


# (名前, スペック(dict or 生テキスト), 期待 rc)
# rc 2 = スペック不正(ビルダーが指示付きで拒否) / 0 = 正常
ADVERSARIAL: list[tuple[str, object, int]] = [
    ("json-syntax", "{broken json", 2),
    ("empty-file", "", 2),
    ("top-level-list", "[1, 2]", 2),
    ("nodes-null", base_spec(nodes=None), 2),
    ("node-no-id", base_spec(nodes=[{"icon": "ec2", "col": 0, "row": 0}]), 2),
    ("dup-node-id", base_spec(nodes=[
        {"id": "a", "icon": "ec2", "col": 0, "row": 0},
        {"id": "a", "icon": "s3", "col": 1, "row": 0}]), 2),
    ("id-clash-edge", base_spec(edges=[
        {"id": "a", "src": "a", "dst": "b"}]), 2),
    ("node-not-dict", base_spec(nodes=["x"]), 2),
    ("reserved-id-1", base_spec(nodes=[
        {"id": "1", "icon": "ec2", "col": 0, "row": 0}]), 2),
    ("reserved-underscore", base_spec(nodes=[
        {"id": "_x", "icon": "ec2", "col": 0, "row": 0}]), 2),
    ("negative-col", base_spec(nodes=[
        {"id": "a", "icon": "ec2", "col": -1, "row": 0}]), 2),
    ("float-col", base_spec(nodes=[
        {"id": "a", "icon": "ec2", "col": 2.7, "row": 0}]), 2),
    ("partial-grid", base_spec(nodes=[
        {"id": "a", "icon": "ec2", "col": 0, "row": 0},
        {"id": "b", "icon": "s3"}]), 2),
    ("parent-missing", base_spec(nodes=[
        {"id": "a", "icon": "ec2", "col": 0, "row": 0, "parent": "nope"},
        {"id": "b", "icon": "s3", "col": 1, "row": 0}]), 2),
    ("parent-cycle", base_spec(containers=[
        {"id": "c1", "type": "vpc", "parent": "c2"},
        {"id": "c2", "type": "vpc", "parent": "c1"}]), 2),
    ("self-loop-node", base_spec(edges=[{"id": "e1", "src": "a", "dst": "a"}]), 0),
    ("edge-no-src", base_spec(edges=[{"id": "e1", "dst": "b"}]), 2),
    ("unknown-kind", base_spec(edges=[
        {"id": "e1", "src": "a", "dst": "b", "kind": "replication"}]), 2),
    ("bad-kind-color", base_spec(
        kinds={"x": {"base": "sub", "color": "red-ish"}},
        edges=[{"id": "e1", "src": "a", "dst": "b", "kind": "x"}]), 2),
    ("bad-kind-base", base_spec(
        kinds={"x": {"base": "solid"}},
        edges=[{"id": "e1", "src": "a", "dst": "b", "kind": "x"}]), 2),
    ("bad-exit-range", base_spec(edges=[
        {"id": "e1", "src": "a", "dst": "b",
         "exit": [1.5, 0], "entry": [0, 0.5]}]), 2),
    ("bad-points-type", base_spec(edges=[
        {"id": "e1", "src": "a", "dst": "b",
         "exit": [1, 0.5], "entry": [0, 0.5], "points": ["x"]}]), 2),
    ("text-node-in-grid", base_spec(nodes=[
        {"id": "a", "text": "hello", "col": 0, "row": 0},
        {"id": "b", "icon": "s3", "col": 1, "row": 0}]), 2),
    ("unknown-icon", base_spec(nodes=[
        {"id": "a", "icon": "dynamodv", "col": 0, "row": 0},
        {"id": "b", "icon": "s3", "col": 1, "row": 0}]), 2),
    ("dup-cell", base_spec(nodes=[
        {"id": "a", "icon": "ec2", "col": 0, "row": 0},
        {"id": "b", "icon": "s3", "col": 0, "row": 0}]), 2),
    ("empty-container", base_spec(containers=[
        {"id": "c1", "type": "vpc"}]), 2),
    ("on-boundary-bad-value", base_spec(
        containers=[{"id": "c1", "type": "vpc"}],
        nodes=[{"id": "a", "icon": "internet_gateway", "col": 0, "row": 0,
                "parent": "c1", "on_boundary": "west"},
               {"id": "b", "icon": "s3", "col": 1, "row": 0,
                "parent": "c1"}]), 2),
    ("on-boundary-no-parent", base_spec(nodes=[
        {"id": "a", "icon": "internet_gateway", "col": 0, "row": 0,
         "on_boundary": "left"},
        {"id": "b", "icon": "s3", "col": 1, "row": 0}]), 2),
    ("on-boundary-abs-path", {"name": "t", "meta": {"purpose": "x"},
                              "nodes": [{"id": "a", "icon": "ec2", "cx": 100,
                                         "cy": 100, "on_boundary": "left"}]}, 2),
    ("empty-diagrams", {"diagrams": []}, 2),
    # 正常系
    ("minimal-ok", base_spec(), 0),
    ("auto-grid-ok", base_spec(nodes=[
        {"id": "a", "icon": "ec2"}, {"id": "b", "icon": "s3"}]), 0),
    ("abs-empty-tab", {"diagrams": [{"name": "x"}]}, 0),
]


class TestGoldenTemplates(unittest.TestCase):
    """同梱テンプレートは常に 0 エラー(差分スコア検算付き)でビルドできる。"""

    def test_templates(self):
        self.assertGreaterEqual(len(TEMPLATES), 4, "テンプレートが見つからない")
        with tempfile.TemporaryDirectory() as td:
            for spec in TEMPLATES:
                with self.subTest(spec=spec.name):
                    cp = Path(td) / spec.name
                    shutil.copy(spec, cp)
                    r = run_build(cp)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertIn("0 error(s)", r.stdout, r.stdout)
                    self.assertNotIn("Traceback", r.stdout + r.stderr)
                    self.assertEqual(cp.read_text(), spec.read_text(),
                                     "ビルドがスペックを書き換えた")
                    # 再生成 = 同梱 .drawio とバイト一致(エンジン変更が既存
                    # 出力を変えていないことの回帰検査。テンプレを意図して
                    # 変えたときは templates/ を再生成してコミットする)
                    committed = spec.with_name(
                        spec.name.replace(".spec.json", ".drawio"))
                    out = cp.parent / (cp.stem + ".out.drawio")
                    self.assertEqual(out.read_text(), committed.read_text(),
                                     f"{spec.name}: 再生成が同梱 .drawio と"
                                     "バイト一致しない")

    def test_meta_updated_pinned(self):
        # meta.updated 未指定は生成日で埋まる仕様のため、テンプレが日付を
        # 明示しないと日をまたいだ再生成でバイトが変わり、CI・リリースの
        # テンプレ同期チェックが破れる(v1.0.1 リリースで実際に発生)
        for spec in TEMPLATES:
            data = json.loads(spec.read_text())
            diags = data["diagrams"] if "diagrams" in data else [data]
            for i, d in enumerate(diags):
                with self.subTest(spec=spec.name, diagram=i):
                    self.assertIn("updated", d.get("meta", {}),
                                  "テンプレの meta.updated が未指定")


class TestAdversarialBuilder(unittest.TestCase):
    """壊れたスペックは期待どおりの rc で、指示付きエラーとして拒否される。"""

    def test_expectations(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for name, spec, want_rc in ADVERSARIAL:
                with self.subTest(case=name):
                    r = build_spec(spec, tmp, name)
                    combined = r.stdout + r.stderr
                    self.assertNotIn("Traceback", combined,
                                     f"{name}: 生 traceback\n{combined[:600]}")
                    self.assertEqual(r.returncode, want_rc,
                                     f"{name}: rc={r.returncode} 期待={want_rc}\n"
                                     f"{combined[:600]}")
                    if want_rc == 2:
                        self.assertIn("ERROR", combined, name)


class TestValidatorAdversarial(unittest.TestCase):
    """バリデータ単体も、壊れた入力でハング・traceback しない。"""

    W8_CYCLE = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="g1" value="VPC" style="grIcon=mxgraph.aws4.group_vpc2;container=1;" vertex="1" parent="g2"><mxGeometry x="0" y="0" width="400" height="300" as="geometry"/></mxCell>
<mxCell id="g2" value="X" style="grIcon=mxgraph.aws4.group_security_group;container=1;fillColor=#E6F6F7;" vertex="1" parent="g1"><mxGeometry x="10" y="10" width="200" height="200" as="geometry"/></mxCell>
<mxCell id="s3n" value="S3" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3;" vertex="1" parent="g1"><mxGeometry x="50" y="50" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    DUP_ID = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="n1" value="A" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="n1" value="B" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3;" vertex="1" parent="1"><mxGeometry x="300" y="0" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def run_validator(self, path: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(VALIDATE), path],
                              capture_output=True, text=True, timeout=15)

    def check(self, r, want_rcs, label):
        self.assertNotIn("Traceback", r.stdout + r.stderr, label)
        self.assertIn(r.returncode, want_rcs,
                      f"{label}: rc={r.returncode}\n{(r.stdout + r.stderr)[:400]}")

    def test_missing_file(self):
        self.check(self.run_validator("/no/such/file.drawio"), (2,), "不在パス")

    def test_not_xml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write("これは XML ではない")
            p = f.name
        try:
            self.check(self.run_validator(p), (2,), "非XML")
        finally:
            os.unlink(p)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            p = f.name
        try:
            self.check(self.run_validator(p), (2,), "空ファイル")
        finally:
            os.unlink(p)

    def test_w8_parent_cycle_no_hang(self):
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(self.W8_CYCLE)
            p = f.name
        try:  # timeout=15 がハングの検出器
            self.check(self.run_validator(p), (0, 1), "W8循環")
        finally:
            os.unlink(p)

    def test_duplicate_xml_id(self):
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(self.DUP_ID)
            p = f.name
        try:
            r = self.run_validator(p)
            self.check(r, (1,), "重複id")
            self.assertIn("E10", r.stdout, "重複 id が E10 で報告されない")
        finally:
            os.unlink(p)


class TestValidatorW4W10(unittest.TestCase):
    """W4(エッジラベル同士の重なり)と W10(サブネット常駐サービス)の回帰。"""

    # 交差する 2 エッジのラベルが中点(100,100)で重なる → W4
    W4_CROSS = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="e1" value="接続A" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="0" y="100" as="sourcePoint"/><mxPoint x="200" y="100" as="targetPoint"/></mxGeometry></mxCell>
<mxCell id="e2" value="接続B" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="100" y="0" as="sourcePoint"/><mxPoint x="100" y="200" as="targetPoint"/></mxGeometry></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    # 平行エッジ(11px 差)のラベルは 3px 程度しか食い込まない → しきい値未満で無視
    W4_TOUCH = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="e1" value="AAAA" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="0" y="100" as="sourcePoint"/><mxPoint x="200" y="100" as="targetPoint"/></mxGeometry></mxCell>
<mxCell id="e2" value="BBBB" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="0" y="113" as="sourcePoint"/><mxPoint x="200" y="113" as="targetPoint"/></mxGeometry></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    # サブネットを持つ VPC 内: SG 直下の EC2 → W10。サブネット内の RDS と
    # VPC 直下の ALB(またぎ表現)は発火しない
    W10_SG = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="vpc" value="VPC" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;container=1;verticalAlign=top;align=left;spacingLeft=30;fillColor=none;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="640" height="300" as="geometry"/></mxCell>
<mxCell id="sub" value="Subnet" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;container=1;verticalAlign=top;align=left;spacingLeft=30;fillColor=#E6F6F7;" vertex="1" parent="vpc"><mxGeometry x="40" y="40" width="180" height="220" as="geometry"/></mxCell>
<mxCell id="sg" value="SG" style="fillColor=none;strokeColor=#DD3522;verticalAlign=top;container=1;" vertex="1" parent="vpc"><mxGeometry x="250" y="40" width="180" height="220" as="geometry"/></mxCell>
<mxCell id="rdsn" value="RDS" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.rds;" vertex="1" parent="sub"><mxGeometry x="40" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="ec2n" value="EC2" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;" vertex="1" parent="sg"><mxGeometry x="40" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="albn" value="ALB" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.application_load_balancer;" vertex="1" parent="vpc"><mxGeometry x="470" y="60" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    # サブネットを描いていない VPC(抽象度の高い図)とクラウド外ノードは対象外
    W10_NO_SUBNET = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="vpc" value="VPC" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;container=1;verticalAlign=top;align=left;spacingLeft=30;fillColor=none;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="300" height="220" as="geometry"/></mxCell>
<mxCell id="ec2n" value="EC2" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;" vertex="1" parent="vpc"><mxGeometry x="40" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="ec2out" value="EC2 演出" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;" vertex="1" parent="1"><mxGeometry x="400" y="60" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def run_validator_on(self, xml: str) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            return subprocess.run([sys.executable, str(VALIDATE), p],
                                  capture_output=True, text=True, timeout=15)
        finally:
            os.unlink(p)

    def test_w4_edge_labels_overlap(self):
        r = self.run_validator_on(self.W4_CROSS)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("W4", r.stdout, "重なるエッジラベルが W4 で警告されない")

    def test_w4_small_contact_ignored(self):
        r = self.run_validator_on(self.W4_TOUCH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W4", r.stdout,
                         "しきい値未満の接触なのに W4 が誤発火した")

    def test_w10_ec2_outside_subnet(self):
        r = self.run_validator_on(self.W10_SG)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("W10", r.stdout, "SG 直下の EC2 が W10 で警告されない")
        self.assertIn("ec2n", r.stdout)
        self.assertEqual(r.stdout.count("W10"), 1,
                         "サブネット内 RDS / またぎ表現の ALB にも誤発火した:\n"
                         + r.stdout)

    def test_w10_no_subnet_vpc_ok(self):
        r = self.run_validator_on(self.W10_NO_SUBNET)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W10", r.stdout,
                         "サブネットを描いていない VPC で W10 が誤発火した")

    def test_w10_security_group_spec(self):
        # 実案件フィードバックのケース: SG 直下の EC2 がビルド経由でも警告される
        spec = {"name": "aws", "meta": {"purpose": "test"},
                "containers": [
                    {"id": "v", "label": "VPC", "type": "vpc"},
                    {"id": "sn", "label": "Private subnet",
                     "type": "private_subnet", "parent": "v"},
                    {"id": "sg", "label": "SG", "type": "security_group",
                     "parent": "v"}],
                "nodes": [
                    {"id": "db", "label": "RDS", "icon": "rds",
                     "parent": "sn", "col": 0, "row": 0},
                    {"id": "web", "label": "EC2", "icon": "ec2",
                     "parent": "sg", "col": 1, "row": 0}],
                "edges": [{"id": "e1", "src": "web", "dst": "db",
                           "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "w10")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("W10", r.stdout, "SG 直下の EC2 が W10 で警告されない")


class TestW14GatewayPlacement(unittest.TestCase):
    """W14(ゲートウェイ/アタッチメント系ノードの配置規約)の回帰。

    規約表は _common.GATEWAY_PLACEMENT。ビルド段(validate_spec)と
    バリデータの両方で、IGW in subnet / NAT in private subnet /
    TGW in VPC を検出し、正当配置(on_boundary・public subnet 内 NAT・
    VPC 外 TGW/DX・規約なし icon・サブネット未描画 VPC の抽象表現)には
    発火しないこと。
    """

    BAD_NODES = [
        {"id": "igw", "label": "IGW", "icon": "internet_gateway",
         "parent": "pub", "col": 1, "row": 1},
        {"id": "nat", "label": "NAT", "icon": "nat_gateway",
         "parent": "priv", "col": 1, "row": 3},
        {"id": "tgw", "label": "TGW", "icon": "transit_gateway",
         "parent": "vpc", "col": 3, "row": 2}]

    # フラットな手編集ファイル(全要素 parent="1")は幾何包含で判定する。
    # igw1 = サブネット矩形の内側 → W14 / igw2 = awsdiagBoundary=1 で
    # VPC 枠線上センターまたぎ(on_boundary 相当)→ 親直下扱いで発火しない
    W14_FLAT = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="vpc" value="VPC" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;container=1;verticalAlign=top;align=left;spacingLeft=30;fillColor=none;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="600" height="300" as="geometry"/></mxCell>
<mxCell id="sub" value="Public subnet" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;container=1;verticalAlign=top;align=left;spacingLeft=30;" vertex="1" parent="1"><mxGeometry x="340" y="60" width="200" height="200" as="geometry"/></mxCell>
<mxCell id="igw1" value="IGW" style="shape=mxgraph.aws4.internet_gateway;fillColor=#8C4FFF;verticalLabelPosition=bottom;verticalAlign=top;" vertex="1" parent="1"><mxGeometry x="400" y="120" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="igw2" value="IGW2" style="shape=mxgraph.aws4.internet_gateway;fillColor=#8C4FFF;verticalLabelPosition=bottom;verticalAlign=top;awsdiagBoundary=1;" vertex="1" parent="1"><mxGeometry x="-39" y="111" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    @staticmethod
    def gw_spec(nodes, containers=None):
        if containers is None:
            containers = [
                {"id": "vpc", "label": "VPC", "type": "vpc"},
                {"id": "pub", "label": "Public subnet",
                 "type": "public_subnet", "parent": "vpc"},
                {"id": "priv", "label": "Private subnet",
                 "type": "private_subnet", "parent": "vpc"}]
        return {"name": "t", "meta": {"purpose": "test"},
                "containers": containers, "nodes": nodes, "edges": []}

    def run_validator_on_file(self, path: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(VALIDATE), str(path)],
                              capture_output=True, text=True, timeout=15)

    def test_w14_build_detects(self):
        # fail-before 検体: IGW in subnet / NAT in private / TGW in VPC が
        # ビルド段で 3 件とも WARN: W14 になる(実装前は無警告で素通りした)
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.gw_spec(self.BAD_NODES), Path(td), "w14bad")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(r.stdout.count("WARN: W14"), 3,
                             "ビルド段 W14 が 3 件出ない:\n" + r.stdout)
            for nid in ("igw", "nat", "tgw"):
                self.assertIn(f"'{nid}'", r.stdout)

    def test_w14_validator_detects(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.gw_spec(self.BAD_NODES), Path(td), "w14bad")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rv = self.run_validator_on_file(Path(td) / "w14bad.spec.out.drawio")
            self.assertEqual(rv.returncode, 0, rv.stdout + rv.stderr)
            self.assertEqual(rv.stdout.count("W14"), 3,
                             "バリデータ W14 が 3 件出ない:\n" + rv.stdout)

    def test_w14_on_boundary_and_correct_ok(self):
        # 正当配置: IGW=VPC 枠線上(on_boundary)/ VGW=VPC 直下 /
        # NAT=public subnet 内 / TGW・DX=VPC 外(トップレベル)
        nodes = [
            {"id": "igw", "label": "IGW", "icon": "internet_gateway",
             "parent": "vpc", "col": 1, "row": 1, "on_boundary": "left"},
            {"id": "vgw", "label": "VGW", "icon": "vpn_gateway",
             "parent": "vpc", "col": 2, "row": 1},
            {"id": "nat", "label": "NAT", "icon": "nat_gateway",
             "parent": "pub", "col": 1, "row": 2},
            {"id": "tgw", "label": "TGW", "icon": "transit_gateway",
             "col": 5, "row": 1},
            {"id": "dx", "label": "DX", "icon": "direct_connect",
             "col": 5, "row": 2}]
        containers = [
            {"id": "vpc", "label": "VPC", "type": "vpc"},
            {"id": "pub", "label": "Public subnet",
             "type": "public_subnet", "parent": "vpc"}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.gw_spec(nodes, containers), Path(td), "w14ok")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W14", r.stdout,
                             "正当配置に W14 が誤発火した:\n" + r.stdout)
            rv = self.run_validator_on_file(Path(td) / "w14ok.spec.out.drawio")
            self.assertEqual(rv.returncode, 0, rv.stdout + rv.stderr)
            self.assertNotIn("W14", rv.stdout,
                             "正当配置にバリデータ W14 が誤発火した:\n" + rv.stdout)

    def test_w14_no_rule_icons_ok(self):
        # 規約なし icon(ELB 系は VPC 直下またぎ・subnet 内の両方が実務にある)
        # とマネージド系は W14 の対象外
        nodes = [
            {"id": "web", "label": "EC2", "icon": "ec2",
             "parent": "pub", "col": 1, "row": 1},
            {"id": "alb", "label": "ALB", "icon": "alb",
             "parent": "priv", "col": 1, "row": 3},
            {"id": "elb", "label": "ELB", "icon": "elastic_load_balancing",
             "parent": "vpc", "col": 3, "row": 2},
            {"id": "st", "label": "S3", "icon": "s3", "col": 6, "row": 1}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.gw_spec(nodes), Path(td), "w14none")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W14", r.stdout,
                             "規約なし icon に W14 が誤発火した:\n" + r.stdout)

    def test_w14_abstract_vpc_nat_ok(self):
        # サブネットを 1 つも描いていない VPC 直下の NAT は抽象表現として
        # 許容(W10 と同じ抽象度ルール。実例: マルチアカウント図の Egress VPC)
        nodes = [
            {"id": "igw", "label": "IGW", "icon": "internet_gateway",
             "parent": "vpc", "col": 1, "row": 1},
            {"id": "nat", "label": "NAT", "icon": "nat_gateway",
             "parent": "vpc", "col": 2, "row": 1}]
        containers = [{"id": "vpc", "label": "Egress VPC", "type": "vpc"}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.gw_spec(nodes, containers), Path(td), "w14abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W14", r.stdout,
                             "サブネット未描画 VPC の NAT に W14 が誤発火した:\n"
                             + r.stdout)
            rv = self.run_validator_on_file(Path(td) / "w14abs.spec.out.drawio")
            self.assertEqual(rv.returncode, 0, rv.stdout + rv.stderr)
            self.assertNotIn("W14", rv.stdout, rv.stdout)

    def test_w14_flat_file_geometry(self):
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(self.W14_FLAT)
            p = f.name
        try:
            r = self.run_validator_on_file(Path(p))
        finally:
            os.unlink(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("W14"), 1,
                         "フラットファイルの幾何判定が期待と違う:\n" + r.stdout)
        self.assertIn("igw1", r.stdout)


class TestSemanticAntipatterns(unittest.TestCase):
    """W16〜W21(アーキテクチャ・アンチパターン検査。SEM-3)の回帰。

    語彙は _common に一本化し、ビルド段(validate_spec)とバリデータの
    両方で検査する。W17/W18/W19 = error(ビルド拒否 / 検証 rc1)、
    W16/W20/W21 = warning。fail-before: 実装前は全ケース素通りした
    (example-multiregion の r53→ALB(DR) 直行がそのまま出荷された)。
    """

    @staticmethod
    def dr_spec(fo_src: str) -> dict:
        """マルチリージョン DR の骨格。fo_src が failover 線の始点。"""
        return {
            "name": "dr", "meta": {"purpose": "test"},
            "kinds": {"failover": {"base": "sub", "color": "#E8730C"}},
            "legend": {"main": "リクエスト", "sub": "補助",
                       "failover": "フェイルオーバー"},
            "containers": [
                {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
                {"id": "regA", "label": "Region A", "type": "region",
                 "parent": "cloud"},
                {"id": "vpcA", "label": "VPC A", "type": "vpc", "parent": "regA"},
                {"id": "pubA", "label": "Public subnet",
                 "type": "public_subnet", "parent": "vpcA"},
                {"id": "regB", "label": "Region B", "type": "region",
                 "parent": "cloud"},
                {"id": "vpcB", "label": "VPC B", "type": "vpc", "parent": "regB"},
                {"id": "pubB", "label": "Public subnet",
                 "type": "public_subnet", "parent": "vpcB"}],
            "nodes": [
                {"id": "users", "label": "ユーザー", "icon": "users",
                 "col": 0, "row": 1},
                {"id": "r53", "label": "Route 53", "icon": "route_53",
                 "parent": "cloud", "col": 1, "row": 3},
                {"id": "cf", "label": "CloudFront", "icon": "cloudfront",
                 "parent": "cloud", "col": 1, "row": 0},
                {"id": "albA", "label": "ALB", "icon": "alb",
                 "parent": "pubA", "col": 2, "row": 1},
                {"id": "albB", "label": "ALB (DR)", "icon": "alb",
                 "parent": "pubB", "col": 4, "row": 1}],
            "edges": [
                {"id": "e1", "src": "users", "dst": "cf", "kind": "main"},
                {"id": "e2", "src": "cf", "dst": "albA", "kind": "main"},
                {"id": "e3", "src": fo_src, "dst": "albB", "kind": "failover",
                 "label": "フェイルオーバー"}]}

    @staticmethod
    def vpc_spec(nodes, edges=None, containers=None, name="t"):
        if containers is None:  # 空コンテナはビルド拒否のため使う分だけ生成
            used = {n.get("parent") for n in nodes}
            containers = [{"id": "vpc", "label": "VPC", "type": "vpc"}]
            if "pub" in used:
                containers.append({"id": "pub", "label": "Public subnet",
                                   "type": "public_subnet", "parent": "vpc"})
            if "priv" in used:
                containers.append({"id": "priv", "label": "Private subnet",
                                   "type": "private_subnet", "parent": "vpc"})
        return {"name": name, "meta": {"purpose": "test"},
                "containers": containers, "nodes": nodes, "edges": edges or []}

    def run_validator_on_file(self, path: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(VALIDATE), str(path)],
                              capture_output=True, text=True, timeout=15)

    def run_validator_on(self, xml: str) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            return self.run_validator_on_file(Path(p))
        finally:
            os.unlink(p)

    # ---- W16: failover 線の CDN/WAF バイパス ----

    def test_w16_bypass_detected_build_and_validator(self):
        # fail-before 検体: r53→ALB(DR) 直行(main 経路は cf→ALB)。
        # 実装前はビルド・検証とも素通りした(multiregion 出荷誤りと同型)
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.dr_spec("r53"), Path(td), "w16bad")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WARN: W16", r.stdout, "ビルド段 W16 が出ない")
            rv = self.run_validator_on_file(Path(td) / "w16bad.spec.out.drawio")
            self.assertEqual(rv.returncode, 0, rv.stdout + rv.stderr)
            self.assertIn("W16", rv.stdout, "バリデータ W16 が出ない")

    def test_w16_symmetric_origin_switch_ok(self):
        # 正しい形: cf→ALB(DR) のオリジン切替(エッジスタック共通)
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.dr_spec("cf"), Path(td), "w16ok")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W16", r.stdout,
                             "対称なオリジン切替に W16 が誤発火した:\n" + r.stdout)
            rv = self.run_validator_on_file(Path(td) / "w16ok.spec.out.drawio")
            self.assertNotIn("W16", rv.stdout, rv.stdout)

    def test_w16_no_cdn_front_ok(self):
        # CloudFront の無い図(main が users→ALB 直)ではバイパス概念が無い
        spec = self.dr_spec("r53")
        spec["nodes"] = [n for n in spec["nodes"] if n["id"] != "cf"]
        spec["edges"] = [
            {"id": "e1", "src": "users", "dst": "albA", "kind": "main"},
            {"id": "e3", "src": "r53", "dst": "albB", "kind": "failover",
             "label": "フェイルオーバー"}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "w16none")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W16", r.stdout,
                             "CDN の無い図に W16 が誤発火した:\n" + r.stdout)

    # ---- W17: グローバルエッジサービスの region/VPC 内配置 ----

    W17_XML = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="reg" value="Region" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;container=1;verticalAlign=top;align=left;spacingLeft=30;fillColor=none;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="700" height="300" as="geometry"/></mxCell>
<mxCell id="cfn" value="CloudFront" style="sketch=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.cloudfront;" vertex="1" parent="reg"><mxGeometry x="40" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="wafn" value="WAF" style="sketch=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.waf;" vertex="1" parent="reg"><mxGeometry x="240" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="wafr" value="WAF (regional)" style="sketch=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.waf;" vertex="1" parent="reg"><mxGeometry x="440" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="wafn" target="cfn"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def test_w17_build_rejects(self):
        # cloudfront が region 内 → error でビルド拒否
        spec = self.dr_spec("cf")
        for n in spec["nodes"]:
            if n["id"] == "cf":
                n["parent"] = "regA"
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "w17bad")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("W17", r.stdout + r.stderr)

    def test_w17_regional_waf_ok(self):
        # ALB にだけ関連付く WAF は region 内が正当 → W17 なし
        nodes = [{"id": "waf", "label": "WAF", "icon": "waf",
                  "parent": "vpc", "col": 1, "row": 1},
                 {"id": "alb", "label": "ALB", "icon": "alb",
                  "parent": "pub", "col": 2, "row": 1}]
        # vpc 内 WAF は W8 対象だが W17(error)ではないことを確認
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(
                nodes, [{"id": "e1", "src": "waf", "dst": "alb",
                         "kind": "main"}]), Path(td), "w17waf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W17", r.stdout,
                             "リージョナル WAF に W17 が誤発火した:\n" + r.stdout)

    def test_w17_validator_detects_and_dedupes(self):
        # region 内の cloudfront と cf 接続 WAF → W17(ERROR・rc1)。
        # 同一ノードを W8/W11 で重複報告しない。ALB 用 WAF は対象外
        r = self.run_validator_on(self.W17_XML)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("W17"), 2,
                         "cloudfront+WAF(CF) の 2 件にならない:\n" + r.stdout)
        self.assertNotIn("wafr", r.stdout, "リージョナル WAF に誤発火")
        self.assertNotIn("W11", r.stdout, "W17 と W11 が重複報告された")
        self.assertNotIn("W8", r.stdout, "W17 と W8 が重複報告された")

    # ---- W18: DB が public subnet 内 ----

    def test_w18_db_in_public_subnet(self):
        nodes = [{"id": "db", "label": "RDS", "icon": "rds",
                  "parent": "pub", "col": 1, "row": 1}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(nodes), Path(td), "w18bad")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("W18", r.stdout + r.stderr)
            # private subnet 配置は正当
            ok = [{"id": "db", "label": "RDS", "icon": "rds",
                   "parent": "priv", "col": 1, "row": 1}]
            r2 = build_spec(self.vpc_spec(ok), Path(td), "w18ok")
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertNotIn("W18", r2.stdout,
                             "private subnet の RDS に W18 が誤発火した")
            rv = self.run_validator_on_file(Path(td) / "w18ok.spec.out.drawio")
            self.assertNotIn("W18", rv.stdout, rv.stdout)

    W18_XML = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="vpc" value="VPC" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;container=1;verticalAlign=top;align=left;spacingLeft=30;fillColor=none;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="400" height="300" as="geometry"/></mxCell>
<mxCell id="pub" value="Public subnet" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;container=1;verticalAlign=top;align=left;spacingLeft=30;" vertex="1" parent="vpc"><mxGeometry x="40" y="40" width="200" height="220" as="geometry"/></mxCell>
<mxCell id="dbn" value="RDS" style="sketch=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.rds;" vertex="1" parent="pub"><mxGeometry x="40" y="60" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def test_w18_validator_detects(self):
        r = self.run_validator_on(self.W18_XML)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("W18", r.stdout)

    # ---- W19: 外部クライアント → DB 直結 ----

    def test_w19_user_to_db_edge(self):
        nodes = [{"id": "u", "label": "ユーザー", "icon": "users",
                  "col": 0, "row": 1},
                 {"id": "db", "label": "Aurora", "icon": "aurora",
                  "parent": "priv", "col": 2, "row": 1}]
        edges = [{"id": "e1", "src": "u", "dst": "db", "kind": "main"}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(nodes, edges), Path(td), "w19bad")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("W19", r.stdout + r.stderr)

    W19_XML = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="u" value="ユーザー" style="sketch=0;shape=mxgraph.aws4.users;" vertex="1" parent="1"><mxGeometry x="0" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="dbn" value="Aurora" style="sketch=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.aurora;" vertex="1" parent="1"><mxGeometry x="300" y="60" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="u" target="dbn"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def test_w19_validator_detects(self):
        r = self.run_validator_on(self.W19_XML)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("W19", r.stdout)

    # ---- W20: HA 表記 × AZ コンテナ数 ----

    def test_w20_ha_text_single_az(self):
        nodes = [{"id": "db", "label": "RDS (Multi-AZ)", "icon": "rds",
                  "parent": "priv", "col": 1, "row": 1}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(nodes), Path(td), "w20bad")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WARN: W20", r.stdout, "ビルド段 W20 が出ない")
            rv = self.run_validator_on_file(Path(td) / "w20bad.spec.out.drawio")
            self.assertIn("W20", rv.stdout, "バリデータ W20 が出ない")

    def test_w20_two_az_ok(self):
        conts = [{"id": "vpc", "label": "VPC", "type": "vpc"},
                 {"id": "az1", "label": "AZ-a", "type": "az", "parent": "vpc"},
                 {"id": "az2", "label": "AZ-c", "type": "az", "parent": "vpc"},
                 {"id": "s1", "label": "Private subnet",
                  "type": "private_subnet", "parent": "az1"},
                 {"id": "s2", "label": "Private subnet",
                  "type": "private_subnet", "parent": "az2"}]
        nodes = [{"id": "db", "label": "RDS (Multi-AZ)", "icon": "rds",
                  "parent": "s1", "col": 1, "row": 1},
                 {"id": "db2", "label": "RDS standby", "icon": "rds",
                  "parent": "s2", "col": 3, "row": 1}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(nodes, containers=conts),
                           Path(td), "w20ok")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W20", r.stdout,
                             "2AZ の図に W20 が誤発火した:\n" + r.stdout)
            rv = self.run_validator_on_file(Path(td) / "w20ok.spec.out.drawio")
            self.assertNotIn("W20", rv.stdout, rv.stdout)

    # ---- W21: private subnet → 外部への直行線 ----

    def test_w21_private_egress_without_nat(self):
        nodes = [{"id": "u", "label": "外部 SaaS 利用者", "icon": "users",
                  "col": 4, "row": 1},
                 {"id": "app", "label": "アプリ", "icon": "fargate",
                  "parent": "priv", "col": 1, "row": 1}]
        edges = [{"id": "e1", "src": "app", "dst": "u", "kind": "main"}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(nodes, edges), Path(td), "w21bad")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WARN: W21", r.stdout, "ビルド段 W21 が出ない")
            rv = self.run_validator_on_file(Path(td) / "w21bad.spec.out.drawio")
            self.assertIn("W21", rv.stdout, "バリデータ W21 が出ない")

    def test_w21_via_nat_ok(self):
        # NAT(public)経由の正しい形と、public subnet からの直行は対象外
        nodes = [{"id": "u", "label": "外部", "icon": "users",
                  "col": 4, "row": 0},
                 {"id": "app", "label": "アプリ", "icon": "fargate",
                  "parent": "priv", "col": 1, "row": 1},
                 {"id": "nat", "label": "NAT", "icon": "nat_gateway",
                  "parent": "pub", "col": 2, "row": 0}]
        edges = [{"id": "e1", "src": "app", "dst": "nat", "kind": "main"},
                 {"id": "e2", "src": "nat", "dst": "u", "kind": "main"}]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.vpc_spec(nodes, edges), Path(td), "w21ok")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("W21", r.stdout,
                             "NAT 経由の egress に W21 が誤発火した:\n" + r.stdout)
            rv = self.run_validator_on_file(Path(td) / "w21ok.spec.out.drawio")
            self.assertNotIn("W21", rv.stdout, rv.stdout)

    # ---- 同梱テンプレ・リファレンスの回帰 ----

    def test_multiregion_template_symmetric(self):
        # multiregion テンプレは修正済み(cf→ALB(DR) のオリジン切替)。
        # W16〜W21 のどれも出ずにビルドできる
        spec = ROOT / "templates" / "example-multiregion.spec.json"
        data = json.loads(spec.read_text())
        edges = data["diagrams"][0]["edges"]
        fo = [e for e in edges if e.get("kind") == "failover"]
        self.assertTrue(fo and all(e["src"] == "cf" for e in fo),
                        "failover 線が CloudFront 起点になっていない")
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / spec.name
            shutil.copy(spec, cp)
            r = run_build(cp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for code in ("W16", "W17", "W18", "W19", "W20", "W21"):
                self.assertNotIn(code, r.stdout,
                                 f"修正済みテンプレに {code} が出た:\n" + r.stdout)

    def test_reference_architectures_clean(self):
        # 検証済みリファレンススペック(正解パターン)では新検査が発火しない
        refs = sorted((ROOT / "references" / "reference-architectures")
                      .glob("*.spec.json"))
        self.assertGreaterEqual(len(refs), 5, "リファレンススペックが見つからない")
        with tempfile.TemporaryDirectory() as td:
            for spec in refs:
                with self.subTest(spec=spec.name):
                    cp = Path(td) / spec.name
                    shutil.copy(spec, cp)
                    r = run_build(cp)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    for code in ("W16", "W17", "W18", "W19", "W20", "W21"):
                        self.assertNotIn(
                            code, r.stdout,
                            f"{spec.name} に {code} が誤発火:\n" + r.stdout)


class TestAbsRoundTrip(unittest.TestCase):
    """--emit-abs の出力は、そのまま再入力できて入力ファイルを汚さない(R3)。"""

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            src = tmp / "t.spec.json"
            shutil.copy(TEMPLATES[0], src)
            r1 = run_build(src, "--emit-abs", "--no-validate", cwd=tmp)
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            abs_path = tmp / (src.stem + ".out.abs.json")
            self.assertTrue(abs_path.exists(), list(tmp.iterdir()))
            before = abs_path.read_text()
            r2 = run_build(abs_path, cwd=tmp)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertIn("0 error(s)", r2.stdout)
            self.assertEqual(abs_path.read_text(), before,
                             "abs.json がビルドで書き換えられた")


class TestSegCross(unittest.TestCase):
    def test_basic_cross(self):
        self.assertTrue(seg_cross((0, 0), (10, 10), (0, 10), (10, 0)))

    def test_no_cross(self):
        self.assertFalse(seg_cross((0, 0), (10, 0), (0, 5), (10, 5)))

    def test_shared_endpoint_excluded(self):
        self.assertFalse(seg_cross((0, 0), (10, 0), (10, 0), (10, 10)))

    def test_collinear_touch_excluded(self):
        self.assertFalse(seg_cross((0, 0), (10, 0), (5, 0), (15, 0)))

    def test_t_touch_counts(self):
        # 端点が他方の線分の内部に乗る T 字接触は従来から交差扱い(保守的)。
        # 高速版が旧 seg_intersect と同じ意味論であることの回帰テスト
        self.assertTrue(seg_cross((0, 0), (10, 0), (5, 0), (5, 10)))

    def test_far_apart_bbox(self):
        self.assertFalse(seg_cross((0, 0), (1, 1), (100, 100), (101, 101)))


class TestFanOutSlots(unittest.TestCase):
    """同一ノード同一辺に多数集まってもクラッシュしない(スロット枯渇 B2)。"""

    def hub_spec(self, hub_row: int) -> dict:
        nodes = [{"id": "hub", "label": "Hub", "icon": "ec2",
                  "col": 0, "row": hub_row}]
        edges = []
        for i in range(6):
            nodes.append({"id": f"n{i}", "label": f"N{i}", "icon": "s3",
                          "col": 2, "row": i})
            edges.append({"id": f"e{i}", "src": "hub", "dst": f"n{i}",
                          "kind": "main"})
        return {"name": "hub", "meta": {"purpose": "test"},
                "nodes": nodes, "edges": edges}

    def run_case(self, hub_row: int, label: str):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.hub_spec(hub_row), Path(td), f"hub{hub_row}")
            self.assertNotIn("Traceback", r.stdout + r.stderr, label)
            self.assertEqual(r.returncode, 0, label + ":" + r.stdout + r.stderr)

    def test_hub_with_direct(self):
        self.run_case(2, "直行便あり(above/below スロット)")

    def test_hub_no_direct(self):
        # ハブと同一行の相手がいない → directs なしの else 分岐で k=6
        self.run_case(10, "直行便なし(FRAC_SLOTS 超過)")


class TestValidateSpec(unittest.TestCase):
    def check_dies(self, spec, fragment):
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(spec)
        self.assertIn(fragment, str(cm.exception))

    def base(self):
        return {"nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0},
                          {"id": "b", "icon": "s3", "col": 1, "row": 0}],
                "containers": [], "edges": []}

    def test_ok(self):
        B.validate_spec(self.base())  # 例外なし

    def test_parent_1_is_root(self):
        s = self.base()
        s["nodes"][0]["parent"] = "1"
        B.validate_spec(s)  # 誤拒否しない

    def test_collects_multiple_errors(self):
        s = self.base()
        s["nodes"][0]["col"] = -1
        s["containers"] = [{"id": "c1", "type": "vpc"}]
        s["nodes"][1]["parent"] = "c1"
        s["edges"] = [{"id": "e1", "src": "c1", "dst": "c1"}]
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(s)
        msg = str(cm.exception)
        self.assertIn("2 件", msg)
        self.assertIn("非負", msg)
        self.assertIn("自己ループ", msg)

    def test_common_key_type_errors_are_friendly(self):
        """meta/legend/icon/parent の型間違いが generic TypeError に落ちない。"""
        s = self.base()
        s["meta"] = "3層の標準構成"          # dict のつもりで文字列
        self.check_dies(s, "meta は")
        s = self.base()
        s["legend"] = ["main"]              # dict の配列のつもりで文字列の配列
        self.check_dies(s, "legend の要素は")
        s = self.base()
        s["nodes"][0]["icon"] = 3           # 文字列のつもりで数値
        self.check_dies(s, "icon はアイコン名の文字列")
        s = self.base()
        s["nodes"][0]["parent"] = ["c1"]    # unhashable(TypeError の元)
        self.check_dies(s, "parent はコンテナ id の文字列")

    def test_duplicate_id(self):
        s = self.base()
        s["nodes"][1]["id"] = "a"
        self.check_dies(s, "重複")

    def test_reserved_id(self):
        s = self.base()
        s["nodes"][0]["id"] = "1"
        self.check_dies(s, "予約")

    def test_parent_cycle_shows_cycle(self):
        s = self.base()
        s["containers"] = [
            {"id": "c1", "type": "vpc", "parent": "c2"},
            {"id": "c2", "type": "vpc", "parent": "c1"}]
        self.check_dies(s, "c1 → c2 → c1")

    def test_bad_kind_color(self):
        s = self.base()
        s["kinds"] = {"x": {"base": "sub", "color": "red-ish"}}
        self.check_dies(s, "#RRGGBB")

    def test_label_at_validated(self):
        s = self.base()
        s["edges"] = [{"id": "e1", "src": "a", "dst": "b", "label_at": 42}]
        self.check_dies(s, "label_at は [数値, 数値]")

    def test_enum_fields_reject_unhashable(self):
        """shape/type/kind/base に list を書いても generic TypeError に落ちない。"""
        s = self.base()
        s["nodes"][0]["shape"] = ["io"]
        self.check_dies(s, "shape は文字列")
        s = self.base()
        s["containers"] = [{"id": "c1", "type": ["vpc"]}]
        self.check_dies(s, "type は文字列")
        s = self.base()
        s["edges"] = [{"id": "e1", "src": "a", "dst": "b", "kind": ["main"]}]
        self.check_dies(s, "kind は文字列")
        s = self.base()
        s["kinds"] = {"main": {"base": ["sub"]}}
        self.check_dies(s, "から選んでください")


class TestAbsAndPageGuards(unittest.TestCase):
    """abs 経路・page の入力ガード(沈黙不良の防止。R2 ファジング指摘の回帰)。"""

    def _abs_node(self, **over):
        n = {"id": "a", "icon": "ec2", "cx": 40, "cy": 40}
        n.update(over)
        return {"name": "t", "nodes": [n]}

    def test_abs_bad_w_rejected_even_without_validate(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._abs_node(w=float("nan")), Path(td),
                           "abs_nan", "--no-validate")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("w は正の数値", r.stdout + r.stderr)

    def test_abs_bad_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._abs_node(id='a"><x'), Path(td),
                           "abs_id", "--no-validate")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("id に使えない文字", r.stdout + r.stderr)

    def test_abs_internal_ids_still_allowed(self):
        """--emit-abs 出力の _meta 等(先頭アンダースコア)は弾かない。"""
        spec = {"name": "t", "nodes": [
            {"id": "_meta", "text": "目的: test", "x": 24, "y": 26,
             "w": 200, "h": 18},
            {"id": "a", "icon": "ec2", "cx": 140, "cy": 140}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "abs_meta")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_bad_page_rejected(self):
        spec = {"name": "t", "page": ['"', "z"],
                "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "badpage", "--no-validate")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("page は", r.stdout + r.stderr)

    def test_build_warns_reported_after_summary(self):
        """meta 欠落はサマリ集計外だが「注意:」行で再通知される。"""
        spec = {"name": "t",
                "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "nometa")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("meta 未指定", r.stdout)
            self.assertIn("注意:", r.stdout)

    def test_abs_field_types_are_friendly(self):
        """abs 経路でも rows/exit/points の型ミスが親切 ERROR になる(grid と対称)。"""
        cases = [
            ({"name": "t", "nodes": [{"id": "e1", "shape": "entity",
                                      "title": "T", "rows": 42,
                                      "cx": 100, "cy": 100}]},
             "rows は文字列の配列"),
            ({"name": "t",
              "nodes": [{"id": "a", "icon": "ec2", "cx": 40, "cy": 40},
                        {"id": "b", "icon": "s3", "cx": 240, "cy": 40}],
              "edges": [{"id": "e1", "src": "a", "dst": "b",
                         "exit": [0.5]}]},
             "exit は [fx, fy]"),
            ({"name": "t",
              "nodes": [{"id": "a", "icon": "ec2", "cx": 40, "cy": 40},
                        {"id": "b", "icon": "s3", "cx": 240, "cy": 40}],
              "edges": [{"id": "e1", "src": "a", "dst": "b",
                         "exit": [1, 0.5], "entry": [0, 0.5],
                         "points": [[1e309, 0]]}]},
             "points は"),
            ({"name": "t",  # null は値ベースのガードをすり抜けた前歴あり
              "nodes": [{"id": "a", "icon": "ec2", "cx": 40, "cy": 40},
                        {"id": "b", "icon": "s3", "cx": 240, "cy": 40}],
              "edges": [{"id": "e1", "src": "a", "dst": "b",
                         "exit": [1, 0.5], "entry": [0, 0.5],
                         "points": None}]},
             "points は"),
            ({"name": "t",  # exit の値域(grid と対称)
              "nodes": [{"id": "a", "icon": "ec2", "cx": 40, "cy": 40},
                        {"id": "b", "icon": "s3", "cx": 240, "cy": 40}],
              "edges": [{"id": "e1", "src": "a", "dst": "b",
                         "exit": [2, -0.5]}]},
             "0〜1"),
        ]
        with tempfile.TemporaryDirectory() as td:
            for i, (spec, frag) in enumerate(cases):
                with self.subTest(case=frag):
                    r = build_spec(spec, Path(td), f"absfield{i}",
                                   "--no-validate")
                    out = r.stdout + r.stderr
                    self.assertEqual(r.returncode, 2, out)
                    self.assertIn(frag, out)
                    self.assertNotIn("想定外のエラー", out)

    def test_explicit_null_parent_not_emitted(self):
        """parent: null が parent="None" の壊れた参照として沈黙生成されない。"""
        spec = {"name": "t", "meta": {"purpose": "t"},
                "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0,
                           "parent": None}]}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "nullparent")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = (tmp / "nullparent.spec.out.drawio").read_text(encoding="utf-8")
            self.assertNotIn('parent="None"', out)

    def test_emit_svg_nonstring_tab_name(self):
        """複数タブで name が非文字列でも --emit-svg が落ちない。"""
        spec = {"diagrams": [
            {"name": 42, "meta": {"purpose": "t"},
             "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0}]},
            {"name": "ok", "meta": {"purpose": "t"},
             "nodes": [{"id": "b", "icon": "s3", "col": 0, "row": 0}]}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "svgname", "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestEntityDiagram(unittest.TestCase):
    """ER/UML の entity 箱ノードと関係線 kind。"""

    def test_er_build(self):
        spec = {"name": "er", "meta": {"purpose": "test"},
                "legend": {"er_1n": "1対多", "uml_inherit": "継承"},
                "nodes": [
                    {"id": "a", "shape": "entity", "title": "users",
                     "rows": ["PK id", "name"], "col": 0, "row": 0},
                    {"id": "b", "shape": "entity", "title": "orders",
                     "rows": ["PK id", "FK user_id"], "col": 1, "row": 0},
                    {"id": "c", "shape": "entity", "title": "Base",
                     "rows2": ["+ run(): void"], "col": 0, "row": 1}],
                "edges": [
                    {"id": "e1", "src": "a", "dst": "b", "kind": "er_1n"},
                    {"id": "e2", "src": "c", "dst": "a", "kind": "uml_inherit"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "er")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout)
            out = Path(td) / "er.spec.out.drawio"
            xml = out.read_text(encoding="utf-8")
            self.assertIn("ERmany", xml)          # クロウズフット
            self.assertIn("endFill=0", xml)        # 継承の白抜き△
            self.assertIn("&lt;hr", xml)           # 区画線入りの箱

    def test_entity_requires_title(self):
        spec = {"nodes": [{"id": "a", "shape": "entity", "col": 0, "row": 0}]}
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(spec)
        self.assertIn("title", str(cm.exception))


class TestMultiCloud(unittest.TestCase):
    """Azure/GCP アイコンの解決と W8(PaaS を VNet に入れない)。"""

    def test_provider_icons_resolve(self):
        from _common import load_icons, resolve_icon, icon_style
        ic = load_icons()
        az = icon_style(resolve_icon(ic, "azure:virtual_machine"))
        self.assertIn("img/lib/azure2/compute/Virtual_Machine.svg", az)
        g = icon_style(resolve_icon(ic, "gcp:bigquery"))
        self.assertIn("mxgraph.gcp3.bigquery", g)

    def test_azure_w8(self):
        spec = {"name": "az", "meta": {"purpose": "test"},
                "containers": [
                    {"id": "sub", "label": "Sub", "type": "subscription"},
                    {"id": "vn", "label": "VNet", "type": "vnet", "parent": "sub"},
                    {"id": "sn", "label": "Subnet", "type": "az_subnet",
                     "parent": "vn"}],
                "nodes": [
                    {"id": "vm", "label": "VM", "icon": "azure:virtual_machine",
                     "parent": "sn", "col": 0, "row": 0},
                    {"id": "st", "label": "Storage",
                     "icon": "azure:storage_accounts", "parent": "sn",
                     "col": 1, "row": 0}],
                "edges": [{"id": "e1", "src": "vm", "dst": "st", "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "az")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("W8", r.stdout, "Storage-in-Subnet が W8 で警告されない")


class TestCrossingBudget(unittest.TestCase):
    """交差目安のハブ次数補正(_common.crossing_budget と次数の数え方)。"""

    def test_no_hub(self):
        from _common import crossing_budget
        # 端点集約済み・ハブなし(dense 相当): 補正 0
        self.assertEqual(crossing_budget(42, [4, 4, 3]), (4, 4, 0, 0))

    def test_single_hub(self):
        from _common import crossing_budget
        # 次数 8 のハブ 1 つ: 補正 = 8-4(ペア加算なし)
        self.assertEqual(crossing_budget(30, [8, 4, 2]), (7, 3, 4, 0))

    def test_two_hubs_agentcore_like(self):
        from _common import crossing_budget
        # 実案件相当(44n・次数 8+6): 4 + (4+2) + ハブペア 1 = 11
        self.assertEqual(crossing_budget(44, [8, 6, 3]), (11, 4, 7, 0))

    def test_density_correction(self):
        from _common import crossing_budget
        # 完全表現の密グラフ(E > 1.3N): 超過分 × 0.7 が密度補正
        # 50n/75e: 超過 10 → +7。1.3N 以下なら 0
        self.assertEqual(crossing_budget(50, [], 75), (12, 5, 0, 7))
        self.assertEqual(crossing_budget(50, [], 60), (5, 5, 0, 0))
        self.assertEqual(crossing_budget(50, []), (5, 5, 0, 0))

    def test_icon_degrees_excludes_containers_and_boxes(self):
        lay = B.Layout(C=3, R=1,
                       cell={"a": (0, 0), "b": (1, 0), "ent": (2, 0)},
                       cmap={}, cext={}, occ=set())
        lay.box_nodes.add("ent")
        edges = [{"src": "a", "dst": "b"}, {"src": "a", "dst": "ent"},
                 {"src": "a", "dst": "vpc1"}, {"src": "b", "dst": "a"}]
        self.assertEqual(B.icon_degrees(lay, edges), [4, 2])


class TestValidatorW567(unittest.TestCase):
    """W5(題字貫通)/ W6(矢じり視認性)/ W7(祖先外走行)の検出力。"""

    HEAD = ("""<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>""")
    TAIL = "</root></mxGraphModel></diagram></mxfile>"
    ICON = ("sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor=#ED7100;"
            "strokeColor=#ffffff;verticalLabelPosition=bottom;verticalAlign=top;"
            "align=center;html=1;shape=mxgraph.aws4.resourceIcon;"
            "resIcon=mxgraph.aws4.ec2;")

    def _vertex(self, vid, x, y, label="N", style=None, parent="1", w=78, h=78):
        return (f'<mxCell id="{vid}" value="{label}" style="{style or self.ICON}" '
                f'vertex="1" parent="{parent}">'
                f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
                f'as="geometry"/></mxCell>')

    def _edge(self, eid, src, dst, style, wps=()):
        pts = "".join(f'<mxPoint x="{x}" y="{y}" />' for x, y in wps)
        arr = f'<Array as="points">{pts}</Array>' if wps else ""
        return (f'<mxCell id="{eid}" style="{style}" edge="1" parent="1" '
                f'source="{src}" target="{dst}">'
                f'<mxGeometry relative="1" as="geometry">{arr}</mxGeometry>'
                f'</mxCell>')

    def _run(self, xml):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "w.drawio"
            f.write_text(xml, encoding="utf-8")
            r = subprocess.run([sys.executable, str(VALIDATE), str(f)],
                               capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr

    def test_w5_title_pierce(self):
        cont = ('<mxCell id="c1" value="Private subnet (App)" '
                'style="fillColor=#E6F6F7;strokeColor=#00A4A6;verticalAlign=top;'
                'align=left;spacingLeft=30;container=1;" vertex="1" parent="1">'
                '<mxGeometry x="100" y="100" width="400" height="300" '
                'as="geometry"/></mxCell>')
        xml = (self.HEAD + cont
               + self._vertex("a", 60, 60, parent="c1")
               + self._vertex("b", 40, 500)
               + self._edge("e1", "b", "a",
                            "exitX=0.5;exitY=0;entryX=0.5;entryY=0;html=1;",
                            wps=[(199, 90), (199, 130)])
               + self.TAIL)
        self.assertIn("W5", self._run(xml))

    def test_w6_close_endpoints(self):
        xml = (self.HEAD
               + self._vertex("a", 400, 100)
               + self._vertex("b", 100, 60)
               + self._vertex("c", 100, 160)
               + self._edge("e1", "b", "a",
                            "exitX=1;exitY=0.5;entryX=0;entryY=0.45;html=1;")
               + self._edge("e2", "c", "a",
                            "exitX=1;exitY=0.5;entryX=0;entryY=0.53;html=1;")
               + self.TAIL)
        self.assertIn("W6", self._run(xml))

    def test_w7_outside_ancestor(self):
        cont = ('<mxCell id="c1" value="AWS Cloud" '
                'style="grIcon=mxgraph.aws4.group_aws_cloud_alt;container=1;'
                'verticalAlign=top;align=left;" vertex="1" parent="1">'
                '<mxGeometry x="50" y="50" width="600" height="400" '
                'as="geometry"/></mxCell>')
        xml = (self.HEAD + cont
               + self._vertex("a", 50, 100, parent="c1")
               + self._vertex("b", 400, 100, parent="c1")
               + self._edge("e1", "a", "b",
                            "exitX=0.5;exitY=0;entryX=0.5;entryY=0;html=1;",
                            wps=[(139, 8), (489, 8)])
               + self.TAIL)
        self.assertIn("W7", self._run(xml))


class TestValidatorErrorDetectors(unittest.TestCase):
    """コア ERROR 検出器(E1/E2/E3/E4/E8)が壊れた図で発火する(真陽性の回帰)。

    Golden テンプレートの「0 error(s)」assert は検出器の無言故障(リファクタで
    発火しなくなる回帰)を捉えられないため、破壊入力での発火をここで固定する。
    """

    HEAD = TestValidatorW567.HEAD
    TAIL = TestValidatorW567.TAIL
    ICON = TestValidatorW567.ICON
    VPC = ('<mxCell id="c" value="VPC" style="grIcon=mxgraph.aws4.group_vpc2;'
           'container=1;verticalAlign=top;align=left;spacingLeft=30;'
           'fillColor=none;" vertex="1" parent="1">'
           '<mxGeometry x="0" y="0" width="{w}" height="{h}" as="geometry"/>'
           '</mxCell>')

    def _vertex(self, vid, x, y, parent="1"):
        return (f'<mxCell id="{vid}" value="{vid.upper()}" style="{self.ICON}" '
                f'vertex="1" parent="{parent}">'
                f'<mxGeometry x="{x}" y="{y}" width="78" height="78" '
                f'as="geometry"/></mxCell>')

    def _edge(self, eid, src, dst):
        return (f'<mxCell id="{eid}" style="exitX=1;exitY=0.5;entryX=0;'
                f'entryY=0.5;html=1;" edge="1" parent="1" '
                f'source="{src}" target="{dst}">'
                f'<mxGeometry relative="1" as="geometry"/></mxCell>')

    def _run(self, xml):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "e.drawio"
            f.write_text(xml, encoding="utf-8")
            r = subprocess.run([sys.executable, str(VALIDATE), str(f)],
                               capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr

    def test_e1_icon_overlap(self):
        xml = (self.HEAD + self._vertex("a", 0, 0) + self._vertex("b", 40, 0)
               + self.TAIL)
        self.assertIn("E1", self._run(xml))

    def test_e2_container_overflow(self):
        xml = (self.HEAD + self.VPC.format(w=300, h=200)
               + self._vertex("a", 350, 40, parent="c") + self.TAIL)
        self.assertIn("E2", self._run(xml))

    def test_e3_edge_pierces_icon(self):
        xml = (self.HEAD + self._vertex("a", 0, 0) + self._vertex("mid", 200, 0)
               + self._vertex("b", 400, 0) + self._edge("e1", "a", "b")
               + self.TAIL)
        self.assertIn("E3", self._run(xml))

    def test_e4_diagonal_segment(self):
        xml = (self.HEAD + self._vertex("a", 0, 0) + self._vertex("b", 300, 300)
               + self._edge("e1", "a", "b") + self.TAIL)
        self.assertIn("E4", self._run(xml))

    def test_e8_straddles_container(self):
        xml = (self.HEAD + self.VPC.format(w=300, h=300)
               + self._vertex("a", 260, 120) + self.TAIL)
        self.assertIn("E8", self._run(xml))


class TestGlobalServicePlacement(unittest.TestCase):
    """W11: グローバルサービスのリージョン内配置を検出し、正しい配置では沈黙。"""

    HEAD = TestValidatorW567.HEAD
    TAIL = TestValidatorW567.TAIL
    REGION = ('<mxCell id="rg" value="Region" style="grIcon=mxgraph.aws4.'
              'group_region;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;'
              'align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;container=1;" '
              'vertex="1" parent="1">'
              '<mxGeometry x="0" y="0" width="600" height="400" as="geometry"/>'
              '</mxCell>')

    def _icon(self, vid, res, x, y, parent="1"):
        style = ("sketch=0;html=1;shape=mxgraph.aws4.resourceIcon;"
                 f"resIcon=mxgraph.aws4.{res};")
        return (f'<mxCell id="{vid}" value="{vid}" style="{style}" vertex="1" '
                f'parent="{parent}"><mxGeometry x="{x}" y="{y}" width="78" '
                f'height="78" as="geometry"/></mxCell>')

    def _run(self, xml):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "g.drawio"
            f.write_text(xml, encoding="utf-8")
            r = subprocess.run([sys.executable, str(VALIDATE), str(f)],
                               capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr

    def test_w11_global_inside_region(self):
        # cloudfront/route_53 は SEM-3 以降 W17(ERROR)へ集約(W11 と重複
        # させない)。W11 は W17 対象外のグローバルサービスに残る
        xml = (self.HEAD + self.REGION
               + self._icon("cf", "cloudfront", 120, 120, parent="rg")
               + self._icon("ga", "global_accelerator", 320, 120, parent="rg")
               + self.TAIL)
        out = self._run(xml)
        self.assertIn("W17", out, "region 内 cloudfront が W17 にならない")
        self.assertIn("'ga'", out)
        self.assertIn("W11", out, "W17 対象外の GA が W11 で警告されない")

    def test_w11_silent_when_outside_region(self):
        xml = (self.HEAD + self.REGION
               + self._icon("cf", "cloudfront", 120, 520) + self.TAIL)
        self.assertNotIn("W11", self._run(xml))

    def test_w11_silent_for_regional_service(self):
        xml = (self.HEAD + self.REGION
               + self._icon("web", "ec2", 120, 120, parent="rg") + self.TAIL)
        self.assertNotIn("W11", self._run(xml))

    def _hug_edge(self, y1, y2):
        """(700,y1)→(60,y1) を経て左下へ折れる 2 ノード+手動 waypoint エッジ。"""
        return (self._icon("a", "ec2", 700, y1 - 39)
                + self._icon("b", "s3", 20, y2)
                + f'<mxCell id="e1" style="exitX=0;exitY=0.5;entryX=0.5;'
                  f'entryY=0;html=1;" edge="1" parent="1" source="a" target="b">'
                  f'<mxGeometry relative="1" as="geometry">'
                  f'<Array as="points"><mxPoint x="60" y="{y1}" /></Array>'
                  f'</mxGeometry></mxCell>')

    def test_w13_edge_hugging_border(self):
        """枠線の 6px 隣を長距離並走するエッジを検出する。"""
        xml = (self.HEAD + self.REGION
               + self._hug_edge(406, 500) + self.TAIL)  # region 下辺 y=400 の 6px 下
        self.assertIn("W13", self._run(xml))

    def test_w13_silent_when_separated(self):
        """枠線から 22px 離れた並走は正常(回廊の標準距離)。"""
        xml = (self.HEAD + self.REGION
               + self._hug_edge(422, 520) + self.TAIL)
        self.assertNotIn("W13", self._run(xml))


class TestReferenceArchitecture(unittest.TestCase):
    """step/steps(リファレンスアーキテクチャ図)のバッジ・説明パネル・整合検査。"""

    def base(self, **over):
        s = {"name": "t", "meta": {"purpose": "test"},
             "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0},
                       {"id": "b", "icon": "s3", "col": 1, "row": 0}],
             "edges": [{"id": "e1", "src": "a", "dst": "b", "step": 1}],
             "steps": ["A から B へ送る"]}
        s.update(over)
        return s

    def test_badge_and_panel_emitted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(self.base(), tmp, "ref")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 0, out)
            self.assertNotIn("step 不整合", out)
            self.assertNotIn("W12", out)
            xml = (tmp / "ref.spec.out.drawio").read_text(encoding="utf-8")
            self.assertEqual(xml.count("awsdiagBadge"), 1, "バッジが 1 個描かれる")
            self.assertIn('id="_steps"', xml)
            self.assertIn("A から B へ送る", xml)

    def test_badge_style_default_and_light(self):
        """badge_style 既定(dark)=濃紺+白数字、light=白地+黒太字+濃紺枠。
        SVG プレビューのバッジ配色も XML に追随する。"""
        for over, fill, font, stroke in (
                ({}, "#232F3E", "#FFFFFF", "#FFFFFF"),
                ({"badge_style": "dark"}, "#232F3E", "#FFFFFF", "#FFFFFF"),
                ({"badge_style": "light"}, "#FFFFFF", "#000000", "#232F3E")):
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                r = build_spec(self.base(**over), tmp, "bs", "--emit-svg")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                xml = (tmp / "bs.spec.out.drawio").read_text(encoding="utf-8")
                m = re.search(r'style="([^"]*awsdiagBadge[^"]*)"', xml)
                self.assertIsNotNone(m, f"バッジセルがない({over})")
                st = m.group(1)
                for part in (f"fillColor={fill}", f"fontColor={font}",
                             f"strokeColor={stroke}", "fontFamily=Arial"):
                    self.assertIn(part, st, f"{over} のバッジ style")
                svg = (tmp / "bs.spec.out.svg").read_text(encoding="utf-8")
                self.assertIn(f'<circle', svg)
                self.assertIn(f'fill="{fill}" stroke="{stroke}"', svg,
                              f"{over} の SVG バッジ配色")

    def test_badge_style_invalid_rejected(self):
        """badge_style の不正値は E(rc 2)で拒否される(enum 検証)。"""
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.base(badge_style="blue"), Path(td), "bsx")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 2, out)
            self.assertIn("badge_style", out)
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(self.base(badge_style="navy"))
        self.assertIn("badge_style", str(cm.exception))

    def test_badge_without_steps_warns(self):
        s = self.base()
        del s["steps"]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(s, Path(td), "ref2")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 0, out)
            self.assertIn("step 不整合", out)  # ビルド段 WARN+注意行

    def test_gap_warns(self):
        s = self.base()
        s["nodes"].append({"id": "c", "icon": "lambda", "col": 2, "row": 0})
        s["edges"].append({"id": "e2", "src": "b", "dst": "c", "step": 3})
        s["steps"] = ["1", "2", "3"]
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(s, Path(td), "ref3")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 0, out)
            self.assertIn("欠番", out)  # ビルド WARN と W12 の双方が拾う

    def test_step_spec_validation(self):
        s = self.base()
        s["edges"][0]["step"] = 0
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(s)
        self.assertIn("1〜99 の整数", str(cm.exception))
        s = self.base()
        s["edges"][0]["step"] = 10 ** 9   # 巨大値は range 爆発の前に拒否
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(s)
        self.assertIn("1〜99 の整数", str(cm.exception))
        s = self.base()
        s["nodes"][0]["step"] = 1  # edge の step 1 と重複
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(s)
        self.assertIn("重複", str(cm.exception))
        s = self.base()
        s["steps"] = "説明"
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(s)
        self.assertIn("steps は説明文字列の配列", str(cm.exception))

    def test_manual_edge_step_warns(self):
        """手動配線エッジの step は無音で消えず、親切 WARN が出る。"""
        s = self.base()
        s["edges"][0].update({"exit": [1, 0.5], "entry": [0, 0.5],
                              "points": []})
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(s, Path(td), "manstep")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 0, out)
            self.assertIn("自動配置できません", out)

    def test_badge_separated_from_own_label(self):
        """短い隣接エッジで label+step を併用してもバッジがラベルに埋没しない。"""
        s = self.base()
        s["edges"][0]["label"] = "最新状態"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(s, tmp, "sep", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            absspec = json.loads(
                (tmp / "sep.spec.out.abs.json").read_text(encoding="utf-8"))
            d = absspec["diagrams"][0]
            badge = next(n for n in d["nodes"] if n.get("badge"))
            bx, by = badge["x"] + 11, badge["y"] + 11
            lx, ly = next(e for e in d["edges"]
                          if e.get("label"))["label_at"]
            self.assertGreaterEqual(math.hypot(bx - lx, by - ly), 14,
                                    "バッジ中心とラベル中心が近すぎる")

    def test_title_node_for_reference_diagram(self):
        """steps 付きの図では name が左上タイトルとして描画される。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(self.base(), tmp, "ttl")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (tmp / "ttl.spec.out.drawio").read_text(encoding="utf-8")
            self.assertIn('id="_title"', xml)
            self.assertIn("fontSize=20", xml)

    BADGE_CELL = ('<mxCell id="sb{i}" value="{v}" style="ellipse;'
                  'awsdiagBadge=1;" vertex="1" parent="1">'
                  '<mxGeometry x="{x}" y="10" width="22" height="22" '
                  'as="geometry"/></mxCell>')

    def _run_validator_xml(self, cells):
        import subprocess
        xml = TestValidatorW567.HEAD + cells + TestValidatorW567.TAIL
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "b.drawio"
            f.write_text(xml, encoding="utf-8")
            r = subprocess.run([sys.executable, str(VALIDATE), str(f)],
                               capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr

    def test_w12_direct_duplicate_and_missing_panel(self):
        """バリデータ単体で W12(重複・パネルなし)が発火する。"""
        cells = (self.BADGE_CELL.format(i=1, v=1, x=10)
                 + self.BADGE_CELL.format(i=2, v=1, x=100))
        out = self._run_validator_xml(cells)
        self.assertIn("W12", out)
        self.assertIn("重複", out)
        self.assertIn("説明パネル", out)

    def test_w12_huge_badge_does_not_hang(self):
        """手編集で巨大な番号が入っても range 爆発せず即座に W12 で返る。"""
        cells = self.BADGE_CELL.format(i=1, v=999999999, x=10)
        out = self._run_validator_xml(cells)  # timeout=30 がハングの回帰網
        self.assertIn("W12", out)
        self.assertIn("大きすぎます", out)


class TestFontFamilyArial(unittest.TestCase):
    """全ラベルのフォントは Arial 明示(公式デッキ準拠+描画一貫性)。"""

    def test_style_constants_include_arial(self):
        from _common import (SERVICE_STYLE, RESOURCE_STYLE, AZURE_STYLE,
                             GCP_STYLE)
        consts = {"TEXT": B.TEXT, "GRP": B.GRP, "PLAIN": B.PLAIN,
                  "E_BASE": B.E_BASE, "ENTITY_STYLE": B.ENTITY_STYLE,
                  "SERVICE_STYLE": SERVICE_STYLE,
                  "RESOURCE_STYLE": RESOURCE_STYLE,
                  "AZURE_STYLE": AZURE_STYLE, "GCP_STYLE": GCP_STYLE}
        consts.update({f"BADGE_STYLES[{k}]": v
                       for k, v in B.BADGE_STYLES.items()})
        consts.update({f"FLOW_STYLES[{k}]": v
                       for k, v in B.FLOW_STYLES.items()})
        consts.update({f"CONTAINER_STYLES[{k}]": v
                       for k, v in B.CONTAINER_STYLES.items()})
        consts.update({f"EDGE_STYLES[{k}]": v
                       for k, v in B.EDGE_STYLES.items()})
        for name, s in consts.items():
            self.assertIn("fontFamily=Arial", s, name)

    def test_edge_label_stays_11pt(self):
        """エッジラベル 11pt は意図的な差(根拠: references/layout-rules.md)。"""
        self.assertIn("fontSize=11", B.E_BASE)


class TestSelfLoop(unittest.TestCase):
    """ER 自己参照(社員→上司)がコの字ループで描ける。"""

    def test_entity_self_reference(self):
        spec = {"name": "sl", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "emp", "shape": "entity", "title": "employees",
                     "rows": ["PK id", "FK manager_id"], "col": 0, "row": 0},
                    {"id": "dep", "shape": "entity", "title": "departments",
                     "rows": ["PK id"], "col": 2, "row": 0}],
                "edges": [
                    {"id": "r1", "src": "emp", "dst": "emp", "kind": "er_1n",
                     "label": "上司"},
                    {"id": "r2", "src": "dep", "dst": "emp", "kind": "er_1n"}]}
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "sl.spec.json"
            cp.write_text(json.dumps(spec, ensure_ascii=False),
                          encoding="utf-8")
            r = run_build(cp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s)", r.stdout)
            xml = (Path(td) / "sl.spec.out.drawio").read_text(encoding="utf-8")
        self.assertRegex(xml, r'<mxCell id="r1"[^>]*source="emp" target="emp"')


DIAMOND_VERTS = {(0.5, 0.0): "T", (0.5, 1.0): "B",
                 (0.0, 0.5): "L", (1.0, 0.5): "R"}


def diamond_endpoints(xml: str) -> list[dict]:
    """XML から decision(rhombus)端点の実測を集める(R7-15/16 検査用)。

    返り値: {"edge", "kind"(in/out), "term", "frac"(fx,fy),
    "vertex"(T/B/L/R/None), "src_above"} のリスト。src_above は
    「src の中心 y が対象ひし形の上端より上」(バリデータ W15 と同規約)。
    """
    import xml.etree.ElementTree as ET_
    out: list[dict] = []
    root = ET_.fromstring(xml)
    for diag in root.iter("diagram"):
        cells, geo = {}, {}
        for c in diag.iter("mxCell"):
            cells[c.get("id")] = c
            g = c.find("mxGeometry")
            if g is not None and c.get("vertex") == "1":
                geo[c.get("id")] = (float(g.get("x", 0)), float(g.get("y", 0)),
                                    float(g.get("width", 0)),
                                    float(g.get("height", 0)))

        def absbox(cid):
            x, y, w, h = geo[cid]
            p = cells[cid].get("parent")
            while p in geo:
                x, y = x + geo[p][0], y + geo[p][1]
                p = cells[p].get("parent")
            return x, y, w, h

        diamonds = {cid for cid, c in cells.items()
                    if c.get("vertex") == "1"
                    and "rhombus" in (c.get("style") or "")}
        for c in diag.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            style = {k: v for k, _, v in
                     (p.partition("=") for p in (c.get("style") or "").split(";"))}
            src, dst = c.get("source"), c.get("target")
            for term, kx, ky in ((src, "exitX", "exitY"),
                                 (dst, "entryX", "entryY")):
                if term not in diamonds or kx not in style:
                    continue
                frac = (float(style[kx]), float(style[ky]))
                other = dst if term == src else src
                above = None
                if term in geo and other in geo:
                    _, ty, _, _th = absbox(term)
                    ox_, oy_, _ow, oh_ = absbox(other)
                    above = oy_ + oh_ / 2 < ty
                out.append({"edge": c.get("id"),
                            "kind": "out" if term == src else "in",
                            "term": term, "frac": frac,
                            "vertex": DIAMOND_VERTS.get(frac),
                            "src_above": above})
    return out


class TestDiamondVertex(unittest.TestCase):
    """decision(ひし形)の端点は頂点(4 頂点のいずれか)に固定される。"""

    def test_endpoints_on_vertices(self):
        import re as re_
        spec = {"name": "dv", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "s", "shape": "terminator", "label": "開始",
                     "col": 1, "row": 0},
                    {"id": "d", "shape": "decision", "label": "OK?",
                     "col": 1, "row": 1},
                    {"id": "a", "shape": "process", "label": "処理A",
                     "col": 1, "row": 2},
                    {"id": "b", "shape": "process", "label": "処理B",
                     "col": 2, "row": 1},
                    {"id": "c", "shape": "process", "label": "戻り",
                     "col": 0, "row": 2}],
                "edges": [
                    {"id": "e1", "src": "s", "dst": "d", "kind": "main"},
                    {"id": "e2", "src": "d", "dst": "a", "kind": "main",
                     "label": "はい"},
                    {"id": "e3", "src": "d", "dst": "b", "kind": "main",
                     "label": "いいえ"},
                    {"id": "e4", "src": "c", "dst": "d", "kind": "sub",
                     "label": "再試行"}]}
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "dv.spec.json"
            cp.write_text(json.dumps(spec, ensure_ascii=False),
                          encoding="utf-8")
            r = run_build(cp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (Path(td) / "dv.spec.out.drawio").read_text(encoding="utf-8")
        # 旧版の正規表現は raw 文字列内の \\d が「バックスラッシュ+d」に
        # なる書式バグで 1 件もマッチせず空回りしていた(R7 バッチA2 で修正)
        ends = diamond_endpoints(xml)
        self.assertGreaterEqual(len(ends), 4, "ひし形端点が検出できない")
        for em in re_.finditer(r'<mxCell id="e\d"[^>]*style="([^"]*)"[^>]*'
                               r'source="(\w+)" target="(\w+)"', xml):
            st = em.group(1)
            # ひし形端点は perimeter 射影付き(bbox 固定点でも輪郭に載る)
            if em.group(2) == "d":
                self.assertIn("exitPerimeter=1", st, em.group(0)[:100])
            if em.group(3) == "d":
                self.assertIn("entryPerimeter=1", st, em.group(0)[:100])
        for it in ends:
            self.assertIsNotNone(
                it["vertex"],
                f"{it['edge']} の端点 {it['frac']} が頂点でない")


class TestDecisionVertexRules(unittest.TestCase):
    """R7-15/R7-16: decision の頂点規約(ユーザー実QA第7R 直接指摘)。

    修正前実測(フロー図3枚の再現ビルド):
      - 01-approval: apply→mgr_check が左頂点(上方 src なのに横入り)、
        amount→acc_check の entry が (0,0.35) = 頂点ですらない斜辺上、
        exit 側にも 0.35/0.65(_fan_slots の FRAC_SLOTS[2])と
        0.715(step=0.215)、fan 無効化でも 0.5929(separate_terminals
        の 13px スライド)
      - 03-order-fulfillment: authorize→pay_check が右頂点
    規約: 上方 src の流入 = 上頂点(1 本のみ・main 優先、残りは側頂点)/
    同行 src = 側頂点 / 下方 src(戻り)= 上頂点以外。流入が上頂点を取る
    ひし形では流出は上頂点を使わない。全端点は常に 4 頂点のいずれか。
    """

    # 01-approval と同構造(ラベル・lane・pin 込み — 修正前に (0,0.35) と
    # 左頂点入りを再現した実測条件そのもの)
    APPROVAL = {
        "name": "flow", "meta": {"purpose": "t"},
        "legend": {"main": "通常", "sub": "例外"},
        "containers": [
            {"id": "lane_emp", "label": "申請者", "type": "lane"},
            {"id": "lane_mgr", "label": "上長", "type": "lane"},
            {"id": "lane_acc", "label": "経理", "type": "lane"}],
        "nodes": [
            {"id": "start", "shape": "terminator", "label": "開始",
             "parent": "lane_emp", "col": 0, "row": 0, "pin": True},
            {"id": "apply", "shape": "io", "label": "経費を申請\n(領収書添付)",
             "parent": "lane_emp", "col": 0, "row": 1, "pin": True},
            {"id": "fix", "shape": "process", "label": "申請を修正",
             "parent": "lane_emp", "col": 1, "row": 1, "pin": True},
            {"id": "mgr_check", "shape": "decision", "label": "上長が\n承認?",
             "parent": "lane_mgr", "col": 2, "row": 2, "pin": True},
            {"id": "amount", "shape": "decision", "label": "金額は\n5万円未満?",
             "parent": "lane_mgr", "col": 2, "row": 3, "pin": True},
            {"id": "rejected", "shape": "terminator", "label": "却下",
             "parent": "lane_mgr", "col": 3, "row": 6, "pin": True},
            {"id": "acc_check", "shape": "decision", "label": "経理が\n承認?",
             "parent": "lane_acc", "col": 4, "row": 4, "pin": True},
            {"id": "approved", "shape": "terminator", "label": "承認済み",
             "parent": "lane_acc", "col": 4, "row": 6, "pin": True}],
        "edges": [
            {"id": "f1", "src": "start", "dst": "apply", "kind": "main"},
            {"id": "f2", "src": "apply", "dst": "mgr_check", "kind": "main",
             "label": "提出"},
            {"id": "f3", "src": "mgr_check", "dst": "amount", "kind": "main",
             "label": "承認"},
            {"id": "f4", "src": "mgr_check", "dst": "fix", "kind": "sub",
             "label": "差し戻し"},
            {"id": "f5", "src": "mgr_check", "dst": "rejected", "kind": "sub",
             "label": "却下"},
            {"id": "f6", "src": "amount", "dst": "approved", "kind": "main",
             "label": "5万円未満"},
            {"id": "f7", "src": "amount", "dst": "acc_check", "kind": "main",
             "label": "5万円以上"},
            {"id": "f8", "src": "acc_check", "dst": "approved", "kind": "main",
             "label": "承認"},
            {"id": "f9", "src": "acc_check", "dst": "rejected", "kind": "sub",
             "label": "却下"},
            {"id": "f10", "src": "acc_check", "dst": "fix", "kind": "sub",
             "label": "差し戻し"},
            {"id": "f11", "src": "fix", "dst": "apply", "kind": "main",
             "label": "再提出"}]}

    def _build(self, spec, name):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), name)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s)", r.stdout)
            xml = (Path(td) / f"{name}.spec.out.drawio").read_text(
                encoding="utf-8")
        return r, xml

    def test_r716_all_endpoints_on_vertices(self):
        # fail-before: (0,0.35)・(1,0.35)/(1,0.65)・(0.715,1) を検出していた
        r, xml = self._build(self.APPROVAL, "ap")
        ends = diamond_endpoints(xml)
        self.assertGreaterEqual(len(ends), 11)
        bad = [it for it in ends if it["vertex"] is None]
        self.assertEqual(bad, [], f"ひし形端点が頂点以外: {bad}")

    def test_r715_above_inflow_enters_top(self):
        # fail-before: f2 が左頂点 (0,0.5)、f7 が (0,0.35) だった
        r, xml = self._build(self.APPROVAL, "ap2")
        self.assertNotIn("W15", r.stdout)
        ins = {it["edge"]: it for it in diamond_endpoints(xml)
               if it["kind"] == "in"}
        for eid in ("f2", "f3", "f7"):   # 上方 src の流入は全て上頂点
            self.assertTrue(ins[eid]["src_above"], f"{eid}: 前提(上方 src)")
            self.assertEqual(ins[eid]["vertex"], "T",
                             f"{eid} の流入が上頂点でない: {ins[eid]}")

    def test_r715_same_row_inflow_enters_side(self):
        # 02-error-retry の fetch_ok→retry_chk(同行横入り)相当
        spec = {"name": "sr", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "a", "shape": "process", "label": "取得",
                     "col": 0, "row": 0},
                    {"id": "d", "shape": "decision", "label": "OK?",
                     "col": 1, "row": 0},
                    {"id": "b", "shape": "process", "label": "次へ",
                     "col": 1, "row": 1}],
                "edges": [
                    {"id": "e1", "src": "a", "dst": "d", "kind": "main"},
                    {"id": "e2", "src": "d", "dst": "b", "kind": "main",
                     "label": "はい"}]}
        _r, xml = self._build(spec, "sr")
        ins = [it for it in diamond_endpoints(xml) if it["kind"] == "in"]
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0]["vertex"], "L",
                         f"同行 src は src 側の側頂点に入る: {ins[0]}")

    def test_r715_multi_above_main_wins_top(self):
        # 上方流入 2 本: 上頂点は 1 本 — 整列している sub より main が優先
        spec = {"name": "ma", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "m", "shape": "process", "label": "主処理",
                     "col": 0, "row": 0},
                    {"id": "s", "shape": "process", "label": "再試行",
                     "col": 1, "row": 0},
                    {"id": "d", "shape": "decision", "label": "OK?",
                     "col": 1, "row": 1},
                    {"id": "b", "shape": "process", "label": "次へ",
                     "col": 1, "row": 2}],
                "edges": [
                    {"id": "e1", "src": "m", "dst": "d", "kind": "main"},
                    {"id": "e2", "src": "s", "dst": "d", "kind": "sub"},
                    {"id": "e3", "src": "d", "dst": "b", "kind": "main",
                     "label": "はい"}]}
        _r, xml = self._build(spec, "ma")
        ins = {it["edge"]: it for it in diamond_endpoints(xml)
               if it["kind"] == "in"}
        self.assertEqual(ins["e1"]["vertex"], "T",
                         f"main 流入が上頂点を取れていない: {ins}")
        self.assertIn(ins["e2"]["vertex"], ("L", "R"),
                      f"2 本目の上方流入は側頂点へ: {ins['e2']}")

    def test_r716_fan_slots_skip_diamond(self):
        # 同一辺 2 端点のスロット分散(FRAC_SLOTS[2]=0.35/0.65)は
        # ひし形では適用しない — (0,0.35) の根因パスの単体固定
        def setup(diamond: bool):
            lay = B.Layout(C=9, R=9)
            lay.boxes.update({"d": (0.0, 0.0, 140.0, 70.0),
                              "a": (300.0, 0.0, 78.0, 78.0),
                              "b": (300.0, 200.0, 78.0, 78.0)})
            if diamond:
                lay.diamond.add("d")
            edges = [{"id": "E1", "src": "d", "dst": "a"},
                     {"id": "E2", "src": "d", "dst": "b"}]
            routes = {eid: B.NodeRoute(exit=("R", 0.5), entry=("L", 0.5),
                                       runs=[B.Run("h", 35.0),
                                             B.Run("v", 250.0),
                                             B.Run("h", 100.0)], direct=False)
                      for eid in ("E1", "E2")}
            return lay, edges, routes
        lay, edges, routes = setup(diamond=True)
        B._fan_slots(lay, edges, routes)
        self.assertEqual({routes["E1"].exit[1], routes["E2"].exit[1]}, {0.5},
                         "ひし形の端点がスロットへ分散された")
        # 対照: 非ひし形は従来どおり分散する(テストが噛んでいる証明)
        lay, edges, routes = setup(diamond=False)
        B._fan_slots(lay, edges, routes)
        self.assertNotEqual(routes["E1"].exit[1], routes["E2"].exit[1],
                            "対照系(非ひし形)が分散しない")

    def test_r716_snap_diamond_ends(self):
        # 最終安全網: 取りこぼした斜辺上の端点を最終折れ線段階で頂点へ戻す
        lay = B.Layout(C=9, R=9)
        lay.boxes["d"] = (0.0, 0.0, 140.0, 70.0)
        lay.diamond.add("d")
        e = {"id": "E1", "src": "d", "dst": "x"}
        poly = [(140.0, 24.5), (300.0, 24.5), (300.0, 200.0)]  # R 辺 frac0.35
        B.snap_diamond_ends(lay, [(None, e, object(), poly)])
        self.assertEqual(poly[0], (140.0, 35.0), f"頂点へ戻らない: {poly}")
        self.assertEqual(poly[1], (300.0, 35.0), "直交性が壊れた")
        self.assertEqual(poly[2], (300.0, 200.0), "無関係な点が動いた")


class TestValidatorW15(unittest.TestCase):
    """W15: decision への上方 src 流入が上頂点以外(手編集図の救済)。"""

    HEAD = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="s" value="src" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="200" y="40" width="120" height="60" as="geometry"/></mxCell>
<mxCell id="s2" value="src2" style="rounded=1;" vertex="1" parent="1"><mxGeometry x="400" y="40" width="120" height="60" as="geometry"/></mxCell>
<mxCell id="d" value="OK?" style="rhombus;whiteSpace=wrap;" vertex="1" parent="1"><mxGeometry x="200" y="240" width="140" height="70" as="geometry"/></mxCell>
"""
    TAIL = "</root></mxGraphModel></diagram></mxfile>"

    def _edge(self, eid, src, ex, ey, points=()):
        pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
        arr = f'<Array as="points">{pts}</Array>' if pts else ""
        return (f'<mxCell id="{eid}" style="edgeStyle=orthogonalEdgeStyle;'
                f'exitX=0.5;exitY=1;entryX={ex};entryY={ey};" edge="1" '
                f'parent="1" source="{src}" target="d">'
                f'<mxGeometry relative="1" as="geometry">{arr}</mxGeometry>'
                '</mxCell>\n')

    def _run(self, xml: str) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            return subprocess.run([sys.executable, str(VALIDATE), p],
                                  capture_output=True, text=True, timeout=15)
        finally:
            os.unlink(p)

    def test_w15_side_entry_from_above(self):
        # s 下辺 (260,100) → 左へ回り込んで d の左頂点 (200,275) へ横入り
        e = self._edge("e1", "s", 0, 0.5,
                       points=((260, 140), (170, 140), (170, 275)))
        r = self._run(self.HEAD + e + self.TAIL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("W15", r.stdout, "上方 src の左頂点入りを見逃した")

    def test_w15_top_entry_ok(self):
        # s 下辺 (260,100) → d の上頂点 (270,240) へ
        e = self._edge("e1", "s", 0.5, 0, points=((260, 170), (270, 170)))
        r = self._run(self.HEAD + e + self.TAIL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W15", r.stdout, "上頂点入りに誤発火した")

    def test_w15_second_above_inflow_tolerated(self):
        # 上頂点は 1 本 — 誰かが取っていれば 2 本目の側頂点は正当
        e1 = self._edge("e1", "s", 0.5, 0, points=((260, 170), (270, 170)))
        e2 = self._edge("e2", "s2", 1, 0.5, points=((460, 275),))
        r = self._run(self.HEAD + e1 + e2 + self.TAIL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W15", r.stdout, "救済されるべき 2 本目に誤発火した")


def entry_fracs(xml: str) -> dict[str, tuple | None]:
    """eid → (entryX, entryY)(未指定は None)を XML から集める(R7-A3)。"""
    import xml.etree.ElementTree as ET_
    out: dict[str, tuple | None] = {}
    for c in ET_.fromstring(xml).iter("mxCell"):
        if c.get("edge") != "1":
            continue
        style = {k: v for k, _, v in
                 (p.partition("=") for p in (c.get("style") or "").split(";"))}
        try:
            out[c.get("id")] = (float(style["entryX"]), float(style["entryY"]))
        except (KeyError, TypeError, ValueError):
            out[c.get("id")] = None
    return out


class TestBoxEntryRules(unittest.TestCase):
    """R7-A3: 上辺入射規約を全フロー箱へ一般化(ユーザー実QA第7R 指摘)。

    fail-before(修正前実測・FORK スペック): fork gateway(中心 (350,203))
    → alloc「在庫引当」process(中心 (108,337))が exit=(0.5,1) なのに
    entry=(1,0.5) 右辺 — 単純な 2 箱では上辺に入るが、fork 分岐先で子が
    別ノードへの流出も持つ混雑配置では、ルータが交差・重なり回避を優先し
    上方流入を側辺へ落としていた。規約: 上方 src(src 下端 ≤ dst 上端)は
    上辺 / 同行 src は側辺(現状維持)/ 下方 src(戻り)は上辺以外。
    """

    FORK = {
        "name": "fork", "meta": {"purpose": "t"},
        "legend": {"main": "通常", "sub": "例外"},
        "nodes": [
            {"id": "start", "shape": "terminator", "label": "開始",
             "col": 2, "row": 0},
            {"id": "fork", "shape": "gateway", "col": 2, "row": 1},
            {"id": "alloc", "shape": "process", "label": "在庫引当",
             "col": 0, "row": 2},
            {"id": "auth", "shape": "process", "label": "決済オーソリ",
             "col": 4, "row": 2},
            {"id": "stock_check", "shape": "decision", "label": "在庫あり?",
             "col": 0, "row": 3},
            {"id": "pay_check", "shape": "decision", "label": "決済成功?",
             "col": 4, "row": 3},
            {"id": "join", "shape": "gateway", "col": 2, "row": 4},
            {"id": "cs", "shape": "process", "label": "CS対応",
             "col": 6, "row": 2},
            {"id": "ship", "shape": "process", "label": "出荷",
             "col": 2, "row": 5}],
        "edges": [
            {"id": "e1", "src": "start", "dst": "fork", "kind": "main"},
            {"id": "e2", "src": "fork", "dst": "alloc", "kind": "main",
             "label": "引当要求"},
            {"id": "e3", "src": "fork", "dst": "auth", "kind": "main",
             "label": "決済要求"},
            {"id": "e4", "src": "alloc", "dst": "stock_check", "kind": "main"},
            {"id": "e5", "src": "auth", "dst": "pay_check", "kind": "main"},
            {"id": "e6", "src": "stock_check", "dst": "join", "kind": "main",
             "label": "在庫あり"},
            {"id": "e7", "src": "pay_check", "dst": "join", "kind": "main",
             "label": "成功"},
            {"id": "e8", "src": "pay_check", "dst": "cs", "kind": "sub",
             "label": "失敗"},
            {"id": "e9", "src": "cs", "dst": "auth", "kind": "sub",
             "label": "再試行"},
            {"id": "e10", "src": "join", "dst": "ship", "kind": "main"}]}

    def _build(self, spec, name):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), name)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
            xml = (Path(td) / f"{name}.spec.out.drawio").read_text(
                encoding="utf-8")
        return r, xml

    def test_congested_fork_children_enter_top(self):
        # fail-before: e2 が entry=(1,0.5) 右辺だった(ユーザー指摘の再現)
        _r, xml = self._build(self.FORK, "fk")
        ins = entry_fracs(xml)
        self.assertEqual(ins["e2"], (0.5, 0.0),
                         f"fork→在庫引当 が上辺中央でない: {ins['e2']}")
        self.assertEqual(ins["e3"], (0.5, 0.0),
                         f"fork→決済オーソリ が上辺中央でない: {ins['e3']}")
        self.assertEqual(ins["e10"], (0.5, 0.0),
                         f"join→出荷 が上辺中央でない: {ins['e10']}")

    def test_congested_fork_diamond_rules_unchanged(self):
        # A2 非退行: gateway/decision は頂点規約のまま(上頂点は 1 本、
        # 2 本目の上方流入は側頂点で正当 — 箱の全数上辺とは別ルール)
        _r, xml = self._build(self.FORK, "fk2")
        ins = entry_fracs(xml)
        join_ins = [ins["e6"], ins["e7"]]
        self.assertIn((0.5, 0.0), join_ins,
                      f"join の上方流入が上頂点を取っていない: {join_ins}")
        other = join_ins[1 - join_ins.index((0.5, 0.0))]
        self.assertIn(other, [(0.0, 0.5), (1.0, 0.5)],
                      f"2 本目の上方流入が側頂点でない: {other}")
        self.assertEqual(ins["e4"], (0.5, 0.0))
        self.assertEqual(ins["e5"], (0.5, 0.0))

    def test_congested_fork_same_row_and_return(self):
        _r, xml = self._build(self.FORK, "fk3")
        ins = entry_fracs(xml)
        # 同行 src(cs → auth)は側辺のまま(現状維持)
        self.assertEqual(ins["e9"], (1.0, 0.5),
                         f"同行 src の側辺入射が変わった: {ins['e9']}")
        # 下方 src(pay_check row3 → cs row2)は上辺に入らない
        self.assertIsNotNone(ins["e8"])
        self.assertNotEqual(ins["e8"][1], 0.0,
                            f"下方 src の流入が上辺に入った: {ins['e8']}")

    def test_simple_above_diagonal_enters_top(self):
        spec = {"name": "sd", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "a", "shape": "process", "label": "受付",
                     "col": 0, "row": 0},
                    {"id": "b", "shape": "process", "label": "処理",
                     "col": 1, "row": 1}],
                "edges": [{"id": "e1", "src": "a", "dst": "b",
                           "kind": "main"}]}
        _r, xml = self._build(spec, "sd")
        self.assertEqual(entry_fracs(xml)["e1"], (0.5, 0.0))

    def test_simple_same_row_enters_side(self):
        spec = {"name": "ss", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "a", "shape": "process", "label": "受付",
                     "col": 0, "row": 0},
                    {"id": "b", "shape": "process", "label": "処理",
                     "col": 1, "row": 0}],
                "edges": [{"id": "e1", "src": "a", "dst": "b",
                           "kind": "main"}]}
        _r, xml = self._build(spec, "ss")
        self.assertEqual(entry_fracs(xml)["e1"], (0.0, 0.5))

    def test_simple_below_src_avoids_top(self):
        spec = {"name": "sb", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "a", "shape": "process", "label": "戻り元",
                     "col": 0, "row": 1},
                    {"id": "b", "shape": "process", "label": "戻り先",
                     "col": 1, "row": 0}],
                "edges": [{"id": "e1", "src": "a", "dst": "b",
                           "kind": "main"}]}
        _r, xml = self._build(spec, "sb")
        ent = entry_fracs(xml)["e1"]
        self.assertIsNotNone(ent)
        self.assertNotEqual(ent[1], 0.0,
                            f"下方 src の流入が上辺に入った: {ent}")


class TestValidatorW15Boxes(unittest.TestCase):
    """W15 一般化(R7-A3): フロー箱への上方 src 流入が上辺以外(手編集図)。"""

    PROCESS = ("rounded=0;whiteSpace=wrap;html=1;fontFamily=Arial;"
               "fillColor=#FFFFFF;strokeColor=#232F3E;")
    TERMINATOR = ("rounded=1;arcSize=50;whiteSpace=wrap;html=1;"
                  "fontFamily=Arial;fillColor=#232F3E;")
    ENTITY = ("rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
              "fillColor=#FFFFFF;strokeColor=#232F3E;")

    def _xml(self, dst_style, edges, src2_y=40):
        head = (
            '<mxfile><diagram id="d0" name="t"><mxGraphModel><root>\n'
            '<mxCell id="0"/><mxCell id="1" parent="0"/>\n'
            f'<mxCell id="s" value="src" style="rounded=1;" vertex="1" '
            f'parent="1"><mxGeometry x="200" y="40" width="120" height="60" '
            'as="geometry"/></mxCell>\n'
            f'<mxCell id="s2" value="src2" style="rounded=1;" vertex="1" '
            f'parent="1"><mxGeometry x="400" y="{src2_y}" width="120" '
            'height="60" as="geometry"/></mxCell>\n'
            f'<mxCell id="p" value="処理" style="{dst_style}" vertex="1" '
            'parent="1"><mxGeometry x="200" y="240" width="120" height="44" '
            'as="geometry"/></mxCell>\n')
        return head + edges + "</root></mxGraphModel></diagram></mxfile>"

    def _edge(self, eid, src, ex, ey, points=(), exit_="0.5,1"):
        exx, exy = exit_.split(",")
        pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
        arr = f'<Array as="points">{pts}</Array>' if pts else ""
        return (f'<mxCell id="{eid}" style="edgeStyle=orthogonalEdgeStyle;'
                f'exitX={exx};exitY={exy};entryX={ex};entryY={ey};" edge="1" '
                f'parent="1" source="{src}" target="p">'
                f'<mxGeometry relative="1" as="geometry">{arr}</mxGeometry>'
                '</mxCell>\n')

    def _run(self, xml: str) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            return subprocess.run([sys.executable, str(VALIDATE), p],
                                  capture_output=True, text=True, timeout=15)
        finally:
            os.unlink(p)

    def test_w15_box_side_entry_from_above(self):
        # s 下辺 (260,100) → 右へ回り込んで p の右辺 (320,262) へ横入り
        e = self._edge("e1", "s", 1, 0.5,
                       points=((260, 140), (360, 140), (360, 262)))
        r = self._run(self._xml(self.PROCESS, e))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("W15", r.stdout, "上方 src の側辺入りを見逃した")

    def test_w15_box_top_entry_ok_any_x(self):
        # 上辺内の x ずれ(fan スロット相当・entry (0.35,0)=(242,240))は正当
        e = self._edge("e1", "s", 0.35, 0,
                       points=((260, 170), (242, 170)))
        r = self._run(self._xml(self.PROCESS, e))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W15", r.stdout, "上辺入射に誤発火した")

    def test_w15_box_below_src_side_ok(self):
        # src が下方(戻り)なら側辺入射は正当。s2 (400,400) 上辺から
        # (460,262) を経て p の右辺 (320,262) へ
        e = self._edge("e1", "s2", 1, 0.5, points=((460, 262),),
                       exit_="0.5,0")
        r = self._run(self._xml(self.PROCESS, e, src2_y=400))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W15", r.stdout, "下方 src の側辺入射に誤発火した")

    def test_w15_box_no_second_inflow_excuse(self):
        # 箱は辺上に複数ポートを並べられる — diamond と違い 2 本目も上辺必須
        e1 = self._edge("e1", "s", 0.5, 0)   # (260,100)→(260,240) 直線
        e2 = self._edge("e2", "s2", 1, 0.5, points=((460, 262),))
        r = self._run(self._xml(self.PROCESS, e1 + e2))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("W15", r.stdout, "箱の 2 本目の側辺入りを見逃した")

    def test_w15_terminator_flagged(self):
        # s 下辺 (260,100) → 左へ回り込んで p の左辺 (200,262) へ横入り
        e = self._edge("e1", "s", 0, 0.5,
                       points=((260, 140), (160, 140), (160, 262)))
        r = self._run(self._xml(self.TERMINATOR, e))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("W15", r.stdout, "terminator の側辺入りを見逃した")

    def test_w15_entity_not_flagged(self):
        # ER/UML の entity はフロー規約の対象外(親→子は横入りが正当)
        e = self._edge("e1", "s", 0, 0.5,
                       points=((260, 140), (160, 140), (160, 262)))
        r = self._run(self._xml(self.ENTITY, e))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("W15", r.stdout, "entity に誤発火した")


class TestStraighten(unittest.TestCase):
    """直線化パス: 小ジョグの併合と端点スライド、塞がっていれば見送り。"""

    def _lay(self):
        return B.Layout(C=5, R=5, cell={}, cmap={}, cext={}, occ=set())

    def test_mid_jog_merge_with_terminal_slide(self):
        lay = self._lay()
        poly = [(0.0, 100.0), (100.0, 100.0), (100.0, 120.0), (300.0, 120.0),
                (300.0, 400.0)]
        B.straighten_polys(lay, [(poly, (0.0, 90.0, 10.0, 60.0), True,
                                  (290.0, 390.0, 20.0, 20.0), True, None)])
        self.assertEqual(len(poly), 3)               # ジョグが消え L 字になる
        self.assertEqual(poly[-1], (300.0, 400.0))   # 終端は不変
        # 直交を維持(角の座標はリシェイプ/併合どちらが効いたかで変わる)
        self.assertEqual(poly[1][1], poly[0][1])
        self.assertEqual(poly[1][0], poly[2][0])

    def test_blocked_by_obstacle(self):
        lay = self._lay()
        # y100(d側併合先)と y120(始端スライド先)の両方を塞ぐ
        lay.obstacles.append((150.0, 90.0, 40.0, 60.0))
        poly = [(0.0, 100.0), (100.0, 100.0), (100.0, 120.0), (300.0, 120.0),
                (300.0, 400.0)]
        before = list(poly)
        B.straighten_polys(lay, [(poly, (0.0, 90.0, 10.0, 60.0), True,
                                  (290.0, 390.0, 20.0, 20.0), True, None)])
        self.assertEqual(poly, before)               # 塞がっていれば動かさない

    def test_vertical_pair_straightens_with_caption_offset(self):
        """縦積みアイコン間の下向きエッジは、キャプション下からの垂直直線
        (exit fy=1 + exit_dy)にリシェイプされる(AWS 公式一頁物の流儀)。"""
        spec = {"name": "vt", "meta": {"purpose": "t"},
                "nodes": [{"id": "a", "icon": "ec2", "label": "上",
                           "col": 0, "row": 0},
                          {"id": "b", "icon": "s3", "label": "下",
                           "col": 0, "row": 1}],
                "edges": [{"id": "e1", "src": "a", "dst": "b",
                           "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "vt", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ab = json.loads((Path(td) / "vt.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
            e = [x for d in ab.get("diagrams", [ab])
                 for x in d["edges"] if x["id"] == "e1"][0]
            xml = (Path(td) / "vt.spec.out.drawio").read_text(encoding="utf-8")
        self.assertEqual(e["exit"][1], 1)            # 下辺から出る
        self.assertGreater(e.get("exit_dy", 0), 10)  # キャプションの下
        self.assertEqual(e.get("points") or [], [])  # 垂直一直線
        self.assertEqual(e["entry"][1], 0)           # 相手の上辺へ
        # 実 draw.io は exitPerimeter=true(既定)だと輪郭射影で Dy を破棄する
        import re as re_
        em = re_.search(r'<mxCell id="e1"[^>]*style="([^"]*)"', xml)
        self.assertIn("exitDy=", em.group(1))
        self.assertIn("exitPerimeter=0", em.group(1))


class TestSameColumnDirect(unittest.TestCase):
    """同一列の縦並びノード間は、回廊競合があっても垂直直線で結ぶ(指摘5)。"""

    def _contention_spec(self) -> dict:
        # e0(app→db)は同一列で間の行は空き。周辺エッジが回廊を奪い合うと
        # 旧実装は左の回廊へ「コ」の字迂回していた(直行ルートで解消)
        nodes = [
            {"id": "app", "icon": "ec2", "label": "App", "col": 4, "row": 2},
            {"id": "db", "icon": "rds", "label": "DB", "col": 4, "row": 4},
            {"id": "l1", "icon": "ec2", "col": 2, "row": 2},
            {"id": "l2", "icon": "ec2", "col": 2, "row": 4},
            {"id": "t1", "icon": "s3", "col": 3, "row": 0},
            {"id": "b1", "icon": "sqs", "col": 3, "row": 6},
            {"id": "r1", "icon": "s3", "col": 6, "row": 2},
            {"id": "r2", "icon": "sqs", "col": 6, "row": 4},
            {"id": "m3", "icon": "lambda", "col": 3, "row": 3},
            {"id": "m5", "icon": "lambda", "col": 5, "row": 3},
        ]
        edges = [{"id": "e0", "src": "app", "dst": "db", "kind": "main"}]
        edges += [{"id": eid, "src": s, "dst": t, "kind": "sub"}
                  for eid, s, t in (("x1", "l1", "db"), ("x2", "t1", "db"),
                                    ("x3", "app", "b1"), ("x4", "r1", "db"),
                                    ("x5", "app", "r2"), ("x6", "m3", "m5"))]
        return {"name": "vd", "meta": {"purpose": "test"},
                "nodes": nodes, "edges": edges}

    def _built_edge(self, spec: dict, name: str, eid: str):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), name, "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout, r.stdout)
            ab = json.loads((Path(td) / f"{name}.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
            xml = (Path(td) / f"{name}.spec.out.drawio").read_text(
                encoding="utf-8")
        e = [x for d in ab.get("diagrams", [ab])
             for x in d["edges"] if x["id"] == eid][0]
        return e, xml

    def test_vertical_direct_under_contention(self):
        e, xml = self._built_edge(self._contention_spec(), "vd", "e0")
        self.assertEqual(e.get("points") or [], [])   # waypoint なし
        self.assertEqual(e["exit"][1], 1)             # 下辺(キャプション下)
        self.assertEqual(e["entry"][1], 0)            # 相手の上辺へ
        # 両端の x が一致 = 垂直直線(両ノードとも 78px 幅・同一列)
        self.assertAlmostEqual(e["exit"][0], e["entry"][0], places=4)
        self.assertGreater(e.get("exit_dy", 0), 10)   # キャプション下アンカー
        import re as re_
        em = re_.search(r'<mxCell id="e0"[^>]*style="([^"]*)"', xml)
        self.assertIn("exitDy=", em.group(1))
        self.assertIn("exitPerimeter=0", em.group(1))

    def test_title_band_centers_direct(self):
        # dst の直上に短いサブネット題字帯があり列中心を塞ぐ場合、列幅拡張で
        # 中心レーンを空けて exit/entry 0.5 の垂直直線になる(FB第4R 指摘C。
        # v1.5.0〜1.6.0 の「±NEAR_FRAC 内でずらした直線」仕様は、中心から
        # 11px 前後ずれた「なんで中央に寄ってないんだろう」線を作るため廃止 —
        # 優先順位は 中心 → 列幅拡張で中心確保 → 帯内シフト → ジョグ → 格子)
        spec = {
            "name": "tb", "meta": {"purpose": "test"},
            "containers": [
                {"id": "vpc", "type": "vpc", "label": "VPC"},
                {"id": "sub1", "type": "private_subnet", "label": "Private",
                 "parent": "vpc"}],
            "nodes": [
                {"id": "app", "icon": "ec2", "col": 2, "row": 1,
                 "parent": "vpc"},
                {"id": "db", "icon": "rds", "col": 2, "row": 3,
                 "parent": "sub1"},
                {"id": "w1", "icon": "ec2", "col": 0, "row": 1,
                 "parent": "vpc"}],
            "edges": [{"id": "e0", "src": "app", "dst": "db", "kind": "main"},
                      {"id": "x1", "src": "w1", "dst": "app", "kind": "main"}]}
        e, _ = self._built_edge(spec, "tb", "e0")
        self.assertEqual(e.get("points") or [], [], "垂直直線(waypoint なし)")
        # 両端の x が一致 = 垂直のまま、かつ列幅拡張で中心 0.5 を保つ
        self.assertAlmostEqual(e["exit"][0], e["entry"][0], places=4)
        self.assertAlmostEqual(e["exit"][0], 0.5, places=4)
        self.assertAlmostEqual(e["entry"][0], 0.5, places=4)

    def test_min_width_vertical_pair_straight(self):
        # 指摘2の元ケース: 最小幅サブネットの縦並び複製ペア。題字
        # 「Private subnet (DB)」が上辺ほぼ全幅を覆い、旧実装ではどの x も
        # 帯に当たる → コの字迂回(手動 pin なら W5)しかなかった。
        # 列幅の局所拡張+x 探索で「垂直直線・W5 なし・0 エラー」になる
        spec = {
            "name": "mw", "meta": {"purpose": "test"},
            "containers": [
                {"id": "vpc", "type": "vpc", "label": "VPC"},
                {"id": "sub1", "type": "private_subnet",
                 "label": "Private subnet (DB)", "parent": "vpc"},
                {"id": "sub2", "type": "private_subnet",
                 "label": "Private subnet (DB)", "parent": "vpc"}],
            "nodes": [
                {"id": "db1", "icon": "aurora", "label": "Aurora primary",
                 "parent": "sub1", "col": 0, "row": 0},
                {"id": "db2", "icon": "aurora", "label": "Aurora standby",
                 "parent": "sub2", "col": 0, "row": 2}],
            "edges": [{"id": "e1", "src": "db1", "dst": "db2",
                       "label": "replication", "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "mw", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s), 0 warning(s)", r.stdout, r.stdout)
            self.assertNotIn("W5", r.stdout, "題字帯貫通が残っている")
            ab = json.loads((Path(td) / "mw.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
            xml = (Path(td) / "mw.spec.out.drawio").read_text(encoding="utf-8")
        e = [x for d in ab.get("diagrams", [ab])
             for x in d["edges"] if x["id"] == "e1"][0]
        self.assertEqual(e.get("points") or [], [], "垂直直線(waypoint なし)")
        self.assertAlmostEqual(e["exit"][0], e["entry"][0], places=4)
        # 「題字+通過帯」が収まる幅への局所拡張が起きている
        # (既定の最小サブネット幅は約 165px)
        import re as re_
        sm = re_.search(r'<mxCell id="sub2".*?width="([\d.]+)"', xml, re_.S)
        self.assertGreater(float(sm.group(1)), 250.0, "コンテナ幅の局所拡張")

    def test_nearest_free_intervals(self):
        # x 探索の中核: 開区間ブロックの引き算。境界(クリアランス
        # ちょうど)は有効、全域が塞がれたら None、空きでは target 優先
        nf = B._nearest_free
        self.assertEqual(nf(50, 0, 100, []), 50)            # 空き=そのまま
        self.assertEqual(nf(50, 0, 100, [(40, 60)]), 40)    # 近い側の境界へ
        self.assertEqual(nf(55, 0, 100, [(40, 60)]), 60)
        self.assertEqual(nf(50, 0, 100, [(-10, 110)]), None)  # 全域ブロック
        self.assertEqual(nf(50, 0, 100, [(-10, 100)]), 100)   # 境界点は有効
        self.assertEqual(nf(50, 0, 100, [(0, 60), (60, 110)]), 60)  # 点区間
        self.assertIsNone(nf(50, 60, 40, []))               # 範囲が負

    def test_manual_pin_fraction_passthrough(self):
        # フィードバックの「entry fraction は 0.25 刻みしか取れない」主張の
        # 反証(実測): 手動 exit/entry の任意 float はそのまま exitX/entryX に
        # 出力される(スペック検証も 0〜1 の実数を許す)
        spec = {
            "name": "pf", "meta": {"purpose": "test"},
            "nodes": [{"id": "a", "icon": "ec2", "col": 0, "row": 0},
                      {"id": "b", "icon": "rds", "col": 0, "row": 2}],
            "edges": [{"id": "e1", "src": "a", "dst": "b",
                       "exit": [0.62, 1], "entry": [0.62, 0]}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "pf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (Path(td) / "pf.spec.out.drawio").read_text(encoding="utf-8")
        self.assertIn("exitX=0.62;", xml)
        self.assertIn("entryX=0.62;", xml)


class TestFanSymmetry(unittest.TestCase):
    """同一ノード同一辺のポートは辺中心 0.5 に対して対称に並ぶ(指摘6)。"""

    W = 78.0

    def _lay(self, boxes: dict) -> "B.Layout":
        lay = B.Layout(C=5, R=5, cell={}, cmap={}, cext={}, occ=set())
        lay.boxes = boxes
        return lay

    def _mover(self) -> "B.NodeRoute":
        # hub 右辺から出て相手側へ折れる 3 Run ルート(上下は相手の箱位置で決まる)
        return B.NodeRoute(exit=("R", .5), entry=("L", .5),
                           runs=[B.Run("h", 0.0), B.Run("v", 200.0),
                                 B.Run("h", 0.0)], direct=False)

    def _fan(self, edges, routes, boxes):
        B.fan_out(self._lay(boxes), edges, routes)
        return {eid: r.exit[1] for eid, r in routes.items()}

    def test_two_movers_mirror(self):
        # 直行便なし・上下 1 本ずつ → 0.5 に対して鏡映(和 = 1.0)
        boxes = {"hub": (0.0, 0.0, self.W, self.W),
                 "up": (300.0, -300.0, self.W, self.W),
                 "down": (300.0, 300.0, self.W, self.W)}
        edges = [{"id": "eu", "src": "hub", "dst": "up"},
                 {"id": "ed", "src": "hub", "dst": "down"}]
        routes = {"eu": self._mover(), "ed": self._mover()}
        fr = self._fan(edges, routes, boxes)
        self.assertLess(fr["eu"], 0.5)
        self.assertGreater(fr["ed"], 0.5)
        self.assertAlmostEqual(fr["eu"] + fr["ed"], 1.0, places=3)

    def test_direct_plus_updown_mirror(self):
        # 直行便 1(0.5 固定)+ 上下 1 本ずつ → 上下は 0.5 に鏡映
        boxes = {"hub": (0.0, 0.0, self.W, self.W),
                 "mid": (300.0, 0.0, self.W, self.W),
                 "up": (300.0, -300.0, self.W, self.W),
                 "down": (300.0, 300.0, self.W, self.W)}
        edges = [{"id": "em", "src": "hub", "dst": "mid"},
                 {"id": "eu", "src": "hub", "dst": "up"},
                 {"id": "ed", "src": "hub", "dst": "down"}]
        routes = {"em": B.NodeRoute(exit=("R", .5), entry=("L", .5),
                                    runs=[B.Run("h", 39.0)], direct=True),
                  "eu": self._mover(), "ed": self._mover()}
        fr = self._fan(edges, routes, boxes)
        self.assertEqual(fr["em"], 0.5)               # 直行便は中心固定
        self.assertAlmostEqual(fr["eu"] + fr["ed"], 1.0, places=3)

    def test_direct_plus_two_below_ladder(self):
        # 直行便 1 + 同じ半分へ 2 本 → 中心から等間隔のラダー
        # (旧実装は帯 0.58〜0.85 の端寄せで直行便との間隔が不均等だった)
        boxes = {"hub": (0.0, 0.0, self.W, self.W),
                 "mid": (300.0, 0.0, self.W, self.W),
                 "d1": (300.0, 300.0, self.W, self.W),
                 "d2": (300.0, 500.0, self.W, self.W)}
        edges = [{"id": "em", "src": "hub", "dst": "mid"},
                 {"id": "e1", "src": "hub", "dst": "d1"},
                 {"id": "e2", "src": "hub", "dst": "d2"}]
        routes = {"em": B.NodeRoute(exit=("R", .5), entry=("L", .5),
                                    runs=[B.Run("h", 39.0)], direct=True),
                  "e1": self._mover(), "e2": self._mover()}
        fr = self._fan(edges, routes, boxes)
        self.assertEqual(fr["em"], 0.5)
        self.assertAlmostEqual(fr["e1"] - fr["em"], fr["e2"] - fr["e1"],
                               places=3)              # 等間隔
        self.assertLessEqual(fr["e2"], 0.85 + 1e-9)   # 帯の外へ出ない


class TestMirrorFanPairs(unittest.TestCase):
    """SEM-6: 同一 src の上下対ファンは折れ構造が鏡像に揃う。

    v1.6.0 対称ユニット・_fan_slots は端点とレーン共有までしか対称化せず、
    探索の SHARE/CROSS が後着の対枝を階段状経路(折れ +2)へ追いやっていた
    (構成図03 実測: 上枝 2 折れ・下枝 4 折れ)。
    """

    def _pair_spec(self, with_share: bool) -> dict:
        """中央 src(alb)から上下 AZ の ECS へのファン対(構成図03 の縮約)。

        with_share=True は受け側 ECS の左辺を ElastiCache 線と共有させる
        (entry が中心から押し出され、非対称が顕在化していた実使用条件。
        旧エンジン実測: 上枝 2 折れ・下枝 4 折れの階段)。コンテナ題字は
        実案件同等の長さが必要 — 短い題字だと T 入射レジームに落ちて
        L/L 対ファン自体が発生しない。
        """
        conts = [
            {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
            {"id": "region", "label": "Region", "type": "region",
             "parent": "cloud"},
            {"id": "vpc", "label": "VPC", "type": "vpc", "parent": "region"}]
        nodes = [
            {"id": "users", "label": "Users", "icon": "users",
             "col": 0, "row": 2},
            {"id": "igw", "label": "Internet Gateway",
             "icon": "internet_gateway", "parent": "vpc",
             "col": 1, "row": 2, "on_boundary": "left"},
            {"id": "alb", "label": "ALB (2AZ 展開)",
             "icon": "application_load_balancer", "parent": "vpc",
             "col": 2, "row": 2},
            {"id": "ecr", "label": "Amazon ECR", "icon": "ecr",
             "parent": "region", "col": 7, "row": 2}]
        edges = [{"id": "e_u", "src": "users", "dst": "igw", "kind": "main"},
                 {"id": "e_in", "src": "igw", "dst": "alb", "kind": "main"}]
        for az, srow in (("a", 1), ("b", 3)):
            conts += [{"id": f"az_{az}", "label": f"Availability Zone {az}",
                       "type": "az", "parent": "vpc"}]
            if with_share:
                conts += [{"id": f"sub_c_{az}", "label": "Cache subnet",
                           "parent": f"az_{az}", "type": "private_subnet"}]
            conts += [
                {"id": f"sub_a_{az}", "label": "App subnet",
                 "parent": f"az_{az}", "type": "private_subnet"},
                {"id": f"sub_d_{az}", "label": "DB subnet",
                 "parent": f"az_{az}", "type": "private_subnet"},
                {"id": f"sub_p_{az}", "label": "Public subnet",
                 "parent": f"az_{az}", "type": "public_subnet"}]
            nodes += [
                {"id": f"ecs_{az}", "label": "ECS サービス", "icon": "ecs",
                 "parent": f"sub_a_{az}", "col": 4, "row": srow},
                {"id": f"db_{az}", "label": "Aurora\n(プライマリ)",
                 "icon": "aurora", "parent": f"sub_d_{az}",
                 "col": 5, "row": srow},
                {"id": f"nat_{az}", "label": "NAT Gateway",
                 "icon": "nat_gateway", "parent": f"sub_p_{az}",
                 "col": 6, "row": srow}]
            edges += [
                {"id": f"e_{az}", "src": "alb", "dst": f"ecs_{az}",
                 "kind": "main"},
                {"id": f"ed_{az}", "src": f"ecs_{az}", "dst": f"db_{az}",
                 "kind": "main"},
                {"id": f"en_{az}", "src": f"nat_{az}", "dst": "ecr",
                 "kind": "main"}]
            if with_share:
                nodes += [{"id": f"cache_{az}",
                           "label": "ElastiCache\n(プライマリ)",
                           "icon": "elasticache", "parent": f"sub_c_{az}",
                           "col": 3, "row": srow}]
                edges += [{"id": f"ec_{az}", "src": f"ecs_{az}",
                           "dst": f"cache_{az}", "kind": "main"}]
        if with_share:   # 中間回廊を横切るレプリケーション線(実使用条件)
            edges += [{"id": "e_repl", "src": "cache_a", "dst": "cache_b",
                       "kind": "main"},
                      {"id": "e_repl_db", "src": "db_a", "dst": "db_b",
                       "kind": "main"}]
        return {"name": "mirror", "meta": {"purpose": "test"},
                "containers": conts, "nodes": nodes, "edges": edges}

    def _fan_wps(self, xml: str) -> dict[str, list[tuple[float, float]]]:
        out = {}
        for eid in ("e_a", "e_b"):
            m = re.search(f'id="{eid}"[^>]*>.*?</mxCell>', xml, re.S)
            self.assertIsNotNone(m, f"edge {eid} が出力に無い")
            out[eid] = [(float(x), float(y)) for x, y in
                        re.findall(r'<mxPoint x="([\d.-]+)" y="([\d.-]+)" />',
                                   m.group(0))]
        return out

    def _assert_mirror(self, xml: str) -> None:
        wps = self._fan_wps(xml)
        # 対枝の折れ数一致(旧実装: 上 2 折れ / 下 4 折れの階段)
        self.assertEqual(len(wps["e_a"]), len(wps["e_b"]),
                         f"対枝の折れ数が不一致: {wps}")
        # 縦レーンの鏡像 = 同一 x(v1.6.0 対称ユニットがレーンを共有する形)
        xs_a = sorted({p[0] for p in wps["e_a"]})
        xs_b = sorted({p[0] for p in wps["e_b"]})
        self.assertEqual(xs_a, xs_b, f"縦レーンが鏡像でない: {wps}")

    def test_pair_with_shared_entry_side(self):
        # 受け側左辺の共有あり(構成図03 と同じ顕在化条件)→ 鏡像 + 最小折れ
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._pair_spec(True), Path(td), "m1")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (Path(td) / "m1.spec.out.drawio").read_text(encoding="utf-8")
        self._assert_mirror(xml)
        wps = self._fan_wps(xml)
        self.assertEqual(len(wps["e_a"]), 2, f"最小折れ(L字)でない: {wps}")

    def test_pair_plain(self):
        # 共有なしの素の上下ファンも折れ構造が鏡像
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._pair_spec(False), Path(td), "m2")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (Path(td) / "m2.spec.out.drawio").read_text(encoding="utf-8")
        self._assert_mirror(xml)

    def _lay(self, boxes: dict) -> "B.Layout":
        lay = B.Layout(C=8, R=8, cell={}, cmap={}, cext={}, occ=set())
        lay.boxes = boxes
        lay.cell = {k: (0, 0) for k in boxes}   # 全てノード扱い
        return lay

    def _route(self, runs, entry=("L", .5)) -> "B.NodeRoute":
        return B.NodeRoute(exit=("R", .5), entry=entry,
                           runs=[B.Run(a, c) for a, c in runs],
                           direct=len(runs) == 1)

    def test_candidates_and_fallbacks(self):
        boxes = {"hub": (0.0, 0.0, 78.0, 78.0),
                 "up": (300.0, -300.0, 78.0, 78.0),
                 "down": (300.0, 300.0, 78.0, 78.0)}
        edges = [{"id": "eu", "src": "hub", "dst": "up"},
                 {"id": "ed", "src": "hub", "dst": "down"}]
        # 上枝 L 字(3 Run)・下枝 階段(5 Run)→ 下枝の鏡像候補 1 件
        routes = {"eu": self._route([("h", 0), ("v", 200.0), ("h", 0)]),
                  "ed": self._route([("h", 0), ("v", 100.0), ("h", 150.0),
                                     ("v", 200.0), ("h", 0)])}
        cands = B._mirror_fan_candidates(self._lay(boxes), edges, routes)
        self.assertEqual(len(cands), 1)
        (e, cand), = cands[0]
        self.assertEqual(e["id"], "ed")
        self.assertEqual([r.axis for r in cand.runs], ["h", "v", "h"])
        self.assertEqual(cand.runs[1].coord, 200.0)   # 縦レーンは同一 x
        # 既に鏡像(中間 Run 一致)→ 候補なし
        routes2 = {"eu": self._route([("h", 0), ("v", 200.0), ("h", 0)]),
                   "ed": self._route([("h", 0), ("v", 200.0), ("h", 0)])}
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes), edges, routes2), [])
        # 対にならないファン(両方とも上)→ 候補なし(従来動作)
        boxes3 = dict(boxes, down=(300.0, -500.0, 78.0, 78.0))
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes3), edges, routes), [])
        # 鏡像 entry がアイコン下辺になる対 → 候補なし(キャプション保護。
        # 鋳型 = 上辺 entry の下枝、鏡像すると上枝の entry が B になる)
        routes4 = {"eu": self._route([("h", 0), ("v", 100.0), ("h", -150.0),
                                      ("v", 200.0), ("h", 0)]),
                   "ed": self._route([("h", 0), ("v", 200.0)],
                                     entry=("T", .5))}
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes), edges, routes4), [])


class TestMirrorFanInPairs(unittest.TestCase):
    """SEM-7-5: 同一 dst へ集まる上下対ファンインは入射辺と折れ構造が鏡像に揃う。

    SEM-6(同一 src のファンアウト)の裏返し。実使用の構成図03 実測:
    上 NAT→ECR が entry=上辺の 2 折れ・下 NAT→ECR が entry=左辺の 3 折れで、
    同一 dst への対枝の入射辺が不一致(左右非対称)だった。鏡像化後は両枝が
    同一辺へ鏡像 frac(0.35/0.65)・同一縦レーンで入る。
    """

    def _pair_spec(self, with_upstream: bool) -> dict:
        """上下 AZ の NAT から region 直下の ECR へ集まるファンイン対
        (構成図03 の縮約)。with_upstream=True は NAT の上流に ECS 鎖を
        足した変種(入射側 ECR の辺共有条件は変えず、経路の混雑だけ変える)。
        旧エンジン実測: どちらも上枝 T 入射・下枝 L 入射の非対称。
        """
        conts = [
            {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
            {"id": "region", "label": "Region", "type": "region",
             "parent": "cloud"},
            {"id": "vpc", "label": "VPC", "type": "vpc", "parent": "region"}]
        nodes = [{"id": "ecr", "label": "Amazon ECR", "icon": "ecr",
                  "parent": "region", "col": 7, "row": 2}]
        edges = []
        for az, srow in (("a", 1), ("c", 3)):
            conts += [{"id": f"az_{az}", "label": f"Availability Zone {az}",
                       "type": "az", "parent": "vpc"},
                      {"id": f"sub_p_{az}", "label": "Public subnet",
                       "type": "public_subnet", "parent": f"az_{az}"}]
            nodes += [{"id": f"nat_{az}", "label": "NAT Gateway",
                       "icon": "nat_gateway", "parent": f"sub_p_{az}",
                       "col": 6, "row": srow}]
            edges += [{"id": f"en_{az}", "src": f"nat_{az}", "dst": "ecr",
                       "kind": "main"}]
            if with_upstream:
                conts += [{"id": f"sub_a_{az}", "label": "App subnet",
                           "type": "private_subnet", "parent": f"az_{az}"}]
                nodes += [{"id": f"ecs_{az}", "label": "ECS サービス",
                           "icon": "ecs", "parent": f"sub_a_{az}",
                           "col": 4, "row": srow}]
                edges += [{"id": f"eb_{az}", "src": f"ecs_{az}",
                           "dst": f"nat_{az}", "kind": "main"}]
        return {"name": "fanin", "meta": {"purpose": "test"},
                "containers": conts, "nodes": nodes, "edges": edges}

    @staticmethod
    def _entry_side(style: str) -> tuple[str, float]:
        ex, ey = re.search(r"entryX=([\d.]+);entryY=([\d.]+)", style).groups()
        ex, ey = float(ex), float(ey)
        if ex == 0.0:
            return "L", ey
        if ex == 1.0:
            return "R", ey
        return ("T", ex) if ey == 0.0 else ("B", ex)

    def _assert_mirror_in(self, xml: str) -> None:
        info = {}
        for eid in ("en_a", "en_c"):
            m = re.search(f'id="{eid}"[^>]*style="([^"]*)".*?</mxCell>',
                          xml, re.S)
            self.assertIsNotNone(m, f"edge {eid} が出力に無い")
            side, frac = self._entry_side(m.group(1))
            wps = [(float(x), float(y)) for x, y in
                   re.findall(r'<mxPoint x="([\d.-]+)" y="([\d.-]+)" />',
                              m.group(0))]
            info[eid] = (side, frac, wps)
        (sa, fa, wa), (sc, fc, wc) = info["en_a"], info["en_c"]
        # 入射辺の一致(旧実装: 上枝 T / 下枝 L の不一致)
        self.assertEqual(sa, sc, f"入射辺が不一致: {info}")
        # 入射 frac の鏡像(辺中心 0.5 に対して対称)
        self.assertAlmostEqual(fa + fc, 1.0, delta=0.02,
                               msg=f"入射 frac が鏡像でない: {info}")
        # 折れ数一致 + 縦レーンの鏡像 = 同一 x(対称ユニットのレーン共有)
        self.assertEqual(len(wa), len(wc), f"対枝の折れ数が不一致: {info}")
        self.assertEqual(sorted({p[0] for p in wa}), sorted({p[0] for p in wc}),
                         f"縦レーンが鏡像でない: {info}")

    def test_pair_plain(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._pair_spec(False), Path(td), "fi1")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s), 0 warning(s)", r.stdout, r.stdout)
            xml = (Path(td) / "fi1.spec.out.drawio").read_text(encoding="utf-8")
        self._assert_mirror_in(xml)

    def test_pair_with_upstream_chain(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._pair_spec(True), Path(td), "fi2")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s), 0 warning(s)", r.stdout, r.stdout)
            xml = (Path(td) / "fi2.spec.out.drawio").read_text(encoding="utf-8")
        self._assert_mirror_in(xml)

    def _lay(self, boxes: dict) -> "B.Layout":
        lay = B.Layout(C=8, R=8, cell={}, cmap={}, cext={}, occ=set())
        lay.boxes = boxes
        lay.cell = {k: (0, 0) for k in boxes}   # 全てノード扱い
        return lay

    def _route(self, runs, entry=("L", .5)) -> "B.NodeRoute":
        return B.NodeRoute(exit=("R", .5), entry=entry,
                           runs=[B.Run(a, c) for a, c in runs],
                           direct=len(runs) == 1)

    def test_candidates_align_fallback(self):
        boxes = {"hub": (300.0, 0.0, 78.0, 78.0),
                 "up": (0.0, -300.0, 78.0, 78.0),
                 "down": (0.0, 300.0, 78.0, 78.0)}
        edges = [{"id": "eu", "src": "up", "dst": "hub"},
                 {"id": "ed", "src": "down", "dst": "hub"}]
        # 構成図03 の形: 上枝 T 入射 2 Run・下枝 L 入射 3 Run。
        # 短い鋳型(T 入射)の鏡像は hub 下辺 = キャプション貫通で不可 →
        # 長い枝を鋳型に、上枝を L 入射 3 Run へ整合させる候補が出る
        routes = {"eu": self._route([("h", 0), ("v", 339.0)],
                                    entry=("T", .5)),
                  "ed": self._route([("h", 0), ("v", 250.0), ("h", 0)])}
        cands = B._mirror_fan_candidates(self._lay(boxes), edges, routes,
                                         "dst")
        self.assertEqual(len(cands), 1)
        (e, cand), = cands[0]
        self.assertEqual(e["id"], "eu")
        self.assertEqual(cand.entry, ("L", .5))
        self.assertEqual([r.axis for r in cand.runs], ["h", "v", "h"])
        self.assertEqual(cand.runs[1].coord, 250.0)   # 縦レーンは同一 x
        self.assertEqual(cand.exit, ("R", .5))        # 自 src の出射は維持
        # Run 差 3 以上の不整合対は整合化しない(過剰一般化の抑止)
        routes5 = {"eu": self._route([("h", 0), ("v", 339.0)],
                                     entry=("T", .5)),
                   "ed": self._route([("h", 0), ("v", 250.0), ("h", 100.0),
                                      ("v", 260.0), ("h", 0)])}
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes), edges, routes5, "dst"),
            [])

    def test_candidates_mirror_and_skip(self):
        boxes = {"hub": (300.0, 0.0, 78.0, 78.0),
                 "up": (0.0, -300.0, 78.0, 78.0),
                 "down": (0.0, 300.0, 78.0, 78.0)}
        edges = [{"id": "eu", "src": "up", "dst": "hub"},
                 {"id": "ed", "src": "down", "dst": "hub"}]
        # 入射辺が揃った対(L/L)の階段枝 → SEM-6 同様に短い枝を鋳型に鏡像
        routes = {"eu": self._route([("h", 0), ("v", 250.0), ("h", 0)]),
                  "ed": self._route([("h", 0), ("v", 100.0), ("h", 150.0),
                                     ("v", 250.0), ("h", 0)])}
        cands = B._mirror_fan_candidates(self._lay(boxes), edges, routes,
                                         "dst")
        self.assertEqual(len(cands), 1)
        (e, cand), = cands[0]
        self.assertEqual(e["id"], "ed")
        self.assertEqual([r.axis for r in cand.runs], ["h", "v", "h"])
        self.assertEqual(cand.runs[1].coord, 250.0)
        self.assertEqual(cand.entry, ("L", .5))   # 既存入射端点を維持
        # 既に鏡像(入射辺整合 + 中間 Run 一致)→ 候補なし(冪等)
        routes2 = {"eu": self._route([("h", 0), ("v", 250.0), ("h", 0)]),
                   "ed": self._route([("h", 0), ("v", 250.0), ("h", 0)])}
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes), edges, routes2, "dst"),
            [])
        # 対にならないファンイン(両 src とも上)→ 候補なし
        boxes3 = dict(boxes, down=(0.0, -500.0, 78.0, 78.0))
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes3), edges, routes, "dst"),
            [])
        # 同一 src ロール(SEM-6)では同一 dst 対は対象外のまま
        self.assertEqual(
            B._mirror_fan_candidates(self._lay(boxes), edges, routes), [])


class TestSparseGrid(unittest.TestCase):
    """空き行/列は潰れる(疎な row/col 指定が余白の海にならない)。"""

    def test_empty_rows_collapse(self):
        import re as re_
        spec = {"name": "sp", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "a", "label": "A", "icon": "ec2", "col": 0, "row": 0},
                    {"id": "b", "label": "B", "icon": "s3", "col": 0, "row": 10}],
                "edges": [{"id": "e1", "src": "a", "dst": "b", "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "sp.spec.json"
            cp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            r = run_build(cp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (Path(td) / "sp.spec.out.drawio").read_text(encoding="utf-8")
        h = int(re_.search(r'pageHeight="(\d+)"', xml).group(1))
        # 空き 9 行が潰れていれば 2 ノード+帯間隔で 900px 未満に収まる
        # (潰れない場合は 9 行 × 約 130px で 1,500px を超える)
        self.assertLess(h, 900, f"pageHeight={h}")


class TestGraphDump(unittest.TestCase):
    """--graph: 構成集合のダンプ(起こし直し前後の 1:1 照合用)。"""

    def test_graph_output(self):
        r = subprocess.run(
            [sys.executable, str(VALIDATE),
             str(ROOT / "templates" / "example-3tier.drawio"), "--graph"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("vertex\tusers\t", r.stdout)
        self.assertIn("edge\tusers->", r.stdout)
        self.assertNotIn("_legend", r.stdout)   # 生成物は除外
        self.assertNotIn("_meta", r.stdout)


class TestLabelPlacement(unittest.TestCase):
    """pick_label_at: ラベルがアイコンを欠かず、横線を覆い切らない(目視QA A/D)。"""

    def test_avoids_obstacle_and_short_segment(self):
        lay = B.Layout(C=3, R=3, cell={}, cmap={}, cext={}, occ=set())
        # 中点(150,100)にアイコン相当の障害物。横線は 100px でラベル幅より短い
        lay.obstacles.append((120.0, 80.0, 60.0, 40.0))
        poly = [(100.0, 100.0), (200.0, 100.0), (200.0, 400.0)]
        x, y = B.pick_label_at(lay, "とても長いラベル文字列", poly)
        # 短い横線(覆い切る)を避け、縦線上の障害物と重ならない位置を選ぶ
        self.assertEqual(x, 200.0)
        self.assertGreater(y, 120.0)

    def test_keeps_midpoint_when_clear(self):
        lay = B.Layout(C=3, R=3, cell={}, cmap={}, cext={}, occ=set())
        poly = [(100.0, 100.0), (500.0, 100.0)]
        x, y = B.pick_label_at(lay, "短", poly)
        self.assertEqual((x, y), (300.0, 100.0))  # 従来どおり中点


class TestReviewFixes(unittest.TestCase):
    """2026-07-07 レビュー3件対応の回帰(SVG正方形+カスタム色/改行/er_nn/手動points)。"""

    def _build_tab(self, tab, name, *extra):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{name}.spec.json"
            cp.write_text(json.dumps(tab, ensure_ascii=False), encoding="utf-8")
            r = run_build(cp, *extra)
            files = {q.name: q.read_text(encoding="utf-8")
                     for q in Path(td).iterdir()
                     if q.suffix in (".drawio", ".svg")}
        return r, files

    def test_svg_square_and_custom_kind_color(self):
        import re as re_
        tab = {"name": "sq", "meta": {"purpose": "t"},
               "kinds": {"cicd": {"base": "ops", "color": "#7D3C98"}},
               "nodes": [
                   {"id": "a", "label": "A", "icon": "ec2", "col": 0, "row": 0},
                   {"id": "b", "label": "B", "icon": "s3", "col": 4, "row": 0}],
               "edges": [{"id": "e1", "src": "a", "dst": "b", "kind": "cicd",
                          "label": "x"}],
               "legend": {"cicd": "CI/CD"}}
        r, files = self._build_tab(tab, "sq", "--emit-svg")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        svg = files["sq.spec.out.svg"]
        m = re_.search(r'<svg[^>]*width="(\d+)" height="(\d+)"', svg)
        self.assertEqual(m.group(1), m.group(2))   # 正方形(qlmanage 対策)
        self.assertIn("#7D3C98", svg)              # カスタム kinds の色が反映

    def test_newline_label_becomes_br(self):
        tab = {"name": "nl", "meta": {"purpose": "t"},
               "nodes": [
                   {"id": "a", "label": "受注\nサービス", "icon": "ec2",
                    "col": 0, "row": 0},
                   {"id": "b", "label": "B", "icon": "s3", "col": 1, "row": 0}],
               "edges": [{"id": "e1", "src": "a", "dst": "b", "kind": "main"}]}
        r, files = self._build_tab(tab, "nl")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        xml = files["nl.spec.out.drawio"]
        self.assertIn("受注&lt;br&gt;サービス", xml)   # \n → <br>(esc 済み)
        self.assertNotIn('value="受注\n', xml)         # 生改行が属性に残らない

    def test_er_nn_and_bidir_warn(self):
        tab = {"name": "er", "meta": {"purpose": "t"},
               "nodes": [
                   {"id": "s", "shape": "entity", "title": "students",
                    "rows": ["PK id"], "col": 0, "row": 0},
                   {"id": "c", "shape": "entity", "title": "courses",
                    "rows": ["PK id"], "col": 2, "row": 0},
                   {"id": "t", "shape": "entity", "title": "teachers",
                    "rows": ["PK id"], "col": 4, "row": 0}],
               "edges": [
                   {"id": "r1", "src": "s", "dst": "c", "kind": "er_nn"},
                   {"id": "r2", "src": "c", "dst": "t", "kind": "er_1n",
                    "bidir": True}],
               "legend": {"er_nn": "多対多", "er_1n": "1対多"}}
        r, files = self._build_tab(tab, "er")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        xml = files["er.spec.out.drawio"]
        self.assertEqual(xml.count("startArrow=ERmany"), 2)  # 本体+凡例
        self.assertIn("bidir の併用", r.stdout)

    def test_manual_points_not_shifted_by_meta(self):
        tab = {"name": "mp", "meta": {"purpose": "テスト", "audience": "x"},
               "nodes": [
                   {"id": "a", "label": "A", "icon": "ec2", "col": 0, "row": 0},
                   {"id": "b", "label": "B", "icon": "s3", "col": 3, "row": 2}],
               "edges": [
                   {"id": "e1", "src": "a", "dst": "b", "kind": "main",
                    "exit": [1, 0.5], "entry": [0, 0.5],
                    "points": [[500, 300]]}]}
        # 検査対象は座標系のみ(検体の直交性は不問)なので --no-validate
        r, files = self._build_tab(tab, "mp", "--no-validate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # メタパネルのシフト(dy)が手動 points に加算されない=最終座標のまま
        self.assertIn('<mxPoint x="500" y="300" />',
                      files["mp.spec.out.drawio"])


class TestContainmentEdge(unittest.TestCase):
    """内包エッジ(cloud→内部ノード)が間のアイコンを貫通しない。

    旧実装は L/Z の簡易配線で障害物を見ず、境界とノードの間に別アイコンが
    あると直線が貫通した(E3)。格子探索+内向きスタブで回避すること。
    """

    def test_container_to_child_avoids_icons(self):
        spec = {"name": "cont", "meta": {"purpose": "test"},
                "containers": [{"id": "cloud", "label": "AWS Cloud",
                                "type": "aws_cloud"}],
                "nodes": [
                    {"id": "w1", "label": "左上", "icon": "ec2",
                     "parent": "cloud", "col": 0, "row": 0},
                    {"id": "w2", "label": "右上", "icon": "ec2",
                     "parent": "cloud", "col": 2, "row": 0},
                    {"id": "ct", "label": "監査", "icon": "cloudtrail",
                     "parent": "cloud", "col": 1, "row": 3},
                    {"id": "blk", "label": "ブロッカ", "icon": "ecr",
                     "parent": "cloud", "col": 1, "row": 4}],
                "edges": [{"id": "e1", "src": "cloud", "dst": "ct",
                           "kind": "ops", "label": "監査"}]}
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "cont.spec.json"
            cp.write_text(json.dumps(spec, ensure_ascii=False),
                          encoding="utf-8")
            r = run_build(cp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("=== 0 error(s)", r.stdout)      # E3 貫通なし
        self.assertNotIn("代替配線", r.stdout)          # 探索で配線できている

    def _run(self, spec):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "v.spec.json"
            cp.write_text(json.dumps(spec, ensure_ascii=False),
                          encoding="utf-8")
            return run_build(cp)

    def test_child_to_ancestor_container(self):
        # 変種1: 子ノード → 祖先コンテナ(逆向きの内包エッジ)
        spec = {"name": "v1", "meta": {"purpose": "test"},
                "containers": [{"id": "cloud", "label": "Cloud",
                                "type": "aws_cloud"},
                               {"id": "vpc", "label": "VPC", "type": "vpc",
                                "parent": "cloud"}],
                "nodes": [
                    {"id": "a", "label": "A", "icon": "ec2",
                     "parent": "vpc", "col": 0, "row": 0},
                    {"id": "b", "label": "B", "icon": "ec2",
                     "parent": "vpc", "col": 1, "row": 0},
                    {"id": "cw", "label": "CW", "icon": "cloudwatch_2",
                     "parent": "cloud", "col": 3, "row": 0}],
                "edges": [{"id": "e1", "src": "a", "dst": "cloud",
                           "kind": "ops", "label": "監査"},
                          {"id": "e2", "src": "a", "dst": "b",
                           "kind": "main"}]}
        r = self._run(spec)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("=== 0 error(s)", r.stdout)

    def test_container_to_contained_container(self):
        # 変種2: コンテナ → 内包コンテナ(cloud→vpc)
        spec = {"name": "v2", "meta": {"purpose": "test"},
                "containers": [{"id": "cloud", "label": "Cloud",
                                "type": "aws_cloud"},
                               {"id": "vpc", "label": "VPC", "type": "vpc",
                                "parent": "cloud"}],
                "nodes": [
                    {"id": "a", "label": "A", "icon": "ec2",
                     "parent": "vpc", "col": 0, "row": 0},
                    {"id": "out", "label": "外", "icon": "s3",
                     "parent": "cloud", "col": 2, "row": 2}],
                "edges": [{"id": "e1", "src": "cloud", "dst": "vpc",
                           "kind": "ops", "label": "統制"}]}
        r = self._run(spec)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("=== 0 error(s)", r.stdout)

    def test_multiple_containment_edges_same_container(self):
        # 変種3: 同一コンテナ端点へ複数本(端点集約の上限 1〜2 本の実挙動)
        spec = {"name": "v3", "meta": {"purpose": "test"},
                "containers": [{"id": "cloud", "label": "Cloud",
                                "type": "aws_cloud"},
                               {"id": "vpc", "label": "VPC", "type": "vpc",
                                "parent": "cloud"}],
                "nodes": [
                    {"id": "a", "label": "A", "icon": "ec2",
                     "parent": "vpc", "col": 0, "row": 0},
                    {"id": "b", "label": "B", "icon": "ec2",
                     "parent": "vpc", "col": 1, "row": 0},
                    {"id": "cw", "label": "CW", "icon": "cloudwatch_2",
                     "parent": "cloud", "col": 3, "row": 0},
                    {"id": "cfg", "label": "Config", "icon": "config",
                     "parent": "cloud", "col": 3, "row": 2}],
                "edges": [{"id": "e1", "src": "vpc", "dst": "cw",
                           "kind": "ops", "label": "メトリクス"},
                          {"id": "e2", "src": "vpc", "dst": "cfg",
                           "kind": "ops", "label": "構成記録"},
                          {"id": "e3", "src": "a", "dst": "b",
                           "kind": "main"}]}
        r = self._run(spec)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("=== 0 error(s)", r.stdout)


class TestValidatorW9(unittest.TestCase):
    """W9(コンテナ階層の慣例)のバリデータ側検査。

    従来はビルド時のみで、手編集した既存 .drawio を validate だけ通す経路では
    VPC 二重入れ子などがすり抜けた(レビュー指摘 2026-07-15)。スタイル署名から
    型を推定して検査し、判別できない独自スタイルはスキップ(偽陽性なし)。
    """

    def _validate(self, path):
        return subprocess.run([sys.executable, str(VALIDATE), str(path)],
                              capture_output=True, text=True, timeout=30)

    def _build_two_vpc(self, tmp: Path) -> Path:
        spec = {"name": "w9", "meta": {"purpose": "test"},
                "containers": [
                    {"id": "cloud", "label": "Cloud", "type": "aws_cloud"},
                    {"id": "vpc1", "label": "VPC-1", "type": "vpc",
                     "parent": "cloud"},
                    {"id": "vpc2", "label": "VPC-2", "type": "vpc",
                     "parent": "cloud"}],
                "nodes": [{"id": "a", "label": "A", "icon": "ec2",
                           "parent": "vpc1", "col": 0, "row": 0},
                          {"id": "b", "label": "B", "icon": "ec2",
                           "parent": "vpc2", "col": 3, "row": 0}],
                "edges": []}
        r = build_spec(spec, tmp, "w9")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return tmp / "w9.spec.out.drawio"

    def test_vpc_inside_vpc_warns(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as td:
            out = self._build_two_vpc(Path(td))
            t = ET.parse(out)
            cells = {c.get("id"): c for c in t.iter("mxCell")}
            # 手編集を模す: vpc2 を vpc1 の内側へ(幾何も内側に収める)
            g1 = cells["vpc1"].find("mxGeometry")
            g1.set("width", "420"); g1.set("height", "320")
            v2 = cells["vpc2"]
            v2.set("parent", "vpc1")
            g2 = v2.find("mxGeometry")
            g2.set("x", "180"); g2.set("y", "60")
            g2.set("width", "200"); g2.set("height", "180")
            gb = cells["b"].find("mxGeometry")
            gb.set("x", "60"); gb.set("y", "60")
            broken = Path(td) / "broken.drawio"
            t.write(broken, encoding="unicode")
            r = self._validate(broken)
        self.assertIn("W9", r.stdout, r.stdout)
        self.assertIn("vpc", r.stdout)

    def test_correct_hierarchy_silent(self):
        # cloud>region>vpc>subnet の正階層と ECS 入れ子(generic>auto_scaling>
        # ec2_contents)は W9 を出さない
        spec = {"name": "ok", "meta": {"purpose": "test"},
                "containers": [
                    {"id": "cloud", "label": "Cloud", "type": "aws_cloud"},
                    {"id": "rg", "label": "Region", "type": "region",
                     "parent": "cloud"},
                    {"id": "vpc", "label": "VPC", "type": "vpc",
                     "parent": "rg"},
                    {"id": "pub", "label": "Public", "type": "public_subnet",
                     "parent": "vpc"},
                    {"id": "cl", "label": "ECS Cluster", "type": "generic",
                     "parent": "rg"},
                    {"id": "svc", "label": "Service", "type": "auto_scaling",
                     "parent": "cl"}],
                "nodes": [{"id": "a", "label": "A", "icon": "ec2",
                           "parent": "pub", "col": 0, "row": 0},
                          {"id": "t1", "label": "Task", "icon": "ec2",
                           "parent": "svc", "col": 3, "row": 0}],
                "edges": []}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "ok")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            v = self._validate(Path(td) / "ok.spec.out.drawio")
        self.assertNotIn("W9", v.stdout, v.stdout)


class TestIconAliases(unittest.TestCase):
    """よく使う略称の解決と、候補提示のプロバイダ絞り込み。"""

    @classmethod
    def setUpClass(cls):
        from _common import load_icons
        cls.icons = load_icons()

    def test_alias_resolves(self):
        from _common import resolve_icon
        self.assertEqual(resolve_icon(self.icons, "cloudwatch")["name"],
                         "cloudwatch_2")
        self.assertEqual(resolve_icon(self.icons, "ses")["name"],
                         "simple_email_service")
        self.assertEqual(resolve_icon(self.icons, "kms")["name"],
                         "key_management_service")

    def test_suggestions_scoped_to_provider(self):
        from _common import resolve_icon
        with self.assertRaises(LookupError) as cm:
            resolve_icon(self.icons, "zzz_no_such_icon")
        self.assertNotIn("azure:", str(cm.exception))  # 無印は AWS 候補のみ
        with self.assertRaises(LookupError) as cm:
            resolve_icon(self.icons, "azure:frontdoor")
        self.assertIn("azure:front_doors", str(cm.exception))


class TestOptimizeDeterminism(unittest.TestCase):
    """--optimize: 予算内で収束する入力なら 2 回実行でバイト一致。"""

    def test_two_runs_identical(self):
        spec = {"name": "opt", "meta": {"purpose": "test"},
                "nodes": [
                    {"id": "a", "label": "A", "icon": "ec2", "col": 0, "row": 0},
                    {"id": "b", "label": "B", "icon": "ec2", "col": 0, "row": 1},
                    {"id": "x", "label": "X", "icon": "s3", "col": 2, "row": 0},
                    {"id": "y", "label": "Y", "icon": "s3", "col": 2, "row": 1}],
                "edges": [
                    {"id": "e1", "src": "a", "dst": "y", "kind": "main"},
                    {"id": "e2", "src": "b", "dst": "x", "kind": "main"}]}
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as td:
                cp = Path(td) / "opt.spec.json"
                cp.write_text(json.dumps(spec, ensure_ascii=False),
                              encoding="utf-8")
                r = run_build(cp, "--optimize", "5")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                outs.append((Path(td) / "opt.spec.out.drawio").read_bytes())
        self.assertEqual(outs[0], outs[1])


class TestOptimizeLabelOverlap(unittest.TestCase):
    """--optimize: 交差を減らす代わりにラベル重なり(E1)を作る手を採用しない。

    全角 2 行ラベル(1 行 32 文字)は列幅上限 290px を超えて隣列へはみ出す
    ため、長ラベル同士を横に隣接させる移動は E1 になる。修正前はこの移動が
    「交差 1 → 0」で採用されて E1 を量産していた(実案件フィードバック)。
    """

    LBL = "長い日本語ラベル" * 4  # 32 文字 × 2 行 → 幅 390px > 列幅上限 290px

    def _spec(self):
        return {"name": "opt-lbl", "meta": {"purpose": "test"},
                "nodes": [
                    {"id": "a", "icon": "ec2", "col": 0, "row": 0,
                     "label": f"{self.LBL}\n{self.LBL}"},
                    {"id": "b", "icon": "s3", "col": 0, "row": 1,
                     "label": f"{self.LBL}\n{self.LBL}"},
                    {"id": "x", "icon": "lambda", "col": 2, "row": 0,
                     "label": f"{self.LBL}\n{self.LBL}"},
                    {"id": "y", "icon": "rds", "col": 2, "row": 1,
                     "label": f"{self.LBL}\n{self.LBL}"}],
                "edges": [
                    {"id": "e1", "src": "a", "dst": "y", "kind": "main"},
                    {"id": "e2", "src": "b", "dst": "x", "kind": "main"}]}

    def test_optimize_does_not_create_e1(self):
        with tempfile.TemporaryDirectory() as td:
            # 初期配置は E1 なし(重なりを「新規に作らない」ことの前提)
            r0 = build_spec(self._spec(), Path(td), "base")
            self.assertEqual(r0.returncode, 0, r0.stdout + r0.stderr)
            # 最適化後も E1 なし、かつ交差の改善(OPT 行)はあきらめない
            r1 = build_spec(self._spec(), Path(td), "opt", "--optimize", "5")
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            self.assertNotIn("E1", r1.stdout + r1.stderr)
            self.assertIn("OPT:", r1.stdout)

    def test_eval_layout_overlap_first_key(self):
        from _common import load_icons
        icons = load_icons()
        spec = {"name": "t", "meta": {"purpose": "test"},
                "nodes": [
                    {"id": "a", "icon": "ec2", "col": 0, "row": 0,
                     "label": self.LBL},
                    {"id": "b", "icon": "s3", "col": 1, "row": 0,
                     "label": self.LBL}],
                "edges": []}
        score, _prob = B.eval_layout(spec, icons, draft=False)
        self.assertGreaterEqual(score[0], 1)  # 隣接列の長ラベル → 重なり検出
        spec["nodes"][1]["col"] = 3           # 1 列空ければ重なりゼロ
        score, _prob = B.eval_layout(spec, icons, draft=False)
        self.assertEqual(score[0], 0)


class TestEmitSvg(unittest.TestCase):
    """--emit-svg: 自己完結 SVG が出力され、要素数が図と対応する。"""

    def test_svg_structure(self):
        import xml.etree.ElementTree as ET
        spec_path = ROOT / "templates" / "example-3tier.spec.json"
        tab = json.loads(spec_path.read_text(encoding="utf-8"))
        tab = tab.get("diagrams", [tab])[0]
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / spec_path.name
            shutil.copy(spec_path, cp)
            r = run_build(cp, "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            svg_path = Path(td) / (cp.stem + ".out.svg")
            self.assertTrue(svg_path.exists(),
                            sorted(p.name for p in Path(td).iterdir()))
            text = svg_path.read_text(encoding="utf-8")
        root = ET.fromstring(text)  # well-formed の確認を兼ねる
        ns = "{http://www.w3.org/2000/svg}"
        rects = len(root.findall(f".//{ns}rect"))
        polys = len(root.findall(f".//{ns}polyline"))
        self.assertGreaterEqual(rects, len(tab["nodes"]))
        self.assertEqual(polys, len(tab["edges"]) + len(tab.get("legend") or ()))
        self.assertNotIn("href", text)  # 外部リソース参照なし(自己完結)


class TestEmitPngAndWrap(unittest.TestCase):
    """--emit-png(CLI 検出/フォールバック)と whiteSpace=wrap の SVG 折り返し。"""

    def test_emit_png_render_or_fallback(self):
        spec_path = ROOT / "templates" / "example-3tier.spec.json"
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / spec_path.name
            shutil.copy(spec_path, cp)
            r = run_build(cp, "--emit-png")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            png = Path(td) / (cp.stem + ".out.png")
            svg = Path(td) / (cp.stem + ".out.svg")
            if B.find_drawio_cli():
                self.assertTrue(png.exists(), r.stdout)
                self.assertGreater(png.stat().st_size, 10_000)
            else:  # CLI 不在環境(CI 等): SVG フォールバック+通知
                self.assertIn("フォールバック", r.stdout)
                self.assertTrue(svg.exists(), r.stdout)

    def test_wrap_text_px_within_width(self):
        from _common import text_width
        cases = [("前提: 情報源は Terraform 静的解析。Lambda コードの確認を"
                  "要する長い前提の文章がパネル幅を超える", 180),
                 ("access log delivered to the bucket via firehose", 120)]
        for s, w in cases:
            wrapped = B._wrap_text_px(s, w, 11)
            for ln in wrapped.split("\n"):
                self.assertLessEqual(text_width(ln, 11), w, (s, ln))
            # 折り返しで文字を落とさない(語境界で捨てるのは空白のみ)
            self.assertEqual(wrapped.replace("\n", "").replace(" ", ""),
                             s.replace(" ", ""))

    def test_meta_panel_wraps_in_svg(self):
        # 長い meta 前提文が SVG でも複数行に折り返される(実 .drawio の
        # whiteSpace=wrap と同じ見た目 → 「見切れ?」の偽疑いを出さない)
        spec = {"name": "wrap",
                "meta": {"purpose": "検証", "assumptions": "あ" * 120},
                "nodes": [{"id": "a", "label": "A", "icon": "ec2",
                           "col": 0, "row": 0},
                          {"id": "b", "label": "B", "icon": "s3",
                           "col": 2, "row": 0}],
                "edges": [{"id": "e1", "src": "a", "dst": "b",
                           "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "wrap", "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            svg = (Path(td) / "wrap.spec.out.svg").read_text(encoding="utf-8")
        # 「あ…」の連が複数 tspan(=複数行)に分割されている
        self.assertGreaterEqual(svg.count("あ</tspan>"), 2, svg[:600])


class TestHubHint(unittest.TestCase):
    """配置原則6: 次数7以上のハブに HINT が出て、リング配置なら成立する。"""

    def _build(self, cells: list[tuple[int, int]], hub: tuple[int, int]):
        nodes = [{"id": "hub", "label": "GW", "icon": "transit_gateway",
                  "col": hub[0], "row": hub[1]}]
        nodes += [{"id": f"s{i}", "label": f"svc{i}", "icon": "ec2",
                   "col": c, "row": r} for i, (c, r) in enumerate(cells)]
        spec = {"name": "hub", "meta": {"purpose": "test"}, "nodes": nodes,
                "edges": [{"id": f"e{i}", "src": "hub", "dst": f"s{i}",
                           "kind": "main"} for i in range(len(cells))]}
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "hub.spec.json"
            cp.write_text(json.dumps(spec, ensure_ascii=False),
                          encoding="utf-8")
            return run_build(cp)

    def test_nine_spokes_hint(self):
        cells = [(c, r) for c in (2, 3, 4) for r in (0, 1, 2)]  # 9 スポーク
        r = self._build(cells, hub=(1, 1))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("配置原則6", r.stdout)
        self.assertIn("次数が 9", r.stdout)

    def test_ring_layout_clean(self):
        cells = [(c, r) for c in (0, 1, 2) for r in (0, 1, 2)
                 if (c, r) != (1, 1)]  # 8近傍リング
        r = self._build(cells, hub=(1, 1))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("=== 0 error(s)", r.stdout)
        self.assertNotIn("[WARN] I1", r.stdout)  # 交差が目安内


class TestForeignTransit(unittest.TestCase):
    """無関係な境界コンテナ(他クラウド・他アカウント)を線が突っ切らない。

    判定は端点込みの全セグメント対矩形(waypoint の点判定だけだと
    曲がりのない直線貫通を見逃す — 実際に見逃した経緯あり)。
    """

    def assert_no_transit(self, tab: dict, xml: str):
        pmap = {}
        cmap = {c["id"]: c for c in tab.get("containers", [])}
        for c in tab.get("containers", []):
            pmap[c["id"]] = c.get("parent")
        for n in tab["nodes"]:
            pmap[n["id"]] = n.get("parent")

        def anc(t):
            out = set()
            cur = pmap.get(t)
            while cur:
                out.add(cur)
                cur = pmap.get(cur)
            return out

        geo, parent_of = {}, {}
        for m in re.finditer(
                r'<mxCell id="([^"]+)"[^>]*?parent="([^"]*)"[^>]*>\s*'
                r'<mxGeometry x="([\d.-]+)" y="([\d.-]+)" '
                r'width="([\d.]+)" height="([\d.]+)"', xml):
            geo[m.group(1)] = tuple(map(float, m.groups()[2:]))
            parent_of[m.group(1)] = m.group(2)

        def absr(nid):
            x, y, w, h = geo[nid]
            p = parent_of.get(nid)
            while p in geo:
                x += geo[p][0]
                y += geo[p][1]
                p = parent_of.get(p)
            return (x, y, x + w, y + h)

        bounds = [cid for cid in cmap
                  if pmap.get(cid) is None
                  or cmap[cid].get("type") in B.BOUNDARY_TRANSIT]
        boxes = {cid: absr(cid) for cid in bounds}
        for em in re.finditer(r'<mxCell id="(\w+)"[^>]*?style="([^"]*)"[^>]*?'
                              r'source="(\w+)" target="(\w+)".*?</mxCell>',
                              xml, re.S):
            eid, style, s, t = em.groups()
            related = anc(s) | anc(t) | {s, t}
            fr = dict(kv.split("=", 1) for kv in style.rstrip(";").split(";")
                      if "=" in kv)
            poly = [(float(a), float(b)) for a, b in
                    re.findall(r'<mxPoint x="([\d.-]+)" y="([\d.-]+)" />',
                               em.group(0))]
            if {"exitX", "exitY", "entryX", "entryY"} <= fr.keys():
                x1, y1, x2, y2 = absr(s)
                poly.insert(0, (x1 + (x2 - x1) * float(fr["exitX"]),
                                y1 + (y2 - y1) * float(fr["exitY"])))
                x1, y1, x2, y2 = absr(t)
                poly.append((x1 + (x2 - x1) * float(fr["entryX"]),
                             y1 + (y2 - y1) * float(fr["entryY"])))
            for cid in bounds:
                if cid in related:
                    continue
                bx1, by1, bx2, by2 = boxes[cid]
                bx1, by1, bx2, by2 = bx1 + 2, by1 + 2, bx2 - 2, by2 - 2
                for (ax, ay), (bx, by) in zip(poly, poly[1:]):
                    if abs(ay - by) < 1:  # 水平セグメント
                        hit = (by1 < ay < by2 and min(ax, bx) < bx2
                               and max(ax, bx) > bx1)
                    else:  # 垂直セグメント
                        hit = (bx1 < ax < bx2 and min(ay, by) < by2
                               and max(ay, by) > by1)
                    self.assertFalse(
                        hit, f"edge '{eid}' が無関係な '{cid}' を貫通: "
                             f"({ax:.0f},{ay:.0f})-({bx:.0f},{by:.0f})")

    def build_tab(self, tab: dict, name: str) -> str:
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / f"{name}.spec.json"
            cp.write_text(json.dumps(tab, ensure_ascii=False),
                          encoding="utf-8")
            r = run_build(cp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return (Path(td) / f"{name}.spec.out.drawio").read_text(
                encoding="utf-8")

    def test_multicloud_no_transit(self):
        spec_path = ROOT / "templates" / "example-multicloud.spec.json"
        tab = json.loads(spec_path.read_text(encoding="utf-8"))["diagrams"][0]
        self.assert_no_transit(tab, self.build_tab(tab, "mc"))

    def test_nested_account_no_transit(self):
        # A→C の直進経路が空きセルの多い B アカウントを貫通したくなる形
        tab = {"name": "acct", "meta": {"purpose": "test"},
               "containers": [
                   {"id": "org", "label": "AWS Cloud", "type": "aws_cloud"},
                   {"id": "a", "label": "Network", "type": "account",
                    "parent": "org"},
                   {"id": "b", "label": "Security", "type": "account",
                    "parent": "org"},
                   {"id": "c", "label": "Workload", "type": "account",
                    "parent": "org"}],
               "nodes": [
                   {"id": "tgw", "label": "TGW", "icon": "transit_gateway",
                    "parent": "a", "col": 0, "row": 1},
                   {"id": "hub", "label": "Hub", "icon": "security_hub",
                    "parent": "b", "col": 1, "row": 0},
                   {"id": "ct", "label": "Trail", "icon": "cloudtrail",
                    "parent": "b", "col": 2, "row": 2},
                   {"id": "alb", "label": "ALB",
                    "icon": "application_load_balancer",
                    "parent": "c", "col": 3, "row": 1}],
               "edges": [{"id": "e1", "src": "tgw", "dst": "alb",
                          "kind": "main", "label": "接続"}]}
        self.assert_no_transit(tab, self.build_tab(tab, "acct"))


class TestFlowchart(unittest.TestCase):
    def test_flow_shapes_build(self):
        spec = {"name": "flow", "meta": {"purpose": "test"},
                "containers": [{"id": "l1", "label": "A", "type": "lane"}],
                "nodes": [
                    {"id": "s", "shape": "terminator", "label": "開始",
                     "parent": "l1", "col": 0, "row": 0},
                    {"id": "p", "shape": "process", "label": "処理する",
                     "parent": "l1", "col": 0, "row": 1},
                    {"id": "d", "shape": "decision", "label": "OK?",
                     "parent": "l1", "col": 0, "row": 2},
                    {"id": "e", "shape": "terminator", "label": "終了",
                     "parent": "l1", "col": 0, "row": 3}],
                "edges": [
                    {"id": "f1", "src": "s", "dst": "p", "kind": "main"},
                    {"id": "f2", "src": "p", "dst": "d", "kind": "main"},
                    {"id": "f3", "src": "d", "dst": "e", "kind": "main",
                     "label": "はい"},
                    {"id": "f4", "src": "d", "dst": "p", "kind": "sub",
                     "label": "いいえ"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "flow")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            xml = (Path(td) / "flow.spec.out.drawio").read_text(encoding="utf-8")
            self.assertIn("rhombus", xml)
            self.assertIn("arcSize=50", xml)

    def test_unknown_shape_rejected(self):
        spec = {"nodes": [{"id": "a", "shape": "hexagon", "col": 0, "row": 0}]}
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(spec)
        self.assertIn("未知", str(cm.exception))


class TestDumpSpec(unittest.TestCase):
    def test_roundtrip(self):
        spec = {"diagrams": [{"name": "t", "meta": {"purpose": "x"},
                              "nodes": [{"id": "a", "icon": "ec2",
                                         "col": 0, "row": 0}],
                              "edges": []}]}
        p = Path(tempfile.mkstemp(suffix=".json")[1])
        try:
            B.dump_spec(spec, p)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), spec)
            self.assertIn('{"id": "a"', p.read_text(encoding="utf-8"))
        finally:
            p.unlink()




class TestTfToSpec(unittest.TestCase):
    """tf_to_spec: HCL パーサと変換の回帰(認証ゼロ・静的解析)。"""

    TF = '''
variable "enable_dr" { default = false }

resource "aws_apigatewayv2_api" "api" {
  name          = "orders-api"   # コメントは無視される
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "i" {
  api_id          = aws_apigatewayv2_api.api.id
  integration_uri = aws_lambda_function.fn.invoke_arn
}

resource "aws_lambda_function" "fn" {
  function_name = "fn"
  filename      = "${path.module}/dist/fn.zip"
  handler       = "h.main"
  policy        = <<EOT
{"ignore": "aws_s3_bucket.phantom"}
EOT
  environment {
    variables = { TABLE = aws_dynamodb_table.t.name }
  }
}

resource "aws_dynamodb_table" "t" {
  name     = "t"
  hash_key = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "dr" {
  count    = var.enable_dr ? 1 : 0
  name     = "dr"
  hash_key = "id"
}

resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }
resource "aws_subnet" "pub" {
  vpc_id                  = aws_vpc.v.id
  map_public_ip_on_launch = true
}
resource "aws_instance" "web" { subnet_id = aws_subnet.pub.id }
resource "aws_iam_role" "r" { name = "r" }
'''

    def _convert(self, tmp: Path):
        import tf_to_spec as T
        (tmp / "main.tf").write_text(self.TF, encoding="utf-8")
        (tmp / "modules" / "orphan").mkdir(parents=True)
        (tmp / "modules" / "orphan" / "main.tf").write_text(
            'resource "aws_sns_topic" "x" { name = "x" }', encoding="utf-8")
        return T.convert(tmp, None)

    def test_parser_blocks_and_refs(self):
        import tf_to_spec as T
        blocks = T.parse_hcl(self.TF, "main.tf")
        types = {b.btype for b in blocks}
        self.assertIn("resource", types)
        fn = next(b for b in blocks if b.labels[:2] ==
                  ["aws_lambda_function", "fn"])
        # heredoc 本文の参照は拾わない(phantom が漏れたら誤エッジの元)
        self.assertNotIn("aws_s3_bucket.phantom",
                         " ".join(T.all_refs(fn)))
        env = fn.find("environment")[0]
        self.assertIn("aws_dynamodb_table.t",
                      " ".join(T.refs_in(env.attrs.get("variables", ""))))

    def test_convert_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            spec, review = self._convert(Path(td))
        ids = {n["id"]: n for n in spec["nodes"]}
        self.assertIn("api", ids)            # API GW は plumbing に食われない
        self.assertIn("fn", ids)
        self.assertNotIn("r", ids)           # IAM はノードにしない
        self.assertEqual(ids["web"]["parent"], "pub")   # サブネット所属
        conts = {c["id"]: c for c in spec["containers"]}
        self.assertEqual(conts["pub"]["type"], "public_subnet")
        self.assertEqual(conts["pub"]["parent"], "v")
        pairs = {(e["src"], e["dst"]) for e in spec["edges"]}
        self.assertIn(("api", "fn"), pairs)  # 統合 → 確定エッジ
        self.assertIn(("fn", "t"), pairs)    # env var 参照 → 確定エッジ
        self.assertIn("[条件付き]", ids["dr"]["label"])
        notes = " ".join(review["notes"])
        self.assertIn("enable_dr", notes)    # count フラグ注記
        self.assertIn("orphan", notes)       # 未参照モジュール注記
        lam = review["lambda_code_review"][0]
        self.assertIn("code=", " ".join(lam["hints"]))  # ソースなしの明示

    def test_generated_spec_builds_clean(self):
        with tempfile.TemporaryDirectory() as td:
            spec, _ = self._convert(Path(td))
            r = build_spec(spec, Path(td), "tf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout)

    def test_module_reuse_and_indirect_refs(self):
        """敵対的レビューの再発防止: モジュール使い回し・間接参照・誤親。"""
        import tf_to_spec as T
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "modules" / "app").mkdir(parents=True)
            (tmp / "modules" / "app" / "main.tf").write_text("""
resource "aws_sqs_queue" "q" { name = "q" }
output "queue_url" { value = aws_sqs_queue.q.url }
""", encoding="utf-8")
            (tmp / "main.tf").write_text("""
module "us" { source = "./modules/app" }
module "eu" { source = "./modules/app" }

resource "aws_lambda_function" "api" {
  function_name = "api"
  filename      = "a.zip"
  environment {
    variables = { QUEUE = module.us.queue_url }
  }
  tags = { note = aws_vpc.v.id }
}
resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }
resource "aws_subnet" "s" { vpc_id = aws_vpc.v.id }
resource "aws_instance" "one_liner" { ami = "x" subnet_id = aws_subnet.s.id }
""", encoding="utf-8")
            spec, review = T.convert(tmp, None)
        ids = {n["id"]: n for n in spec["nodes"]}
        # 使い回しモジュールは両インスタンス展開される(F1)
        self.assertIn("us__q", ids)
        self.assertIn("eu__q", ids)
        notes = " ".join(review["notes"])
        self.assertNotIn("循環", notes)
        self.assertNotIn("未参照", notes)          # F5: 呼ばれているので誤検出しない
        # module 出力経由の env var がエッジになる(F4)
        pairs = {(e["src"], e["dst"]) for e in spec["edges"]}
        self.assertIn(("api", "us__q"), pairs)
        # tags の言及では VPC に入らない(F2)/ 1 行複数属性でも所属が取れる
        self.assertEqual(ids["api"]["parent"], "cloud")
        self.assertEqual(ids["one_liner"]["parent"], "s")

    def test_state_canary_never_leaks(self):
        """--state の秘密値が出力のどこにも漏れない(恒久カナリア検査)。

        state には DB パスワード等が平文で入る。ツールは type/name の
        位相情報だけを読む設計 — その保証をバイト検索で常時検証する。"""
        import subprocess
        CANARY = "CANARY_SECRET_hunter2_zz93"
        tool = Path(__file__).resolve().parent / "tf_to_spec.py"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "main.tf").write_text(
                'resource "aws_db_instance" "db" { identifier = "db" }\n'
                'resource "aws_s3_bucket" "b" { bucket = "b" }\n',
                encoding="utf-8")
            # state pull 形式: attributes / outputs に秘密値
            pull = tmp / "state.json"
            pull.write_text(json.dumps({
                "version": 4,
                "outputs": {"pw": {"value": CANARY, "sensitive": True}},
                "resources": [
                    {"mode": "managed", "type": "aws_db_instance",
                     "name": "db", "instances": [{"attributes": {
                         "identifier": "db", "password": CANARY}}]},
                ],
            }), encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(tool), td,
                 "-o", f"{td}/o.spec.json", "--review", f"{td}/o.review.json",
                 "--state", str(pull)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            blobs = {
                "stdout": r.stdout, "stderr": r.stderr,
                "spec": (tmp / "o.spec.json").read_text(encoding="utf-8"),
                "review": (tmp / "o.review.json").read_text(encoding="utf-8"),
            }
            for where, blob in blobs.items():
                self.assertNotIn(CANARY, blob, f"秘密値が {where} に漏れた")
            # s3 バケットは state に無い → 未適用の注記が出る(照合が効いている)
            self.assertIn("state に存在しない", blobs["review"])
            # 壊れた state(カナリア入り)のエラー文言にも値が漏れない
            broken = tmp / "broken.json"
            broken.write_text('{"password": "' + CANARY + '"',
                              encoding="utf-8")
            r2 = subprocess.run(
                [sys.executable, str(tool), td, "--state", str(broken)],
                capture_output=True, text=True)
            self.assertNotEqual(r2.returncode, 0)
            self.assertNotIn(CANARY, r2.stdout + r2.stderr,
                             "秘密値がエラー文言に漏れた")

    def test_state_ids_both_formats(self):
        import tf_to_spec as T
        with tempfile.TemporaryDirectory() as td:
            pull = Path(td) / "pull.json"
            pull.write_text(json.dumps({"resources": [
                {"mode": "managed", "type": "aws_s3_bucket", "name": "b"},
                {"mode": "data", "type": "aws_ami", "name": "x"}]}),
                encoding="utf-8")
            self.assertEqual(T.load_state_ids(pull), {"aws_s3_bucket.b"})
            show = Path(td) / "show.json"
            show.write_text(json.dumps({"values": {"root_module": {
                "resources": [{"address": "aws_sqs_queue.q"}],
                "child_modules": [{"resources": [
                    {"address": "module.m.aws_sns_topic.t"}]}]}}}),
                encoding="utf-8")
            self.assertEqual(T.load_state_ids(show),
                             {"aws_sqs_queue.q", "aws_sns_topic.t"})


class TestTfForEachAndOrphan(unittest.TestCase):
    """tf_to_spec: for_each 展開・インスタンス指定エッジ・レガシーモジュール注記。

    従来の取りこぼし(e15 evalで実証): for_each リソースが黙って 1 ノードに
    縮約され、出力未参照のモジュールが無警告で稼働構成に混入していた。"""

    TF = '''
locals {
  fns = {
    ingest    = { dir = "src/ingest" }
    transform = { dir = "src/transform" }
  }
}

resource "aws_dynamodb_table" "t" {
  name     = "t"
  hash_key = "id"
}

resource "aws_lambda_function" "fn" {
  for_each      = local.fns
  function_name = "evt-${each.key}"
  filename      = each.value.dir
  handler       = "index.handler"
  environment {
    variables = {
      TABLE = aws_dynamodb_table.t.name
      QUEUE = module.q.url
    }
  }
}

module "q" {
  source = "./modules/q"
}

module "legacy" {
  source = "./modules/legacy"
}

resource "aws_lambda_event_source_mapping" "m" {
  event_source_arn = module.q.arn
  function_name    = aws_lambda_function.fn["transform"].arn
}

resource "aws_lambda_function" "opaque" {
  for_each      = var.unknown_map
  function_name = "x"
  filename      = "x.zip"
  handler       = "h"
}
'''

    Q = '''
resource "aws_sqs_queue" "main" { name = "q" }
output "url" { value = aws_sqs_queue.main.url }
output "arn" { value = aws_sqs_queue.main.arn }
'''

    LEG = 'resource "aws_s3_bucket" "old" { bucket = "old" }'

    def _convert(self, tmp: Path):
        import tf_to_spec as T
        (tmp / "main.tf").write_text(self.TF, encoding="utf-8")
        for name, body in (("q", self.Q), ("legacy", self.LEG)):
            d = tmp / "modules" / name
            d.mkdir(parents=True)
            (d / "main.tf").write_text(body, encoding="utf-8")
        src = tmp / "src" / "ingest"
        src.mkdir(parents=True)
        (src / "index.js").write_text("//", encoding="utf-8")
        return T.convert(tmp, None)

    def test_foreach_expansion_and_keyed_edges(self):
        with tempfile.TemporaryDirectory() as td:
            spec, review = self._convert(Path(td))
        ids = {n["id"] for n in spec["nodes"]}
        self.assertIn("fn_ingest", ids)
        self.assertIn("fn_transform", ids)
        pairs = {(e["src"], e["dst"]) for e in spec["edges"]}
        # env var は全インスタンスから、ESM はキー指定インスタンスだけへ
        self.assertIn(("fn_ingest", "t"), pairs)
        self.assertIn(("fn_transform", "t"), pairs)
        self.assertIn(("q__main", "fn_transform"), pairs)
        self.assertNotIn(("q__main", "fn_ingest"), pairs)
        notes = " ".join(review["notes"])
        self.assertIn("for_each を 2 インスタンスに展開", notes)
        # キー解決不能な for_each は縮約のまま注記(黙らない)
        self.assertIn("opaque", ids)
        self.assertIn("静的解決できず", notes)

    def test_orphan_output_module_note(self):
        with tempfile.TemporaryDirectory() as td:
            _, review = self._convert(Path(td))
        notes = " ".join(review["notes"])
        self.assertIn("モジュール legacy", notes)          # 出力未参照 → 注記
        self.assertNotIn("モジュール q:", notes)           # 使用中 → 注記なし

    def test_source_hint_from_existing_filename(self):
        with tempfile.TemporaryDirectory() as td:
            _, review = self._convert(Path(td))
        ing = next(l for l in review["lambda_code_review"]
                   if l["node"] == "fn_ingest")
        self.assertTrue(any(h.startswith("source=") and "src/ingest" in h
                            for h in ing["hints"]), ing["hints"])
        # 実在しないパスは source に昇格しない(transform 側)
        tra = next(l for l in review["lambda_code_review"]
                   if l["node"] == "fn_transform")
        self.assertFalse(any(h.startswith("source=") for h in tra["hints"]),
                         tra["hints"])


class TestOnBoundary(unittest.TestCase):
    """on_boundary: ゲートウェイ系を親コンテナの枠線上センターまたぎに描く。"""

    SPEC = {
        "name": "t",
        "meta": {"purpose": "test", "updated": "2026-07-15"},
        "containers": [{"id": "vpc", "label": "VPC", "type": "vpc"}],
        "nodes": [
            {"id": "users", "label": "Users", "icon": "users",
             "col": 0, "row": 0},
            {"id": "igw", "label": "IGW", "icon": "internet_gateway",
             "parent": "vpc", "col": 1, "row": 0, "on_boundary": "left"},
            {"id": "alb", "label": "ALB", "icon": "application_load_balancer",
             "parent": "vpc", "col": 2, "row": 0},
            {"id": "ec2", "label": "EC2", "icon": "ec2",
             "parent": "vpc", "col": 3, "row": 0}],
        "edges": [
            {"id": "e1", "src": "users", "dst": "igw", "kind": "main"},
            {"id": "e2", "src": "igw", "dst": "alb", "kind": "main"},
            {"id": "e3", "src": "alb", "dst": "ec2", "kind": "main"}]}

    def test_igw_straddles_parent_left_border(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(self.SPEC, tmp, "onb")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout, r.stdout)
            xml = (tmp / "onb.spec.out.drawio").read_text(encoding="utf-8")
            cells = {c.get("id"): c for c in
                     ET.fromstring(xml).iter("mxCell")}
            igw = cells["igw"]
            # XML 親は vpc → 相対座標。中心 x ≈ 0 が「親の左枠線上」
            self.assertEqual(igw.get("parent"), "vpc")
            g = igw.find("mxGeometry")
            center_rel = float(g.get("x", 0)) + float(g.get("width")) / 2
            self.assertLessEqual(abs(center_rel), 2.0,
                                 f"IGW 中心が VPC 左枠線から {center_rel}px")
            self.assertIn("awsdiagBoundary=1;", igw.get("style"),
                          "境界またぎマーカーが style にない")
            # マーカーは指定ノードだけに付く
            self.assertNotIn("awsdiagBoundary", cells["alb"].get("style"))

    NESTED = {
        "name": "t",
        "meta": {"purpose": "test", "updated": "2026-07-15"},
        "containers": [
            {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
            {"id": "region", "label": "Region", "type": "region",
             "parent": "cloud"},
            {"id": "vpc", "label": "VPC", "type": "vpc", "parent": "region"}],
        "nodes": [
            {"id": "igw", "label": "IGW", "icon": "internet_gateway",
             "parent": "vpc", "col": 0, "row": 0, "on_boundary": "left"},
            {"id": "alb", "label": "ALB",
             "icon": "application_load_balancer",
             "parent": "vpc", "col": 1, "row": 0},
            {"id": "ec2", "label": "EC2", "icon": "ec2",
             "parent": "vpc", "col": 2, "row": 0}],
        "edges": [
            {"id": "e1", "src": "igw", "dst": "alb", "kind": "main"},
            {"id": "e2", "src": "alb", "dst": "ec2", "kind": "main"}]}

    def test_nested_ancestor_clearance(self):
        # 3 段入れ子(cloud > region > vpc)で vpc 左枠に on_boundary した
        # IGW の外側端と、祖先(region)左枠線の間にアイコン幅の 1/2 以上の
        # クリアランスを確保する(修正前は −19px = 祖先枠線に重なっていた)
        spec = json.loads(json.dumps(self.NESTED))
        B.validate_spec(spec)
        lay, _conts, _nodes = B.place(spec, B.load_icons())
        igw = lay.boxes["igw"]
        vpc, reg = lay.boxes["vpc"], lay.boxes["region"]
        cloud = lay.boxes["cloud"]
        # またぎの不変条件: 中心は親(vpc)の左枠線上のまま
        self.assertLessEqual(abs((igw[0] + igw[2] / 2) - vpc[0]), 1.0)
        half = igw[2] / 2
        self.assertGreaterEqual(igw[0] - reg[0], half - 0.5,
                                f"region 左枠線とのクリアランス {igw[0] - reg[0]}px"
                                f" < アイコン幅/2 ({half}px)")
        self.assertGreaterEqual(igw[0] - cloud[0], half - 0.5,
                                "cloud 左枠線とのクリアランス不足")
        # end-to-end でも 0 エラー
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.NESTED, Path(td), "onb3")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout, r.stdout)

    HAND = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="vpc" value="VPC" style="grIcon=mxgraph.aws4.group_vpc2;container=1;" vertex="1" parent="1"><mxGeometry x="200" y="100" width="400" height="300" as="geometry"/></mxCell>
<mxCell id="igw" value="IGW" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.internet_gateway;{M}" vertex="1" parent="1"><mxGeometry x="161" y="200" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def test_marker_exempts_hand_edited_e8(self):
        # 手編集(XML 親=ルート)で公式流に境界上へ置いた図: マーカーなしは
        # E8、awsdiagBoundary=1 を足せば 0 エラーで通る
        with tempfile.TemporaryDirectory() as td:
            for marker, want_rc in (("", 1), ("awsdiagBoundary=1;", 0)):
                f = Path(td) / f"hand{want_rc}.drawio"
                f.write_text(self.HAND.replace("{M}", marker),
                             encoding="utf-8")
                r = subprocess.run(
                    [sys.executable, str(VALIDATE), str(f)],
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(r.returncode, want_rc, r.stdout + r.stderr)
                if want_rc == 1:
                    self.assertIn("E8", r.stdout, r.stdout)
                else:
                    self.assertNotIn("E8", r.stdout, r.stdout)


class TestForkTrunkE7(unittest.TestCase):
    """fork(同一 source・同一始点から出て分岐点まで同走)のトランクは E7 免除。

    手動 pin で辺中心 1 点から 2 本を出しトランクを共有させると、修正前は
    共有区間が E7「重走」の誤警告になっていた。始点が一致しない同走
    (別レーン)は引き続き E7 で捕まえる(誤免除しない)。
    """

    ICON = ("sketch=0;outlineConnect=0;fontColor=#232F3E;fillColor={F};"
            "strokeColor=#ffffff;verticalLabelPosition=bottom;"
            "verticalAlign=top;align=center;html=1;fontSize=12;aspect=fixed;"
            "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{I};")
    EDGE = ("edgeStyle=orthogonalEdgeStyle;html=1;endArrow=open;endFill=0;"
            "strokeColor=#232F3E;exitX={EX};exitY=1;exitDx=0;exitDy=0;"
            "entryX=0.5;entryY=0;entryDx=0;entryDy=0;")
    XML = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="s" value="S" style="{S_ICON}" vertex="1" parent="1"><mxGeometry x="300" y="100" width="48" height="48" as="geometry"/></mxCell>
<mxCell id="t1" value="T1" style="{T_ICON}" vertex="1" parent="1"><mxGeometry x="100" y="300" width="48" height="48" as="geometry"/></mxCell>
<mxCell id="t2" value="T2" style="{T_ICON}" vertex="1" parent="1"><mxGeometry x="500" y="300" width="48" height="48" as="geometry"/></mxCell>
<mxCell id="f1" style="{E1}" edge="1" parent="1" source="s" target="t1"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="{X1}" y="{Y}"/><mxPoint x="124" y="{Y}"/></Array></mxGeometry></mxCell>
<mxCell id="f2" style="{E2}" edge="1" parent="1" source="s" target="t2"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="{X2}" y="{Y}"/><mxPoint x="524" y="{Y}"/></Array></mxGeometry></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def _validate(self, xml: str, name: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / f"{name}.drawio"
            f.write_text(xml, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATE), str(f)],
                capture_output=True, text=True, timeout=15)

    def _xml(self, ex1: str, x1: str, ex2: str, x2: str, y: str) -> str:
        return (self.XML
                .replace("{S_ICON}", self.ICON.format(F="#ED7100", I="ec2"))
                .replace("{T_ICON}", self.ICON.format(
                    F="#7AA116", I="simple_storage_service"))
                .replace("{E1}", self.EDGE.replace("{EX}", ex1))
                .replace("{E2}", self.EDGE.replace("{EX}", ex2))
                .replace("{X1}", x1).replace("{X2}", x2).replace("{Y}", y))

    def test_fork_trunk_not_e7(self):
        # 同一 exit(辺中心 0.5)から (324,148)→(324,220) の 72px を共有 →
        # トランクは意図的な同走なので E7 を出さない
        r = self._validate(self._xml("0.5", "324", "0.5", "324", "220"),
                           "fork")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("E7", r.stdout, r.stdout)

    def test_offset_parallel_still_e7(self):
        # 同一 source でも始点が 4.8px ずれた平行同走(exit 0.45 / 0.55)は
        # トランクではない → E7 は出続ける(誤免除しない)
        r = self._validate(
            self._xml("0.45", "321.6", "0.55", "326.4", "240"), "ctrl")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("E7", r.stdout, r.stdout)

    def test_duplicate_edge_still_e7(self):
        # src も dst も同じで経路全体が一致する重複エッジは「分岐しない fork」
        # ではなくただの二重線 → トランク免除せず E7 で捕まえる
        xml = (self._xml("0.5", "324", "0.5", "324", "220")
               .replace('target="t2"', 'target="t1"')
               .replace('x="524"', 'x="124"'))
        r = self._validate(xml, "dup")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("E7", r.stdout, r.stdout)


class TestFanInTrunkE7(unittest.TestCase):
    """R4-5: fan-in(同一 target・同一終点へ収束)のトランクも E7 免除。

    fork 免除(v1.6.0)の鏡映。終点が一致しない平行同走は引き続き E7 で
    捕まえる(誤免除ガードも src 側と同水準)。完全重複(src・dst とも同一)
    の二重線ガードは TestForkTrunkE7.test_duplicate_edge_still_e7 が
    両側トランク化後も E7 のままであることを担保する(dst 側の全長一致
    ガードが無いとそちらが免除に落ちて失敗する)。
    """

    # 2 ソース(下段)→ 1 ターゲット T(上段中央)。エッジは T の下辺
    # entry {EN} へ収束し、合流点から終点までがトランクになる
    EDGE = ("edgeStyle=orthogonalEdgeStyle;html=1;endArrow=open;endFill=0;"
            "strokeColor=#232F3E;exitX=0.5;exitY=0;exitDx=0;exitDy=0;"
            "entryX={EN};entryY=1;entryDx=0;entryDy=0;")
    XML = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="t" value="T" style="{S_ICON}" vertex="1" parent="1"><mxGeometry x="300" y="100" width="48" height="48" as="geometry"/></mxCell>
<mxCell id="s1" value="S1" style="{T_ICON}" vertex="1" parent="1"><mxGeometry x="100" y="300" width="48" height="48" as="geometry"/></mxCell>
<mxCell id="s2" value="S2" style="{T_ICON}" vertex="1" parent="1"><mxGeometry x="500" y="300" width="48" height="48" as="geometry"/></mxCell>
<mxCell id="f1" style="{E1}" edge="1" parent="1" source="s1" target="t"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="124" y="{Y}"/><mxPoint x="{X1}" y="{Y}"/></Array></mxGeometry></mxCell>
<mxCell id="f2" style="{E2}" edge="1" parent="1" source="s2" target="t"><mxGeometry relative="1" as="geometry"><Array as="points"><mxPoint x="524" y="{Y}"/><mxPoint x="{X2}" y="{Y}"/></Array></mxGeometry></mxCell>
</root></mxGraphModel></diagram></mxfile>"""

    def _xml(self, en1: str, x1: str, en2: str, x2: str, y: str) -> str:
        icon = TestForkTrunkE7.ICON
        return (self.XML
                .replace("{S_ICON}", icon.format(F="#ED7100", I="ec2"))
                .replace("{T_ICON}", icon.format(
                    F="#7AA116", I="simple_storage_service"))
                .replace("{E1}", self.EDGE.replace("{EN}", en1))
                .replace("{E2}", self.EDGE.replace("{EN}", en2))
                .replace("{X1}", x1).replace("{X2}", x2).replace("{Y}", y))

    def _validate(self, xml: str, name: str) -> subprocess.CompletedProcess:
        return TestForkTrunkE7._validate(self, xml, name)

    def test_fanin_trunk_not_e7(self):
        # 同一 entry(下辺中心 0.5)へ (324,220)→(324,148) の 72px を共有 →
        # 合流トランクは意図的な同走なので E7 を出さない
        r = self._validate(self._xml("0.5", "324", "0.5", "324", "220"),
                           "fanin")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("E7", r.stdout, r.stdout)

    def test_offset_parallel_still_e7(self):
        # 同一 target でも終点が 4.8px ずれた平行同走(entry 0.45 / 0.55)は
        # トランクではない → E7 は出続ける(誤免除しない)
        r = self._validate(
            self._xml("0.45", "321.6", "0.55", "326.4", "240"), "fanin-ctrl")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("E7", r.stdout, r.stdout)


class _AbsBuildBase(unittest.TestCase):
    """abs スペック経由でエッジ端点を検証するテストの共有ヘルパー。"""

    W = 78.0   # アイコン標準幅(frac→px 換算用)

    def _build_abs(self, spec: dict, name: str) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), name, "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s), 0 warning(s)", r.stdout, r.stdout)
            ab = json.loads((Path(td) / f"{name}.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
        return ab, r.stdout

    @staticmethod
    def _edge(ab: dict, eid: str) -> dict:
        return [x for d in ab.get("diagrams", [ab])
                for x in d["edges"] if x["id"] == eid][0]

    @staticmethod
    def _node(ab: dict, nid: str) -> dict:
        return [x for d in ab.get("diagrams", [ab])
                for x in d["nodes"] if x["id"] == nid][0]

    def _pairs_spec(self) -> dict:
        # 指摘1・2の再現: 縦並び複製ペア2組を隣接列に配置。sub の題字
        # 「Private subnet (DB)」が Aurora 列の中心を覆う(v1.5.0 は
        # x 探索が端点を frac 0.9215 = ほぼ右角へ追いやっていた)
        return {
            "name": "r3pairs", "meta": {"purpose": "test"},
            "containers": [
                {"id": "vpc", "type": "vpc", "label": "VPC"},
                {"id": "sub1", "type": "private_subnet",
                 "label": "Private subnet (DB)", "parent": "vpc"},
                {"id": "sub2", "type": "private_subnet",
                 "label": "Private subnet (DB)", "parent": "vpc"}],
            "nodes": [
                {"id": "db1", "icon": "aurora", "label": "Aurora primary",
                 "parent": "sub1", "col": 4, "row": 2},
                {"id": "ca1", "icon": "elasticache",
                 "label": "ElastiCache primary", "parent": "sub1",
                 "col": 5, "row": 2},
                {"id": "db2", "icon": "aurora", "label": "Aurora standby",
                 "parent": "sub2", "col": 4, "row": 4},
                {"id": "ca2", "icon": "elasticache",
                 "label": "ElastiCache replica", "parent": "sub2",
                 "col": 5, "row": 4}],
            "edges": [
                {"id": "e6", "src": "db1", "dst": "db2",
                 "label": "Replication", "kind": "sub"},
                {"id": "e7", "src": "ca1", "dst": "ca2",
                 "label": "Replication", "kind": "sub"}]}


class TestFeedbackRound3(_AbsBuildBase):
    """外部フィードバック第3ラウンド(v1.5.0 直線優先化の副作用群)の回帰。

    大原則: エッジ端点は「接続して見える(辺中心付近から出入り)>
    直線 > 折れ点最少」。直線化のために端点を中心から遠ざけない。
    ①並走レーンの分離漏れ ②exit/entry frac のほぼ角(0.9215)進出
    ③同一 src ファンアウトの階段状崩れ、を機械検証する。
    """

    def test_2_endpoint_fraction_near_center(self):
        # 指摘2: 自動エッジの端点 frac は 0.35〜0.65(辺中心付近)に収まる。
        # 修正前実測: e6 が exit/entry [0.9215, 1]/[0.9215, 0](中心+33px)
        ab, out = self._build_abs(self._pairs_spec(), "r3frac")
        self.assertNotIn("W5", out, "題字帯貫通")
        for eid in ("e6", "e7"):
            e = self._edge(ab, eid)
            self.assertEqual(e.get("points") or [], [],
                             f"{eid}: 垂直直線(拡張された列内)のはず")
            for key, idx in (("exit", 0), ("entry", 0)):
                f = e[key][idx]
                self.assertGreaterEqual(f, 0.35, f"{eid}.{key} が中心付近でない")
                self.assertLessEqual(f, 0.65, f"{eid}.{key} が中心付近でない")

    def test_1_parallel_lanes_separated(self):
        # 指摘1: 隣接2ペアの縦レプリケーション線は同一レーンに乗らない
        # (レーン x が 14px 以上離れる)。E7 も出ない
        ab, out = self._build_abs(self._pairs_spec(), "r3lane")
        self.assertNotIn("E7", out, "レプリケーション線の重走")
        xs = []
        for eid, nid in (("e6", "db1"), ("e7", "ca1")):
            e = self._edge(ab, eid)
            n = self._node(ab, nid)
            xs.append(n["cx"] + (e["exit"][0] - 0.5) * self.W)
        self.assertGreaterEqual(abs(xs[0] - xs[1]), 14.0,
                                f"レーン分離不足: {xs}")

    def test_1_corun_audit_moves_middle_run(self):
        # 指摘1(機構): assign_lanes は直行直線(単一 Run)を見ないため、
        # 別エッジの中間 Run が同座標に落ちても分離されなかった。
        # separate_corun_runs が中間セグメントを LANE_STEP(14px)へ離す
        import types
        lay = types.SimpleNamespace(obstacles=[], title_bands=[])
        rt = object()   # r is not None でありさえすればよい
        direct = [(100.0, 50.0), (100.0, 500.0)]
        bent = [(20.0, 80.0), (103.0, 80.0), (103.0, 470.0), (20.0, 470.0)]
        pending = [
            (None, {"id": "A", "src": "a", "dst": "b"}, rt, direct),
            (None, {"id": "B", "src": "c", "dst": "d"}, rt, bent)]
        B.separate_corun_runs(lay, pending, {})
        self.assertEqual(direct, [(100.0, 50.0), (100.0, 500.0)],
                         "直行直線(端点)は動かさない")
        self.assertEqual(bent[1][0], 114.0, "中間 Run が +14px 離れていない")
        self.assertEqual(bent[2][0], 114.0)

    def test_1_corun_audit_exempts_fork(self):
        # 同一 src のペアは fork トランクの意図的な同走 → 監査対象外
        import types
        lay = types.SimpleNamespace(obstacles=[], title_bands=[])
        rt = object()
        direct = [(100.0, 50.0), (100.0, 500.0)]
        bent = [(20.0, 80.0), (103.0, 80.0), (103.0, 470.0), (20.0, 470.0)]
        pending = [
            (None, {"id": "A", "src": "a", "dst": "b"}, rt, direct),
            (None, {"id": "B", "src": "a", "dst": "d"}, rt, bent)]
        B.separate_corun_runs(lay, pending, {})
        self.assertEqual(bent[1][0], 103.0, "同一 src は動かさない")

    def test_2_jog_when_growth_capped(self):
        # 指摘2フォールバック: 題字が広く列幅拡張(上限 365px)でも中心
        # ±NEAR_FRAC に直線を引けない場合、端(角)から出る直線ではなく
        # 「中心出射+最小ジョグ」(v–h–v–h–v)になる。W5 なし。
        # 修正前実測: exit R のコの字迂回が sub2 の題字帯を貫通(W5)。
        # さらにジョグの中間 Run は隣ペアの直行直線(assign_lanes の
        # 死角)と同座標に落ちるが、separate_corun_runs が 14px 離す(指摘1)
        spec = {
            "name": "r3jog", "meta": {"purpose": "test"},
            "containers": [
                {"id": "cloud", "type": "aws_cloud", "label": "AWS Cloud"},
                {"id": "vpc", "type": "vpc", "label": "VPC",
                 "parent": "cloud"},
                {"id": "az1", "type": "az", "label": "Availability Zone A",
                 "parent": "vpc"},
                {"id": "sub1", "type": "private_subnet",
                 "label": "Private subnet (database tier)", "parent": "az1"},
                {"id": "az2", "type": "az", "label": "Availability Zone C",
                 "parent": "vpc"},
                {"id": "sub2", "type": "private_subnet",
                 "label": "Private subnet (database tier)", "parent": "az2"}],
            "nodes": [
                {"id": "db1", "icon": "aurora", "label": "Aurora primary",
                 "parent": "sub1", "col": 4, "row": 2},
                {"id": "ca1", "icon": "elasticache",
                 "label": "ElastiCache primary", "parent": "sub1",
                 "col": 5, "row": 3},
                {"id": "db2", "icon": "aurora", "label": "Aurora standby",
                 "parent": "sub2", "col": 4, "row": 5},
                {"id": "ca2", "icon": "elasticache",
                 "label": "ElastiCache replica", "parent": "sub2",
                 "col": 5, "row": 6}],
            "edges": [
                {"id": "r_db", "src": "db1", "dst": "db2",
                 "label": "Replication", "kind": "sub"},
                {"id": "r_ca", "src": "ca1", "dst": "ca2",
                 "label": "Replication", "kind": "sub"}]}
        ab, out = self._build_abs(spec, "r3jog")
        self.assertNotIn("W5", out, "題字帯貫通")
        self.assertNotIn("E7", out, "重走")
        e = self._edge(ab, "r_db")
        self.assertEqual(e["exit"], [0.5, 1], "中心出射のはず")
        self.assertEqual(e["entry"], [0.5, 0], "中心進入のはず")
        pts = e.get("points") or []
        self.assertEqual(len(pts), 4, f"最小ジョグ(4 waypoint)のはず: {pts}")
        self.assertAlmostEqual(pts[0][0], pts[3][0], places=1)   # 中心線
        self.assertAlmostEqual(pts[1][0], pts[2][0], places=1)   # ジョグ線
        self.assertGreaterEqual(abs(pts[1][0] - pts[0][0]), 6.0)
        # 隣列のペアは辺中心付近の垂直直線のまま
        e2 = self._edge(ab, "r_ca")
        self.assertEqual(e2.get("points") or [], [])
        for key in ("exit", "entry"):
            self.assertGreaterEqual(e2[key][0], 0.35)
            self.assertLessEqual(e2[key][0], 0.65)
        # 指摘1: ジョグの中間 Run と隣の直行直線のレーンは 14px 以上離れる
        ca_x = (self._node(ab, "ca1")["cx"]
                + (e2["exit"][0] - 0.5) * self.W)
        self.assertGreaterEqual(abs(pts[1][0] - ca_x), 14.0,
                                f"ジョグ {pts[1][0]} と直行線 {ca_x} が近すぎる")

    def test_3_fanout_symmetry(self):
        # 指摘3: 同一 src から上下対称のファンアウトは、①縦レーン x を
        # 共有し(±7px の階段状オフセットにしない)②entry frac が対で
        # 一致する。修正前実測: レーン x=223/209(14px ずれ)
        spec = {
            "name": "r3fan", "meta": {"purpose": "test"},
            "nodes": [
                {"id": "waf", "icon": "waf", "label": "AWS WAF",
                 "col": 1, "row": 1},
                {"id": "alb", "icon": "application_load_balancer",
                 "label": "ALB", "col": 1, "row": 2},
                {"id": "cog", "icon": "cognito", "label": "Cognito",
                 "col": 1, "row": 3},
                {"id": "ecs1", "icon": "ecs", "label": "ECS Service A",
                 "col": 2, "row": 1},
                {"id": "mid", "icon": "elasticache", "label": "ElastiCache",
                 "col": 2, "row": 2},
                {"id": "ecs2", "icon": "ecs", "label": "ECS Service B",
                 "col": 2, "row": 3}],
            "edges": [
                {"id": "e1", "src": "alb", "dst": "ecs1", "kind": "main"},
                {"id": "e2", "src": "alb", "dst": "ecs2", "kind": "main"}]}
        ab, _ = self._build_abs(spec, "r3fan")
        e1, e2 = self._edge(ab, "e1"), self._edge(ab, "e2")
        # 出射は右辺 0.5 対称(0.35/0.65)
        self.assertEqual(e1["exit"][0], 1)
        self.assertEqual(e2["exit"][0], 1)
        self.assertAlmostEqual(e1["exit"][1] + e2["exit"][1], 1.0, places=3)
        # entry frac は対で一致
        self.assertEqual(e1["entry"], e2["entry"], "entry frac が不揃い")
        # 縦レーン x は共有(両エッジの waypoint x が一致)
        lane1 = {p[0] for p in e1["points"]}
        lane2 = {p[0] for p in e2["points"]}
        self.assertEqual(len(lane1), 1, f"e1 の縦レーンが 1 本でない: {e1['points']}")
        self.assertEqual(lane1, lane2, "レーン x が共有されていない(階段状)")


class TestFeedbackRound4(_AbsBuildBase):
    """実使用フィードバック第4ラウンド(6図発注の目視レビュー)の回帰。

    A: 行き先と逆を向いた辺からの出入り(回り込み)を許さない —
       _dir_penalty の反対側強罰 + route_all の anti 端点修復(交差非増加時のみ)
    B: コンテナ上辺進入の降下線・矢先がタイトル文字帯に当たる列は
       帯右端 + TITLE_CLEAR へ自動オフセット(container_stubs)
    C: 垂直複製ペアの直線は中心 0.5 が最優先 — 帯が中心を塞ぐ列は
       列幅拡張で中心レーンを空ける(_grow_cols_for_vertical_pairs)
    """

    def test_a_dir_penalty_orders_sides(self):
        # 正面 < 斜め < 垂直 < 反対側。反対側の上限は ANTI_ALIGN
        p = B._dir_penalty
        self.assertAlmostEqual(p("T", 0, -100), 0.0)                 # 正面
        self.assertLess(p("T", 60, -100), p("L", 60, -100))          # 斜め前 < 斜め後
        self.assertAlmostEqual(p("L", 100, 0), B.Router.ANTI_ALIGN)  # 真後ろ
        self.assertAlmostEqual(p("R", 0, 100), B.Router.MISALIGN)    # 垂直
        self.assertGreater(B.Router.ANTI_ALIGN, 2 * B.Router.MISALIGN,
                           "反対側の辺は垂直より十分強く嫌う")

    def test_a_no_anti_ends_in_complex_template(self):
        # 修正前実測(example-complex): e10(svc2→右上の ddb)が左辺から
        # 出て大回り(余弦 -0.70)、e23(svc2→右下の xray)が右辺=行き先の
        # 逆側から進入(余弦 -0.51)。anti 修復後は両端点とも行き先側
        # (交差数 4→4 のまま。修復は交差を増やす解を採らない)
        spec = json.loads(
            (ROOT / "templates" / "example-complex.spec.json").read_text(
                encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "cx", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ab = json.loads((Path(td) / "cx.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
        for eid, src, dst, key, bad in (("e10", "svc2", "ddb", "exit", [0, 0.5]),
                                        ("e23", "svc2", "xray", "entry",
                                         [1, 0.5])):
            e = self._edge(ab, eid)
            fc = self._end_cos(ab, e, src, dst, key)
            self.assertGreater(
                fc, -0.3, f"{eid}.{key} が行き先と逆の辺(余弦 {fc:.2f})")
            self.assertNotEqual(e[key][0], bad[0],
                                f"{eid}.{key} が修正前の辺に戻っている")

    def _end_cos(self, ab: dict, e: dict, src: str, dst: str,
                 key: str) -> float:
        """端点の辺の外向き法線と相手方向の余弦(anti = 負)。"""
        ns, nd = self._node(ab, src), self._node(ab, dst)
        vx = nd["cx"] - ns["cx"]   # abs スペックのノードは中心座標 cx/cy
        vy = nd["cy"] - ns["cy"]
        if key == "entry":
            vx, vy = -vx, -vy
        d = math.hypot(vx, vy) or 1.0
        fx, fy = e[key]
        side = ("T" if fy == 0 else "B" if fy == 1
                else "L" if fx == 0 else "R")
        nx, ny = B._SIDE_NORMAL[side]
        return (nx * vx + ny * vy) / d

    def test_b_top_entry_offsets_off_title_band(self):
        # 修正前実測(図4相当): アカウント題字帯が VPC の全列中心を覆うと、
        # 上辺進入をあきらめ左外周へ回り込む(または帯上に W5)。
        # 修正後: 進入 x を帯右端 + TITLE_CLEAR へ自動オフセットして
        # 自然な降下のまま文字を避ける
        label = "Shared Services (2222-2222-2222) - DNS/AD"
        spec = {
            "name": "r4band", "meta": {"purpose": "test"},
            "containers": [
                {"id": "net", "label": "Network (1111-1111-1111)",
                 "type": "account"},
                {"id": "sh", "label": label, "type": "account"},
                {"id": "shvpc", "label": "Shared VPC", "type": "vpc",
                 "parent": "sh"},
                {"id": "shpriv", "label": "Private subnet",
                 "type": "private_subnet", "parent": "shvpc"}],
            "nodes": [
                {"id": "tgw", "icon": "transit_gateway",
                 "label": "Transit Gateway", "parent": "net",
                 "col": 0, "row": 0},
                {"id": "ds", "icon": "directory_service",
                 "label": "Directory Service", "parent": "shpriv",
                 "col": 0, "row": 2},
                {"id": "ds2", "icon": "managed_ms_ad", "label": "Managed AD",
                 "parent": "shpriv", "col": 1, "row": 2}],
            "edges": [{"id": "a1", "src": "tgw", "dst": "shvpc"}]}
        ab, out = self._build_abs(spec, "r4band")
        self.assertNotIn("W5", out, "題字帯貫通が残っている")
        e = self._edge(ab, "a1")
        conts = {c["id"]: c for d in ab.get("diagrams", [ab])
                 for c in d["containers"]}
        sh, vpc = conts["sh"], conts["shvpc"]
        band_right = sh["x"] + 28 + B.text_width(label, 12) + 12
        self.assertEqual(e["entry"][1], 0, "上辺(T)進入のはず")
        entry_x = vpc["x"] + e["entry"][0] * vpc["w"]
        self.assertGreaterEqual(
            entry_x, band_right + B.TITLE_CLEAR - 0.5,
            f"進入 x {entry_x:.1f} が帯右端 {band_right:.1f} を避けていない")
        # 降下線(進入 x の縦線)が帯 y 域で帯 x 域に入っていないことも確認
        self.assertGreater(entry_x, band_right,
                           "矢先がタイトル文字の上に載っている")

    def test_c_replica_pair_centers_at_half(self):
        # 修正前実測(pairs-anchor / 実案件03の複製ペア相当): 題字帯が列中心を
        # 塞ぐと「ずらした直線」exit/entry 0.6484(中心 +11.6px)が先に採用
        # された。修正後: 列幅拡張で中心レーンを空け、両端 0.5 の垂直直線
        ab, out = self._build_abs(self._pairs_spec(), "r4pairs")
        self.assertNotIn("W5", out, "題字帯貫通")
        for eid in ("e6", "e7"):
            e = self._edge(ab, eid)
            self.assertEqual(e.get("points") or [], [],
                             f"{eid}: 垂直直線のはず")
            self.assertAlmostEqual(e["exit"][0], 0.5, places=4,
                                   msg=f"{eid}.exit が中心でない")
            self.assertAlmostEqual(e["entry"][0], 0.5, places=4,
                                   msg=f"{eid}.entry が中心でない")


class TestEqualizeContainers(_AbsBuildBase):
    """R4-6: 同じ親・同じ type の兄弟コンテナの寸法等化。

    縦積みの subnet 群は幅がグループ和集合に揃う(広げる方向のみ)。
    "equalize_containers": false でオプトアウト。広げた矩形が非所属
    ノードに掛かるグループは等化を諦める。等化起因で ERROR/WARN が
    増えるタブのロールバックは TestGoldenTemplates(multiaccount が
    バイト一致のまま)が回帰を担保する。
    """

    @staticmethod
    def _cont(ab: dict, cid: str) -> dict:
        return [x for d in ab.get("diagrams", [ab])
                for x in d["containers"] if x["id"] == cid][0]

    def _spec(self, **over) -> dict:
        # sub1(col 4-5)と sub2(col 4 のみ)の縦積み同種サブネット。
        # 等化で sub2 の幅が sub1 と同じ和集合スパンへ広がる
        s = {
            "name": "eq", "meta": {"purpose": "test"},
            "containers": [
                {"id": "vpc", "type": "vpc", "label": "VPC"},
                {"id": "sub1", "type": "private_subnet",
                 "label": "Private subnet (DB)", "parent": "vpc"},
                {"id": "sub2", "type": "private_subnet",
                 "label": "Private subnet (Cache)", "parent": "vpc"}],
            "nodes": [
                {"id": "db1", "icon": "aurora", "label": "Aurora",
                 "parent": "sub1", "col": 4, "row": 2},
                {"id": "db2", "icon": "rds", "label": "RDS read replica",
                 "parent": "sub1", "col": 5, "row": 2},
                {"id": "ca1", "icon": "elasticache", "label": "ElastiCache",
                 "parent": "sub2", "col": 4, "row": 4}],
            "edges": [{"id": "e1", "src": "db1", "dst": "ca1",
                       "kind": "sub"}]}
        s.update(over)
        return s

    def test_stacked_siblings_get_equal_width(self):
        ab, _ = self._build_abs(self._spec(), "eq-on")
        s1, s2 = self._cont(ab, "sub1"), self._cont(ab, "sub2")
        self.assertAlmostEqual(s1["w"], s2["w"], places=1,
                               msg=f"幅が揃っていない: {s1['w']} / {s2['w']}")
        self.assertAlmostEqual(s1["x"], s2["x"], places=1,
                               msg="左端が揃っていない")

    def test_opt_out_keeps_natural_width(self):
        ab, _ = self._build_abs(self._spec(equalize_containers=False),
                                "eq-off")
        s1, s2 = self._cont(ab, "sub1"), self._cont(ab, "sub2")
        self.assertGreater(s1["w"], s2["w"] + 50,
                           "オプトアウト時は自然幅(sub1 の方が広い)のはず")

    def test_opt_out_value_is_validated(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._spec(equalize_containers="yes"),
                           Path(td), "eq-bad")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("equalize_containers", r.stdout + r.stderr)

    def test_growth_over_foreign_node_is_skipped(self):
        # sub2 の拡張先セル (5,4) に VPC 直下の非所属ノードがいる →
        # そのグループは等化を諦める(安全側)
        spec = self._spec()
        # ELB は VPC 直下が正当な配置(W14 の対象外。NAT だと W14 が出る)
        spec["nodes"].append({"id": "lb", "icon": "elastic_load_balancing",
                              "label": "ELB", "parent": "vpc",
                              "col": 5, "row": 4})
        ab, _ = self._build_abs(spec, "eq-guard")
        s1, s2 = self._cont(ab, "sub1"), self._cont(ab, "sub2")
        self.assertGreater(s1["w"], s2["w"] + 50,
                           "非所属ノードに掛かる等化は見送られるはず")


class TestNearFracClamp(unittest.TestCase):
    """R4-4: 端点ずらし系後処理の NEAR_FRAC(0.35〜0.65)クランプ。

    単独ポートのノード端点は、_fan_deconflict_runs(LANE_STEP=14px)や
    _slide_end(±12〜14px)のずらしで帯外(78px アイコンで frac 0.6795)へ
    出ない。同一辺に複数付くポート群は対称ラダーが正当なので従来どおり。
    修正前実測: dense/hub-star/multiregion テンプレに 0.6795 端点が計 7 件
    (eval 側は SLIDE_MAX≤14.5px 免除で吸収していた — 免除は撤去済み)。
    """

    @staticmethod
    def _lay(boxes: dict) -> "B.Layout":
        lay = B.Layout(C=9, R=9)
        lay.boxes.update(boxes)
        return lay

    def _deconflict_setup(self, extra_edges=()):
        # E1: a→b の水平直行直線(y=39)。E2: c→d の折れ線で、c 右辺からの
        # 出射スタブ(y=39・span 198〜250)が E1 と同一線上に重なる
        lay = self._lay({"a": (0.0, 0.0, 78.0, 78.0),
                         "b": (300.0, 0.0, 78.0, 78.0),
                         "c": (120.0, 0.0, 78.0, 78.0),
                         "d": (300.0, 200.0, 78.0, 78.0),
                         "d2": (300.0, 400.0, 78.0, 78.0)})
        e1 = {"id": "E1", "src": "a", "dst": "b"}
        e2 = {"id": "E2", "src": "c", "dst": "d"}
        r1 = B.NodeRoute(exit=("R", 0.5), entry=("L", 0.5),
                         runs=[B.Run("h", 39.0)], direct=True)
        r2 = B.NodeRoute(exit=("R", 0.5), entry=("L", 0.5),
                         runs=[B.Run("h", 39.0), B.Run("v", 250.0),
                               B.Run("h", 239.0)], direct=False)
        edges = [e1, e2, *extra_edges]
        routes = {"E1": r1, "E2": r2}
        return lay, edges, routes

    def test_deconflict_clamps_single_port_to_band(self):
        # 修正前: E2 の出射が 0.5+14/78=0.6795 へ。修正後: 帯端 0.65 で
        # クランプ(11.7px)され、7px 以上の分離は保たれる
        lay, edges, routes = self._deconflict_setup()
        B._fan_deconflict_runs(lay, edges, routes)
        side, f = routes["E2"].exit
        self.assertEqual(side, "R")
        self.assertLessEqual(f, 0.65, f"単独ポートが帯外へ: {f}")
        self.assertGreaterEqual(f, 0.35)
        self.assertGreaterEqual(abs(f - 0.5) * 78.0, 7.0,
                                "クランプ後も E1 と 7px 以上離れること")

    def test_deconflict_keeps_ladder_range(self):
        # 同一辺 2 本以上(ラダー)は従来どおり 0.05〜0.95 — c 右辺に
        # もう 1 本足すと E2 は 0.6795(帯外)まで動いてよい
        e3 = {"id": "E3", "src": "c", "dst": "d2"}
        lay, edges, routes = self._deconflict_setup(extra_edges=(e3,))
        routes["E3"] = B.NodeRoute(exit=("R", 0.5), entry=("L", 0.5),
                                   runs=[B.Run("h", 39.0), B.Run("v", 260.0),
                                         B.Run("h", 439.0)], direct=False)
        B._fan_deconflict_runs(lay, edges, routes)
        fracs = sorted(routes[eid].exit[1] for eid in ("E2", "E3"))
        self.assertGreater(fracs[1], 0.65 + 1e-9,
                           f"ラダーまで帯内へ制限された: {fracs}")

    def test_slide_end_clamps_single_port(self):
        import types
        lay = types.SimpleNamespace(obstacles=[], title_bands=[])
        box = (0.0, 0.0, 78.0, 78.0)
        poly = [(78.0, 39.0), (200.0, 39.0)]
        ok = B._slide_end(lay, poly, False, 14.0, box, "R", [poly])
        self.assertTrue(ok, "帯端までのクランプ適用(11.7px)は成功する")
        self.assertAlmostEqual(poly[0][1], 0.65 * 78.0, places=3)
        # exact(題字帯回避)はクランプが必要になった時点で失敗し、動かさない
        poly2 = [(78.0, 39.0), (200.0, 39.0)]
        ok2 = B._slide_end(lay, poly2, False, 14.0, box, "R", [poly2],
                           exact=True)
        self.assertFalse(ok2)
        self.assertEqual(poly2[0], (78.0, 39.0), "exact 失敗時は現状維持")

    def test_slide_end_full_delta_for_multi_port(self):
        # 同一辺に他エッジの端点がある(端点分離 pass1 の形)なら従来どおり
        # 全量スライド(0.6795 相当)を許す — ラダーの分離を狭めない
        import types
        lay = types.SimpleNamespace(obstacles=[], title_bands=[])
        box = (0.0, 0.0, 78.0, 78.0)
        poly = [(78.0, 39.0), (200.0, 39.0)]
        other = [(78.0, 70.0), (200.0, 120.0)]
        ok = B._slide_end(lay, poly, False, 14.0, box, "R", [poly, other])
        self.assertTrue(ok)
        self.assertAlmostEqual(poly[0][1], 53.0, places=3)


class TestExternalPatchA(_AbsBuildBase):
    """外部フィードバック第4ラウンド A(実装済みパッチ 3 件)の回帰。

    A-1: 同一 src から片側方向へ出る対エッジ群の出射辺・(コンテナ宛の)
         入射辺を揃える(fan_fixes + スコア第 4 キー + 修復パス)
    A-2: 折れ点 3 以上のエッジを全エッジ確定後に再配線する磨きパス
         (リップアップは交差関与エッジしか引き直さないための追い撃ち)
    A-3: 手動 pin 端点の台帳化(Layout.pinned_ports)— _fan_slots が
         pin と同一点・近接点へ自動エッジを割り当てない
    """

    def test_a1_fan_exit_entry_unified(self):
        # ノード → コンテナ×2(右上・右下)のファンアウト。修正前実測:
        # e1 exit [1,0.35]/entry B、e2 exit B/entry L と対で不揃い。
        # 修正後: 出射は右辺の対称スロット、入射は対面辺の鏡映で統一
        spec = {
            "name": "a1fan", "meta": {"purpose": "test"},
            "containers": [
                {"id": "svc1", "type": "generic", "label": "ECS Service A"},
                {"id": "svc2", "type": "generic", "label": "ECS Service B"}],
            "nodes": [
                {"id": "alb", "icon": "application_load_balancer",
                 "label": "ALB", "col": 0, "row": 2},
                {"id": "t1", "icon": "ecs", "label": "Task A",
                 "parent": "svc1", "col": 2, "row": 1},
                {"id": "t2", "icon": "ecs", "label": "Task B",
                 "parent": "svc2", "col": 2, "row": 3}],
            "edges": [
                {"id": "e1", "src": "alb", "dst": "svc1", "kind": "main"},
                {"id": "e2", "src": "alb", "dst": "svc2", "kind": "main"}]}
        ab, _ = self._build_abs(spec, "a1fan")
        e1, e2 = self._edge(ab, "e1"), self._edge(ab, "e2")
        # 出射辺は 2 本とも dst 側を向く右辺(exit x = 1)で対称スロット
        self.assertEqual(e1["exit"][0], 1, f"e1 の出射が右辺でない: {e1['exit']}")
        self.assertEqual(e2["exit"][0], 1, f"e2 の出射が右辺でない: {e2['exit']}")
        self.assertAlmostEqual(e1["exit"][1] + e2["exit"][1], 1.0, places=3)
        # 入射は群内で流儀統一(ここでは対面縦辺の鏡映: 上の svc1 は下辺、
        # 下の svc2 は上辺)。h 流儀(両方 L)へ倒れても「統一」は満たすが、
        # このスペックの実測は鏡映 v 流儀
        self.assertEqual(e1["entry"], [0.5, 1], f"e1 の入射: {e1['entry']}")
        self.assertEqual(e2["entry"], [0.5, 0], f"e2 の入射: {e2['entry']}")

    def test_a2_polish_reduces_bends(self):
        # 折れ点 3 以上で交差ゼロのエッジは、リップアップ(交差関与のみ)の
        # 対象外のため初期配線順の巡り合わせのまま残る。磨きパスが全エッジ
        # 確定後の文脈で引き直す。修正前実測: e5(n1→n2 の同一行横断)が
        # 6 折れの大回り → 修正後 2 折れ(交差数は 12 のまま非増加)
        spec = {
            "name": "a2polish", "meta": {"purpose": "test"},
            "nodes": [
                {"id": "n0", "icon": "ec2", "label": "N0", "col": 0, "row": 3},
                {"id": "n1", "icon": "s3", "label": "N1", "col": 0, "row": 2},
                {"id": "n2", "icon": "lambda", "label": "N2", "col": 4, "row": 2},
                {"id": "n3", "icon": "sqs", "label": "N3", "col": 3, "row": 2},
                {"id": "n4", "icon": "sns", "label": "N4", "col": 1, "row": 1},
                {"id": "n5", "icon": "dynamodb", "label": "N5", "col": 2, "row": 0},
                {"id": "n6", "icon": "rds", "label": "N6", "col": 2, "row": 3},
                {"id": "n7", "icon": "api_gateway", "label": "N7", "col": 1, "row": 3},
                {"id": "n8", "icon": "cognito", "label": "N8", "col": 4, "row": 0},
                {"id": "n9", "icon": "cloudfront", "label": "N9", "col": 4, "row": 3},
                {"id": "n10", "icon": "ses", "label": "N10", "col": 1, "row": 2},
                {"id": "n11", "icon": "elasticache", "label": "N11", "col": 4, "row": 1},
                {"id": "n12", "icon": "waf", "label": "N12", "col": 0, "row": 1}],
            "edges": [
                {"id": "e0", "src": "n0", "dst": "n1", "kind": "main"},
                {"id": "e1", "src": "n0", "dst": "n2", "kind": "main"},
                {"id": "e2", "src": "n0", "dst": "n3", "kind": "main"},
                {"id": "e3", "src": "n0", "dst": "n4", "kind": "main"},
                {"id": "e4", "src": "n0", "dst": "n5", "kind": "main"},
                {"id": "e5", "src": "n1", "dst": "n2", "kind": "main"},
                {"id": "e6", "src": "n11", "dst": "n4", "kind": "main"},
                {"id": "e7", "src": "n2", "dst": "n8", "kind": "main"},
                {"id": "e8", "src": "n10", "dst": "n12", "kind": "main"},
                {"id": "e9", "src": "n3", "dst": "n1", "kind": "main"},
                {"id": "e10", "src": "n9", "dst": "n1", "kind": "main"},
                {"id": "e12", "src": "n6", "dst": "n5", "kind": "main"},
                {"id": "e14", "src": "n7", "dst": "n10", "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "a2polish", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 error(s)", r.stdout, r.stdout)
            ab = json.loads((Path(td) / "a2polish.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
        e5 = self._edge(ab, "e5")
        wps = len(e5.get("points") or [])
        self.assertLessEqual(wps, 3, f"e5 の折れ点が磨かれていない: {wps} 折れ "
                                     f"(磨きパス導入前実測 6 / 導入後 2)")

    def test_a3_pin_ledger_blocks_same_point(self):
        # 手動 pin(hub 左辺 0.4)は _fan_slots から不可視で、自動エッジが
        # 8px 隣(L 0.5)へ置かれ W6(矢じり重なり)になっていた。台帳化後は
        # pin を固定スロットとして数え、最寄りスロットを避ける。
        # _build_abs の「0 warning(s)」assert が W6 消滅の検証を兼ねる
        spec = {
            "name": "a3pin", "meta": {"purpose": "test"},
            "nodes": [
                {"id": "hub", "icon": "ec2", "label": "Hub", "col": 2, "row": 1},
                {"id": "m", "icon": "s3", "label": "Pinned src", "col": 0, "row": 1},
                {"id": "a1", "icon": "lambda", "label": "Auto src 1", "col": 0, "row": 0},
                {"id": "a2", "icon": "sqs", "label": "Auto src 2", "col": 0, "row": 2}],
            "edges": [
                {"id": "pin", "src": "m", "dst": "hub",
                 "exit": [1, 0.4], "entry": [0, 0.4]},
                {"id": "auto1", "src": "a1", "dst": "hub", "kind": "main"},
                {"id": "auto2", "src": "a2", "dst": "hub", "kind": "main"}]}
        ab, out = self._build_abs(spec, "a3pin")
        self.assertNotIn("W6", out, "pin と自動端点の矢じり重なり")
        auto2 = self._edge(ab, "auto2")
        side_x, frac = auto2["entry"][0], auto2["entry"][1]
        if side_x == 0:   # hub 左辺に入る場合は pin(0.4)から 10px 以上離れる
            self.assertGreaterEqual(abs(frac - 0.4) * self.W, 10.0,
                                    f"pin 0.4 と近接: {auto2['entry']}")


class TestCenterFork(_AbsBuildBase):
    """R5-B: fork(中心からの二股)の自動生成。

    外部フィードバックが手動 pin で実証した形状仕様の 3 点
    (①同一辺の対称スロット出射 ②同一レーン x で折れて上下に分岐
    ③宛先対面辺へレーン x と同位置で入射)を座標で検証する。
    修正前実測(同スペック): e_up が x=304.4・e_dn が x=395.4 と
    別々の位置で折れる「平行 2 レーン」だった。
    検出は安全側限定 — 境界(宛先 3 つ / ノード宛 / レーン塞がり)では
    発動せず、現行ルータへフォールバックすることも検証する。
    """

    @staticmethod
    def _fork_spec(az_a="Availability Zone A", az_c="Availability Zone C"):
        return {
            "name": "fork", "meta": {"purpose": "test"},
            "containers": [
                {"id": "vpc", "label": "VPC", "type": "vpc"},
                {"id": "az1", "label": az_a, "type": "az", "parent": "vpc"},
                {"id": "az1_app", "label": "Private subnet (App)",
                 "type": "private_subnet", "parent": "az1"},
                {"id": "az1_db", "label": "Isolated subnet (DB)",
                 "type": "private_subnet", "parent": "az1"},
                {"id": "az2", "label": az_c, "type": "az", "parent": "vpc"},
                {"id": "az2_app", "label": "Private subnet (App)",
                 "type": "private_subnet", "parent": "az2"},
                {"id": "az2_db", "label": "Isolated subnet (DB)",
                 "type": "private_subnet", "parent": "az2"}],
            "nodes": [
                {"id": "alb", "icon": "application_load_balancer",
                 "label": "ALB", "col": 0, "row": 1, "parent": "vpc"},
                {"id": "ecs1", "icon": "ecs", "label": "ECS Service A",
                 "col": 1, "row": 0, "parent": "az1_app"},
                {"id": "aurora1", "icon": "aurora", "label": "Aurora A",
                 "col": 2, "row": 0, "parent": "az1_db"},
                {"id": "ecs2", "icon": "ecs", "label": "ECS Service C",
                 "col": 1, "row": 2, "parent": "az2_app"},
                {"id": "aurora2", "icon": "aurora", "label": "Aurora C",
                 "col": 2, "row": 2, "parent": "az2_db"}],
            "edges": [
                {"id": "e_up", "src": "alb", "dst": "az1", "kind": "main"},
                {"id": "e_dn", "src": "alb", "dst": "az2", "kind": "main"}]}

    def _cont(self, ab: dict, cid: str) -> dict:
        return [x for d in ab.get("diagrams", [ab])
                for x in d["containers"] if x["id"] == cid][0]

    def test_fork_three_invariants(self):
        ab, out = self._build_abs(self._fork_spec(), "fork-fire")
        self.assertIn("fork 配線", out, "fork が発動していない")
        eu, ed = self._edge(ab, "e_up"), self._edge(ab, "e_dn")
        # ① 同一辺(右辺)の対称スロット 0.35 / 0.65
        self.assertEqual(eu["exit"], [1, 0.35], f"e_up exit: {eu['exit']}")
        self.assertEqual(ed["exit"], [1, 0.65], f"e_dn exit: {ed['exit']}")
        # トランクはノード辺から水平に出る(折れ点 y = 出射 y)
        alb = self._node(ab, "alb")
        top = alb["cy"] - self.W / 2
        self.assertEqual(len(eu["points"]), 1, eu["points"])
        self.assertEqual(len(ed["points"]), 1, ed["points"])
        self.assertAlmostEqual(eu["points"][0][1], top + 0.35 * self.W,
                               delta=0.6)
        self.assertAlmostEqual(ed["points"][0][1], top + 0.65 * self.W,
                               delta=0.6)
        # ② 2 本が同じレーン x で折れる(修正前: 304.4 / 395.4 と別々)
        lane = eu["points"][0][0]
        self.assertAlmostEqual(ed["points"][0][0], lane, delta=0.01,
                               msg=f"折れ x が別々: {eu['points']} / {ed['points']}")
        # ③ 宛先の対面辺(上=下辺 / 下=上辺)へレーン x と同位置で入射
        self.assertEqual(eu["entry"][1], 1, f"e_up の入射が下辺でない: {eu['entry']}")
        self.assertEqual(ed["entry"][1], 0, f"e_dn の入射が上辺でない: {ed['entry']}")
        for e, cid in ((eu, "az1"), (ed, "az2")):
            c = self._cont(ab, cid)
            self.assertAlmostEqual(c["x"] + e["entry"][0] * c["w"], lane,
                                   delta=0.6,
                                   msg=f"{e['id']} の entry frac がレーン x と不一致")

    def test_fork_lane_anchor_is_first_child(self):
        # レーン x のアンカー = 宛先コンテナ先頭(src 寄り)の子ボックス中心。
        # 題字が短く帯シフトが働かないスペックで、アンカーそのものを検証する
        # (長い題字では R4-2 の題字回避と同じ最小シフトが掛かる —
        # test_fork_three_invariants 側は仕様 3 点のみを見る)
        ab, out = self._build_abs(self._fork_spec("AZ A", "AZ C"),
                                  "fork-anchor")
        self.assertIn("fork 配線", out)
        eu = self._edge(ab, "e_up")
        app = self._cont(ab, "az1_app")
        self.assertAlmostEqual(eu["points"][0][0], app["x"] + app["w"] / 2,
                               delta=0.6, msg="レーン x が先頭子ボックス中心でない")

    def test_no_fire_three_destinations(self):
        spec = self._fork_spec("AZ A", "AZ C")
        spec["edges"].append(
            {"id": "e_3", "src": "alb", "dst": "az1_db", "kind": "main"})
        ab, out = self._build_abs(spec, "fork-3dst")
        self.assertNotIn("fork 配線", out, "宛先 3 つで発動してはならない")

    def test_no_fire_node_destination(self):
        spec = self._fork_spec("AZ A", "AZ C")
        spec["edges"] = [
            {"id": "e_up", "src": "alb", "dst": "ecs1", "kind": "main"},
            {"id": "e_dn", "src": "alb", "dst": "ecs2", "kind": "main"}]
        ab, out = self._build_abs(spec, "fork-nodedst")
        self.assertNotIn("fork 配線", out, "ノード宛で発動してはならない")

    def test_no_fire_lane_blocked_falls_back(self):
        # トランク回廊に障害ノードが居る → 不発動で現行ルータに
        # フォールバックし、それでも 0e0w で納品できる
        spec = self._fork_spec("AZ A", "AZ C")
        spec["nodes"].append(
            {"id": "blocker", "icon": "internet_gateway", "label": "IGW",
             "col": 1, "row": 1, "parent": "vpc"})
        ab, out = self._build_abs(spec, "fork-blocked")
        self.assertNotIn("fork 配線", out, "レーン塞がりで発動してはならない")

    def test_no_fire_manual_poly_crosses_lane(self):
        # 手動配線(固定折れ線)がトランクを横切る → fork は固定配線で
        # 後から避けられないため不発動(横切らない手動配線なら発動する)。
        # 座標はこのスペックの実レイアウト(ecs1/ecs2 左辺中心 (265.4, 237)/
        # (265.4, 633)。x=250 の縦ランが 2 本のトランクを横切る)
        spec = self._fork_spec("AZ A", "AZ C")
        spec["edges"].append(
            {"id": "e_manual", "src": "ecs1", "dst": "ecs2",
             "exit": [0, 0.5], "entry": [0, 0.5],
             "points": [[250, 237], [250, 633]]})
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "fork-manual-x")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("fork 配線", r.stdout,
                             "手動配線がレーンを横切るのに発動した")
        spec["edges"][-1] = {
            "id": "e_manual", "src": "aurora1", "dst": "aurora2",
            "exit": [1, 0.5], "entry": [1, 0.5],
            "points": [[640, 237], [640, 633]]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "fork-manual-far")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("fork 配線", r.stdout,
                          "レーン外の手動配線で不発動になった")


class TestSublaneRepair(unittest.TestCase):
    """R5-C: 終端二段ステップの近傍サブレーン修復の回帰。

    回廊格子だけでは、終端手前の登りが他エッジの縦レーンと交差/重走する
    図で「横→短い段差→横」の二段ステップが最適解になる(理想の一本登りが
    探索空間に無い — 磨きパスも回廊格子上の経路しか返せない)。修復は
    回廊±SUBLANE_OFF のサブレーン入り拡張格子で該当エッジだけを引き直す。
    """

    # ファズ検体 fc109 の最小化(コンテナ 1+5 ノード 5 エッジ)。修正前実測:
    # e4 が exit 直後 32px で 36.3px の小段差(横32→縦36.3→横170→縦61.7→横32)
    SPEC = {
        "name": "r5c-min", "meta": {"purpose": "t"},
        "containers": [
            {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"}],
        "nodes": [
            {"id": "n0", "icon": "ec2", "label": "N0", "col": 1, "row": 0,
             "parent": "cloud"},
            {"id": "n1", "icon": "s3", "label": "N1", "col": 0, "row": 1,
             "parent": "cloud"},
            {"id": "n2", "icon": "lambda", "label": "N2", "col": 3, "row": 0,
             "parent": "cloud"},
            {"id": "n4", "icon": "sns", "label": "N4", "col": 0, "row": 0,
             "parent": "cloud"},
            {"id": "n5", "icon": "dynamodb", "label": "N5", "col": 2, "row": 0,
             "parent": "cloud"}],
        "edges": [
            {"id": "e3", "src": "n1", "dst": "n2", "kind": "main"},
            {"id": "e4", "src": "n5", "dst": "n4", "kind": "main"},
            {"id": "e5", "src": "n4", "dst": "n2", "kind": "main"},
            {"id": "e6", "src": "n0", "dst": "n4", "kind": "main"},
            {"id": "e7", "src": "n1", "dst": "n5", "kind": "main"}]}

    def _route(self, disable_repair: bool = False):
        spec = json.loads(json.dumps(self.SPEC))
        icons = B.load_icons()
        B.validate_spec(spec)
        lay, _, _ = B.place(spec, icons)
        edges = spec["edges"]
        B.validate_spec_edges(lay, edges, None)
        _, routable, _, fixed_polys = B.classify_edges(lay, edges)
        router = B.Router(lay.xs, lay.ys, lay.obstacles,
                          borders=[lay.boxes[cid] for cid in lay.cmap],
                          title_bands=lay.title_bands)
        orig = B._two_step_ends
        if disable_repair:   # 検出を空振りさせて修復前の経路を観測する
            B._two_step_ends = lambda _p: 0
        try:
            routes = B.route_all(router, lay, routable, fixed_polys, None)
        finally:
            B._two_step_ends = orig
        return lay, routes, B.finalize_polys(lay, routable, routes)

    def test_detector_shapes(self):
        two_step = [(379.0, 91.3), (347.0, 91.3), (347.0, 55.0),
                    (177.0, 55.0), (177.0, 116.7), (145.0, 116.7)]
        self.assertEqual(B._two_step_ends(two_step), 1, "src 側の二段ステップ")
        mirror = [(p[0], -p[1]) for p in reversed(two_step)]
        self.assertEqual(B._two_step_ends(mirror), 1, "dst 側の二段ステップ")
        z = [(0, 0), (100, 0), (100, 20), (250, 20)]  # 3 区間の Z 字は正常形
        self.assertEqual(B._two_step_ends(z), 0)
        tall = [(0, 0), (60, 0), (60, 90), (200, 90), (200, 180), (230, 180)]
        self.assertEqual(B._two_step_ends(tall), 0, "段差が大きければ対象外")
        diag = [(0, 0), (100, 0), (150, 30), (150, 100), (140, 100),
                (140, 130)]
        self.assertEqual(B._two_step_ends(diag), 0, "斜め区間を含めば対象外")

    def test_repair_resolves_two_step(self):
        # 修復無効(before): e4 に二段ステップが残ることを生きた実測で確認
        _, _, polys0 = self._route(disable_repair=True)
        self.assertEqual(B._two_step_ends(polys0["e4"]), 1,
                         f"再現前提が崩れた: {polys0['e4']}")
        x0 = len(B.crossing_pairs(list(polys0.items())))
        # 修復有効(after): 段差が消え、登りはサブレーン(回廊±18)を通る
        lay, routes, polys = self._route()
        for eid, poly in polys.items():
            self.assertEqual(B._two_step_ends(poly), 0,
                             f"{eid} に二段ステップが残存: {poly}")
        runs = routes["e4"].runs
        sub_x = lay.xs[lay.xi_corr[2]] - B.SUBLANE_OFF
        sub_y = lay.ys[lay.yi_corr[1]] - B.SUBLANE_OFF
        self.assertTrue(any(r.axis == "v" and abs(r.coord - sub_x) < 0.6
                            for r in runs),
                        f"縦の登りがサブレーン x={sub_x} を通らない: "
                        f"{[(r.axis, r.coord) for r in runs]}")
        self.assertTrue(any(r.axis == "h" and abs(r.coord - sub_y) < 0.6
                            for r in runs),
                        f"横断がサブレーン y={sub_y} を通らない: "
                        f"{[(r.axis, r.coord) for r in runs]}")
        x1 = len(B.crossing_pairs(list(polys.items())))
        self.assertLessEqual(x1, x0, f"修復で交差が増えた: {x0}→{x1}")

    def test_repair_build_clean(self):
        # サブレーン経路込みの最終出力が 0e0w(E7 重走・W5 題字貫通なし)
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self.SPEC, Path(td), "r5c-min")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stdout, r.stdout)
        self.assertNotIn("E7", r.stdout, r.stdout)
        self.assertNotIn("W5", r.stdout, r.stdout)

    def test_straight_edge_untouched(self):
        # 修復フェーズは段差検出ゼロの図に手を出さない(直線の非退行)
        spec = base_spec()
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "r5c-straight", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ab = json.loads((Path(td) / "r5c-straight.spec.out.abs.json")
                            .read_text(encoding="utf-8"))
        e1 = [e for d in ab["diagrams"] for e in d["edges"]
              if e["id"] == "e1"][0]
        self.assertEqual(e1.get("points") or [], [], f"直線が折れた: {e1}")


class TestRouteInertia(unittest.TestCase):
    """R5-D: 経路の慣性(<out>.routes.json キャッシュ)の回帰。

    ルータは毎ビルド全エッジを引き直すため、pin を 1 本追加しただけで
    無関係なエッジの経路が大きく変わる(実測: 下の SPEC で e7 を同一形状の
    まま pin 化すると、e3 が 2 折れの直登から外周帯経由の大迂回になる)。
    キャッシュは前回経路を初期解として保持し、(a) 幾何的に有効かつ
    (b) タブ全体のスコア(交差→題字→anti→fan→折れ→長さ)が悪化しない
    限り維持する。読みはファイルが存在する場合のみ・書きは --route-cache
    指定時か既存ファイルの更新時のみ(テンプレ・CI・eval のバイト一致検証を
    壊さない既定)。
    """

    # TestSublaneRepair と同系のファズ最小化スペック(5 ノード 5 エッジ)
    SPEC = {
        "name": "r5d-min", "meta": {"purpose": "t"},
        "containers": [
            {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"}],
        "nodes": [
            {"id": "n0", "icon": "ec2", "label": "N0", "col": 1, "row": 0,
             "parent": "cloud"},
            {"id": "n1", "icon": "s3", "label": "N1", "col": 0, "row": 1,
             "parent": "cloud"},
            {"id": "n2", "icon": "lambda", "label": "N2", "col": 3, "row": 0,
             "parent": "cloud"},
            {"id": "n4", "icon": "sns", "label": "N4", "col": 0, "row": 0,
             "parent": "cloud"},
            {"id": "n5", "icon": "dynamodb", "label": "N5", "col": 2, "row": 0,
             "parent": "cloud"}],
        "edges": [
            {"id": "e3", "src": "n1", "dst": "n2", "kind": "main"},
            {"id": "e4", "src": "n5", "dst": "n4", "kind": "main"},
            {"id": "e5", "src": "n4", "dst": "n2", "kind": "main"},
            {"id": "e6", "src": "n0", "dst": "n4", "kind": "main"},
            {"id": "e7", "src": "n1", "dst": "n5", "kind": "main"}]}

    def _build(self, spec, tmp: Path, *extra):
        """spec を同一パスへ書いてビルドし(=キャッシュを共有)、エッジ形状を返す。"""
        p = tmp / "inertia.spec.json"
        p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        r = run_build(p, "--emit-abs", "--no-validate", *extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads((tmp / "inertia.spec.out.abs.json")
                       .read_text(encoding="utf-8"))["diagrams"][0]
        geo = {e["id"]: (e.get("exit"), e.get("entry"), e.get("points"))
               for e in d["edges"]}
        return geo, r.stdout

    def _pin(self, spec, geo, eid):
        """ビルド済み形状そのままで 1 エッジを手動配線(pin)に凍結する。"""
        s2 = json.loads(json.dumps(spec))
        e = [x for x in s2["edges"] if x["id"] == eid][0]
        ex, en, pts = geo[eid]
        e["exit"], e["entry"] = ex, en
        if pts:
            e["points"] = pts
        return s2

    def test_pin_keeps_unrelated_edges(self):
        # 再現→修復: pin 1 本の追加で無関係エッジが動く事象を before で実測し、
        # キャッシュ有効の after では座標まで維持されることを assert する
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            geo0, _ = self._build(self.SPEC, tmp)
            cache = tmp / "inertia.spec.out.routes.json"
            self.assertFalse(cache.exists(),
                             "フラグ無しのビルドがキャッシュを書いた")
            geo1, _ = self._build(self.SPEC, tmp, "--route-cache")
            self.assertTrue(cache.exists())
            self.assertEqual(geo0, geo1, "キャッシュ書き込みが図を変えた")
            pinned = self._pin(self.SPEC, geo0, "e7")
            with tempfile.TemporaryDirectory() as td2:  # before: キャッシュ無し
                geo_b, _ = self._build(pinned, Path(td2))
            changed_b = [k for k in geo0 if k != "e7" and geo_b[k] != geo0[k]]
            self.assertIn("e3", changed_b, f"再現前提が崩れた: {changed_b}")
            self.assertGreater(
                len(geo_b["e3"][2] or []), len(geo0["e3"][2] or []),
                f"再現前提(e3 の大迂回)が崩れた: {geo_b['e3']}")
            geo_a, _ = self._build(pinned, tmp)         # after: キャッシュあり
            for eid in ("e3", "e5", "e6"):
                self.assertEqual(geo_a[eid], geo0[eid],
                                 f"無関係エッジ {eid} が維持されない")
            changed_a = [k for k in geo0 if k != "e7" and geo_a[k] != geo0[k]]
            # e4 は pin と同じポート辺(n5 の L)を共有するためスロット再割当
            # のみ許容(経路の runs は維持される)
            self.assertLessEqual(set(changed_a), {"e4"}, f"{changed_a}")

    def test_rebuild_deterministic(self):
        # 同一 spec+キャッシュ → .drawio もキャッシュもバイト一致(決定論)。
        # フラグ無しでも既存キャッシュは読み書きされる(オプトイン後は自動)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._build(self.SPEC, tmp, "--route-cache")
            out = tmp / "inertia.spec.out.drawio"
            cache = tmp / "inertia.spec.out.routes.json"
            xml1, cj1 = out.read_bytes(), cache.read_bytes()
            data = json.loads(cj1.decode("utf-8"))
            self.assertEqual(data["version"], B.ROUTE_CACHE_VERSION)
            tab = data["tabs"][0]
            self.assertRegex(tab["hash"], r"^[0-9a-f]{64}$")
            self.assertEqual(set(tab["edges"]),
                             {"e3", "e4", "e5", "e6", "e7"})
            _, out2 = self._build(self.SPEC, tmp)
            self.assertEqual(out.read_bytes(), xml1,
                             "キャッシュヒットで出力が変わった")
            self.assertEqual(cache.read_bytes(), cj1,
                             "キャッシュ内容が安定しない")
            self.assertIn("経路キャッシュ", out2)

    def test_quality_beats_inertia_bends(self):
        # 品質劣後: pin 下で生じた大迂回 e3 がキャッシュに残っていても、
        # pin を外した再ビルドでは棄却され、素の解とバイト一致する
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            geo0, _ = self._build(self.SPEC, tmp)
            xml0 = (tmp / "inertia.spec.out.drawio").read_bytes()
            self._build(self._pin(self.SPEC, geo0, "e7"), tmp, "--route-cache")
            cache = json.loads((tmp / "inertia.spec.out.routes.json")
                               .read_text(encoding="utf-8"))
            self.assertGreaterEqual(
                len(cache["tabs"][0]["edges"]["e3"]["runs"]), 5,
                "前提が崩れた: キャッシュの e3 が迂回形でない")
            self.assertNotIn("e7", cache["tabs"][0]["edges"],
                             "手動配線(pin)がキャッシュに入った")
            self._build(self.SPEC, tmp)
            self.assertEqual((tmp / "inertia.spec.out.drawio").read_bytes(),
                             xml0, "劣化キャッシュが棄却されていない")

    def _route_square(self):
        """コンテナ無し 2x2 の直行 2 本(交差ゼロ)を in-process で配線する。"""
        spec = {"name": "sq", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "a", "icon": "ec2", "label": "A", "col": 0, "row": 0},
                    {"id": "b", "icon": "s3", "label": "B", "col": 1, "row": 0},
                    {"id": "c", "icon": "lambda", "label": "C", "col": 0, "row": 1},
                    {"id": "d", "icon": "sqs", "label": "D", "col": 1, "row": 1}],
                "edges": [{"id": "e1", "src": "a", "dst": "b", "kind": "main"},
                          {"id": "e2", "src": "c", "dst": "d", "kind": "main"}]}
        icons = B.load_icons()
        B.validate_spec(spec)
        lay, _, _ = B.place(spec, icons)
        edges = spec["edges"]
        B.validate_spec_edges(lay, edges, None)
        _, routable, _, fixed_polys = B.classify_edges(lay, edges)
        router = B.Router(lay.xs, lay.ys, lay.obstacles,
                          borders=[lay.boxes[cid] for cid in lay.cmap],
                          title_bands=lay.title_bands)
        return lay, routable, fixed_polys, router

    def test_quality_beats_inertia_crossings(self):
        # 交差が増える旧経路は、幾何的に有効でも棄却される(スコア第 1 キー)
        lay, routable, fixed_polys, router = self._route_square()
        fresh = B.route_all(router, lay, routable, fixed_polys, None)
        polys_f = B.finalize_polys(lay, routable, fresh)
        xf = len(B.crossing_pairs(list(polys_f.items())))
        xm = lay.xs[lay.xi_corr[1]]      # col0-col1 間の回廊
        xr = lay.xs[lay.xi_corr[2]]      # 右外周回廊
        yb = lay.ys[lay.yi_corr[2]]      # 下外周回廊
        # e1(a→b)を下段の外周へ潜らせて戻す迂回: e2 の直行線を 1 回横切る
        seed = B.NodeRoute(exit=("R", .5), entry=("R", .5),
                           runs=[B.Run("h", 0.0), B.Run("v", xm),
                                 B.Run("h", yb), B.Run("v", xr),
                                 B.Run("h", 0.0)], direct=False)
        e1 = routable[0]
        self.assertTrue(B._seed_geometry_ok(lay, e1, seed),
                        "前提が崩れた: 迂回シードが幾何的に無効")
        forced = dict(fresh)
        forced["e1"] = seed
        xx = len(B.crossing_pairs(
            list(B.finalize_polys(lay, routable, forced).items())))
        self.assertGreater(xx, xf, "前提が崩れた: シードが交差を増やさない")
        routes2 = B.route_all(router, lay, routable, fixed_polys, None,
                              seed_routes={"e1": seed})
        self.assertEqual(routes2["e1"], fresh["e1"],
                         "交差が増える旧経路が棄却されていない")

    def test_identical_seed_kept(self):
        # 新規経路と同一のシードはそのまま維持される(スコア同点は旧を採る)
        lay, routable, fixed_polys, router = self._route_square()
        fresh = B.route_all(router, lay, routable, fixed_polys, None)
        copy = B.NodeRoute(exit=fresh["e1"].exit, entry=fresh["e1"].entry,
                           runs=[B.Run(r.axis, r.coord)
                                 for r in fresh["e1"].runs],
                           direct=fresh["e1"].direct)
        routes2 = B.route_all(router, lay, routable, fixed_polys, None,
                              seed_routes={"e1": copy})
        self.assertEqual(routes2["e1"], fresh["e1"])

    def test_struct_hash_invalidation(self):
        # ハッシュは ノード/エッジ集合(id・col/row・parent・src/dst)にのみ反応。
        # pin・ラベル・kind の変更では不変(慣性を生かす)
        h0 = B.routes_struct_hash(self.SPEC)
        pinned = json.loads(json.dumps(self.SPEC))
        pinned["edges"][0].update(
            {"exit": [1, 0.5], "entry": [0, 0.5], "points": [[10, 20]]})
        pinned["edges"][1]["label"] = "変更"
        pinned["edges"][2]["kind"] = "sub"
        self.assertEqual(B.routes_struct_hash(pinned), h0)
        for mutate in (
                lambda s: s["nodes"].append(
                    {"id": "n9", "icon": "ec2", "col": 4, "row": 1,
                     "parent": "cloud"}),
                lambda s: s["nodes"][0].update({"col": 4}),
                lambda s: s["nodes"][0].pop("parent"),
                lambda s: s["edges"][0].update({"dst": "n5"}),
                lambda s: s["edges"].pop()):
            s2 = json.loads(json.dumps(self.SPEC))
            mutate(s2)
            self.assertNotEqual(B.routes_struct_hash(s2), h0, s2)
        # ハッシュ不一致のタブはシード復元されない(全体無効)
        route = {"exit": ["R", 0.5], "entry": ["L", 0.5],
                 "runs": [["h", 100.0]], "direct": True}
        cache = {"version": B.ROUTE_CACHE_VERSION,
                 "tabs": [{"hash": h0, "equalized": False,
                           "edges": {"e3": route}}]}
        got = B.seed_routes_from_cache(cache, 0, self.SPEC)
        self.assertIsNotNone(got)
        seeds, equalized = got
        self.assertEqual(set(seeds), {"e3"})
        self.assertFalse(equalized)
        added = json.loads(json.dumps(self.SPEC))
        added["nodes"].append({"id": "n9", "icon": "ec2", "col": 4, "row": 1})
        self.assertIsNone(B.seed_routes_from_cache(cache, 0, added))
        self.assertIsNone(B.seed_routes_from_cache(cache, 1, self.SPEC))

    def test_invalidation_end_to_end(self):
        # ノード追加 → 構成ハッシュ不一致で全体無効(クラッシュせず素の配線)。
        # キャッシュは新しいハッシュで書き直される
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._build(self.SPEC, tmp, "--route-cache")
            cache = tmp / "inertia.spec.out.routes.json"
            h1 = json.loads(cache.read_text(encoding="utf-8"))["tabs"][0]["hash"]
            grown = json.loads(json.dumps(self.SPEC))
            grown["nodes"].append({"id": "n9", "icon": "ec2", "label": "N9",
                                   "col": 3, "row": 1, "parent": "cloud"})
            grown["edges"].append({"id": "e9", "src": "n2", "dst": "n9",
                                   "kind": "main"})
            geo_g, _ = self._build(grown, tmp)
            with tempfile.TemporaryDirectory() as td2:  # 素の配線と一致する
                geo_f, _ = self._build(grown, Path(td2))
            self.assertEqual(geo_g, geo_f,
                             "無効なはずのキャッシュが配線に影響した")
            h2 = json.loads(cache.read_text(encoding="utf-8"))["tabs"][0]["hash"]
            self.assertNotEqual(h1, h2, "ハッシュが更新されていない")

    def test_corrupt_cache_ignored(self):
        # 壊れたキャッシュは WARN して無視(ビルドは素の配線で成功)し、
        # 有効な内容で書き直される(自己修復)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with tempfile.TemporaryDirectory() as td2:
                geo_f, _ = self._build(self.SPEC, Path(td2))
            cache = tmp / "inertia.spec.out.routes.json"
            for garbage in ("{broken json",
                            json.dumps({"version": 99, "tabs": []})):
                cache.write_text(garbage, encoding="utf-8")
                geo, out = self._build(self.SPEC, tmp)
                self.assertIn("WARN: 経路キャッシュ", out)
                self.assertEqual(geo, geo_f)
                data = json.loads(cache.read_text(encoding="utf-8"))
                self.assertEqual(data["version"], B.ROUTE_CACHE_VERSION)

    def test_equalize_rollback_idempotent(self):
        # 等化ロールバック(R4-6)が起きるテンプレ(multiaccount の CI/CD タブ)
        # でも、キャッシュ付き再ビルドは冪等でテンプレとバイト一致のまま。
        # 非等化ビルド由来のシードを等化レイアウトに注入するとロールバック
        # 判定が変わり build1→build2 で出力が黙って変わるバグの回帰(実測)
        src = ROOT / "templates" / "example-multiaccount.spec.json"
        committed = (ROOT / "templates" / "example-multiaccount.drawio"
                     ).read_bytes()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = tmp / src.name
            shutil.copy(src, spec)
            r1 = run_build(spec, "--route-cache")
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            out = tmp / (spec.stem + ".out.drawio")
            self.assertEqual(out.read_bytes(), committed)
            cache = json.loads(
                (tmp / (spec.stem + ".out.routes.json"))
                .read_text(encoding="utf-8"))
            self.assertFalse(cache["tabs"][1]["equalized"],
                             "前提が崩れた: CI/CD タブがロールバックされていない")
            r2 = run_build(spec)     # キャッシュ読み込みつき再ビルド
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertEqual(out.read_bytes(), committed,
                             "キャッシュ付き再ビルドが冪等でない")

    def test_decode_route_validation(self):
        ok = {"exit": ["R", 0.5], "entry": ["L", 0.5],
              "runs": [["h", 100.0]], "direct": True}
        self.assertIsNotNone(B._decode_route(ok))
        bads = [
            {**ok, "exit": ["X", 0.5]},                  # 未知の辺
            {**ok, "entry": ["L", 1.5]},                 # frac 範囲外
            {**ok, "exit": ["R", float("nan")]},         # 非有限
            {**ok, "runs": []},                          # 空経路
            {**ok, "runs": [["h", 1.0], ["h", 2.0]],
             "direct": False},                           # 同軸連続
            {**ok, "runs": [["v", 1.0]]},                # exit R と軸不一致
            {**ok, "runs": [["h", 1.0], ["v", 2.0]]},    # entry L と軸不一致
            {**ok, "runs": [["h", 1.0], ["v", 2.0], ["h", 3.0]]},  # direct 矛盾
            {**ok, "direct": "yes"},                     # 型不正
            "not-a-dict",
        ]
        for bad in bads:
            self.assertIsNone(B._decode_route(bad), bad)


class TestJsUnsafeIds(unittest.TestCase):
    """R7-1: JS 予約語 id は XML 上でのみ退避され、CLI エクスポートが通る。

    drawio CLI v30.3.11 の id スイープ実測: Array.prototype / Object.prototype
    のプロパティ名と同名の mxCell id は PNG/SVG 書き出しが全フォーマットで
    「Export failed」(詳細なし)になる(バリデータ 0e0w でも成果物が出ない
    沈黙破損)。ビルダーは XML 上の id だけ末尾 "_" へ退避し(spec は不変)、
    バリデータは手書き XML の危険 id を E11 で拒否する。
    """

    def _spec(self):
        return {"name": "js", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "start", "shape": "terminator", "label": "Start",
                     "col": 0, "row": 0},
                    {"id": "join", "shape": "process", "label": "Join",
                     "col": 1, "row": 0}],
                "edges": [{"id": "map", "src": "start", "dst": "join",
                           "kind": "main"}]}

    def test_xml_ids_sanitized(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._spec(), Path(td), "js")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s)", r.stdout)
            self.assertIn("NOTE: id 'join'", r.stdout)
            self.assertIn("NOTE: id 'map'", r.stdout)
            xml = (Path(td) / "js.spec.out.drawio").read_text(encoding="utf-8")
            self.assertIn('id="join_"', xml)
            self.assertIn('target="join_"', xml)
            self.assertIn('id="map_"', xml)
            self.assertNotIn('id="join"', xml)
            self.assertNotIn('id="map"', xml)
            self.assertNotIn('target="join"', xml)

    def test_id_map_identity_and_collision(self):
        # 安全な id は不変(空マップ=既存出力バイト不変の根拠)
        self.assertEqual(B.xml_id_map(
            {"nodes": [{"id": "joinx"}, {"id": "merge"}]}), {})
        # 退避先が既存 id と衝突するときは "_" を追加(単射を維持)
        m = B.xml_id_map({"nodes": [{"id": "join"}, {"id": "join_"}]})
        self.assertEqual(m, {"join": "join__"})

    def test_denylists_in_sync(self):
        import validate_drawio as V
        self.assertEqual(B.JS_UNSAFE_IDS, V.JS_UNSAFE_IDS,
                         "build と validate の予約語集合がずれています")

    def test_validator_e11_on_handmade_xml(self):
        xml = """<mxfile><diagram id="d0" name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="join" value="A" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""
        with tempfile.NamedTemporaryFile("w", suffix=".drawio",
                                         delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            r = subprocess.run([sys.executable, str(VALIDATE), p],
                               capture_output=True, text=True, timeout=15)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("E11", r.stdout)
            self.assertIn("join", r.stdout)
        finally:
            os.unlink(p)

    @unittest.skipUnless(shutil.which("drawio"),
                         "drawio CLI 不在(id 退避の単体テストで代替)")
    def test_cli_export_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._spec(), Path(td), "js")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            src = Path(td) / "js.spec.out.drawio"
            png = Path(td) / "js.png"
            rc = subprocess.run(
                ["drawio", "-x", "-f", "png", "-o", str(png), str(src)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            self.assertTrue(png.exists() and png.stat().st_size > 0,
                            "PNG が生成されていない")


class TestSelfLoopLabelPlacement(unittest.TestCase):
    """R7-2: 自己参照ループの label が高い entity 箱+隣接密集でも E5 にならない。

    旧実装はラベルをブラケット内側(箱の縁から 14px)に置いたため、6 行の
    entity では必ず箱に食い込み E5 でビルドが失敗した(監査4: 実測 6x16px)。
    新実装はループ縦線の外側で障害物と重ならない y を探索し、収まらなければ
    ループごと反対辺へ切り替える。
    """

    def _spec(self):
        rows6 = ["PK id: bigint", "FK task_id", "FK user_id",
                 "FK parent_comment_id", "body: text", "created_at: timestamp"]
        return {"name": "sl2", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "left_n", "shape": "entity", "title": "team_members",
                     "rows": ["PK id", "FK team_id"], "col": 0, "row": 0},
                    {"id": "comments", "shape": "entity", "title": "comments",
                     "rows": rows6, "col": 1, "row": 0},
                    {"id": "right_n", "shape": "entity", "title": "task_assignees",
                     "rows": ["PK id", "FK task_id"], "col": 2, "row": 0}],
                "edges": [
                    {"id": "r1", "src": "comments", "dst": "comments",
                     "kind": "er_0n", "label": "parent"},
                    {"id": "r2", "src": "left_n", "dst": "comments",
                     "kind": "er_1n"},
                    {"id": "r3", "src": "comments", "dst": "right_n",
                     "kind": "er_1n"}]}

    def test_no_e5_and_label_outside_boxes(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._spec(), Path(td), "sl2", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
            absspec = json.loads(
                (Path(td) / "sl2.spec.out.abs.json").read_text(encoding="utf-8"))
            d = absspec["diagrams"][0] if "diagrams" in absspec else absspec
            loop = next(e for e in d["edges"] if e["id"] == "r1")
            self.assertIn("label_at", loop)
            lx, ly = loop["label_at"]
            lw, lh = B.text_size("parent", 11)
            lbox = (lx - lw / 2, ly - lh / 2, lw, lh)
            for n in d["nodes"]:
                if n.get("shape") != "entity":
                    continue   # 生成ノード(メタ等)は cx を持たない
                _lbl, iw, ih = B.entity_geometry(n)
                w, h = n.get("w", iw), n.get("h", ih)
                x, y = n["cx"] - w / 2, n["cy"] - h / 2
                self.assertFalse(
                    B._rect_hits(lbox, (x, y, w, h)),
                    f"ラベル {lbox} が entity '{n['id']}' "
                    f"({x},{y},{w},{h}) と重なっています")

    def test_label_free_side_still_works(self):
        # 疎な図(自己ループ+ラベルのみ)も従来どおり 0e0w
        spec = {"name": "sl3", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "emp", "shape": "entity", "title": "employees",
                     "rows": ["PK id", "FK manager_id"], "col": 0, "row": 0}],
                "edges": [
                    {"id": "r1", "src": "emp", "dst": "emp", "kind": "er_1n",
                     "label": "上司"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "sl3")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)


class TestR7BatchB(unittest.TestCase):
    """R7-4 両端ラベル / R7-5 ER端別 / R7-6 stereotype の回帰。"""

    META = {"purpose": "t", "audience": "t", "scope": "t",
            "abstraction": "t", "assumptions": "t"}

    @staticmethod
    def _cells(path: Path):
        import xml.etree.ElementTree as ET
        return {c.get("id"): c for c in ET.parse(path).iter("mxCell")}

    @staticmethod
    def _entity_box(n: dict):
        _label, iw, ih = B.entity_geometry(n)
        w, h = n.get("w", iw), n.get("h", ih)
        if "cx" in n:
            return n["cx"] - w / 2, n["cy"] - h / 2, w, h
        return n["x"], n["y"], w, h

    def test_grid_end_labels_are_native_near_ends_and_clear(self):
        spec = {"name": "r74-grid", "meta": self.META,
                "nodes": [
                    {"id": "order", "shape": "entity", "title": "Order",
                     "rows": ["+ id: int"], "col": 0, "row": 0},
                    {"id": "line", "shape": "entity", "title": "OrderLine",
                     "rows": ["+ qty: int"], "col": 0, "row": 1}],
                "edges": [{"id": "rel", "src": "order", "dst": "line",
                           "kind": "uml_compose", "label": "contains",
                           "src_label": "1", "dst_label": "1..*"}]}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "r74-grid", "--emit-abs", "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
            drawio = tmp / "r74-grid.spec.out.drawio"
            cells = self._cells(drawio)
            children = [c for c in cells.values()
                        if c.get("parent") == "rel"
                        and "edgeLabel" in c.get("style", "")]
            self.assertEqual({c.get("value") for c in children}, {"1", "1..*"})
            self.assertEqual({c.find("mxGeometry").get("x") for c in children},
                             {"-1", "1"})
            self.assertTrue(all(c.find("mxGeometry").get("relative") == "1"
                                for c in children))

            data = json.loads((tmp / "r74-grid.spec.out.abs.json").read_text(
                encoding="utf-8"))["diagrams"][0]
            edge = next(e for e in data["edges"] if e["id"] == "rel")
            nodes = {n["id"]: n for n in data["nodes"]
                     if n.get("shape") == "entity"}
            boxes = {nid: self._entity_box(n) for nid, n in nodes.items()}
            endpoints = {}
            for term, frac in (("src", "exit"), ("dst", "entry")):
                x, y, w, h = boxes[edge[term]]
                fx, fy = edge[frac]
                endpoints[term] = (x + fx * w, y + fy * h)
            for term, label in (("src", "1"), ("dst", "1..*")):
                pos = edge[f"{term}_label_at"]
                self.assertLessEqual(math.dist(pos, endpoints[term]), 90)
                lw, lh = B.text_size(label, 11)
                lbox = (pos[0] - lw / 2, pos[1] - lh / 2, lw, lh)
                self.assertFalse(any(B._rect_hits(lbox, box)
                                     for box in boxes.values()), (term, lbox, boxes))
            svg = (tmp / "r74-grid.spec.out.svg").read_text(encoding="utf-8")
            self.assertIn(">1<", svg)
            self.assertIn(">1..*<", svg)

    def _abs_spec(self, src_label_at=None):
        edge = {"id": "rel", "src": "parent", "dst": "child",
                "kind": "er_01n", "exit": [1, 0.5], "entry": [0, 0.5],
                "src_label": "0..1", "dst_label": "*"}
        if src_label_at is not None:
            edge["src_label_at"] = src_label_at
        return {"name": "r7-abs", "meta": self.META,
                "nodes": [
                    {"id": "parent", "shape": "entity", "title": "Gateway",
                     "stereotype": "interface", "rows2": ["+ run()"],
                     "x": 40, "y": 40, "w": 160, "h": 80},
                    {"id": "child", "shape": "entity", "title": "Worker",
                     "rows": ["+ id"], "x": 360, "y": 40,
                     "w": 160, "h": 80}],
                "edges": [edge], "page": [640, 240]}

    def test_abs_path_supports_all_three_features_and_svg(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(self._abs_spec(), tmp, "r7-abs", "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
            xml = (tmp / "r7-abs.spec.out.drawio").read_text(encoding="utf-8")
            self.assertIn("ERzeroToOne", xml)
            self.assertIn("fontStyle=3", xml)
            cells = self._cells(tmp / "r7-abs.spec.out.drawio")
            children = [c for c in cells.values() if c.get("parent") == "rel"]
            self.assertEqual({c.get("value") for c in children}, {"0..1", "*"})
            self.assertEqual({c.find("mxGeometry").get("x") for c in children},
                             {"-1", "1"})
            svg = (tmp / "r7-abs.spec.out.svg").read_text(encoding="utf-8")
            self.assertIn(">0..1<", svg)
            self.assertIn(">*<", svg)
            self.assertIn("«interface»", svg)
            self.assertRegex(svg, r'font-style="italic"[^>]*>.*Gateway')
            self.assertIn("<circle", svg)  # ERzeroToOne の親側 ○

    def test_validator_checks_child_end_label_against_endpoint_box(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(self._abs_spec(src_label_at=[120, 80]), Path(td),
                           "r74-overlap")
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("E5", r.stdout + r.stderr)
            self.assertIn("0..1", r.stdout + r.stderr)

    def test_end_label_and_stereotype_invalid_values_rejected_in_both_paths(self):
        grid = {"nodes": [
                    {"id": "a", "shape": "entity", "title": "A",
                     "stereotype": 3, "col": 0, "row": 0},
                    {"id": "b", "shape": "entity", "title": "B",
                     "col": 1, "row": 0}],
                "edges": [{"id": "e", "src": "a", "dst": "b",
                           "src_label": ""}]}
        with self.assertRaises(B.SpecError) as cm:
            B.validate_spec(grid)
        self.assertIn("stereotype", str(cm.exception))
        self.assertIn("src_label", str(cm.exception))

        bad_abs_st = self._abs_spec()
        bad_abs_st["nodes"][0]["stereotype"] = []
        with self.assertRaises(B.SpecError) as cm2:
            B.check_abs_basics(bad_abs_st)
        self.assertIn("stereotype", str(cm2.exception))

        bad_abs_label = self._abs_spec()
        bad_abs_label["edges"][0]["dst_label"] = ""
        with self.assertRaises(B.SpecError) as cm3:
            B.check_abs_basics(bad_abs_label)
        self.assertIn("dst_label", str(cm3.exception))

    def test_er_endpoint_kinds_and_legend_keep_parent_marker_at_source(self):
        spec = {"name": "r75", "meta": self.META,
                "legend": {"er_01n": "nullable FK", "er_11n": "required FK"},
                "nodes": [
                    {"id": "p01", "shape": "entity", "title": "teams",
                     "rows": ["PK id"], "col": 0, "row": 0},
                    {"id": "c01", "shape": "entity", "title": "projects",
                     "rows": ["FK team_id"], "col": 1, "row": 0},
                    {"id": "p11", "shape": "entity", "title": "accounts",
                     "rows": ["PK id"], "col": 0, "row": 1},
                    {"id": "c11", "shape": "entity", "title": "members",
                     "rows": ["FK account_id"], "col": 1, "row": 1}],
                "edges": [
                    {"id": "e01", "src": "p01", "dst": "c01",
                     "kind": "er_01n"},
                    {"id": "e11", "src": "p11", "dst": "c11",
                     "kind": "er_11n"}]}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "r75", "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
            cells = self._cells(tmp / "r75.spec.out.drawio")
            self.assertEqual((cells["e01"].get("source"), cells["e01"].get("target")),
                             ("p01", "c01"))
            self.assertIn("startArrow=ERzeroToOne", cells["e01"].get("style"))
            self.assertIn("endArrow=ERmany", cells["e01"].get("style"))
            self.assertEqual((cells["e11"].get("source"), cells["e11"].get("target")),
                             ("p11", "c11"))
            self.assertIn("startArrow=ERmandOne", cells["e11"].get("style"))
            self.assertIn("endArrow=ERmany", cells["e11"].get("style"))
            self.assertIn("startArrow=ERzeroToOne", cells["_lg_e0"].get("style"))
            self.assertIn("startArrow=ERmandOne", cells["_lg_e1"].get("style"))
            svg = (tmp / "r75.spec.out.svg").read_text(encoding="utf-8")
            self.assertIn("<circle", svg)
            self.assertGreaterEqual(B._svg_marker((20, 0), (0, 0), "#000",
                                                   "ERmandOne", False).count("M "), 2)

    def test_grid_stereotype_line_and_title_italic_in_xml_and_svg(self):
        spec = {"name": "r76", "meta": self.META,
                "nodes": [
                    {"id": "iface", "shape": "entity",
                     "title": "PaymentGateway", "stereotype": "interface",
                     "rows2": ["+ charge()"], "col": 0, "row": 0},
                    {"id": "base", "shape": "entity", "title": "BaseOrder",
                     "stereotype": "abstract", "rows": ["# id"],
                     "col": 1, "row": 0}], "edges": []}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "r76", "--emit-svg")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            cells = self._cells(tmp / "r76.spec.out.drawio")
            for nid, stereotype, title in (
                    ("iface", "interface", "PaymentGateway"),
                    ("base", "abstract", "BaseOrder")):
                self.assertIn("fontStyle=3", cells[nid].get("style"))
                value = cells[nid].get("value")
                self.assertIn(f"«{stereotype}»", value)
                self.assertIn(f"<i><b>{title}</b></i>", value)
            svg = (tmp / "r76.spec.out.svg").read_text(encoding="utf-8")
            self.assertIn("«interface»", svg)
            self.assertIn("«abstract»", svg)
            self.assertRegex(svg, r'font-style="italic"[^>]*>.*PaymentGateway')
            self.assertRegex(svg, r'font-style="italic"[^>]*>.*BaseOrder')


class TestR7BatchC(unittest.TestCase):
    """R7-7〜10: 並行 gateway / 新 flow shape / subprocess link。"""

    META = {"purpose": "t", "audience": "t", "scope": "t",
            "abstraction": "t", "assumptions": "t", "updated": "2026-07-18"}

    def test_cli_verified_styles_geometry_and_and_or_distinction(self):
        expected = {
            "gateway": ("shape=mxgraph.bpmn.gateway2", (64.0, 64.0)),
            "delay": ("shape=delay", (120.0, 56.0)),
            "preparation": ("shape=hexagon", (140.0, 56.0)),
            "junction": ("ellipse;aspect=fixed", (28.0, 28.0)),
            "connector": ("ellipse;aspect=fixed", (42.0, 42.0)),
        }
        for shape, (style_part, geometry) in expected.items():
            with self.subTest(shape=shape):
                self.assertIn(style_part, B.FLOW_STYLES[shape])
                self.assertEqual(B.flow_geometry({"shape": shape}), geometry)
        self.assertIn("gwType=parallel", B.FLOW_STYLES["gateway"])
        self.assertIn("rhombus", B.FLOW_STYLES["decision"])
        self.assertNotEqual(B.FLOW_STYLES["gateway"],
                            B.FLOW_STYLES["decision"])

    def test_new_shapes_emit_native_xml_and_matching_svg(self):
        shapes = ("gateway", "delay", "preparation", "junction", "connector")
        labels = {"delay": "待機", "preparation": "準備", "connector": "A"}
        spec = {"name": "r7c-shapes", "meta": self.META,
                "nodes": [
                    {"id": shape, "shape": shape,
                     "label": labels.get(shape, ""), "col": i, "row": 0}
                    for i, shape in enumerate(shapes)],
                "edges": []}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "r7c-shapes", "--emit-svg", "--emit-abs")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
            import xml.etree.ElementTree as ET
            cells = {c.get("id"): c for c in ET.parse(
                tmp / "r7c-shapes.spec.out.drawio").iter("mxCell")}
            for shape in shapes:
                self.assertEqual(cells[shape].get("style"), B.FLOW_STYLES[shape])
            svg = (tmp / "r7c-shapes.spec.out.svg").read_text(encoding="utf-8")
            self.assertIn('stroke-width="5"', svg)  # gateway 内部の +
            self.assertGreaterEqual(svg.count("<polygon"), 2)  # gateway + preparation
            self.assertGreaterEqual(svg.count("<path"), 2)     # gateway + delay
            self.assertGreaterEqual(svg.count("<ellipse"), 2)  # junction + connector

    def test_subprocess_link_uses_user_object_and_validates(self):
        for i, link in enumerate(("detail-flow.drawio",
                                  "https://example.com/flow?id=1&tab=detail")):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                spec = {"name": "r7c-link", "meta": self.META,
                        "nodes": [
                            {"id": "start", "shape": "terminator", "label": "開始",
                             "col": 0, "row": 0},
                            {"id": "detail", "shape": "subprocess", "label": "詳細処理",
                             "link": link, "col": 0, "row": 1},
                            {"id": "end", "shape": "terminator", "label": "終了",
                             "col": 0, "row": 2}],
                        "edges": [
                            {"id": "e1", "src": "start", "dst": "detail",
                             "kind": "main"},
                            {"id": "e2", "src": "detail", "dst": "end",
                             "kind": "main"}]}
                r = build_spec(spec, tmp, f"r7c-link-{i}")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("=== 0 error(s), 0 warning(s)", r.stdout)
                import xml.etree.ElementTree as ET
                root = ET.parse(tmp / f"r7c-link-{i}.spec.out.drawio")
                obj = root.find(".//UserObject[@id='detail']")
                self.assertIsNotNone(obj)
                self.assertEqual(obj.get("label"), "詳細処理")
                self.assertEqual(obj.get("link"), link)
                cell = obj.find("mxCell")
                self.assertIsNotNone(cell)
                self.assertIn("shape=process", cell.get("style"))
                edges = {e.get("id"): e for e in root.iter("mxCell")
                         if e.get("edge") == "1"}
                self.assertEqual(edges["e1"].get("target"), "detail")
                self.assertEqual(edges["e2"].get("source"), "detail")

    def test_link_rejects_empty_non_string_and_non_subprocess_in_both_paths(self):
        invalid_grid = (
            {"id": "p", "shape": "process", "label": "x", "link": "x",
             "col": 0, "row": 0},
            {"id": "s", "shape": "subprocess", "link": "", "col": 0, "row": 0},
            {"id": "s", "shape": "subprocess", "link": "   ", "col": 0, "row": 0},
            {"id": "s", "shape": "subprocess", "link": [], "col": 0, "row": 0},
        )
        for node in invalid_grid:
            with self.subTest(path="grid", node=node), self.assertRaises(B.SpecError):
                B.validate_spec({"nodes": [node], "edges": []})
        invalid_abs = (
            {"id": "p", "shape": "process", "link": "x", "x": 0, "y": 0},
            {"id": "s", "shape": "subprocess", "link": "", "x": 0, "y": 0},
            {"id": "s", "shape": "subprocess", "link": "   ", "x": 0, "y": 0},
            {"id": "s", "shape": "subprocess", "link": {}, "x": 0, "y": 0},
        )
        for node in invalid_abs:
            with self.subTest(path="abs", node=node), self.assertRaises(B.SpecError):
                B.check_abs_basics({"nodes": [node], "edges": []})


class TestOptimizeConventions(unittest.TestCase):
    """R7-3: --optimize の採点に向き慣例ペナルティ(監査1・監査4)。

    フロー: 終了系 terminator を流入元より上へ吊り上げる手は「交差 2 個の
    削減」より重く弾く(監査1の実測: rejected (3,6)→(4,3) が交差 2→0 で
    採用され下→上の逆流を生んだ)。ER: er_1n/er_0n の親を子より右へ置く
    手は交差同数のタイブレークで弾く(監査4相当: 総延長の改善だけで
    親→子=左→右が壊れた)。
    """

    # 監査1(01-approval)相当・pin なし
    def _flow_spec(self):
        lanes = [{"id": f"lane_{s}", "label": lbl, "type": "lane"}
                 for s, lbl in (("emp", "申請者"), ("mgr", "上長"),
                                ("acc", "経理"))]
        mk = (("start", "terminator", "開始", "emp", 0, 0),
              ("apply", "io", "経費を申請", "emp", 0, 1),
              ("fix", "process", "申請を修正", "emp", 1, 1),
              ("mgr_check", "decision", "上長が\n承認?", "mgr", 2, 2),
              ("amount", "decision", "5万円\n以上?", "mgr", 2, 3),
              ("rejected", "terminator", "却下", "mgr", 3, 6),
              ("acc_check", "decision", "経理が\n承認?", "acc", 4, 4),
              ("approved", "terminator", "承認済み", "acc", 4, 6))
        nodes = [{"id": i, "shape": sh, "label": lb, "parent": f"lane_{ln}",
                  "col": c, "row": r} for i, sh, lb, ln, c, r in mk]
        edges = [{"id": f"f{k}", "src": s, "dst": t, "kind": kd}
                 for k, (s, t, kd) in enumerate((
                     ("start", "apply", "main"), ("apply", "mgr_check", "main"),
                     ("mgr_check", "amount", "main"),
                     ("mgr_check", "fix", "sub"),
                     ("mgr_check", "rejected", "sub"),
                     ("amount", "approved", "main"),
                     ("amount", "acc_check", "main"),
                     ("acc_check", "approved", "main"),
                     ("acc_check", "rejected", "sub"),
                     ("acc_check", "fix", "sub"),
                     ("fix", "apply", "main")), 1)]
        return {"name": "flow", "meta": {"purpose": "t"},
                "containers": lanes, "nodes": nodes, "edges": edges}

    @staticmethod
    def _term_violations(spec):
        pos = {n["id"]: (n["col"], n["row"]) for n in spec["nodes"]}
        shapes = {n["id"]: n.get("shape") for n in spec["nodes"]}
        return [e["id"] for e in spec["edges"]
                if shapes.get(e["dst"]) == "terminator"
                and e["src"] != e["dst"]
                and pos[e["dst"]][1] < pos[e["src"]][1]]

    def test_terminator_hoist_scores_worse_than_two_crossings(self):
        # ゲート: 「terminator 下部・交差 5」<「terminator 上部・交差 2
        # +逆流ペナルティ 4」(逆流ペナルティ 4 > 交差 3 個分の削減、という
        # 重み設計を監査1の実配置で固定。交差の絶対数は R7-15/16 の
        # diamond 頂点規約で 2/0 → 4/2、R7-A3 の上辺入射規約で 4/2 → 5/2 に
        # 変化。A3 では下部 terminator への合流が側辺退避できず正当配置の
        # 交差が +1 構造化したため、係数も 3 → 4 に再校正(旧係数では
        # 同点になり総延長タイブレークで吊り上げが勝ってしまう)。検証する
        # トレードオフ「向き慣例 > 僅かな交差削減」は同一
        from _common import load_icons
        icons = load_icons()
        spec = self._flow_spec()
        low, _ = B.eval_layout(spec, icons, draft=False)   # rejected (3,6)
        rej = next(n for n in spec["nodes"] if n["id"] == "rejected")
        rej["col"], rej["row"] = 4, 3                      # 監査1の採用位置
        hoist, _ = B.eval_layout(spec, icons, draft=False)
        self.assertEqual(low[1], 5, "前提: 下部配置は交差 5")
        self.assertEqual(hoist[1], 6, "吊り上げ = 交差 2 + 逆流ペナルティ 4")
        self.assertLess(low, hoist,
                        "terminator 逆流が交差 3 個分より軽く採点されています")
        # 逆流の検出自体も確認(acc_check row4 → rejected row3)
        lay, _c, _n = B.place(spec, icons)
        term, er, ids = B.convention_penalties(spec, lay)
        self.assertEqual((term, er), (1, 0))
        self.assertIn("rejected", ids)

    def test_optimize_keeps_terminator_below_sources(self):
        from _common import load_icons
        icons = load_icons()
        spec = self._flow_spec()
        moves = B.optimize_placement(spec, icons, budget_s=12.0)
        self.assertEqual(self._term_violations(spec), [],
                         f"最適化後に terminator 逆流: {spec['nodes']}\n{moves}")

    # 監査4相当: 交差同数のまま総延長だけ改善する「親を子の右へ」移動。
    # 修正前エンジンは p (0,2)→(1,0) を採用していた(実測)。
    def _er_spec(self):
        lbl = "長い日本語ラベル" * 4
        wall = [f"col_{i}: text" for i in range(20)]
        return {"name": "er", "meta": {"purpose": "t"},
                "nodes": [
                    {"id": "c", "shape": "entity", "title": "children",
                     "rows": ["PK id", "FK parent_id"], "col": 0, "row": 0},
                    {"id": "p", "shape": "entity", "title": "parents",
                     "rows": ["PK id"], "col": 0, "row": 2},
                    {"id": "wall", "shape": "entity", "title": "wall",
                     "rows": wall, "col": 1, "row": 2, "pin": True},
                    {"id": "f", "shape": "entity", "title": "far",
                     "rows": ["PK id"], "col": 2, "row": 2, "pin": True},
                    # 解消不能な E1 ペア(探索ループを回し続けるための錘)
                    {"id": "o1", "icon": "ec2", "label": f"{lbl}\n{lbl}",
                     "col": 4, "row": 5, "pin": True},
                    {"id": "o2", "icon": "s3", "label": f"{lbl}\n{lbl}",
                     "col": 5, "row": 5, "pin": True}],
                "edges": [
                    {"id": "r1", "src": "p", "dst": "c", "kind": "er_1n"},
                    {"id": "r2", "src": "p", "dst": "f", "kind": "er_11"}]}

    def test_er_parent_right_scores_worse_at_equal_crossings(self):
        from _common import load_icons
        icons = load_icons()
        spec = self._er_spec()
        keep, _ = B.eval_layout(spec, icons, draft=False)   # p (0,2)
        p = next(n for n in spec["nodes"] if n["id"] == "p")
        p["col"], p["row"] = 1, 0    # 修正前エンジンが採用した違反位置(実測)
        viol, _ = B.eval_layout(spec, icons, draft=False)
        self.assertEqual(keep[1], viol[1], "前提: 交差スコアは同数")
        self.assertEqual((keep[2], viol[2]), (0, 1),
                         "ER 慣例違反が第3キーに載っていない")
        self.assertLess(keep, viol)
        self.assertLess(viol[3], keep[3],
                        "前提: 違反位置の方が総延長は短い(タイブレークの検証対象)")

    def test_optimize_keeps_er_parent_left(self):
        from _common import load_icons
        icons = load_icons()
        spec = self._er_spec()
        B.optimize_placement(spec, icons, budget_s=12.0)
        pos = {n["id"]: (n["col"], n["row"]) for n in spec["nodes"]}
        self.assertLessEqual(pos["p"][0], pos["c"][0],
                             f"親 p が子 c より右に移動: p={pos['p']} c={pos['c']}")


class TestCodexReviewR7(unittest.TestCase):
    """第7R 独立レビュー(REV-1〜11)+ A3 免除境界の回帰。

    eval 側(evals/check_diagram.py)の偽陽性修正は、修正前に実測再現した
    最小ケースを spec から再ビルドして検証する。境界(免除しない側)も
    同じ形の対照ケースで固定する。
    """

    META = {"purpose": "t", "audience": "t", "scope": "t",
            "abstraction": "t", "assumptions": "t"}

    @staticmethod
    def _check_diagram():
        sys.path.insert(0, str(HERE.parent / "evals"))
        import check_diagram as C
        return C

    @staticmethod
    def _drawio(body: str) -> str:
        return ('<mxfile><diagram id="d0" name="t"><mxGraphModel><root>'
                '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                f'{body}</root></mxGraphModel></diagram></mxfile>')

    @staticmethod
    def _node(nid: str, x: float, y: float, w: float = 100, h: float = 60,
              style: str = "rounded=0;") -> str:
        return (f'<mxCell id="{nid}" value="{nid}" style="{style}" vertex="1" '
                f'parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" '
                f'height="{h}" as="geometry"/></mxCell>')

    @staticmethod
    def _edge(eid: str, src: str, dst: str, style: str) -> str:
        return (f'<mxCell id="{eid}" style="{style}" edge="1" parent="1" '
                f'source="{src}" target="{dst}">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>')

    def _write(self, tmp: Path, name: str, body: str) -> Path:
        p = tmp / name
        p.write_text(self._drawio(body), encoding="utf-8")
        return p

    def test_rev1_long_end_label_not_flagged_far_label_still_flagged(self):
        C = self._check_diagram()
        spec = {"name": "long-label", "meta": self.META,
                "nodes": [
                    {"id": "order", "shape": "entity", "title": "Order",
                     "rows": ["+ id: int"], "col": 0, "row": 0},
                    {"id": "line", "shape": "entity", "title": "OrderLine",
                     "rows": ["+ qty: int"], "col": 0, "row": 2}],
                "edges": [{"id": "rel", "src": "order", "dst": "line",
                           "kind": "uml_assoc", "src_label": "1",
                           "dst_label": "orderLineItems collection 0..*"}]}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "long-label")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = tmp / "long-label.spec.out.drawio"
            self.assertEqual(C.check_end_labels(out), [],
                             "幅 210px 級の長ラベルが端点距離で偽陽性(REV-1)")
            # 対照: オフセットを離せば依然として検出する(検出力の維持)
            xml = out.read_text(encoding="utf-8")
            m = re.search(r'(<mxPoint x=")(-?[\d.]+)(" y=")(-?[\d.]+)'
                          r'(" as="offset"\s*/>)', xml)
            self.assertIsNotNone(m, "端ラベルの offset mxPoint が無い")
            far = xml.replace(m.group(0), f'{m.group(1)}{float(m.group(2)) + 200:g}'
                              f'{m.group(3)}{m.group(4)}{m.group(5)}', 1)
            far_path = tmp / "far.drawio"
            far_path.write_text(far, encoding="utf-8")
            self.assertTrue(any("離れている" in v["detail"]
                                for v in C.check_end_labels(far_path)))

    def test_rev2_decision_self_loop_exempt_offvertex_still_flagged(self):
        C = self._check_diagram()
        spec = {"name": "dec-selfloop", "meta": self.META,
                "nodes": [
                    {"id": "start", "shape": "terminator", "label": "Start",
                     "col": 0, "row": 0},
                    {"id": "chk", "shape": "decision", "label": "OK?",
                     "col": 0, "row": 1},
                    {"id": "end", "shape": "terminator", "label": "End",
                     "col": 0, "row": 2}],
                "edges": [
                    {"id": "e1", "src": "start", "dst": "chk", "kind": "main"},
                    {"id": "e2", "src": "chk", "dst": "end", "kind": "main",
                     "label": "yes"},
                    {"id": "e3", "src": "chk", "dst": "chk", "kind": "sub",
                     "label": "retry"}]}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            r = build_spec(spec, tmp, "dec-selfloop")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = tmp / "dec-selfloop.spec.out.drawio"
            self.assertEqual(C.check_diamond_vertices(out), [],
                             "decision 自己ループ(retry)が4頂点則で偽陽性(REV-2)")
            # 対照: 非自己ループ(e2 = chk→end)の頂点外れは依然として検出する
            xml = out.read_text(encoding="utf-8")
            i = xml.index('id="e2"')
            self.assertIn("exitY=1;", xml[i:])
            bad = tmp / "offvertex.drawio"
            bad.write_text(
                xml[:i] + xml[i:].replace("exitY=1;", "exitY=0.72;", 1),
                encoding="utf-8")
            self.assertTrue(C.check_diamond_vertices(bad))

    def test_rev11_frac_pair_none_and_invalid_are_skipped(self):
        import types
        C = self._check_diagram()
        edge = types.SimpleNamespace(style={"exitX": "abc", "exitY": "0.5"})
        self.assertIsNone(C._frac_pair(edge, "exit"))  # 不正値でも例外落ちしない
        self.assertIsNone(C._frac_pair(
            types.SimpleNamespace(style={}), "exit"))
        # 端点未指定の decision エッジは E6 の領分として skip(二重報告しない)
        with tempfile.TemporaryDirectory() as td:
            path = self._write(Path(td), "noexit.drawio",
                self._node("d", 100, 100, style="rhombus;whiteSpace=wrap;")
                + self._node("p", 100, 300)
                + self._edge("e", "d", "p", "edgeStyle=orthogonalEdgeStyle;"))
            self.assertEqual(C.check_diamond_vertices(path), [])

    def test_a3_exit_direction_return_edge_exemption_boundary(self):
        C = self._check_diagram()
        style = "edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0.5;entryY=1;"
        nodes = self._node("a", 600, 600) + self._node("b", 100, 100)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # 破線+dst が上流(行が上)= 戻りエッジ → 免除(01-approval f10)
            ret = self._write(tmp, "return.drawio",
                              nodes + self._edge("e", "a", "b", style + "dashed=1;"))
            self.assertEqual(C.check_exit_direction(ret), [])
            # 実線の同型(complex e10 と同じ非破線・上向き)→ 検出維持
            solid = self._write(tmp, "solid.drawio",
                                nodes + self._edge("e", "a", "b", style))
            self.assertEqual([v["edge"] for v in C.check_exit_direction(solid)],
                             ["e"])
            # 破線でも dst が下流(complex e23 と同じ向き)→ 検出維持
            down = self._write(
                tmp, "down.drawio",
                self._node("a", 100, 100) + self._node("b", 600, 600)
                + self._edge("e", "a", "b",
                             "edgeStyle=orthogonalEdgeStyle;dashed=1;"
                             "exitX=0;exitY=0.5;entryX=0.5;entryY=0;"))
            self.assertEqual([v["edge"] for v in C.check_exit_direction(down)],
                             ["e"])

    def test_a3_exit_direction_er_hub_exemption_boundary(self):
        C = self._check_diagram()
        er = "edgeStyle=orthogonalEdgeStyle;startArrow=ERone;endArrow=ERmany;"
        bad = er + "exitX=0;exitY=0.5;entryX=0.5;entryY=1;"  # 左辺から右下宛
        nodes = (self._node("hub", 100, 100) + self._node("t1", 600, 700)
                 + self._node("t2", 300, 400) + self._node("t3", 300, 700))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            hub3 = self._write(tmp, "hub3.drawio", nodes
                               + self._edge("r1", "hub", "t1", bad)
                               + self._edge("r2", "hub", "t2", er)
                               + self._edge("r3", "hub", "t3", er))
            self.assertEqual(C.check_exit_direction(hub3), [],
                             "ER ハブ(次数3)の回廊迂回が偽陽性(A3-#2)")
            # 次数 2 では免除しない(境界の下側。exit/entry の両端が掛かる)
            hub2 = self._write(tmp, "hub2.drawio", nodes
                               + self._edge("r1", "hub", "t1", bad)
                               + self._edge("r2", "hub", "t2", er))
            self.assertEqual({v["edge"] for v in C.check_exit_direction(hub2)},
                             {"r1"})

    def test_rev8_mixed_gateway_topology_flagged(self):
        C = self._check_diagram()
        gw = ("shape=mxgraph.bpmn.gateway2;gwType=parallel;")
        plain = "edgeStyle=orthogonalEdgeStyle;"
        nodes = (self._node("g", 300, 300, 64, 64, gw)
                 + self._node("a", 100, 100) + self._node("b", 500, 100)
                 + self._node("c", 100, 500) + self._node("d", 500, 500))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mixed = self._write(tmp, "mixed.drawio", nodes
                                + self._edge("e1", "a", "g", plain)
                                + self._edge("e2", "b", "g", plain)
                                + self._edge("e3", "g", "c", plain)
                                + self._edge("e4", "g", "d", plain))
            self.assertTrue(C.check_gateway_topology(mixed),
                            "入出とも複数の混合 gateway が素通り(REV-8)")
            fork = self._write(tmp, "fork.drawio", nodes
                               + self._edge("e1", "a", "g", plain)
                               + self._edge("e3", "g", "c", plain)
                               + self._edge("e4", "g", "d", plain))
            self.assertEqual(C.check_gateway_topology(fork), [])

    def test_rev9_rev5_object_wrapped_cells_visible(self):
        C = self._check_diagram()
        obj = ('<object id="map" label="Detail" link="x.drawio">'
               '<mxCell style="shape=process;whiteSpace=wrap;" vertex="1" '
               'parent="1"><mxGeometry x="300" y="100" width="120" height="44" '
               'as="geometry"/></mxCell></object>')
        with tempfile.TemporaryDirectory() as td:
            path = self._write(Path(td), "obj.drawio",
                               self._node("a", 100, 100) + obj)
            # REV-5: <object> 包みセルが validator の走査に現れる
            import validate_drawio as V
            for _tab, model in V.load_models(str(path)):
                diag = V.Diagram(model)
                self.assertIn("map", diag.cells)
                self.assertEqual(diag.cells["map"].link, "x.drawio")
            # REV-9: 危険 id は object/UserObject 包みでも検出する
            self.assertEqual([v["id"] for v in C.check_safe_cell_ids(path)],
                             ["map"])

    def test_rev10_custom_er_pair_not_flagged_missing_marker_flagged(self):
        C = self._check_diagram()
        base = "edgeStyle=orthogonalEdgeStyle;startArrow=ERzeroToOne;endArrow="
        nodes = self._node("p", 100, 100) + self._node("c", 400, 100)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            custom = self._write(tmp, "custom.drawio", nodes
                                 + self._edge("r", "p", "c", base + "ERone;"))
            self.assertEqual(C.check_er_cardinality(custom), [],
                             "カスタム kind の 0..1:1 が偽陽性(REV-10)")
            missing = self._write(tmp, "missing.drawio", nodes
                                  + self._edge("r", "p", "c", base + "open;"))
            self.assertTrue(C.check_er_cardinality(missing))

    def test_rev4_overlength_end_label_still_avoids_obstacles(self):
        lay = B.Layout(C=1, R=1)
        label = "orderLineItems collection 0..*"
        lw, lh = B.text_size(label, 11)
        poly = [(200.0, 300.0), (200.0, 330.0), (400.0, 330.0)]  # 30px の縦端
        # 素朴位置(旧実装のフォールバック: d=18 右側)を覆う障害物を置く
        naive_x = 200.0 + lw / 2 + 5.0
        naive_y = 300.0 + 18.0 + lh / 2
        lay.obstacles.append((naive_x - 40.0, naive_y - 12.0, 80.0, 24.0))
        at = B.pick_end_label_at(lay, label, poly, at_end=False)
        box = (at[0] - lw / 2, at[1] - lh / 2, lw, lh)
        self.assertFalse(
            B._rect_hits(box, lay.obstacles[0]),
            f"セグメント長超ラベルが障害物回避をバイパス(REV-4): {at}")

    def test_rev7_gateway_label_warns(self):
        spec = {"name": "gw-label", "meta": self.META,
                "nodes": [
                    {"id": "a", "shape": "process", "label": "Step A",
                     "col": 0, "row": 0},
                    {"id": "gw", "shape": "gateway", "label": "並行開始",
                     "col": 0, "row": 1},
                    {"id": "b", "shape": "process", "label": "Step B",
                     "col": 0, "row": 2},
                    {"id": "c", "shape": "process", "label": "Step C",
                     "col": 1, "row": 2}],
                "edges": [
                    {"id": "e1", "src": "a", "dst": "gw", "kind": "main"},
                    {"id": "e2", "src": "gw", "dst": "b", "kind": "main"},
                    {"id": "e3", "src": "gw", "dst": "c", "kind": "main"}]}
        with tempfile.TemporaryDirectory() as td:
            r = build_spec(spec, Path(td), "gw-label")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("gateway のラベル", r.stdout)
            spec["nodes"][1].pop("label")
            r2 = build_spec(spec, Path(td), "gw-nolabel")
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertNotIn("gateway のラベル", r2.stdout)


if __name__ == "__main__":
    unittest.main()

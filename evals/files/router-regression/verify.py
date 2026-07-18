#!/usr/bin/env python3
"""e17/e18 ルータ回帰の fail-before/pass-after 検証スクリプト。

固定スペック(このディレクトリの12本+templates/example-complex)をエンジンで
ビルドし、evals/check_diagram.py のルータ検査17個(接続アンカー / ファンアウト
対称 / レーン分離 = FB第3R、出射辺の方向 / 垂直ペア中心 / 兄弟コンテナ寸法 =
FB第4R、ファン辺の流儀統一 / 折れ点上限 / 同一辺ポート分離 / fork 形状 =
FB第5R、decision 頂点 / safe id / 両端ラベル / ER端別 / stereotype /
flow shape+link / gateway topology = 第7R)を走らせる。fail-before は世代
(--era)ごとに「狙いのチェック」が決まる:

  r3(旧 = v1.5.0、R3 修正前)
    multi-az-ecs.spec.json  → corun_separation(実測: 2.4px 間隔で 129px 並走)
    pairs-anchor.spec.json  → anchor_fractions(実測: frac 0.9215)
    fan-symmetry.spec.json  → fan_symmetry(実測: レーン x=223/209 に分裂)
  r4(旧 = v1.6.0、R4 修正前)
    example-complex.spec.json → exit_direction(実測: 余弦 -0.698 / -0.513)
    pairs-anchor.spec.json    → pair_center(実測: frac 0.6484)
    multi-az-ecs.spec.json    → sibling_dims(実測: サブネット高 154 / 318)
  r5(旧 = v1.7.0、外部パッチ A / R5-B/C 実装前)
    fan-mixed.spec.json    → fan_side_consistency(実測: 対の exit 右辺/下辺・
                             entry v/h 流儀の混在)
    pin-ladder.spec.json   → pin_slot_distance(実測: pin frac 0.4 の 7.8px 隣
                             = W6 へ自動割当)
    center-fork.spec.json  → fork_absent(旧エンジンには fork 機能自体が無く、
                             対称スロット 0.35/0.65 +対面辺入射の署名にならない
                             — 実測: exit [0.5,0]/[1,0.5] の不揃い 2 レーン)
    sublane-step.spec.json → two_step_ends(実測: s4 の src 側に 32px→36.3px の
                             終端二段ステップ)
  r7(旧 = 第7R 開始前、A/A2/B/C 実装前)
    r7-decision.spec.json       → diamond_vertices
    r7-id-labels-uml.spec.json  → safe_cell_ids / end_labels / stereotype_italic
    r7-er-cardinality.spec.json → er_cardinality(旧は未知 kind として build reject)
    r7-flow-shapes.spec.json    → flow_shapes_links / gateway_topology /
                                  diamond_vertices(旧は未知 shape として build reject)
    r7-subprocess-link.spec.json → flow_shapes_links

build reject の 2 spec は旧エンジンで検査関数が一度も実行されない(機能未実装の
証拠にはなるが検査の判別力は証明しない)ため、broken/ の破損フィクスチャ
(現行ビルドの正しい出力を人工的に壊した固定 .drawio)へ現行 check_diagram を
通し、各検査が違反を実際に出すことを pass-after 実行時に毎回実証する(REV-3):
    broken-er-cardinality.drawio  → er_cardinality(er_11n の子側 ERmany を open に)
    broken-flow-shapes.drawio     → flow_shapes_links(gwType を exclusive に)/
                                    gateway_topology(fork の出射 1 本を削除 = 1→1)/
                                    diamond_vertices(exit を頂点外 0.72 に)
    broken-subprocess-link.drawio → flow_shapes_links(link 属性を除去)

era=sem(SEM-4)はルータ幾何でなく**アーキテクチャ正しさ(W16〜W21)**の回帰:
`evals/files/sem-regression/` の誤りスペック7本(w16〜w21 の最小形+
multiregion-prefix = 出荷済みテンプレ example-multiregion の SEM-3 修正前形 =
DR フェイルオーバー非対称の実誤り)を旧エンジン(v1.9.0 = W16-21 実装前)が
**素通り**(ビルド成功・W コードなし・旧 validate も 0 件)させ、**同じ産物**で
現行 validate が狙いのコードを検出することを実証する。pass-after(引数なし)では
現行エンジンが誤り7本を発火(W17/W18/W19 = ビルド拒否、W16/W20/W21 = WARN +
validate 発火)し、正解6本(ok/)を 0 件で通し、凍結産物(broken/*.drawio =
旧 v1.9.0 エンジンで誤りスペックをビルドした固定 .drawio)で validate 段の
判別力を毎回実証する。

使い方:
  # 現行エンジン(pass-after): 全スペックで17チェック 0 違反+fork 発動+
  # W16〜W21 の誤り=発火・正解=非発火を確認
  python3 evals/files/router-regression/verify.py

  # 旧エンジン(fail-before): 世代の狙いのチェックが ≥1 違反することを確認
  python3 evals/files/router-regression/verify.py \
      --engine <旧 build_drawio.py へのパス> --expect-fail [--era r3|r4|r5|r7|sem]

  # W16〜W21 の誤検知ゼロ確認(テンプレ+リファレンス5+構成図/フロー図)
  python3 evals/files/router-regression/verify.py --sweep-sem

--era の既定は r4。旧エンジンのスナップショットはスキル外(例: scratchpad の
バックアップ)に置いたものを --engine で指すこと(era=sem は旧 build_drawio.py と
同ディレクトリに旧 validate_drawio.py があれば validate 側の素通りも確認する)。
スペックは一時ディレクトリへコピーしてビルドするため、committed ファイルには
書き戻されない。R5-D(経路の慣性)は <out>.routes.json キャッシュがあるときだけ
働く機能で、ここでは常にキャッシュなしの新規ビルドを行うため対象外。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVALS = HERE.parent.parent
sys.path.insert(0, str(EVALS))
import check_diagram as C  # noqa: E402

SPECS = {
    "multi-az-ecs.spec.json": HERE,
    "pairs-anchor.spec.json": HERE,
    "fan-symmetry.spec.json": HERE,
    "fan-mixed.spec.json": HERE,
    "pin-ladder.spec.json": HERE,
    "center-fork.spec.json": HERE,
    "sublane-step.spec.json": HERE,
    "r7-decision.spec.json": HERE,
    "r7-id-labels-uml.spec.json": HERE,
    "r7-er-cardinality.spec.json": HERE,
    "r7-flow-shapes.spec.json": HERE,
    "r7-subprocess-link.spec.json": HERE,
    "example-complex.spec.json": EVALS.parent / "templates",
}
CHECKS = {
    "anchor_fractions": C.check_anchor_fractions,
    "fan_symmetry": C.check_fan_symmetry,
    "corun_separation": C.check_corun_separation,
    "exit_direction": C.check_exit_direction,
    "pair_center": C.check_pair_center,
    "sibling_dims": C.check_sibling_dims,
    "fan_side_consistency": C.check_fan_side_consistency,
    "max_bends": C.check_max_bends,
    "pin_slot_distance": C.check_pin_slot_distance,
    "fork_shape": C.check_fork_shape,
    "diamond_vertices": C.check_diamond_vertices,
    "safe_cell_ids": C.check_safe_cell_ids,
    "end_labels": C.check_end_labels,
    "er_cardinality": C.check_er_cardinality,
    "stereotype_italic": C.check_stereotype_italic,
    "flow_shapes_links": C.check_flow_shapes_links,
    "gateway_topology": C.check_gateway_topology,
}

SPEC_AWARE = {"diamond_vertices", "safe_cell_ids", "end_labels",
              "er_cardinality", "stereotype_italic", "flow_shapes_links",
              "gateway_topology"}

_STEP_MAX, _STEP_NEAR = 42.0, 36.0  # scripts の R5-C 検出と同じ実証値を凍結


def two_step_ends(path):
    """終端 3 区間が「直進→短い段差→終端直進」を成すエッジ(R5-C の検出形状)。

    scripts/build_drawio.py の _two_step_ends と同じ規約を eval 側に凍結した
    再実装(エンジン側の将来変更から fail-before の定義を独立させる)。
    """
    out = []
    for tab, _diag, edges, polys in C._tabs(path):
        for e in edges:
            poly = polys.get(e.id) or []
            segs = []
            diagonal = False
            for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
                dx, dy = abs(x1 - x2), abs(y1 - y2)
                if dx < 0.5 and dy < 0.5:
                    continue
                if dx >= 0.5 and dy >= 0.5:
                    diagonal = True
                    break
                segs.append(("h" if dx > dy else "v", dx + dy))
            if diagonal or len(segs) < 4:
                continue
            axes = [a for a, _ in segs]
            for at_dst in (True, False):
                (a1, l1), (a2, l2), (a3, l3) = segs[-3:] if at_dst else segs[:3]
                term = l3 if at_dst else l1
                rest = axes[:-3] if at_dst else axes[3:]
                if (a1 == a3 and a2 != a1 and l2 <= _STEP_MAX
                        and term <= _STEP_NEAR and a2 in rest):
                    out.append({"tab": tab, "edge": e.id,
                                "end": "dst" if at_dst else "src"})
    return out


def fork_absent(path):
    """fork 署名(R5-B)が無ければその旨を返す(fail-before 専用の擬似チェック)。"""
    if C.detect_forks(path):
        return []
    return [{"detail": "fork 署名なし(対称スロット 0.35/0.65 +対面辺入射に"
                       "ならない = 機能未実装)"}]


# fail-before 専用(pass-after の 0 違反スイープには入れない)
SPECIAL = {"fork_absent": fork_absent, "two_step_ends": two_step_ends}

TARGETS = {
    "r3": {
        "multi-az-ecs.spec.json": "corun_separation",
        "pairs-anchor.spec.json": "anchor_fractions",
        "fan-symmetry.spec.json": "fan_symmetry",
    },
    "r4": {
        "example-complex.spec.json": "exit_direction",
        "pairs-anchor.spec.json": "pair_center",
        "multi-az-ecs.spec.json": "sibling_dims",
    },
    "r5": {
        "fan-mixed.spec.json": "fan_side_consistency",
        "pin-ladder.spec.json": "pin_slot_distance",
        "center-fork.spec.json": "fork_absent",
        "sublane-step.spec.json": "two_step_ends",
    },
    "r7": {
        "r7-decision.spec.json": "diamond_vertices",
        "r7-id-labels-uml.spec.json":
            ("safe_cell_ids", "end_labels", "stereotype_italic"),
        "r7-er-cardinality.spec.json": "er_cardinality",
        "r7-flow-shapes.spec.json":
            ("flow_shapes_links", "gateway_topology", "diamond_vertices"),
        "r7-subprocess-link.spec.json": "flow_shapes_links",
    },
}

# R7開始前のエンジンは新 kind/shape を黙って欠落させず入力境界で拒否する。
# この2本だけは、その明示拒否を「機能未実装」の fail-before 証拠として扱う
# (検査自体の判別力は BROKEN の破損フィクスチャが実証する)。
R7_BUILD_REJECT = {
    "r7-er-cardinality.spec.json": "kind 'er_01n' は未知です",
    "r7-flow-shapes.spec.json": "shape 'connector' は未知です",
}

# 検査の判別力(REV-3): 破損フィクスチャ → (狙いの検査, 対応 spec)。
# pass-after 実行(引数なし)で毎回、各検査が ≥1 違反を出すことを確認する。
BROKEN = {
    "broken-er-cardinality.drawio":
        (("er_cardinality",), "r7-er-cardinality.spec.json"),
    "broken-flow-shapes.drawio":
        (("flow_shapes_links", "gateway_topology", "diamond_vertices"),
         "r7-flow-shapes.spec.json"),
    "broken-subprocess-link.drawio":
        (("flow_shapes_links",), "r7-subprocess-link.spec.json"),
}

# pass-after 専用の追加確認: 現行エンジンではこのスペックで fork が発動し、
# 署名(対称スロット出射+対面辺入射)が実際に生成されること
AFTER_FORK_SPECS = ("center-fork.spec.json",)

# ---- era=sem(SEM-4): アーキテクチャ正しさ W16〜W21 の回帰 ----
SEM_DIR = EVALS / "files" / "sem-regression"
SEM_CODES = ("W16", "W17", "W18", "W19", "W20", "W21")
# 誤りスペック → (狙いのコード, 現行ビルド段の扱い)。
# multiregion-prefix は出荷済みテンプレ example-multiregion の SEM-3 修正前形
# (r53→albB 直行 = DR フェイルオーバー非対称)をそのまま凍結した最重要 fixture。
SEM_WRONG = {
    "multiregion-prefix.spec.json": ("W16", "warn"),
    "w16-dr-asymmetric.spec.json": ("W16", "warn"),
    "w17-global-in-region.spec.json": ("W17", "error"),
    "w18-db-public-subnet.spec.json": ("W18", "error"),
    "w19-external-db-direct.spec.json": ("W19", "error"),
    "w20-ha-single-az.spec.json": ("W20", "warn"),
    "w21-private-egress-direct.spec.json": ("W21", "warn"),
}
# 正解スペック(ok/): 同じ題材の正しい形。W16〜W21 が 1 件も出ないこと
SEM_OK = ("w16-ok.spec.json", "w17-ok.spec.json", "w18-ok.spec.json",
          "w19-ok.spec.json", "w20-ok.spec.json", "w21-ok.spec.json")
# 誤検知ゼロの固定対象(--sweep-sem): 存在しないディレクトリは SKIP 表示
SWEEP_DIRS = (
    ("templates", EVALS.parent / "templates"),
    ("構成図", Path("/Users/user/Documents/Github/構成図")),
    ("フロー図", Path("/Users/user/Documents/Github/フロー図")),
)
REFARCH = EVALS.parent / "references" / "reference-architectures"


def build(engine, spec_name, td, spec_dir=None):
    """spec を一時ディレクトリへコピーしてビルド(spec への書き戻しを隔離)。"""
    spec = Path(td) / spec_name
    shutil.copy((spec_dir or SPECS[spec_name]) / spec_name, spec)
    out = Path(td) / spec_name.replace(".spec.json", ".drawio")
    cp = subprocess.run(
        [sys.executable, str(engine), str(spec), "-o", str(out)],
        capture_output=True, text=True)
    return out if out.exists() else None, cp


def sem_codes(path):
    """現行 validate_drawio が出す W16〜W21 のコード集合。"""
    result = C.validate_json(path)
    return {f["code"] for f in result["findings"] if f["code"] in SEM_CODES}


def _sem_log_codes(log):
    """ビルドログに現れた W16〜W21 のコード集合。"""
    return {c for c in SEM_CODES if f"{c}:" in log}


def sem_pass_after(engine, td):
    """現行エンジン: 誤り=発火(build 段+validate 段)・正解=非発火を実証。"""
    ok = True
    for spec_name, (code, klass) in SEM_WRONG.items():
        out, cp = build(engine, spec_name, td, spec_dir=SEM_DIR)
        log = cp.stdout + cp.stderr
        if klass == "error":
            good = out is None and code in _sem_log_codes(log)
            print(("OK" if good else "NG"),
                  f"sem/{spec_name}: 現行ビルドが {code} で拒否"
                  f"(build={'拒否' if out is None else '成功'}, "
                  f"log codes={sorted(_sem_log_codes(log))})")
        else:
            fired_build = out is not None and code in _sem_log_codes(log)
            fired_val = out is not None and code in sem_codes(out)
            good = fired_build and fired_val
            print(("OK" if good else "NG"),
                  f"sem/{spec_name}: 現行が {code} を検出"
                  f"(build WARN={fired_build}, validate={fired_val})")
        ok = ok and good
    # validate 段の判別力: 凍結産物(broken/ = 旧 v1.9.0 エンジンでビルドした
    # 誤り .drawio)へ現行 validate — W17/18/19 は現行ビルドが拒否して産物を
    # 作れないため、validate 段はこの凍結産物だけが実証できる(REV-3 と同型)
    for spec_name, (code, _klass) in SEM_WRONG.items():
        fixture = SEM_DIR / "broken" / spec_name.replace(".spec.json", ".drawio")
        codes = sem_codes(fixture)
        good = code in codes
        print(("OK" if good else "NG"),
              f"sem/broken/{fixture.name}: validate が {code} を検出"
              f"(検査の判別力, codes={sorted(codes)})")
        ok = ok and good
    for spec_name in SEM_OK:
        out, cp = build(engine, spec_name, td, spec_dir=SEM_DIR / "ok")
        log = cp.stdout + cp.stderr
        build_codes = _sem_log_codes(log)
        val_codes = sem_codes(out) if out is not None else None
        good = out is not None and not build_codes and not val_codes
        print(("OK" if good else "NG"),
              f"sem/ok/{spec_name}: W16〜W21 非発火"
              f"(build={sorted(build_codes)}, validate="
              f"{sorted(val_codes) if val_codes is not None else 'ビルド失敗'})")
        ok = ok and good
    return ok


def sem_fail_before(engine, td):
    """era=sem: 旧エンジン(v1.9.0 = SEM-3 前)が誤りスペックを素通りさせ、
    同じ産物で現行 validate が発火することを実証する。"""
    ok = True
    old_validator = Path(engine).parent / "validate_drawio.py"
    for spec_name, (code, _klass) in SEM_WRONG.items():
        out, cp = build(engine, spec_name, td, spec_dir=SEM_DIR)
        log = cp.stdout + cp.stderr
        if out is None:
            print(f"NG sem/{spec_name}: 旧エンジンでビルド失敗"
                  f"(素通りの前提が崩れた)\n{log}")
            ok = False
            continue
        silent = not _sem_log_codes(log)
        cur = sem_codes(out)
        fired = code in cur
        print(("OK" if silent else "NG"),
              f"sem/{spec_name}: 旧ビルドが W16〜W21 を出さず素通り"
              f"(fail-before, era=sem, log codes={sorted(_sem_log_codes(log))})")
        print(("OK" if fired else "NG"),
              f"sem/{spec_name}: 同じ産物で現行 validate が {code} を検出"
              f"(codes={sorted(cur)})")
        good = silent and fired
        if old_validator.exists():
            cpv = subprocess.run(
                [sys.executable, str(old_validator), str(out), "--json"],
                capture_output=True, text=True)
            try:
                data = json.loads(cpv.stdout)
                old = {f["code"] for f in data["findings"]
                       if f["code"] in SEM_CODES}
            except (json.JSONDecodeError, KeyError):
                old = None
            v_ok = old == set()
            print(("OK" if v_ok else "NG"),
                  f"sem/{spec_name}: 旧 validate も素通り"
                  f"(codes={sorted(old) if old else old})")
            good = good and v_ok
        ok = ok and good
    return ok


def sem_sweep(engine, td):
    """W16〜W21 の誤検知ゼロ固定: テンプレ・実案件図は validate 直、
    リファレンススペック5本は現行ビルド+validate で確認する。"""
    ok = True
    total = 0
    for label, d in SWEEP_DIRS:
        if not d.is_dir():
            print(f"SKIP {label}: {d} なし(この環境には無い)")
            continue
        for p in sorted(d.glob("*.drawio")):
            codes = sem_codes(p)
            total += 1
            print(("OK" if not codes else "NG"),
                  f"sweep {label}/{p.name}: W16〜W21 = {sorted(codes)}")
            ok = ok and not codes
    for p in sorted(REFARCH.glob("*.spec.json")):
        out, cp = build(engine, p.name, td, spec_dir=REFARCH)
        log = cp.stdout + cp.stderr
        codes = _sem_log_codes(log) | (sem_codes(out) if out is not None
                                       else {"ビルド失敗"})
        total += 1
        print(("OK" if not codes else "NG"),
              f"sweep reference-architectures/{p.name}: W16〜W21 = {sorted(codes)}")
        ok = ok and not codes
    print(f"sweep 対象 {total} ファイル")
    return ok


def targets_for(era, spec_name):
    target = TARGETS[era][spec_name]
    return (target,) if isinstance(target, str) else target


def run_check(name, out, spec_name):
    fn = CHECKS[name]
    spec_path = SPECS[spec_name] / spec_name
    return fn(out, spec_path) if name in SPEC_AWARE else fn(out)


def main(argv):
    engine = EVALS.parent / "scripts" / "build_drawio.py"
    expect_fail = "--expect-fail" in argv
    era = argv[argv.index("--era") + 1] if "--era" in argv else "r4"
    if era not in TARGETS and era != "sem":
        print(f"ERROR: --era は {sorted(TARGETS) + ['sem']} から指定してください")
        return 2
    if "--engine" in argv:
        engine = Path(argv[argv.index("--engine") + 1])
    ok = True
    with tempfile.TemporaryDirectory(prefix="router-regression-") as td:
        if "--sweep-sem" in argv:
            ok = sem_sweep(engine, td)
            print("=>", "PASS" if ok else "FAIL")
            return 0 if ok else 1
        if expect_fail and era == "sem":
            ok = sem_fail_before(engine, td)
            print("=>", "PASS" if ok else "FAIL")
            return 0 if ok else 1
        names = TARGETS[era] if expect_fail else SPECS
        for spec_name in names:
            out, cp = build(engine, spec_name, td)
            if out is None:
                build_log = cp.stdout + cp.stderr
                expected = R7_BUILD_REJECT.get(spec_name) if era == "r7" else None
                good = bool(expect_fail and expected and expected in build_log)
                if good:
                    for target in targets_for(era, spec_name):
                        print("OK", f"{spec_name}: {target} は機能未実装"
                              f"(fail-before, era={era}, 旧エンジンが build reject。"
                              "検査の判別力は broken/ フィクスチャで実証)")
                else:
                    print(f"NG {spec_name}: ビルド失敗\n{build_log}")
                ok = ok and good
                continue
            if expect_fail:
                good = True
                for target in targets_for(era, spec_name):
                    hit = (SPECIAL[target](out) if target in SPECIAL
                           else run_check(target, out, spec_name))
                    target_good = len(hit) >= 1
                    print(("OK" if target_good else "NG"),
                          f"{spec_name}: {target} が {len(hit)} 違反"
                          f"(fail-before, era={era})")
                    for v in hit:
                        print("   ", v)
                    good = good and target_good
            else:
                results = {k: run_check(k, out, spec_name) for k in CHECKS}
                bad = {k: v for k, v in results.items() if v}
                if spec_name in AFTER_FORK_SPECS and not C.detect_forks(out):
                    bad["fork_fired"] = [{"detail": "現行エンジンで fork 署名が"
                                                    "生成されていない"}]
                if two_step_ends(out):
                    bad["two_step_ends"] = two_step_ends(out)
                good = not bad
                print(("OK" if good else "NG"),
                      f"{spec_name}: {len(CHECKS)}チェック違反 "
                      f"{[len(results[k]) for k in CHECKS]}(pass-after)")
                for k, v in bad.items():
                    print(f"    {k}: {v}")
            ok = ok and good
        if not expect_fail:
            # 検査の判別力(REV-3): 破損フィクスチャで各検査が違反を出すこと
            for fixture, (targets, spec_name) in BROKEN.items():
                fixture_path = HERE / "broken" / fixture
                for target in targets:
                    hit = run_check(target, fixture_path, spec_name)
                    good = len(hit) >= 1
                    print(("OK" if good else "NG"),
                          f"broken/{fixture}: {target} が {len(hit)} 違反"
                          "(検査の判別力)")
                    ok = ok and good
            # era=sem(SEM-4): W16〜W21 誤り=発火・正解=非発火・凍結産物の判別力
            ok = sem_pass_after(engine, td) and ok
    print("=>", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

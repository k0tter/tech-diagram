#!/usr/bin/env python3
"""atheris(カバレッジ誘導)によるビルダーの堅牢性ファザー。

tools/fuzz_layout.py が「正当なスペックの生成ベース」なのに対し、こちらは
敵対的な入力(壊れた JSON・型違い・極端な値)を変異で作り、次の不変条件を検証する:

  構造検証(check_structure / validate_spec)を通過した入力に対して、
  ビルドは SpecError 以外の例外を出さず、well-formed な XML を返すこと。
  (SpecError = 設計どおりの拒否。それ以外の例外・ハング = 堅牢性バグ)

シードコーパスはリポジトリ同梱の実スペック(templates / reference-architectures)。
CI では時間制限付きスモークとして実行する(依存 atheris は CI 専用 —
スキル本体の stdlib-only は不変)。

使い方: python3 tools/fuzz_atheris.py <corpus_dir> [libFuzzer 引数...]
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
with atheris.instrument_imports():
    import build_drawio as bd

ICONS = bd.load_icons()

# 1 実行あたりの時間を抑えるための上限(経路探索は規模に非線形)
MAX_BYTES = 60_000
MAX_NODES = 60
MAX_EDGES = 90
MAX_TABS = 4


def test_one_input(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        return
    try:
        spec = json.loads(data)
    except Exception:
        return
    if not isinstance(spec, dict):
        return
    diagrams = spec["diagrams"] if "diagrams" in spec else [spec]
    if not isinstance(diagrams, list) or not diagrams:
        return
    bd.BUILD_WARNS.clear()
    try:
        # WARN/INFO の print はファジングでは雑音なので捨てる
        with contextlib.redirect_stdout(io.StringIO()):
            for i, d in enumerate(diagrams[:MAX_TABS]):
                if not isinstance(d, dict):
                    return
                bd.check_structure(d)
                if not bd.is_grid(d):
                    continue
                nodes = d.get("nodes") or []
                edges = d.get("edges") or []
                if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
                    continue
                absd = bd.grid_to_abs(d, ICONS)
                xml = bd.build_diagram(absd, ICONS, i)
                ET.fromstring(f"<mxfile>{xml}</mxfile>")
    except bd.SpecError:
        return  # 設計どおりの拒否


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()

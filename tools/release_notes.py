#!/usr/bin/env python3
"""リリースノート生成: 前タグ→対象タグのコミットを種別ごとに分類して
Markdown を標準出力へ出す(Release ワークフローが使用)。

使い方: python3 tools/release_notes.py <タグ>   例: v1.0.0
前タグが無ければ最初のコミットから対象タグまでを範囲とする。
"""

from __future__ import annotations

import subprocess
import sys

TITLES = [("feat", "## 機能"), ("fix", "## 修正"), ("perf", "## 性能"),
          ("docs", "## ドキュメント"), ("ci", "## CI"),
          ("other", "## その他")]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    tag = sys.argv[1]
    prev = git("describe", "--tags", "--abbrev=0", f"{tag}^")
    rng = f"{prev}..{tag}" if prev else tag
    subjects = git("log", "--no-merges", "--pretty=%s", rng).splitlines()
    groups: dict[str, list[str]] = {k: [] for k, _ in TITLES}
    for ln in subjects:
        ln = ln.strip()
        if not ln:
            continue
        key = ln.split(":", 1)[0].strip()
        if key in groups and ":" in ln:
            groups[key].append(ln.split(":", 1)[1].strip())
        else:
            groups["other"].append(ln)
    if prev:
        print(f"{prev} からの変更点。\n")
    for k, title in TITLES:
        if groups[k]:
            print(title)
            for item in groups[k]:
                print(f"- {item}")
            print()
    print("---")
    print("インストール: zip をお使いのエージェントのスキル探索"
          "ディレクトリに `tech-diagram` の名前で展開(配置場所は自由 — "
          "スキル内部にパスのハードコードなし)。詳細は README。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

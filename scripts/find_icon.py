#!/usr/bin/env python3
"""アイコン検索(AWS / Azure / GCP)。nodes.icon に書く name を 1 行 1 件で出力する。

使い方:
  python3 find_icon.py <キーワード> [キーワード...]   # 例: find_icon.py kafka
  python3 find_icon.py --provider azure <キーワード>  # プロバイダで絞る
  python3 find_icon.py --exact <name>                 # name の完全一致
  python3 find_icon.py --style <name>                 # スタイル文字列を出力

AWS はそのまま、Azure/GCP は "azure:virtual_machine" のようにプレフィックス付きの
name をスペックに書く。スタイル・色・サイズはジェネレータが自動解決。
TSV(計 1,600 種超)を直接 Read で全読みしないこと。
"""
from __future__ import annotations

import sys

from _common import icon_style, load_icons

MAX_HITS = 15


def search(icons: dict, terms: list[str], exact: bool,
           provider: str | None = None) -> list[dict]:
    hits = []
    for name, rows in icons.items():
        if provider:
            want = provider != "aws"
            if (":" in name) != want or (want and not name.startswith(provider + ":")):
                continue
        for row in rows:
            row = dict(row, _name=name)
            # 空白区切りの複合語("iot core")でも当たるよう正規化名も含める
            key = f"{name} {name.replace('_', ' ')} {row['label']}".lower()
            if exact:
                if name.lower() in terms:
                    hits.append(row)
            elif all(t in key for t in terms):
                hits.append(row)
    # service を優先、名前の短い順(素の名前が先に来る)
    hits.sort(key=lambda r: (r["kind"] != "service", len(r["name"])))
    return hits


def fuzzy_names(icons: dict, terms: list[str],
                provider: str | None = None) -> list[str]:
    import difflib
    names = list(icons)
    if provider:  # search() と同じ絞り込み(他社の候補を提示しない)
        want = provider != "aws"
        names = [n for n in names
                 if (":" in n) == want
                 and (not want or n.startswith(provider + ":"))]
    return difflib.get_close_matches("_".join(terms), names, n=8, cutoff=0.5)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    exact = style = False
    provider = None
    terms: list[str] = []
    expect_provider = False
    for a in argv:
        if expect_provider:
            provider = a.lower()
            expect_provider = False
            continue
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        if a == "--exact":
            exact = True
        elif a == "--style":
            style = True
        elif a == "--provider":
            expect_provider = True
        elif a.startswith("-"):
            print(f"ERROR: 不明なオプション: {a}(--help で使い方)", file=sys.stderr)
            return 2
        else:
            terms.append(a.lower())
    if not terms:
        print(__doc__)
        return 2
    if provider is not None and provider not in ("aws", "azure", "gcp"):
        print(f"ERROR: --provider は aws / azure / gcp のいずれかです({provider})",
              file=sys.stderr)
        return 2

    icons = load_icons()
    hits = search(icons, terms, exact, provider)
    if not hits:
        cands = fuzzy_names(icons, terms, provider)
        print(f"該当なし: {' '.join(terms)}")
        if cands:
            print(f"近い名前: {', '.join(cands)}")
        else:
            print("別の英語キーワードで再検索してください")
        if provider == "gcp":
            print("GCP は製品アイコンが少数(19 種)。無い製品はカテゴリアイコン"
                  "(gcp:dataanalytics / gcp:networking / gcp:integrationservices 等)"
                  "+正式名ラベルで表す(references/azure-gcp.md 参照)")
        return 1

    for r in hits[:MAX_HITS]:
        size = f"{r['w']}x{r['h']}"
        disp = r.get("_name", r["name"])
        print(f"{disp:<44} [{r['kind']:<8} {size:>7}] {r['label']} ({r['category']})")
        if style:
            print(f"  {icon_style(r)}")
    if len(hits) > MAX_HITS:
        print(f"... 他 {len(hits) - MAX_HITS} 件。キーワードを絞ってください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

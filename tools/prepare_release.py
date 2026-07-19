#!/usr/bin/env python3
"""最小配布ディレクトリを作り、Markdown の相対リンク切れを拒否する。

使い方:
  python3 tools/prepare_release.py --ref v1.2.0 --output dist/tech-diagram

標準ライブラリのみ。出力先は存在しないディレクトリに限る。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
FILES = ("SKILL.md", "README.md", "README.ja.md", "README.id.md",
         "LICENSE", "NOTICE")
DIRS = ("references", "scripts", "templates")
# `](` から読むことで `[![alt](image)](image)` の内側と外側を両方扱う。
MARKDOWN_LINK = re.compile(r"(\]\()([^\s)]+)([^)]*\))")
REMOTE_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_REF = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


class PackageError(ValueError):
    """配布物を安全に作れない、またはリンクが壊れている。"""


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _copy_file(src: Path, dst: Path) -> None:
    if src.is_symlink():
        raise PackageError(f"symlink は配布物へ入れません: {src}")
    if not src.is_file():
        raise PackageError(f"通常ファイルではありません: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    if src.is_symlink():
        raise PackageError(f"symlink は配布物へ入れません: {src}")
    if not src.is_dir():
        raise PackageError(f"必須ディレクトリではありません: {src}")
    source_root = src.resolve()
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            raise PackageError(f"symlink は配布物へ入れません: {path}")
        if not _inside(path, source_root):
            raise PackageError(f"配布元ディレクトリ外を参照しています: {path}")
        rel = path.relative_to(src)
        if any(part == "__pycache__" for part in rel.parts):
            continue
        if path.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        elif path.is_file() and not (
                src.name == "scripts" and rel.as_posix() == "tests.py"):
            _copy_file(path, dst / rel)
        elif not path.is_file():
            raise PackageError(f"通常ファイルではありません: {path}")


def _relative_target(markdown: Path, raw_url: str, root: Path) -> Path | None:
    parts = urlsplit(raw_url)
    if parts.scheme or parts.netloc or raw_url.startswith(("#", "mailto:")):
        return None
    if raw_url.startswith("/"):
        raise PackageError(f"絶対ファイルリンクは禁止: {markdown}: {raw_url}")
    target = (markdown.parent / unquote(parts.path)).resolve()
    if not _inside(target, root):
        raise PackageError(f"リンクが配布ルート外を指しています: {markdown}: {raw_url}")
    return target


def rewrite_readme_links(readme: Path, package: Path, source: Path,
                         ref: str, repo: str) -> None:
    """同梱しない公開資産へのリンクをタグ固定 URL に変換する。"""
    text = readme.read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        raw = match.group(2)
        package_target = _relative_target(readme, raw, package)
        if package_target is None or package_target.exists():
            return match.group(0)
        parts = urlsplit(raw)
        source_target = (source / unquote(parts.path)).resolve()
        if not _inside(source_target, source) or not source_target.exists():
            raise PackageError(f"公開元にも存在しないリンクです: {readme.name}: {raw}")
        rel = source_target.relative_to(source.resolve()).as_posix()
        encoded_ref, encoded_path = quote(ref, safe=""), quote(rel, safe="/")
        if source_target.suffix.lower() in IMAGE_SUFFIXES:
            url = f"https://raw.githubusercontent.com/{repo}/{encoded_ref}/{encoded_path}"
        else:
            kind = "tree" if source_target.is_dir() else "blob"
            url = f"https://github.com/{repo}/{kind}/{encoded_ref}/{encoded_path}"
        if parts.fragment:
            url += "#" + parts.fragment
        return match.group(1) + url + match.group(3)

    readme.write_text(MARKDOWN_LINK.sub(replace, text), encoding="utf-8")


def check_markdown_links(package: Path) -> list[str]:
    """配布物内の Markdown 相対リンクについて欠損を返す。"""
    missing = []
    for markdown in sorted(package.rglob("*.md")):
        text = markdown.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            raw = match.group(2)
            try:
                target = _relative_target(markdown, raw, package)
            except PackageError as exc:
                missing.append(str(exc))
                continue
            if target is not None and not target.exists():
                missing.append(
                    f"{markdown.relative_to(package)}: {raw} -> 欠損")
    return missing


def prepare(source: Path, output: Path, ref: str, repo: str) -> None:
    source, output = source.resolve(), output.resolve()
    if not RELEASE_REF.fullmatch(ref):
        raise PackageError(f"--ref は SemVer タグ(vX.Y.Z)で指定してください: {ref}")
    if not REMOTE_REPO.fullmatch(repo):
        raise PackageError(f"--repo は owner/name で指定してください: {repo}")
    if output.exists():
        raise PackageError(f"出力先が既に存在します: {output}")
    if output == source or _inside(source, output):
        raise PackageError("出力先にソース自身またはその親は指定できません")
    output.mkdir(parents=True)
    for name in FILES:
        _copy_file(source / name, output / name)
    for name in DIRS:
        _copy_tree(source / name, output / name)
    for name in ("README.md", "README.ja.md", "README.id.md"):
        rewrite_readme_links(output / name, output, source, ref, repo)
    missing = check_markdown_links(output)
    if missing:
        raise PackageError("配布物の Markdown リンクが壊れています:\n- "
                           + "\n- ".join(missing))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--repo", default="k0tter/tech-diagram")
    args = parser.parse_args(argv)
    try:
        prepare(args.source, args.output, args.ref, args.repo)
    except (OSError, PackageError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    count = sum(1 for p in args.output.rglob("*") if p.is_file())
    print(f"配布物: {args.output} ({count} files, Markdown links OK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

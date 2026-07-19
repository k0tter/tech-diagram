# Contributing

[English](CONTRIBUTING.md) | [日本語](CONTRIBUTING.ja.md) | [Bahasa Indonesia](CONTRIBUTING.id.md)

tech-diagram の開発の回し方。依存は Python 標準ライブラリのみ(3.10+)で、
セットアップは clone だけです。

## 開発ループ

### 1. 回帰テスト

```bash
python3 scripts/tests.py
```

スキルパッケージ / ビルダー / バリデータ / レイアウトエンジン / tf_to_spec を検証する。
**変更の前後で必ず実行**し、全件 OK を保つ。エンジンに手を入れたら、対応する
テストを同ファイルに追加する。`SKILL.md` 編集中の frontmatter / パッケージ簡易検査は:

```bash
python3 scripts/tests.py TestSkillPackage
```

### 2. テンプレート再生成とバイト一致ゲート

`templates/` の `.spec.json` と `.drawio` はペアでコミットされており、CI が
「現行エンジンで再生成してバイト一致」を検証する。エンジンの出力を意図して変えた場合は
**全テンプレートを再生成してコミットに含める**:

```bash
for f in templates/*.spec.json; do
  python3 scripts/build_drawio.py "$f" -o "${f%.spec.json}.drawio"
done
git diff --stat -- templates/   # 差分が意図どおりかを目視
```

各テンプレートは 0 エラー・0 警告(`=== 0 error(s), 0 warning(s) ===`)が必須。
再生成せずに push すると CI のテンプレ同期ゲートで落ちる。

### 3. 配線品質のルータ検査

配線・配置に触れる変更は、バリデータに加えてルータ検査を通す — 全 17 検査:
配線幾何 10 検査(接続アンカー / ファンアウト対称 / レーン分離 / 出射辺の方向 /
垂直ペア中心 / 兄弟コンテナ寸法 / ファン辺の流儀統一 / 折れ点上限 /
同一辺ポート分離 / fork 形状)+形状・コントラクト 7 検査(decision 頂点 /
safe id / 両端ラベル / ER 端別カーディナリティ / stereotype 斜体 /
フロー shape・link / gateway トポロジ):

```bash
python3 evals/check_diagram.py <out.drawio> --router
```

テンプレートと回帰フィクスチャで誤検知ゼロに校正済みのため、違反が出たら
検査ではなくエンジン側を疑う。

### 4. fail-before 検証(配線回帰フィクスチャ)

配線改善は `evals/files/router-regression/verify.py` で固定する:

```bash
# pass-after: 現行エンジンで全スペック 0 違反
python3 evals/files/router-regression/verify.py

# fail-before: 修正前エンジンのスナップショットで「狙いの検査」が実際に落ちることを確認
python3 evals/files/router-regression/verify.py \
    --engine <旧 build_drawio.py へのパス> --expect-fail --era <r3|r4|r5|r7|sem>
```

fail-before が確認できない検査は回帰防止になっていない(最初から通る検査は
何も守らない)ため、取り込まない。

## 修正の流儀 — 再現スペック → fail-before → 回帰テスト

配線・レイアウトのバグ修正は次の順で進める:

1. **再現スペック**: 不具合が再現する最小の `.spec.json` を作る(Issue の
   「配線・レイアウト不具合報告」フォームの必須項目と同じ)。
2. **fail-before**: 修正前に、その事象を機械検出する検査を `check_diagram.py` 側に
   書き、現行(修正前)エンジンで**実際に落ちる**ことを実測する。
3. **修正**: エンジンを直し、同じ検査が通ることを確認する。
4. **回帰固定**: 再現スペックを `evals/files/router-regression/` のフィクスチャに
   追加し、`scripts/tests.py` にも単体レベルの回帰テストを足す。
5. 全テンプレート再生成(上記 2.)+ `python3 scripts/tests.py` 全件 OK。

「見た目が直った」は完了条件にしない。検査が before で落ち after で通ること、
既存の校正ファイルで誤検知が増えないことをもって完了とする。

## Pull Request

- 1 PR = 1 論理変更。無関係のリファクタ・整形を混ぜない。
- コミットメッセージは既存の慣例(`feat:` / `fix:` / `evals:` / `docs:` など)に合わせる。
- CI(回帰テスト py3.10/3.13・テンプレ同期・ファザースモーク・draw.io 実描画スモーク・
  gitleaks)が全て通ることがマージ条件。
- 不具合報告は Issue テンプレート(配線・レイアウト不具合報告 / 構造化フィードバック)へ。
  「事象 + 再現 + 実測値」が揃っていれば、そのまま fail-before フィクスチャに取り込める。

## 脆弱性の報告

セキュリティに関わる報告は Issue ではなく [SECURITY.ja.md](SECURITY.ja.md) の手順で。

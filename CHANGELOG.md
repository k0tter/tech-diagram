# Changelog

All notable changes to this project are documented in this file, newest
first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versioning follows [Semantic Versioning](https://semver.org/). The
distribution zip and auto-generated notes for each version live on GitHub
Releases.

## [1.0.0] - 2026-07-18

First public release. / 初回公開リリース。/ Rilis publik pertama.

### Added

- **Diagram types**: AWS / Azure / GCP and multi-cloud architecture diagrams,
  ER diagrams, UML class diagrams, flowcharts (with swimlanes), and reference
  architecture diagrams (numbered badges + step descriptions), all as
  draw.io (`.drawio`) output
- **Layout engine**: an integer grid (`col`/`row`) JSON spec is turned into
  pixel coordinates, nested container sizing, orthogonal routing and label
  placement; automatic layout when `col`/`row` are omitted; deterministic
  `--optimize` placement local search with `pin` support
- **Validator**: about 20 machine checks — geometric (label overlaps, node
  piercing, edge crossings with hub-degree correction, boundary correctness)
  and semantic checks W8–W21, including architecture anti-pattern detection
  W16–W21 (global edge services drawn inside a region/VPC/subnet, databases
  in public subnets, external-client-to-database edges, failover lines that
  bypass CloudFront/WAF, HA labels with a single AZ, unreachable
  private-subnet egress)
- **Reference architecture library**:
  `references/patterns.md` — an AWS pattern catalog grounded in primary
  sources — plus 5 verified starter specs in
  `references/reference-architectures/` (all build at 0 errors / 0 warnings)
- **Icon catalogs**: AWS 960 / Azure 641 / GCP 45 icon entries (names and
  style metadata extracted from draw.io; no icon images bundled)
- **Terraform import**: `tf_to_spec.py` parses `.tf` files directly into a
  spec skeleton with review notes (no credentials, terraform CLI or state)
- **Preview**: `--emit-png` real rendering (draw.io CLI auto-detection) and
  self-contained `--emit-svg`
- **Templates**: 10 worked examples as `.spec.json` + generated `.drawio`
  pairs, with a gallery on GitHub Pages
- **Evaluation suite**: 20 end-to-end evals / 118 expectations with
  independent grading and machine checks, including fail-before routing
  regression fixtures and architecture-correctness regression sets
- **CI and supply chain**: regression tests (Python 3.10/3.13), template
  sync gate, fuzzer smoke, real draw.io render smoke (weekly compatibility
  against latest draw.io), CodeQL, gitleaks, Secret Scanning Push Protection,
  Dependabot, SHA-pinned Actions, OpenSSF Scorecard; releases ship
  `SHA256SUMS` and a build provenance attestation
- **Zero runtime dependencies**: Python standard library only (3.10+)

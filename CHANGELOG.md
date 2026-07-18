# Changelog

All notable changes to this project are documented in this file, newest
first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versioning follows [Semantic Versioning](https://semver.org/). The
distribution zip and auto-generated notes for each version live on GitHub
Releases.

## [1.1.0] - 2026-07-19

Architectural-placement correctness. / 配置のアーキテクチャ的正しさ。/
Ketepatan penempatan arsitektur.

### Added

- **Public-subnet-front principle**: public subnets (the internet entry side)
  are placed at the front (left/top) of the VPC, private subnets (App / DB /
  Cache) behind them, so every diagram reads internet → IGW → public →
  private (SKILL.md placement principle 7, patterns.md AP14)
- **Internet-facing ALB placement rule (two forms)**: diagrams without
  explicit AZs draw the ALB inside the public subnet; diagrams with explicit
  AZs draw a single ALB node (no duplication) in the public-subnet column at
  VPC level, sandwiched between the AZs' public subnets — grounded in the AWS
  VPC documentation ("each public subnet contains a NAT gateway and a load
  balancer node")

### Changed

- **Fan-in mirroring**: paired edges converging on the same destination now
  take mirror-image routes, generalizing the existing same-source fan-out
  mirroring (e.g. the two NAT → ECR lines are symmetric)
- Reference specs (`references/reference-architectures/`) and the bundled
  templates updated to the ALB / public-subnet rules above; all gallery
  images regenerated from the current engine
- Template PNGs now live only under `docs/images/templates/`
  (`templates/*.png` removed)

### Fixed

- CI fuzz no longer counts W16–W21 architectural build rejections as layout
  failures

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

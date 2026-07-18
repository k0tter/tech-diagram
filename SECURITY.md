# Security Policy

[English](SECURITY.md) | [日本語](SECURITY.ja.md) | [Bahasa Indonesia](SECURITY.id.md)

## Reporting a vulnerability

**Do not open a public issue.** Report vulnerabilities through GitHub's
private vulnerability reporting:

1. Open [Security tab → Report a vulnerability](https://github.com/k0tter/tech-diagram/security/advisories/new)
2. Describe the reproduction steps (ideally with a repro spec / input file)
   and the impact, then submit

The report arrives as a private Security Advisory and stays private until a
fix is released. You will receive an initial response within 7 days.

## Supported versions

| Version | Supported |
|---|---|
| Latest release (newest on [Releases](https://github.com/k0tter/tech-diagram/releases)) | Yes |
| Anything older | No (please update to the latest) |

## Assumptions (attack surface)

- The only runtime dependency is the Python standard library, and the scripts
  **make no network access**.
- The main attack surface is parsing of input files (`.spec.json` / `.tf` /
  `.drawio`). Robustness against garbage and adversarial input is
  continuously verified by the fuzzer smoke tests in CI (`tools/fuzz_hcl.py` /
  `tools/fuzz_layout.py`).
- The integrity of the distribution zip can be verified with the release
  asset `SHA256SUMS` and the build provenance attestation:

  ```bash
  sha256sum -c SHA256SUMS   # on macOS: shasum -a 256 -c SHA256SUMS
  gh attestation verify tech-diagram-vX.Y.Z.zip --repo k0tter/tech-diagram
  ```

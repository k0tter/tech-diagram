# Kebijakan Keamanan

[English](SECURITY.md) | [日本語](SECURITY.ja.md) | [Bahasa Indonesia](SECURITY.id.md)

## Melaporkan kerentanan

**Jangan buka issue publik.** Laporkan kerentanan melalui private
vulnerability reporting milik GitHub:

1. Buka [tab Security → Report a vulnerability](https://github.com/k0tter/tech-diagram/security/advisories/new)
2. Jelaskan langkah reproduksi (idealnya dengan spesifikasi repro / berkas
   input) beserta dampaknya, lalu kirim

Laporan diterima sebagai Security Advisory privat dan tetap tertutup hingga
perbaikan dirilis. Anda akan menerima tanggapan awal dalam 7 hari.

## Versi yang didukung

| Versi | Didukung |
|---|---|
| Rilis terbaru (paling baru di [Releases](https://github.com/k0tter/tech-diagram/releases)) | Ya |
| Yang lebih lama | Tidak (silakan perbarui ke yang terbaru) |

## Asumsi (permukaan serangan)

- Satu-satunya dependensi runtime adalah pustaka standar Python, dan skrip
  **tidak melakukan akses jaringan sama sekali**.
- Permukaan serangan utama adalah parsing berkas input (`.spec.json` /
  `.tf` / `.drawio`). Ketahanan terhadap input sampah dan input berbahaya
  diverifikasi terus-menerus oleh smoke test fuzzer di CI
  (`tools/fuzz_hcl.py` / `tools/fuzz_layout.py`).
- Integritas zip distribusi dapat diverifikasi dengan aset rilis `SHA256SUMS`
  dan attestation asal-usul build:

  ```bash
  sha256sum -c SHA256SUMS   # di macOS: shasum -a 256 -c SHA256SUMS
  gh attestation verify tech-diagram-vX.Y.Z.zip --repo k0tter/tech-diagram
  ```

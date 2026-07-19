# Berkontribusi

[English](CONTRIBUTING.md) | [日本語](CONTRIBUTING.ja.md) | [Bahasa Indonesia](CONTRIBUTING.id.md)

Cara pengembangan tech-diagram berjalan. Satu-satunya dependensi adalah
pustaka standar Python (3.10+), jadi persiapan cukup dengan clone.

## Siklus pengembangan

### 1. Tes regresi

```bash
python3 scripts/tests.py
```

Suite memeriksa paket skill, builder, validator, mesin tata letak, dan
tf_to_spec. **Jalankan sebelum dan sesudah setiap perubahan** dan jaga
semuanya tetap lulus. Jika Anda menyentuh mesin, tambahkan tes yang sesuai di
berkas yang sama. Untuk pemeriksaan cepat paket/frontmatter saat mengubah
`SKILL.md`, jalankan:

```bash
python3 scripts/tests.py TestSkillPackage
```

### 2. Regenerasi templat dan gerbang byte-identik

Berkas `.spec.json` dan `.drawio` di `templates/` di-commit berpasangan, dan
CI memverifikasi bahwa regenerasi dengan mesin saat ini menghasilkan keluaran
yang byte-identik. Jika Anda sengaja mengubah keluaran mesin,
**regenerasi semua templat dan sertakan dalam commit**:

```bash
for f in templates/*.spec.json; do
  python3 scripts/build_drawio.py "$f" -o "${f%.spec.json}.drawio"
done
git diff --stat -- templates/   # periksa bahwa diff sesuai maksud Anda
```

Setiap templat wajib ter-build dengan 0 error / 0 warning
(`=== 0 error(s), 0 warning(s) ===`). Push tanpa regenerasi akan gagal di
gerbang sinkronisasi templat pada CI.

### 3. Pemeriksaan router untuk kualitas perutean

Perubahan yang menyentuh perutean atau penempatan harus lulus pemeriksaan
router di samping validator — 17 pemeriksaan: 10 pemeriksaan geometri
perutean (jangkar koneksi / simetri fan-out / pemisahan lajur / arah sisi
keluar / pemusatan pasangan vertikal / dimensi kontainer saudara /
konsistensi sisi fan / batas jumlah belokan / pemisahan port sesisi / bentuk
fork) plus 7 pemeriksaan bentuk-dan-kontrak (verteks decision / id sel aman /
label kedua ujung / kardinalitas ER per ujung / miring stereotype / shape dan
link flow / topologi gateway):

```bash
python3 evals/check_diagram.py <out.drawio> --router
```

Pemeriksaan sudah dikalibrasi hingga nol false positive pada templat dan
fixture regresi; jadi jika muncul pelanggaran, curigai mesinnya, bukan
pemeriksaannya.

### 4. Verifikasi fail-before (fixture regresi perutean)

Peningkatan perutean dikunci dengan
`evals/files/router-regression/verify.py`:

```bash
# pass-after: mesin saat ini, nol pelanggaran pada semua spesifikasi
python3 evals/files/router-regression/verify.py

# fail-before: pastikan pemeriksaan yang dituju benar-benar gagal pada
# snapshot mesin sebelum perbaikan
python3 evals/files/router-regression/verify.py \
    --engine <path ke build_drawio.py lama> --expect-fail --era <r3|r4|r5|r7|sem>
```

Pemeriksaan tanpa fail-before yang terkonfirmasi bukanlah penjaga regresi
(pemeriksaan yang lulus sejak hari pertama tidak melindungi apa pun), sehingga
tidak akan dimasukkan.

## Alur perbaikan — spesifikasi repro → fail-before → tes regresi

Perbaikan bug perutean/tata letak berjalan dengan urutan berikut:

1. **Spesifikasi repro**: buat `.spec.json` terkecil yang mereproduksi masalah
   (kolom wajibnya sama dengan formulir issue "Routing / layout bug report").
2. **fail-before**: sebelum memperbaiki, tulis pemeriksaan di
   `check_diagram.py` yang mendeteksi fenomena itu secara mekanis, dan ukur
   bahwa pemeriksaan itu **benar-benar gagal** pada mesin saat ini (sebelum
   perbaikan).
3. **Perbaiki**: ubah mesin dan pastikan pemeriksaan yang sama lulus.
4. **Kunci regresinya**: tambahkan spesifikasi repro ke fixture di
   `evals/files/router-regression/`, dan tambahkan tes regresi tingkat unit ke
   `scripts/tests.py`.
5. Regenerasi semua templat (langkah 2 di atas) + `python3 scripts/tests.py`
   semuanya lulus.

"Kelihatannya sudah beres" bukan kriteria selesai. Selesai berarti:
pemeriksaan gagal pada kondisi before dan lulus pada after, dan tidak ada
false positive baru pada berkas kalibrasi yang ada.

## Pull request

- 1 PR = 1 perubahan logis. Jangan campur refactoring atau perapian yang
  tidak terkait.
- Ikuti konvensi pesan commit yang ada (`feat:` / `fix:` / `evals:` /
  `docs:` dsb.).
- CI harus lulus seluruhnya untuk merge: tes regresi Python 3.10/3.13,
  sinkronisasi templat, smoke test fuzzer, smoke test render draw.io
  sungguhan, gitleaks.
- Laporkan bug lewat templat issue (Routing / layout bug report / Structured
  feedback). Laporan dengan "fenomena + reproduksi + nilai terukur" dapat
  langsung dijadikan fixture fail-before.

## Melaporkan kerentanan

Untuk laporan terkait keamanan, jangan buka issue — ikuti proses di
[SECURITY.id.md](SECURITY.id.md).

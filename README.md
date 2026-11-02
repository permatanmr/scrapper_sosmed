# Scraper Post X

Mengambil post X terkait Raffi Ahmad melalui ScrapeCreators API, memfilter hasil berdasarkan tanggal, lalu menyimpannya sebagai CSV.

## Persiapan

Gunakan Python 3 dan buat virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Buat API key di ScrapeCreators, lalu buat file `.env` di direktori proyek:

```dotenv
SCRAPECREATORS_API_KEY=your-api-key
```

Script memuat file ini secara otomatis. File `.env` sudah diabaikan oleh Git. Sebagai alternatif, API key dapat diberikan melalui environment variable; argumen `--api-key` memiliki prioritas tertinggi.

## Menjalankan

```bash
python scrapper_x.py
```

Secara default, scraper menggunakan beberapa variasi kueri, mengambil maksimal 3 halaman per kueri, memfilter post sejak 28 Oktober 2026 hingga waktu berjalan (WIB), dan menyimpan hasil di folder `output/` dengan nama `rafi_ahmad_x_raw_YYYYMMDD_HHMMSS_WIB.csv`. Timestamp menggunakan waktu mulai proses dalam zona WIB, sehingga hasil tiap run memiliki nama berbeda. Gunakan `--out hasil.csv` untuk memilih nama lain di dalam folder `output/`.

Contoh opsi:

```bash
python scrapper_x.py --since 2026-10-28 --until 2026-11-02 --out hasil.csv
python scrapper_x.py --strict --max-pages 5
python scrapper_x.py --query "raffi ahmad rans" --query "#raffinagita"
python scrapper_x.py --api-key "your-api-key"
```

- `--since` menetapkan tanggal awal dalam format `YYYY-MM-DD` (mulai pukul 00:00 WIB).
- `--until` menetapkan tanggal akhir dalam format `YYYY-MM-DD` (termasuk sepanjang hari tersebut, WIB).
- `--out` menetapkan nama file CSV di folder `output/`.
- `--query` dapat diulang; jika digunakan, kueri bawaan tidak dipakai.
- `--max-pages` membatasi halaman per kueri ke rentang 1-11. Setiap halaman dapat menggunakan kredit API.
- `--strict` hanya menyimpan post yang teksnya secara eksplisit cocok dengan variasi nama Raffi Ahmad.

Jangan commit API key atau file yang berisi kredensial. Data CSV keluaran adalah hasil scrape dan dapat berisi konten pengguna.

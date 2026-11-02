#!/usr/bin/env python3
"""
Search postingan X (Twitter) terkait "Rafi Ahmad" via ScrapeCreators API,
difilter mulai 28 Oktober 2026 s.d. sekarang, lalu simpan ke CSV dengan kolom:

interaction_id,timestamp,platform,author_id,author_username,interaction_type,
target_id,post_id,parent_post_id,text,hashtags,urls,likes,shares

Pemakaian:
    pip install -r requirements.txt
    # Tambahkan SCRAPECREATORS_API_KEY=xxxxx ke file .env
    python scrape_rafi_ahmad.py
    python scrape_rafi_ahmad.py --since 2026-10-28 --out rafi_ahmad_x.csv
    python scrape_rafi_ahmad.py --strict --max-pages 5      # hanya post yang menyebut Raffi Ahmad
    python scrape_rafi_ahmad.py --query "raffi ahmad rans" --query "#raffinagita"

Catatan penting tentang endpoint:
- Endpoint: GET https://api.scrapecreators.com/v1/twitter/search/posts
- Parameter hanya `query` dan `cursor` (cursor 1-11, 1 kredit/halaman).
  TIDAK ada parameter filter tanggal, jadi filter tanggal dilakukan di sisi klien.
- Sumber hasil adalah post X yang terindeks Google, sehingga tidak dijamin
  lengkap/kronologis. Karena itu dipakai beberapa variasi query lalu di-dedup.
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
import requests

BASE_URL = "https://api.scrapecreators.com/v1/twitter/search/posts"
MAX_CURSOR = 11  # batas halaman yang didukung API
WIB = timezone(timedelta(hours=7))

# Variasi query agar cakupan lebih luas (masing-masing memakan s.d. 11 kredit).
DEFAULT_QUERIES = [
    # Variasi ejaan nama (ejaan resmi: "Raffi Ahmad", sering ditulis "Rafi Ahmad")
    "raffi ahmad",
    "rafi ahmad",
    "raffiahmad",
    "rafiahmad",
    "#raffiahmad",
    "#rafiahmad",
    "\"raffi ahmad\"",
    # Panggilan / sebutan
    "mas raffi",
    "raffi ahmad artis",
    # Keluarga & entitas terkait
    "raffi nagita",
    "raffi nagita slavina",
    "rafathar raffi",
    "rans entertainment raffi",
    "rans nusantara hebat raffi",
    # Topik berita
    "raffi ahmad utusan khusus presiden",
    "raffi ahmad berita terbaru",
]

# Dipakai oleh --strict: post hanya disimpan bila teksnya menyebut Raffi Ahmad
# (berbagai ejaan). Tanpa --strict, semua hasil pencarian dalam rentang tanggal disimpan.
RELEVANCE_RE = re.compile(
    r"\b(raffi|rafi|raffy|rafy)\s*ahmad\b|raffiahmad|rafiahmad|raffinagita|"
    r"\bmas\s+raffi\b|\braffi\s+nagita\b|\bnagita\s+raffi\b",
    re.IGNORECASE,
)

FIELDNAMES = [
    "interaction_id", "timestamp", "platform", "author_id", "author_username",
    "interaction_type", "target_id", "post_id", "parent_post_id", "text",
    "hashtags", "urls", "likes", "shares",
]

HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
URL_RE = re.compile(r"https?://\S+")
USER_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/]+)/status/(\d+)")


def parse_created_at(s):
    """'Thu Oct 01 18:50:27 +0000 2026' -> datetime (aware)."""
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
    except (TypeError, ValueError):
        return None


def fetch_page(session, api_key, query, cursor, retries=4):
    params = {"query": query}
    if cursor:
        params["cursor"] = str(cursor)
    for attempt in range(retries):
        try:
            r = session.get(
                BASE_URL,
                headers={"x-api-key": api_key},
                params=params,
                timeout=60,
            )
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  ! network error ({e}); retry {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code == 401:
            sys.exit("401 Unauthorized: cek API key (header x-api-key).")
        if r.status_code == 402:
            sys.exit("402 Payment Required: kredit habis.")
        if r.status_code >= 500 or r.status_code == 429:
            wait = 2 ** attempt
            print(f"  ! HTTP {r.status_code}; retry {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            print(f"  ! HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return None
        return r.json()
    return None


def post_to_row(post):
    """Petakan satu objek post ScrapeCreators ke baris CSV. Aman terhadap field yang hilang."""
    legacy = post.get("legacy") or {}
    post_id = str(post.get("rest_id") or legacy.get("id_str") or "")
    url = post.get("url") or ""
    text = legacy.get("full_text") or legacy.get("text") or ""

    # author_username dari URL status (author_id tidak tersedia di endpoint ini
    # kecuali jika API menyertakan user_id_str / core.user_results).
    author_username = ""
    m = USER_RE.match(url)
    if m:
        author_username = m.group(1)
        post_id = post_id or m.group(2)
    core_user = ((post.get("core") or {}).get("user_results") or {}).get("result") or {}
    author_id = (
        legacy.get("user_id_str")
        or core_user.get("rest_id")
        or ""
    )
    author_username = (
        (core_user.get("legacy") or {}).get("screen_name") or author_username
    )

    # Tipe interaksi & relasi post
    reply_to = legacy.get("in_reply_to_status_id_str") or ""
    quoted = legacy.get("quoted_status_id_str") or ""
    retweeted = ((legacy.get("retweeted_status_result") or {}).get("result") or {}).get("rest_id") or ""
    if retweeted or text.startswith("RT @"):
        interaction_type, parent, target = "retweet", retweeted, retweeted
    elif reply_to:
        interaction_type, parent, target = "reply", reply_to, reply_to
    elif quoted:
        interaction_type, parent, target = "quote", quoted, quoted
    else:
        interaction_type, parent, target = "post", "", ""

    # Hashtag & URL: pakai entities bila ada, fallback regex dari teks
    ents = legacy.get("entities") or {}
    tags = [h.get("text") for h in ents.get("hashtags", []) if h.get("text")]
    if not tags:
        tags = HASHTAG_RE.findall(text)
    urls = [
        u.get("expanded_url") or u.get("url")
        for u in ents.get("urls", [])
        if u.get("expanded_url") or u.get("url")
    ]
    if not urls:
        urls = URL_RE.findall(text)

    dt = parse_created_at(legacy.get("created_at"))
    return dt, {
        "interaction_id": post_id,  # 1 post = 1 interaksi; id sama dengan post_id
        "timestamp": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else "",
        "platform": "x",
        "author_id": author_id,
        "author_username": author_username,
        "interaction_type": interaction_type,
        "target_id": target,
        "post_id": post_id,
        "parent_post_id": parent,
        "text": text.replace("\r", " ").replace("\n", " ").strip(),
        "hashtags": "|".join(tags),
        "urls": "|".join(urls),
        "likes": legacy.get("favorite_count", 0),
        "shares": legacy.get("retweet_count", 0),
    }


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Scrape postingan X tentang Rafi Ahmad via ScrapeCreators")
    ap.add_argument("--api-key", default=os.getenv("SCRAPECREATORS_API_KEY"))
    ap.add_argument("--since", default="2026-10-28", help="YYYY-MM-DD (00:00 WIB), default 2026-10-28")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD (akhir hari WIB); default: sekarang")
    default_out = f"rafi_ahmad_x_raw_{datetime.now(WIB):%Y%m%d_%H%M%S}_WIB.csv"
    ap.add_argument("--out", default=default_out, help="Nama file keluaran di folder output/")
    ap.add_argument("--query", action="append", help="Boleh diulang. Default: beberapa variasi 'rafi ahmad'")
    ap.add_argument("--max-pages", type=int, default=3,
                    help="Maks halaman per query (1-11, default 3). 1 halaman = 1 kredit")
    ap.add_argument("--strict", action="store_true",
                    help="Hanya simpan post yang teksnya menyebut Raffi Ahmad (berbagai ejaan)")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("Set env SCRAPECREATORS_API_KEY atau gunakan --api-key.")

    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=WIB)
    if args.until:
        until = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=WIB) + timedelta(days=1)
    else:
        until = datetime.now(WIB)
    queries = args.query or DEFAULT_QUERIES
    max_pages = max(1, min(args.max_pages, MAX_CURSOR))

    session = requests.Session()
    rows, seen = [], set()
    total_seen, credits = 0, 0

    for q in queries:
        print(f"[query] {q!r}")
        for page in range(1, max_pages + 1):
            data = fetch_page(session, args.api_key, q, page)
            if not data or not data.get("success", True):
                print(f"  halaman {page}: gagal/kosong, lanjut query berikutnya")
                break
            credits += data.get("credits_charged", 1) or 0
            posts = data.get("posts") or []
            if isinstance(posts, dict):  # dokumentasi menyebut 'object'; antisipasi
                posts = list(posts.values())
            kept = 0
            for p in posts:
                total_seen += 1
                dt, row = post_to_row(p)
                if not dt or not (since <= dt.astimezone(WIB) <= until):
                    continue
                if args.strict and not RELEVANCE_RE.search(row["text"]):
                    continue
                if row["post_id"] in seen:
                    continue
                seen.add(row["post_id"])
                rows.append(row)
                kept += 1
            print(f"  halaman {page}: {len(posts)} post, {kept} baru dalam rentang tanggal")
            # cursor null -> tidak ada halaman lagi
            if not posts or data.get("cursor") in (None, "", "null"):
                break
            time.sleep(0.3)

    rows.sort(key=lambda r: r["timestamp"])
    output_dir = Path(__file__).resolve().parent / "output"
    output_path = output_dir / args.out
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)

    print(
        f"\nSelesai. {len(rows)} post unik "
        f"({since:%Y-%m-%d} s.d. {until:%Y-%m-%d %H:%M} WIB) dari {total_seen} hasil "
        f"-> {output_path} | kredit terpakai ~{credits}"
    )


if __name__ == "__main__":
    main()
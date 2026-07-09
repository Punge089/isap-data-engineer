"""Step 6: latest-file detector (ข้อ 3b).

Checks whether a newer report has been published on each source's listing
page than what's already recorded in raw/manifest.json. This step only
DETECTS and REPORTS ("new file found: <date>" / "nothing new") — it never
downloads anything. Downloading is Step 7's job (ข้อ 3c), kept separate the
same way extraction and cleaning were.

Known, permanent limitations found while building this (not TODOs):

- OCSC's listing page is behind a Cloudflare managed JS challenge ("Just a
  moment...", HTTP 403) that plain requests/BeautifulSoup cannot pass —
  there is no header or cookie that defeats this without executing
  JavaScript, which is out of scope for this project (PROJECT_SPEC.md §11
  anticipated exactly this risk). A saved copy of that exact challenge page
  is in tests/fixtures/ocsc_cloudflare_challenge.html. Since OCSC only
  publishes once a year, the honest fallback is a manual check, not an
  automated one — see check_ocsc()'s returned message.

- CGD's listing page DOES work with plain requests + BeautifulSoup. Each
  report row has a dedicated 'วัน/เดือน/ปี' column in 'DD/MM/YYYY' format
  (Buddhist Era year) — that column is used as the date source, not the
  Thai free-text title (title parsing would need a 12-entry Thai month
  name table and two different phrasings; the date column needs none of
  that and is far less likely to break).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "raw" / "manifest.json"

CGD_URL = "https://www.cgd.go.th/cs/internet/internet/%E0%B8%82%E0%B9%88%E0%B8%B2%E0%B8%A7%E0%B8%AA%E0%B8%96%E0%B8%B4%E0%B8%95%E0%B8%B4.html"
OCSC_URL = "https://www.ocsc.go.th/strategy-policy-work-plan/reports-statistics/government-workforce-statistics-report/2021-present-workforce-statistics/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ISAP-student-project/0.1; educational data pipeline)"
}

CGD_REPORT_TITLE_PREFIX = "ผลการเบิกจ่ายเงิน"


# ---------------------------------------------------------------- parsing

def parse_thai_be_date(text: str) -> date:
    """'DD/MM/YYYY' with a Buddhist Era year -> a CE date.

    e.g. '03/07/2569' -> date(2026, 7, 3)
    """
    day_str, month_str, year_be_str = text.strip().split("/")
    return date(int(year_be_str) - 543, int(month_str), int(day_str))


def find_latest_cgd_report(html: str) -> tuple[str, date] | None:
    """Return (title, report_date) for the most recent report on the CGD
    listing page, or None if no report rows were found at all — a
    structural change worth failing loud on, not silently reporting
    'nothing new'.
    """
    soup = BeautifulSoup(html, "html.parser")

    reports = []
    for heading in soup.find_all("h2", class_="news-title"):
        link = heading.find("a")
        if link is None:
            continue
        title = link.get_text(strip=True)
        if not title.startswith(CGD_REPORT_TITLE_PREFIX):
            continue

        row = heading.find_parent("tr")
        if row is None:
            continue
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        try:
            report_date = parse_thai_be_date(cells[2].get_text(strip=True))
        except ValueError:
            continue

        reports.append((title, report_date))

    if not reports:
        return None
    # Take the max by parsed date rather than trusting page order, in case
    # a future layout change reorders the rows.
    return max(reports, key=lambda pair: pair[1])


# ---------------------------------------------------------------- manifest

def load_known_cgd_date() -> date | None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["source"] == "CGD":
            return date.fromisoformat(entry["report_date"])
    return None


# ---------------------------------------------------------------- reporting

def format_cgd_result(latest: tuple[str, date] | None, known_date: date | None) -> str:
    if latest is None:
        return (
            "CGD: page fetched but no report rows found — the listing page's "
            "structure may have changed since this was written, check manually "
            f"at {CGD_URL}"
        )

    title, latest_date = latest
    if known_date is None or latest_date > known_date:
        return f"CGD: new file found — {title} ({latest_date.isoformat()})"
    return f"CGD: nothing new (latest on site is {latest_date.isoformat()}, already have it)"


# ---------------------------------------------------------------- network

def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def check_cgd() -> str:
    known_date = load_known_cgd_date()
    try:
        html = fetch_html(CGD_URL)
    except requests.exceptions.RequestException as e:
        return f"CGD: could not fetch listing page ({type(e).__name__}: {e})"
    return format_cgd_result(find_latest_cgd_report(html), known_date)


def check_ocsc() -> str:
    try:
        fetch_html(OCSC_URL)
    except requests.exceptions.RequestException as e:
        return (
            f"OCSC: could not fetch listing page automatically ({type(e).__name__}: {e}). "
            "Known cause as of this writing: this URL returns a Cloudflare managed JS "
            "challenge ('Just a moment...', HTTP 403) that requests/BeautifulSoup cannot "
            "pass — see tests/fixtures/ocsc_cloudflare_challenge.html for a saved copy of "
            "that exact page. (If the error above is SSL-related instead, that's a local "
            "network/proxy certificate issue, not this site.) OCSC publishes once a year, "
            f"so check manually at {OCSC_URL}"
        )
    # If this ever succeeds, no parser has been built or tested for OCSC's
    # real listing markup — we have never seen it. Deliberately conservative
    # rather than guessing at a structure.
    return (
        "OCSC: fetched successfully, but no parser exists for this page's structure "
        f"(never seen past the Cloudflare challenge before) — check manually at {OCSC_URL}"
    )


def main() -> None:
    print(check_cgd())
    print(check_ocsc())


if __name__ == "__main__":
    main()

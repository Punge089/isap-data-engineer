"""Step 6: latest-file detector (ข้อ 3b).

Checks whether a newer report has been published on each source's listing
page than what's already recorded in raw/manifest.json. This step only
DETECTS and REPORTS ("new file found: <date>" / "nothing new") — it never
downloads anything. Downloading is Step 7's job (ข้อ 3c), kept separate the
same way extraction and cleaning were.

Known, permanent limitations found while building this (not TODOs):

- OCSC's listing page has given TWO DIFFERENT real responses on two
  separate live requests to the exact same URL, and this is not treated as
  one superseding the other — see HANDOFF.md's "Open risk: OCSC detection
  may be non-deterministic" for the full record. Both are handled:
  (1) sometimes a Cloudflare managed JS challenge ("Just a moment...",
  HTTP 403) — see tests/fixtures/ocsc_cloudflare_challenge.html for a real
  saved copy; (2) sometimes a clean 200 with the real WordPress/Elementor
  page — see tests/fixtures/ocsc_real_page_no_file_links.html — but even
  then the report list isn't in that HTML. It's a "custom-field-filter-form"
  widget backed by a WordPress admin-ajax.php call that only populates
  results after JavaScript runs (confirmed: zero .xlsx/.xls/.pdf/.zip links
  anywhere in that real, successfully-fetched 369KB page). So neither
  outcome is scrapable with requests/BeautifulSoup: one is blocked before
  reaching the content, the other reaches content that still requires
  JavaScript to populate, which is out of scope for this project
  (PROJECT_SPEC.md §11 anticipated the general risk; these are the two
  confirmed concrete shapes it took). Since OCSC only publishes once a
  year, the honest fallback is a manual check either way — see
  check_ocsc()'s returned messages for both cases.

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
from typing import NamedTuple

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


class CgdReport(NamedTuple):
    """One report row from CGD's listing page.

    download_href is the raw <a href> string — for CGD that's a
    javascript:openDownload(...) call, not a plain URL (see Step 6 finding
    in this module's docstring). src/download.py is what actually extracts
    the real download URL out of it; this module just carries it through
    unparsed, since detect.py's own job is reporting, not downloading.
    """
    title: str
    report_date: date
    download_href: str


# ---------------------------------------------------------------- parsing

def parse_thai_be_date(text: str) -> date:
    """'DD/MM/YYYY' with a Buddhist Era year -> a CE date.

    e.g. '03/07/2569' -> date(2026, 7, 3)
    """
    day_str, month_str, year_be_str = text.strip().split("/")
    return date(int(year_be_str) - 543, int(month_str), int(day_str))


def find_latest_cgd_report(html: str) -> CgdReport | None:
    """Return the most recent report on the CGD listing page, or None if no
    report rows were found at all — a structural change worth failing loud
    on, not silently reporting 'nothing new'.
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

        reports.append(CgdReport(title=title, report_date=report_date, download_href=link.get("href", "")))

    if not reports:
        return None
    # Take the max by parsed date rather than trusting page order, in case
    # a future layout change reorders the rows.
    return max(reports, key=lambda r: r.report_date)


# ---------------------------------------------------------------- manifest

def latest_cgd_date_from_manifest(manifest: dict) -> date | None:
    """The most recent report_date across ALL manifest entries for CGD.

    Manifest order is not trusted here for the same reason
    find_latest_cgd_report doesn't trust page order: once Step 7 can append
    a second CGD entry (e.g. next month's report), the newest one is not
    guaranteed to be last (or first) in the file.
    """
    known_dates = [
        date.fromisoformat(entry["report_date"])
        for entry in manifest["files"]
        if entry["source"] == "CGD"
    ]
    return max(known_dates) if known_dates else None


def load_known_cgd_date() -> date | None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return latest_cgd_date_from_manifest(manifest)


# ---------------------------------------------------------------- reporting

def format_cgd_result(latest: CgdReport | None, known_date: date | None) -> str:
    if latest is None:
        return (
            "CGD: page fetched but no report rows found — the listing page's "
            "structure may have changed since this was written, check manually "
            f"at {CGD_URL}"
        )

    if known_date is None or latest.report_date > known_date:
        return f"CGD: new file found — {latest.title} ({latest.report_date.isoformat()})"
    return f"CGD: nothing new (latest on site is {latest.report_date.isoformat()}, already have it)"


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


FILE_LINK_EXTENSIONS = (".xlsx", ".xls", ".pdf", ".zip", ".doc", ".docx")


def html_has_file_links(html: str) -> bool:
    """True if the HTML contains any direct link to a document file.

    Used to confirm, on every run, whether OCSC's page happens to expose
    its report list statically, or is still hiding it behind the
    JS-driven filter widget described in this module's docstring — rather
    than assuming today's finding holds forever.
    """
    soup = BeautifulSoup(html, "html.parser")
    return any(
        any(ext in a["href"].lower() for ext in FILE_LINK_EXTENSIONS)
        for a in soup.find_all("a", href=True)
    )


def check_ocsc() -> str:
    try:
        html = fetch_html(OCSC_URL)
    except requests.exceptions.RequestException as e:
        return (
            f"OCSC: could not fetch listing page ({type(e).__name__}: {e}). Observed "
            "intermittently while building this: this URL is sometimes served behind a "
            "Cloudflare managed JS challenge ('Just a moment...', HTTP 403) — see "
            "tests/fixtures/ocsc_cloudflare_challenge.html for a saved copy. OCSC publishes "
            f"once a year, so check manually at {OCSC_URL}"
        )

    if not html_has_file_links(html):
        return (
            "OCSC: fetched the real page successfully, but it contains no direct file "
            "links at all — the report list is rendered by a JS-driven filter widget "
            "(WordPress admin-ajax.php), not present in the static HTML. Confirmed true "
            "even on a clean 200 response (see tests/fixtures/ocsc_real_page_no_file_links.html) "
            "— not scrapable with requests/BeautifulSoup regardless of whether Cloudflare "
            f"challenges this particular request. Check manually at {OCSC_URL}"
        )

    # If this ever triggers, the page's structure changed to expose file
    # links statically for the first time -- worth investigating for real,
    # not something this function has a parser for yet.
    return (
        "OCSC: fetched successfully and found file links directly in the static HTML — "
        "this is new (previously the list was JS-rendered only, see module docstring). "
        f"No parser exists yet to pick the latest one — check manually at {OCSC_URL}"
    )


def main() -> None:
    print(check_cgd())
    print(check_ocsc())


if __name__ == "__main__":
    main()

"""Step 6: latest-file detector (ข้อ 3b). Reports "new file" / "nothing
new" per source, never downloads (Step 7's job). OCSC isn't scrapable
(Cloudflare + JS-rendered widget, see HANDOFF.md) -- manual fallback.
CGD works fine via requests + BeautifulSoup."""

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
    """One CGD report row. download_href is the raw, unparsed
    javascript:openDownload(...) href -- download.py extracts the URL."""
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
    """Most recent report on the CGD listing page, or None if no rows found."""
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
    """Most recent report_date across all CGD manifest entries -- never
    trusts manifest order (Step 7 can append entries out of date order)."""
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
    """True if the HTML has any direct link to a document file -- checked
    fresh every run rather than assuming the JS-widget finding holds forever."""
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

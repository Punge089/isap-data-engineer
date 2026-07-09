"""Step 6 detector tests.

IMPORTANT — what these tests do and do NOT prove:

All tests here run against SAVED, LOCAL copies of real page HTML
(tests/fixtures/*.html), never the live URLs. That's deliberate: hitting a
government site's real page on every CI run / every local `pytest` is
unreliable (their servers, their uptime, their rate limits) and rude
(repeated automated requests to a small government site with no caching).

This means: passing tests prove the PARSING LOGIC is correct against the
exact HTML shape captured on 2026-07-09 when this step was built. They do
NOT prove src/detect.py still works against the live CGD/OCSC sites today
— a real layout change on either site would not fail any test here, only a
live run of `python src/detect.py` would catch that. Re-fetch and update
the fixtures periodically (or whenever a live run behaves unexpectedly) to
keep this coverage honest.

tests/fixtures/cgd_listing_sample.html is a trimmed excerpt (just the
report-listing table) of the real page fetched while building this step —
CGD's site returned a normal 200 with real content, no bot protection
encountered.

OCSC's live URL gave TWO DIFFERENT real responses on two separate live
requests made while building this step. Neither fixture below supersedes
or invalidates the other — both are genuine observations, and
HANDOFF.md's "Open risk: OCSC detection may be non-deterministic" records
this explicitly so Step 7 doesn't assume either one is the permanent
behavior:
  - tests/fixtures/ocsc_cloudflare_challenge.html — the real response on a
    request that WAS challenged (HTTP 403, "Just a moment...").
  - tests/fixtures/ocsc_real_page_no_file_links.html — the real response on
    a separate request that was NOT challenged (clean HTTP 200, genuine
    WordPress/Elementor page), trimmed to the relevant containers. Even
    here, there are zero .xlsx/.xls/.pdf/.zip links anywhere in the full
    369KB page — the report list is rendered by a JS-driven filter widget
    (form.custom-field-filter-form, backed by wp-admin/admin-ajax.php), not
    present in the static HTML at all. So getting past Cloudflare on a
    given request would not be enough on its own; this is why there is no
    find_latest_ocsc_report function to test.
"""

from datetime import date
from pathlib import Path

import pytest

from detect import (
    CGD_REPORT_TITLE_PREFIX,
    CgdReport,
    find_latest_cgd_report,
    format_cgd_result,
    html_has_file_links,
    latest_cgd_date_from_manifest,
    parse_thai_be_date,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_parse_thai_be_date():
    assert parse_thai_be_date("03/07/2569") == date(2026, 7, 3)
    assert parse_thai_be_date("31/05/2569") == date(2026, 5, 31)
    assert parse_thai_be_date("08/05/2569") == date(2026, 5, 8)


def test_find_latest_cgd_report_from_real_fixture():
    html = (FIXTURES_DIR / "cgd_listing_sample.html").read_text(encoding="utf-8")
    result = find_latest_cgd_report(html)

    assert result is not None
    assert result.title.startswith(CGD_REPORT_TITLE_PREFIX)
    assert result.report_date == date(2026, 7, 3)
    assert "3 กรกฎาคม 2569" in result.title
    # the real row's href is a javascript:openDownload(...) call, not a plain URL
    assert result.download_href.startswith("javascript:openDownload(")


def test_find_latest_cgd_report_picks_max_date_not_first_row():
    """The fixture happens to list newest-first already, but the function
    must not rely on that — verified by checking it against every row, not
    just confirming the first row's date came back."""
    html = (FIXTURES_DIR / "cgd_listing_sample.html").read_text(encoding="utf-8")
    result = find_latest_cgd_report(html)

    # every other date visible in the real fixture must be older
    other_known_dates = [
        date(2026, 6, 30), date(2026, 6, 26), date(2026, 6, 19),
        date(2026, 6, 12), date(2026, 6, 5), date(2026, 5, 31),
        date(2026, 5, 22), date(2026, 5, 15), date(2026, 5, 8),
    ]
    assert all(result.report_date > d for d in other_known_dates)


def test_find_latest_cgd_report_returns_none_on_structural_change():
    """If the page no longer has any 'news-title' h2s (a real layout
    change), the function must say so via None, not crash or silently
    invent a result."""
    assert find_latest_cgd_report("<html><body>nothing here</body></html>") is None


def test_format_cgd_result_new_file_found():
    latest = CgdReport(title="ผลการเบิกจ่ายเงิน ณ วันที่ 3 กรกฎาคม 2569", report_date=date(2026, 7, 3), download_href="javascript:openDownload('a','b','/cs/Satellite?x');")
    message = format_cgd_result(latest, known_date=date(2026, 6, 26))
    assert "new file found" in message
    assert "2026-07-03" in message


def test_format_cgd_result_nothing_new():
    latest = CgdReport(title="ผลการเบิกจ่ายเงิน ณ วันที่ 3 กรกฎาคม 2569", report_date=date(2026, 7, 3), download_href="javascript:openDownload('a','b','/cs/Satellite?x');")
    message = format_cgd_result(latest, known_date=date(2026, 7, 3))
    assert "nothing new" in message


def test_format_cgd_result_no_known_date_counts_as_new():
    latest = CgdReport(title="ผลการเบิกจ่ายเงิน ณ วันที่ 3 กรกฎาคม 2569", report_date=date(2026, 7, 3), download_href="javascript:openDownload('a','b','/cs/Satellite?x');")
    message = format_cgd_result(latest, known_date=None)
    assert "new file found" in message


def test_format_cgd_result_none_latest_flags_structural_change():
    message = format_cgd_result(None, known_date=date(2026, 7, 3))
    assert "structure may have changed" in message


def test_ocsc_fixture_is_a_cloudflare_challenge_not_real_content():
    """One of two DIFFERENT real responses observed from OCSC's live URL on
    two separate requests (see HANDOFF.md's "Open risk: OCSC detection may
    be non-deterministic"). This one: Cloudflare's bot-challenge
    interstitial, not the listing page itself. Neither this nor the next
    test's fixture supersedes the other — both are genuine, and Step 7 must
    handle both, not assume either is the permanent behavior."""
    html = (FIXTURES_DIR / "ocsc_cloudflare_challenge.html").read_text(encoding="utf-8")
    assert "Just a moment" in html
    assert not html_has_file_links(html)


def test_ocsc_real_successful_page_still_has_no_file_links():
    """The other of the two real responses observed from OCSC's live URL
    (see previous test's docstring): a clean, non-challenged 200 response
    that STILL contains zero direct file links anywhere. The report list
    is rendered by a JS-driven filter widget, not present in static HTML —
    this is why there is no find_latest_ocsc_report function to test,
    regardless of which of the two observed responses a given request
    gets."""
    html = (FIXTURES_DIR / "ocsc_real_page_no_file_links.html").read_text(encoding="utf-8")
    assert "Just a moment" not in html  # confirms this fixture is NOT a challenge page
    assert not html_has_file_links(html)


def test_latest_cgd_date_from_manifest_order_independent_ascending():
    """Manifest lists the older entry first, newer entry second."""
    manifest = {
        "files": [
            {"source": "CGD", "report_date": "2026-06-05"},
            {"source": "CGD", "report_date": "2026-07-03"},
            {"source": "OCSC", "fiscal_year_be": 2567},
        ]
    }
    assert latest_cgd_date_from_manifest(manifest) == date(2026, 7, 3)


def test_latest_cgd_date_from_manifest_order_independent_descending():
    """Same two entries, reverse order — must give the same answer as the
    ascending case above, proving the function doesn't trust manifest
    order any more than find_latest_cgd_report trusts page order."""
    manifest = {
        "files": [
            {"source": "CGD", "report_date": "2026-07-03"},
            {"source": "CGD", "report_date": "2026-06-05"},
            {"source": "OCSC", "fiscal_year_be": 2567},
        ]
    }
    assert latest_cgd_date_from_manifest(manifest) == date(2026, 7, 3)


def test_latest_cgd_date_from_manifest_no_cgd_entries_returns_none():
    manifest = {"files": [{"source": "OCSC", "fiscal_year_be": 2567}]}
    assert latest_cgd_date_from_manifest(manifest) is None

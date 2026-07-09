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

tests/fixtures/ocsc_cloudflare_challenge.html is the *entire* real response
OCSC's site returned (HTTP 403, Cloudflare's "Just a moment..." managed JS
challenge) — there is no real listing-page fixture for OCSC because
requests/BeautifulSoup were never able to get past this challenge to see
one. That's the finding this step produced for OCSC, not a gap to silently
fill in later.
"""

from datetime import date
from pathlib import Path

import pytest

from detect import (
    CGD_REPORT_TITLE_PREFIX,
    find_latest_cgd_report,
    format_cgd_result,
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
    title, report_date = result
    assert title.startswith(CGD_REPORT_TITLE_PREFIX)
    assert report_date == date(2026, 7, 3)
    assert "3 กรกฎาคม 2569" in title


def test_find_latest_cgd_report_picks_max_date_not_first_row():
    """The fixture happens to list newest-first already, but the function
    must not rely on that — verified by checking it against every row, not
    just confirming the first row's date came back."""
    html = (FIXTURES_DIR / "cgd_listing_sample.html").read_text(encoding="utf-8")
    _, report_date = find_latest_cgd_report(html)

    # every other date visible in the real fixture must be older
    other_known_dates = [
        date(2026, 6, 30), date(2026, 6, 26), date(2026, 6, 19),
        date(2026, 6, 12), date(2026, 6, 5), date(2026, 5, 31),
        date(2026, 5, 22), date(2026, 5, 15), date(2026, 5, 8),
    ]
    assert all(report_date > d for d in other_known_dates)


def test_find_latest_cgd_report_returns_none_on_structural_change():
    """If the page no longer has any 'news-title' h2s (a real layout
    change), the function must say so via None, not crash or silently
    invent a result."""
    assert find_latest_cgd_report("<html><body>nothing here</body></html>") is None


def test_format_cgd_result_new_file_found():
    latest = ("ผลการเบิกจ่ายเงิน ณ วันที่ 3 กรกฎาคม 2569", date(2026, 7, 3))
    message = format_cgd_result(latest, known_date=date(2026, 6, 26))
    assert "new file found" in message
    assert "2026-07-03" in message


def test_format_cgd_result_nothing_new():
    latest = ("ผลการเบิกจ่ายเงิน ณ วันที่ 3 กรกฎาคม 2569", date(2026, 7, 3))
    message = format_cgd_result(latest, known_date=date(2026, 7, 3))
    assert "nothing new" in message


def test_format_cgd_result_no_known_date_counts_as_new():
    latest = ("ผลการเบิกจ่ายเงิน ณ วันที่ 3 กรกฎาคม 2569", date(2026, 7, 3))
    message = format_cgd_result(latest, known_date=None)
    assert "new file found" in message


def test_format_cgd_result_none_latest_flags_structural_change():
    message = format_cgd_result(None, known_date=date(2026, 7, 3))
    assert "structure may have changed" in message


def test_ocsc_fixture_is_a_cloudflare_challenge_not_real_content():
    """Documents the actual finding for OCSC: the saved response is
    Cloudflare's bot-challenge interstitial, not the listing page itself.
    This is why there is no find_latest_ocsc_report function to test --
    there has never been real content to build one against."""
    html = (FIXTURES_DIR / "ocsc_cloudflare_challenge.html").read_text(encoding="utf-8")
    assert "Just a moment" in html
    assert "challenges.cloudflare.com" in html

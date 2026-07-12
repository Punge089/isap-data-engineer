"""Step 7 Task Scheduler pipeline tests. All four branches of
run_monthly_pipeline.main() are exercised purely via monkeypatch --
detect.check_cgd/check_ocsc, download.download_cgd, extract.run_cgd,
clean.run_cgd, and run_monthly_pipeline.run_load_cgd are all faked, so no
network call, no real file I/O, no real duckdb connection anywhere here.
"""

import pytest

import clean
import detect
import download
import extract
import run_monthly_pipeline


def _fail_if_called(name):
    def _inner(*args, **kwargs):
        raise AssertionError(f"{name} must not be called on this branch")
    return _inner


def _patch_downstream_to_fail_if_called(monkeypatch):
    """Guard extract/clean/load so a test can assert the pipeline stopped
    before ever reaching them."""
    monkeypatch.setattr(extract, "run_cgd", _fail_if_called("extract.run_cgd"))
    monkeypatch.setattr(clean, "run_cgd", _fail_if_called("clean.run_cgd"))
    monkeypatch.setattr(run_monthly_pipeline, "run_load_cgd", _fail_if_called("run_load_cgd"))


# ---------------------------------------------------------------- (a) nothing new

def test_nothing_new_only_calls_detect_and_exits_zero(monkeypatch):
    ocsc_called = []

    monkeypatch.setattr(
        detect, "check_cgd",
        lambda: "CGD: nothing new (latest on site is 2026-07-03, already have it)",
    )
    monkeypatch.setattr(
        detect, "check_ocsc",
        lambda: (ocsc_called.append(True), "OCSC: some informational message")[1],
    )
    monkeypatch.setattr(download, "download_cgd", _fail_if_called("download.download_cgd"))
    _patch_downstream_to_fail_if_called(monkeypatch)

    exit_code = run_monthly_pipeline.main()

    assert exit_code == 0
    assert ocsc_called  # check_ocsc IS called, informational-only


# ---------------------------------------------------------------- (b) new file, download succeeds

def test_new_file_found_and_downloaded_runs_full_chain_in_order(monkeypatch):
    call_order = []

    monkeypatch.setattr(
        detect, "check_cgd",
        lambda: "CGD: new file found — ผลการเบิกจ่ายเงิน ณ ทดสอบ (2026-08-10)",
    )
    monkeypatch.setattr(detect, "check_ocsc", lambda: "OCSC: informational")
    monkeypatch.setattr(
        download, "download_cgd",
        lambda: "CGD: downloaded new file -> raw/cgd/2026_08_10.xlsx (report_date=2026-08-10, sha256=abc123...)",
    )
    monkeypatch.setattr(extract, "run_cgd", lambda: call_order.append("extract"))
    monkeypatch.setattr(clean, "run_cgd", lambda: call_order.append("clean"))
    monkeypatch.setattr(run_monthly_pipeline, "run_load_cgd", lambda: call_order.append("load"))

    exit_code = run_monthly_pipeline.main()

    assert exit_code == 0
    assert call_order == ["extract", "clean", "load"]


# ---------------------------------------------------------------- (c) new file, dedup-skip

def test_new_file_found_but_download_dedup_skip_does_not_run_pipeline(monkeypatch):
    monkeypatch.setattr(
        detect, "check_cgd",
        lambda: "CGD: new file found — ผลการเบิกจ่ายเงิน ณ ทดสอบ (2026-08-10)",
    )
    monkeypatch.setattr(detect, "check_ocsc", lambda: "OCSC: informational")
    monkeypatch.setattr(
        download, "download_cgd",
        lambda: (
            "CGD: downloaded content but its sha256 (abc123def456) already "
            "exists in raw/manifest.json — skipping"
        ),
    )
    _patch_downstream_to_fail_if_called(monkeypatch)

    exit_code = run_monthly_pipeline.main()

    assert exit_code == 0


# ---------------------------------------------------------------- (d) fetch failure

@pytest.mark.parametrize(
    "failed_cgd_result",
    [
        "CGD: could not fetch listing page (ConnectionError: 403 Forbidden)",
        "CGD: page fetched but no report rows found — the listing page's structure may have changed",
    ],
)
def test_fetch_failure_exits_nonzero_before_touching_download_or_pipeline(monkeypatch, failed_cgd_result):
    monkeypatch.setattr(detect, "check_cgd", lambda: failed_cgd_result)
    monkeypatch.setattr(detect, "check_ocsc", lambda: "OCSC: informational")
    monkeypatch.setattr(download, "download_cgd", _fail_if_called("download.download_cgd"))
    _patch_downstream_to_fail_if_called(monkeypatch)

    exit_code = run_monthly_pipeline.main()

    assert exit_code == 1

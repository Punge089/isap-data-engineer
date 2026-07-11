"""Step 7: downloader (ข้อ 3c). Downloads a new CGD report and appends a
lineage entry to raw/manifest.json (append-only). Only file that writes
to raw/. OCSC has no automated path -- download_ocsc() just refuses."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

import detect

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "raw" / "manifest.json"

CGD_BASE_URL = "https://www.cgd.go.th"

# CGD's report links are javascript:openDownload('NewsStat_C', id,
# '/cs/Satellite?...') calls, not plain hrefs (found in Step 6) -- the real
# download path is the 3rd string argument.
OPEN_DOWNLOAD_RE = re.compile(r"openDownload\('([^']*)','([^']*)','([^']*)'\)")


def extract_download_url(href: str) -> str | None:
    """Pull the real URL out of a javascript:openDownload(...) href.
    Returns None if the href doesn't match the expected shape.
    """
    match = OPEN_DOWNLOAD_RE.search(href)
    if match is None:
        return None
    return urljoin(CGD_BASE_URL, match.group(3))


def hash_exists_in_manifest(sha256_hex: str, manifest: dict) -> bool:
    return any(entry.get("sha256") == sha256_hex for entry in manifest["files"])


def build_manifest_entry(
    report: detect.CgdReport, file_bytes: bytes, template_entry: dict
) -> dict:
    """Build a new manifest entry; template_entry supplies source_name_th/
    source_url so those aren't hardcoded again."""
    filename = report.report_date.strftime("%Y_%m_%d") + ".xlsx"
    return {
        "source": "CGD",
        "source_name_th": template_entry["source_name_th"],
        "source_url": template_entry["source_url"],
        "local_path": f"raw/cgd/{filename}",
        "report_date": report.report_date.isoformat(),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "downloaded_by": "auto",
    }


def process_download(
    report: detect.CgdReport, file_bytes: bytes, manifest: dict, template_entry: dict
) -> dict | None:
    """Pure, no I/O: return the entry to append, or None if a hash duplicate."""
    sha256_hex = hashlib.sha256(file_bytes).hexdigest()
    if hash_exists_in_manifest(sha256_hex, manifest):
        return None
    return build_manifest_entry(report, file_bytes, template_entry)


def append_manifest_entry(new_entry: dict) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["files"].append(new_entry)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def download_cgd() -> str:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cgd_entries = [e for e in manifest["files"] if e["source"] == "CGD"]
    if not cgd_entries:
        return (
            "CGD: no existing manifest entry to use as a template for source_name_th/"
            "source_url — add the first CGD entry manually before automating downloads"
        )
    template_entry = max(cgd_entries, key=lambda e: e["report_date"])

    try:
        html = detect.fetch_html(detect.CGD_URL)
    except requests.exceptions.RequestException as e:
        return f"CGD: could not fetch listing page ({type(e).__name__}: {e})"

    latest = detect.find_latest_cgd_report(html)
    if latest is None:
        return (
            "CGD: page fetched but no report rows found — the listing page's structure "
            "may have changed, check manually before assuming there's nothing new"
        )

    known_date = detect.latest_cgd_date_from_manifest(manifest)
    if known_date is not None and latest.report_date <= known_date:
        return (
            f"CGD: nothing new to download (latest on site is "
            f"{latest.report_date.isoformat()}, already have it)"
        )

    download_url = extract_download_url(latest.download_href)
    if download_url is None:
        return (
            f"CGD: found a new report ({latest.title}) but could not extract a download "
            f"URL from its link ({latest.download_href!r}) — the page's download "
            "mechanism may have changed"
        )

    try:
        resp = requests.get(download_url, headers=detect.HEADERS, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return f"CGD: found a new report but the download failed ({type(e).__name__}: {e})"

    file_bytes = resp.content
    new_entry = process_download(latest, file_bytes, manifest, template_entry)
    if new_entry is None:
        sha256_hex = hashlib.sha256(file_bytes).hexdigest()
        return (
            f"CGD: downloaded content but its sha256 ({sha256_hex[:12]}...) already "
            "exists in raw/manifest.json — skipping (not saved to disk, not re-added "
            "to the manifest); likely the same file republished under a new date"
        )

    local_path = REPO_ROOT / new_entry["local_path"]
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(file_bytes)
    append_manifest_entry(new_entry)

    return (
        f"CGD: downloaded new file -> {new_entry['local_path']} "
        f"(report_date={new_entry['report_date']}, sha256={new_entry['sha256'][:12]}...)"
    )


def download_ocsc() -> str:
    return (
        "OCSC: no automated download path exists. The listing page cannot be reliably "
        "scraped (see detect.py's docstring and HANDOFF.md's OCSC findings — sometimes "
        "Cloudflare-challenged, and even when not, the report list is JS-rendered, not "
        f"in the static HTML). Download the current yearbook manually from "
        f"{detect.OCSC_URL} if a new one has been published (OCSC updates once a year)."
    )


def main() -> None:
    print(download_cgd())
    print(download_ocsc())


if __name__ == "__main__":
    main()

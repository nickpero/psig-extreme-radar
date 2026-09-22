"""Lightweight SEC catalyst monitor for PSIG."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import requests

SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK0001997201.json"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/1997201/"
HEADERS = {
    "User-Agent": "PSIG-Extreme-Radar/2.0 contact=github-actions",
    "Accept-Encoding": "gzip, deflate",
}


def _classify(form: str, primary: str) -> str:
    text = f"{form} {primary}".lower()
    if form in {"F-3", "F-1", "424B3", "424B4", "S-8"} or any(
        x in text for x in ("offering", "registration", "securities")
    ):
        return "FINANCING"
    if form in {"6-K", "20-F"}:
        return "SEC_6K"
    if form in {"3", "4", "5", "13D", "13G"}:
        return "OWNERSHIP"
    return form


def recent_filings(max_age_hours: int = 36) -> list[dict]:
    r = requests.get(SEC_SUBMISSIONS, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    out = []
    forms = recent.get("form", [])
    for i, form in enumerate(forms):
        try:
            dt = datetime.fromisoformat(recent["filingDate"][i]).replace(tzinfo=timezone.utc)
        except (IndexError, ValueError):
            continue
        if dt < cutoff:
            continue
        accession = recent["accessionNumber"][i]
        doc = recent.get("primaryDocument", [""] * len(forms))[i]
        desc = recent.get("primaryDocDescription", [""] * len(forms))[i]
        out.append({
            "accession": accession,
            "form": form,
            "filing_date": recent["filingDate"][i],
            "primary_document": doc,
            "description": desc,
            "type": _classify(form, desc),
            "url": f"{SEC_ARCHIVES}{accession.replace('-', '')}/{doc}",
        })
    out.sort(key=lambda x: (x["filing_date"], x["accession"]), reverse=True)
    return out


def latest_catalyst(max_age_hours: int = 36) -> dict | None:
    filings = recent_filings(max_age_hours)
    return filings[0] if filings else None

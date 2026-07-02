#!/usr/bin/env python3
"""Collect likely working-paper links from configured economists' websites.

This is deliberately a generic link scraper. It is useful as an MVP, while the
small functions below make it straightforward to add site-specific rules later.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
import yaml
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ECONOMISTS_FILE = PROJECT_ROOT / "economists.yaml"
DATA_FILE = PROJECT_ROOT / "data" / "papers.json"
# The mirror lets `python -m http.server 8000 -d site` serve /data/papers.json.
SITE_DATA_FILE = PROJECT_ROOT / "site" / "data" / "papers.json"

KEYWORDS = (
    "paper",
    "working paper",
    "pdf",
    "research",
    "draft",
    "nber",
    "cepr",
)
NON_PAPER_KEYWORDS = (
    "curriculum vitae",
    " cv",
    "/cv",
    "cv_",
    "syllabus",
    "teaching",
    "slides",
    "supplement",
    "lecture",
    "seminar",
    "research grants",
    "research opportunities",
    "reading list",
    "published papers",
    "publications & papers",
    "/research/fields/",
)
SECTION_LABELS = {"paper", "papers", "working paper", "working papers", "research", "publications"}
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
DATE_PATTERNS = (
    # ISO-style dates are the least ambiguous.
    re.compile(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b"),
    # Common prose dates, e.g. March 14, 2026.
    re.compile(
        r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2})\b",
        re.IGNORECASE,
    ),
    # A year alone is still useful metadata when pages omit a full date.
    re.compile(r"\b(20\d{2})\b"),
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def load_yaml(path: Path) -> list[dict[str, Any]]:
    """Load and minimally validate the economist configuration."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a YAML list")

    valid_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(data, start=1):
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("papers_url"):
            LOGGER.warning("Skipping invalid economist entry %s", index)
            continue
        valid_entries.append(entry)
    return valid_entries


def load_existing_papers(path: Path) -> list[dict[str, Any]]:
    """Return existing records, or an empty list if the data file is unusable."""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("top-level JSON value is not a list")
        return [item for item in data if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        LOGGER.error("Could not read %s (%s); starting with no old records", path, exc)
        return []


def canonicalize_url(url: str) -> str:
    """Remove fragments and common tracking parameters for stable matching."""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    """Create a conservative title key for duplicate detection."""
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def clean_title(raw_text: str, url: str) -> str:
    """Clean link text and fall back to a readable PDF/file name."""
    title = " ".join(raw_text.split())
    if not title or title.casefold() in {"pdf", "paper", "draft", "download", "link"}:
        filename = Path(urlsplit(url).path).stem
        title = re.sub(r"[-_]+", " ", filename)
    return title.strip(" -–—|:")


def detect_date(context: str) -> str | None:
    """Find a displayed date near a link without guessing missing components."""
    for pattern in DATE_PATTERNS:
        match = pattern.search(context)
        if match:
            return match.group(1)
    return None


def is_likely_paper(link_text: str, href: str, context: str) -> bool:
    """Apply the keyword heuristic without inheriting site-navigation text.

    The surrounding context is intentionally not searched: on many sites an
    `<a>` sits inside a very large container whose text contains "research",
    causing every navigation link to look like a paper.
    """
    del context  # Kept in the signature so site-specific rules can use it later.
    haystack = " ".join((link_text, href)).casefold()
    if any(keyword in haystack for keyword in NON_PAPER_KEYWORDS):
        return False
    if normalize_title(link_text) in SECTION_LABELS:
        return False
    # "research" is unusually common in navigation URLs, so require it in
    # visible link text. The other, more specific signals may occur in either.
    specific_keywords = (keyword for keyword in KEYWORDS if keyword != "research")
    return "research" in link_text.casefold() or any(
        keyword in haystack for keyword in specific_keywords
    )


def scrape_economist(
    economist: dict[str, Any], session: requests.Session, first_seen: str
) -> list[dict[str, Any]]:
    """Fetch one page and turn matching links into paper records."""
    source_page = str(economist["papers_url"])
    response = session.get(source_page, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    records: list[dict[str, Any]] = []
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", "")).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue

        absolute_url = urljoin(response.url, href)
        if urlsplit(absolute_url).scheme not in {"http", "https"}:
            continue

        link_text = link.get_text(" ", strip=True)
        # Parent text helps catch a PDF link beside a paper title/date.
        context = link.parent.get_text(" ", strip=True) if link.parent else link_text
        if not is_likely_paper(link_text, absolute_url, context):
            continue

        title = clean_title(link_text, absolute_url)
        if not title:
            continue
        records.append(
            {
                "economist": economist["name"],
                "title": title,
                "url": canonicalize_url(absolute_url),
                "source_page": canonicalize_url(source_page),
                "detected_date": detect_date(context),
                "first_seen": first_seen,
            }
        )
    return records


def merge_papers(
    existing: list[dict[str, Any]], discovered: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge records while preserving the earliest known first_seen date.

    URLs are matched globally. Normalized titles are matched within an
    economist, which avoids merging different authors' papers called, say,
    "Trade and Growth".
    """
    merged: list[dict[str, Any]] = []
    url_index: dict[str, int] = {}
    title_index: dict[tuple[str, str], int] = {}

    for paper in [*existing, *discovered]:
        if not paper.get("url") or not paper.get("title"):
            continue
        candidate = dict(paper)
        candidate["url"] = canonicalize_url(str(candidate["url"]))
        title_key = (
            str(candidate.get("economist", "")).casefold(),
            normalize_title(str(candidate["title"])),
        )
        match_index = url_index.get(candidate["url"])
        if match_index is None:
            match_index = title_index.get(title_key)

        if match_index is None:
            match_index = len(merged)
            merged.append(candidate)
        else:
            old = merged[match_index]
            old_first_seen = old.get("first_seen")
            new_first_seen = candidate.get("first_seen")
            # Fresh metadata may improve, but first_seen must never move later.
            merged[match_index] = {**old, **candidate}
            if old_first_seen and new_first_seen:
                merged[match_index]["first_seen"] = min(old_first_seen, new_first_seen)
            elif old_first_seen:
                merged[match_index]["first_seen"] = old_first_seen

        url_index[candidate["url"]] = match_index
        title_index[title_key] = match_index

    return sorted(
        merged,
        key=lambda paper: (paper.get("first_seen", ""), paper.get("title", "").casefold()),
        reverse=True,
    )


def write_json(papers: list[dict[str, Any]], path: Path) -> None:
    """Write deterministic, human-readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(papers, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    """Run every configured scraper, continuing after individual failures."""
    try:
        economists = load_yaml(ECONOMISTS_FILE)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        LOGGER.error("Could not load configuration: %s", exc)
        return 1

    existing = load_existing_papers(DATA_FILE)
    discovered: list[dict[str, Any]] = []
    today = date.today().isoformat()

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "trade-research-tracker/0.1 (+static academic paper index)"}
    )

    for economist in economists:
        try:
            papers = scrape_economist(economist, session, today)
            discovered.extend(papers)
            LOGGER.info("%s: found %s candidate links", economist["name"], len(papers))
        except requests.RequestException as exc:
            LOGGER.error("%s: failed to fetch %s (%s)", economist["name"], economist["papers_url"], exc)
        except Exception:
            # A malformed site must not prevent other economists from updating.
            LOGGER.exception("%s: unexpected parsing failure", economist["name"])

    merged = merge_papers(existing, discovered)
    write_json(merged, DATA_FILE)
    SITE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA_FILE, SITE_DATA_FILE)
    LOGGER.info("Wrote %s papers to %s", len(merged), DATA_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())

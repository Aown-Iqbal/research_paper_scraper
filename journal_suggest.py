"""
Journal Suggester
=================
Quickly suggests the best-fit journal for a given topic by querying OpenAlex
and ranking journals by publication frequency and citation count.

Usage:
    python journal_suggest.py --topic "polyphenols fermented beverages"
    python journal_suggest.py --topic "fish quality preservation" --type review
    python journal_suggest.py --topic "probiotics dairy" --top 10
"""

import json
import time
import random
import argparse
from collections import Counter

import requests

from paper_fetcher import _load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

OPENALEX_BASE  = "https://api.openalex.org"
OPENALEX_EMAIL = "research@example.com"
CACHE_FILE     = "journal_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def sleep():
    time.sleep(random.uniform(2.0, 5.0))


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── Journal suggestion ────────────────────────────────────────────────────────

def suggest_journal(topic: str, article_type: str = "review") -> str:
    """
    Query OpenAlex for papers matching the topic, count journal frequencies,
    and return the most common journal as the suggested target.
    """
    print(f"\n[Suggest] Searching for top journal for '{topic}' ({article_type})...")

    journal_counts = Counter()
    journal_citations = Counter()
    seen_ids = set()
    page = 1
    fetched = 0
    target = 500

    while fetched < target:
        params = {
            "search":   topic,
            "filter":   f"publication_year:2023-2026,type:{article_type}",
            "per-page": 50,
            "page":     page,
            "mailto":   OPENALEX_EMAIL,
            "select":   "id,primary_location,cited_by_count",
        }

        try:
            resp = requests.get(f"{OPENALEX_BASE}/works", params=params,
                                headers=HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [!] Request failed: {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        for item in results:
            oa_id = item.get("id", "")
            if oa_id in seen_ids:
                continue
            seen_ids.add(oa_id)

            primary_loc = item.get("primary_location") or {}
            source = primary_loc.get("source") or {}
            journal = source.get("display_name", "")

            if journal:
                journal_counts[journal] += 1
                journal_citations[journal] += item.get("cited_by_count", 0)

            fetched += 1
            if fetched >= target:
                break

        print(f"  Page {page}: collected {fetched} papers | {len(journal_counts)} unique journals")
        page += 1
        sleep()

    if not journal_counts:
        raise RuntimeError(f"No journals found for topic '{topic}'")

    # Filter out journals with fewer than 3 appearances
    qualified = {j: c for j, c in journal_counts.items() if c >= 3}
    if not qualified:
        qualified = dict(journal_counts)

    # Sort by count descending, then by total citations for ties
    sorted_journals = sorted(qualified.items(),
                             key=lambda x: (x[1], journal_citations.get(x[0], 0)),
                             reverse=True)

    return sorted_journals[0][0]


def suggest_top_journals(topic: str, article_type: str = "review", top_n: int = 5) -> list[tuple[str, int]]:
    """Like suggest_journal but returns the top N journals with their counts."""
    print(f"\n[Suggest] Searching for top journals for '{topic}' ({article_type})...")

    journal_counts = Counter()
    journal_citations = Counter()
    seen_ids = set()
    page = 1
    fetched = 0
    target = 500

    while fetched < target:
        params = {
            "search":   topic,
            "filter":   f"publication_year:2023-2026,type:{article_type}",
            "per-page": 50,
            "page":     page,
            "mailto":   OPENALEX_EMAIL,
            "select":   "id,primary_location,cited_by_count",
        }

        try:
            resp = requests.get(f"{OPENALEX_BASE}/works", params=params,
                                headers=HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [!] Request failed: {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        for item in results:
            oa_id = item.get("id", "")
            if oa_id in seen_ids:
                continue
            seen_ids.add(oa_id)

            primary_loc = item.get("primary_location") or {}
            source = primary_loc.get("source") or {}
            journal = source.get("display_name", "")

            if journal:
                journal_counts[journal] += 1
                journal_citations[journal] += item.get("cited_by_count", 0)

            fetched += 1
            if fetched >= target:
                break

        print(f"  Page {page}: collected {fetched} papers | {len(journal_counts)} unique journals")
        page += 1
        sleep()

    if not journal_counts:
        raise RuntimeError(f"No journals found for topic '{topic}'")

    qualified = {j: c for j, c in journal_counts.items() if c >= 3}
    if not qualified:
        qualified = dict(journal_counts)

    sorted_journals = sorted(qualified.items(),
                             key=lambda x: (x[1], journal_citations.get(x[0], 0)),
                             reverse=True)

    return sorted_journals[:top_n]


# ── CLI ───────────────────────────────────────────────────────────────────────

import os

if __name__ == "__main__":
    _load_dotenv()

    parser = argparse.ArgumentParser(
        description="Journal Suggester — find the best-fit journal for a topic via OpenAlex"
    )
    parser.add_argument("--topic", required=True,
                        help="Topic to suggest journals for")
    parser.add_argument("--type", default="review", dest="article_type",
                        help="Article type hint (default: review)")
    parser.add_argument("--top", type=int, default=5,
                        help="Show top N journals (default: 5)")
    args = parser.parse_args()

    top = suggest_top_journals(args.topic, args.article_type, args.top)

    print(f"\n[Suggest] Top {len(top)} journals:")
    for j, c in top:
        print(f"  {c:3d} papers — {j}")

    print(f"\n[Suggest] Selected: {top[0][0]}")

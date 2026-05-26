"""
Journal Profiler
================
Infers a journal's style requirements by analyzing its recent published papers
via OpenAlex. Downloads PDFs to measure word counts. Maintains a persistent
cache so each journal is only analyzed once.

For suggesting a journal from a topic, use journal_suggest.py instead.

Usage:
    python journal_analyzer.py --journal "Food Chemistry"
    python journal_analyzer.py --journal "LWT" --force
"""

import os
import re
import json
import time
import random
import shutil
import tempfile
import argparse
from datetime import datetime, timezone
from collections import Counter

import pypdf
import requests

from paper_fetcher import (
    _load_dotenv,
    download_direct,
    download_elsevier,
    download_scihub,
    get_working_domain,
    sanitize,
)

# ── Config ────────────────────────────────────────────────────────────────────

OPENALEX_BASE   = "https://api.openalex.org"
OPENALEX_EMAIL  = "research@example.com"
CACHE_FILE      = "journal_cache.json"
PDF_SAMPLE_SIZE = 25  # how many full-text PDFs to download for word-count analysis

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def sleep():
    time.sleep(random.uniform(2.0, 5.0))


def reconstruct_abstract(inverted_index: dict) -> str | None:
    if not inverted_index:
        return None
    try:
        max_pos = max(p for positions in inverted_index.values() for p in positions)
        words = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for p in positions:
                words[p] = word
        return " ".join(w for w in words if w)
    except Exception:
        return None


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


# ── Stopwords for keyword extraction ──────────────────────────────────────────

STOPWORDS = set([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "you",
    "your", "we", "our", "their", "its", "it", "this", "that", "these",
    "those", "not", "no", "nor", "so", "if", "than", "then", "also",
    "very", "too", "just", "about", "into", "over", "after", "before",
    "between", "under", "above", "such", "each", "all", "both", "few",
    "more", "most", "other", "some", "only", "which", "who", "whom",
    "what", "when", "where", "how", "up", "down", "out", "off", "new",
    "using", "during", "through", "based", "due", "well", "however",
    "therefore", "thus", "while", "although", "because", "since",
    "among", "within", "without", "along", "toward", "towards",
    "found", "study", "effect", "effects", "results", "analysis",
    "data", "research", "used", "two", "one", "three", "first",
    "different", "high", "low", "et", "al",
])

# ── Word count extraction (Semantic Scholar + Unpaywall) ─────────────────────

def _fetch_semantic_abstract(doi: str) -> str | None:
    """Fetch full abstract from Semantic Scholar API (free, no key needed)."""
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("abstract")
    except Exception:
        return None


def _extract_word_counts(source_id: str, elsevier_api_key: str | None = None) -> tuple[list[int], list[int]]:
    """
    Fetch papers from 2019-2024 for this journal, then:
    1. Use Semantic Scholar API to get full abstracts (not truncated like OpenAlex).
    2. Use the paper_fetcher pipeline for PDFs. Non-Elsevier DOIs are tried
       oldest-first (better Sci-Hub coverage for older papers); Elsevier DOIs
       use the API which works regardless of year.
    Returns (abstract_word_counts, fulltext_word_counts).
    """
    print(f"\n  [3/4] Extracting word counts...")

    # Fetch candidate DOIs — two passes: recent (for Elsevier API) then older
    # (for Sci-Hub, which has better coverage for papers a few years old)
    candidate_papers = []
    year_ranges = ["2022-2024", "2019-2021"]
    min_candidates = PDF_SAMPLE_SIZE * 4  # 100 — plenty to pick from

    for yr in year_ranges:
        if len(candidate_papers) >= min_candidates:
            break
        page = 1
        while len(candidate_papers) < min_candidates:
            params = {
                "filter":   f"primary_location.source.id:{source_id},"
                            f"publication_year:{yr}",
                "sort":     "publication_date:desc",
                "per-page": 50,
                "page":     page,
                "mailto":   OPENALEX_EMAIL,
                "select":   "id,doi,best_oa_location",
            }
            try:
                resp = requests.get(f"{OPENALEX_BASE}/works", params=params,
                                    headers=HEADERS, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [!] OpenAlex fetch failed: {e}")
                break
            results = data.get("results", [])
            if not results:
                break
            for item in results:
                doi = (item.get("doi") or "").replace("https://doi.org/", "").strip()
                if doi and not any(p["doi"] == doi for p in candidate_papers):
                    best_oa = item.get("best_oa_location") or {}
                    candidate_papers.append({
                        "doi":         doi,
                        "oa_pdf_url":  best_oa.get("pdf_url"),
                    })
            page += 1
            sleep()

    print(f"  Fetched {len(candidate_papers)} candidate DOIs")

    # Pass 1: Semantic Scholar for full abstracts
    print(f"  [Semantic Scholar] Fetching full abstracts...")
    abstract_word_counts = []
    s2_misses = 0
    for i, p in enumerate(candidate_papers):
        ab = _fetch_semantic_abstract(p["doi"])
        if ab:
            abstract_word_counts.append(len(ab.split()))
            s2_misses = 0
        else:
            s2_misses += 1
            # Fast-fail: if first 5 all miss, S2 doesn't cover this journal
            if s2_misses == 5 and len(abstract_word_counts) == 0:
                print(f"    S2 has no coverage for this journal — skipping remaining lookups")
                break
        if (i + 1) % 10 == 0 or i == len(candidate_papers) - 1:
            print(f"    {i+1}/{len(candidate_papers)} — {len(abstract_word_counts)} abstracts collected "
                  f"(avg {sum(abstract_word_counts)//len(abstract_word_counts) if abstract_word_counts else 0} words)")
        sleep()

    # Pass 2: paper_fetcher download pipeline for full-text word counts
    print(f"  [PDFs] Downloading full-text via paper_fetcher pipeline...")
    scihub_domain = get_working_domain()
    fulltext_word_counts = []
    tmpdir = tempfile.mkdtemp(prefix="journal_pdfs_")
    downloaded = 0

    # Sort: Elsevier first (API works for any year), then non-Elsevier oldest-first
    # (Sci-Hub coverage is better for older papers)
    elsevier_candidates = [p for p in candidate_papers if p["doi"].startswith("10.1016/")]
    non_elsevier_candidates = [p for p in candidate_papers if not p["doi"].startswith("10.1016/")]
    # Non-Elsevier: reverse so oldest are tried first — much better Sci-Hub hit rate
    non_elsevier_candidates.reverse()

    ordered_papers = elsevier_candidates + non_elsevier_candidates
    n_elsevier = len(elsevier_candidates)
    n_non_elsevier = len(non_elsevier_candidates)
    print(f"  Candidates: {n_elsevier} Elsevier (API) + {n_non_elsevier} non-Elsevier (Sci-Hub, oldest-first)")

    for p in ordered_papers:
        if downloaded >= PDF_SAMPLE_SIZE:
            break

        doi = p["doi"]
        out_path = os.path.join(tmpdir, sanitize(doi))
        success = False

        # Elsevier API
        if elsevier_api_key and doi.startswith("10.1016/"):
            success = download_elsevier(doi, elsevier_api_key, out_path)

        # Sci-Hub
        if not success and scihub_domain:
            sleep()
            success = download_scihub(doi, scihub_domain, out_path)

        # OA direct
        if not success and p.get("oa_pdf_url"):
            success = download_direct(p["oa_pdf_url"], out_path)

        if success:
            try:
                reader = pypdf.PdfReader(out_path)
                text = ""
                for pg in reader.pages:
                    extracted = pg.extract_text()
                    if extracted:
                        text += extracted + "\n"
                if text.strip():
                    fulltext_word_counts.append(len(text.split()))
                    downloaded += 1
                    print(f"    [{downloaded}/{PDF_SAMPLE_SIZE}] {doi} "
                          f"— {fulltext_word_counts[-1]:,} words")
            except Exception:
                pass

        sleep()

    # Clean up temp PDFs
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError:
        pass

    print(f"  Abstracts: {len(abstract_word_counts)} | "
          f"Full-text PDFs: {len(fulltext_word_counts)}")
    return abstract_word_counts, fulltext_word_counts


# ── Journal profile analysis ──────────────────────────────────────────────────

def get_journal_profile(journal_name: str, elsevier_api_key: str | None = None) -> dict:
    """
    Get a journal's style profile. Checks cache first, then fetches and analyzes
    50 recent papers from OpenAlex.
    """
    cache = load_cache()
    key = journal_name.lower()

    if key in cache:
        entry = cache[key]
        print(f"[Cache] Loaded profile for '{journal_name}' "
              f"(analyzed {entry.get('analyzed_at', 'unknown')})")
        return entry

    print(f"\n[Analyze] Building profile for '{journal_name}'...")

    # Step 1: Look up journal on OpenAlex /sources
    print(f"  [1/4] Looking up journal on OpenAlex...")
    source_params = {
        "filter": f"display_name.search:{journal_name}",
        "per-page": 10,
        "mailto": OPENALEX_EMAIL,
    }

    try:
        resp = requests.get(f"{OPENALEX_BASE}/sources", params=source_params,
                            headers=HEADERS, timeout=20)
        resp.raise_for_status()
        sources_data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Failed to look up journal '{journal_name}': {e}")

    sources = sources_data.get("results", [])
    if not sources:
        raise RuntimeError(f"Journal '{journal_name}' not found on OpenAlex")

    def _normalize(s):
        return (s or "").lower().replace("&", "and").replace("  ", " ").strip()

    # Best match: normalized name match preferred, otherwise first result
    target = _normalize(journal_name)
    source = None
    for s in sources:
        if _normalize(s.get("display_name", "")) == target:
            source = s
            break
    if source is None:
        # Fuzzy fallback: target words must be a subset AND source can't have
        # many extra words (prevents "Food Science" matching "Agricultural Food Science")
        target_words = set(target.split())
        for s in sources:
            s_words = set(_normalize(s.get("display_name", "")).split())
            if not target_words.issubset(s_words) or len(target_words) < 3:
                continue
            # At least 90% of source words must be in target
            overlap = len(target_words & s_words) / len(s_words)
            if overlap >= 0.90:
                source = s
                break
    if source is None:
        source = sources[0]
        print(f"  [!] Warning: no close match found; using '{source.get('display_name')}'")

    source_id = source.get("id", "")
    homepage = source.get("homepage_url", "")
    publisher = source.get("host_organization_name", "")
    issn_l = source.get("issn_l", "")

    print(f"  Found: {source.get('display_name')} (ID: {source_id})")

    # Step 2: Fetch 50 most recent papers
    print(f"  [2/4] Fetching 50 most recent papers...")

    papers = []
    page = 1

    while len(papers) < 50:
        params = {
            "filter":   f"primary_location.source.id:{source_id}",
            "sort":     "publication_date:desc",
            "per-page": 50,
            "page":     page,
            "mailto":   OPENALEX_EMAIL,
            "select":   "id,doi,title,publication_year,primary_location,"
                        "authorships,abstract_inverted_index,type,cited_by_count,"
                        "best_oa_location",
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
            if len(papers) >= 50:
                break

            primary_loc = item.get("primary_location") or {}
            authorships = item.get("authorships") or []
            best_oa = item.get("best_oa_location") or {}

            papers.append({
                "id":               item.get("id", ""),
                "doi":              (item.get("doi") or "").replace("https://doi.org/", "").strip(),
                "title":            item.get("title") or "",
                "year":             item.get("publication_year"),
                "abstract":         reconstruct_abstract(item.get("abstract_inverted_index") or {}),
                "article_type":     item.get("type", ""),
                "author_count":     len(authorships),
                "primary_location": primary_loc,
                "cited_by_count":   item.get("cited_by_count", 0),
                "oa_pdf_url":       best_oa.get("pdf_url"),
            })

        print(f"  Page {page}: {len(results)} results | collected: {len(papers)}")

        if len(results) < 50:
            break

        page += 1
        sleep()

    print(f"  Collected {len(papers)} papers")

    # Step 3: Extract real word counts (CrossRef abstracts + Unpaywall full-text)
    abstract_word_counts, fulltext_word_counts = _extract_word_counts(source_id, elsevier_api_key)

    # Step 4: Analyze
    print(f"  [4/4] Analyzing...")

    profile = _analyze_papers(papers, journal_name, source_id, homepage,
                               publisher, issn_l,
                               abstract_word_counts=abstract_word_counts,
                               fulltext_word_counts=fulltext_word_counts)

    # Save to cache
    cache[key] = profile
    save_cache(cache)
    print(f"  [Cache] Saved profile for '{journal_name}'")

    return profile


def _analyze_papers(papers: list[dict], journal_name: str, source_id: str,
                    homepage: str, publisher: str, issn_l: str,
                    abstract_word_counts: list[int] | None = None,
                    fulltext_word_counts: list[int] | None = None) -> dict:
    """Run inference logic on collected papers."""

    # Article types
    type_counts = Counter(p.get("article_type", "unknown") for p in papers)
    article_types = dict(type_counts)

    # Average abstract length — prefer PDF-extracted counts, fall back to API
    if abstract_word_counts:
        avg_abstract_length = sum(abstract_word_counts) / len(abstract_word_counts)
    else:
        abstract_lengths = []
        for p in papers:
            ab = p.get("abstract")
            if ab:
                abstract_lengths.append(len(ab.split()))
        avg_abstract_length = (sum(abstract_lengths) / len(abstract_lengths)
                               if abstract_lengths else 0)

    # Longest full-text word count from PDFs — better estimate of the journal's
    # upper limit than the mean (which gets dragged down by short communications)
    max_paper_length = None
    if fulltext_word_counts:
        max_paper_length = max(fulltext_word_counts)

    # Average author count
    author_counts = [p.get("author_count", 0) for p in papers]
    typical_author_count = (sum(author_counts) / len(author_counts)
                            if author_counts else 0)

    # Reference style detection
    reference_style = _detect_reference_style(papers, publisher)

    # Elsevier heuristics for highlights / graphical abstract
    publisher_lower = (publisher or "").lower()
    has_sciencedirect = any(
        "sciencedirect" in str(p.get("primary_location") or {}).lower()
        for p in papers
    )
    is_elsevier = "elsevier" in publisher_lower
    has_highlights = is_elsevier or has_sciencedirect
    has_graphical_abstract = is_elsevier or has_sciencedirect

    # Common sections based on article type distribution
    common_sections = _infer_sections(type_counts)

    # Top keywords from titles
    top_keywords = _extract_keywords(papers)

    return {
        "journal_name":          journal_name,
        "openalex_id":           source_id,
        "homepage_url":          homepage,
        "publisher":             publisher,
        "issn_l":                issn_l,
        "papers_analyzed":       len(papers),
        "pdfs_extracted":        len(fulltext_word_counts) if fulltext_word_counts else 0,
        "article_types":         article_types,
        "avg_abstract_length":   round(avg_abstract_length, 1),
        "max_paper_length":      max_paper_length,
        "typical_author_count":  round(typical_author_count, 1),
        "has_highlights":        has_highlights,
        "has_graphical_abstract": has_graphical_abstract,
        "reference_style":       reference_style,
        "common_sections":       common_sections,
        "top_keywords":          top_keywords,
        "analyzed_at":           datetime.now(timezone.utc).isoformat(),
    }


def _detect_reference_style(papers: list[dict], publisher: str) -> str:
    """Detect reference style: 'numeric' or 'author-date'."""
    author_date_pattern = re.compile(
        r'\([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?,?\s*\d{4}[a-z]?\)'
    )
    numeric_pattern = re.compile(r'\[\d+(?:[,-]\d+)*\]')

    author_date_count = 0
    numeric_count = 0

    for p in papers:
        abstract = p.get("abstract") or ""
        title = p.get("title") or ""
        text = title + " " + abstract

        if author_date_pattern.search(text):
            author_date_count += 1
        if numeric_pattern.search(text):
            numeric_count += 1

    if numeric_count > author_date_count:
        return "numeric"
    elif author_date_count > numeric_count:
        return "author-date"
    else:
        publisher_lower = (publisher or "").lower()
        if "elsevier" in publisher_lower:
            return "numeric"
        return "numeric"


def _infer_sections(type_counts: dict) -> list[str]:
    """Infer expected sections based on article type distribution."""
    review_count = type_counts.get("review", 0)
    article_count = (type_counts.get("journal-article", 0) +
                     type_counts.get("article", 0))

    if review_count > article_count:
        return ["Introduction", "Body Sections", "Conclusion"]
    else:
        return ["Introduction", "Materials and Methods", "Results",
                "Discussion", "Conclusion"]


def _extract_keywords(papers: list[dict]) -> list[str]:
    """Extract top keywords from paper titles."""
    word_counter = Counter()

    for p in papers:
        title = p.get("title") or ""
        words = re.findall(r'[a-z]+', title.lower())
        for w in words:
            if len(w) > 2 and w not in STOPWORDS:
                word_counter[w] += 1

    return [word for word, _ in word_counter.most_common(20)]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _load_dotenv()

    parser = argparse.ArgumentParser(
        description="Journal Profiler — infer journal style requirements from OpenAlex"
    )
    parser.add_argument("--journal", required=True,
                        help="Journal name to analyze")
    parser.add_argument("--force", action="store_true",
                        help="Force re-analysis even if cached")
    parser.add_argument("--output", default=None,
                        help="Save profile to JSON file")
    parser.add_argument("--elsevier-key", default=os.environ.get("ELSEVIER_API_KEY"),
                        help="Elsevier API key (or set ELSEVIER_API_KEY in .env)")
    args = parser.parse_args()

    # Handle --force: delete cached entry before analysis
    if args.force:
        cache = load_cache()
        key = args.journal.lower()
        if key in cache:
            del cache[key]
            save_cache(cache)
            print(f"[Force] Removed cached entry for '{args.journal}'")

    profile = get_journal_profile(args.journal, args.elsevier_key)

    # Pretty print
    print(f"\n{'='*60}")
    print(f"Journal Profile: {profile['journal_name']}")
    print(f"{'='*60}")
    print(f"  Publisher:              {profile['publisher']}")
    print(f"  ISSN-L:                 {profile['issn_l']}")
    print(f"  Papers analyzed:        {profile['papers_analyzed']}")
    print(f"  PDFs extracted:         {profile['pdfs_extracted']}")
    print(f"  Avg abstract length:    {profile['avg_abstract_length']} words")
    if profile.get('max_paper_length'):
        print(f"  Max paper length:       {profile['max_paper_length']:,} words")
    print(f"  Typical author count:   {profile['typical_author_count']}")
    print(f"  Reference style:        {profile['reference_style']}")
    print(f"  Has highlights:         {profile['has_highlights']}")
    print(f"  Has graphical abstract: {profile['has_graphical_abstract']}")
    print(f"  Common sections:        {', '.join(profile['common_sections'])}")
    print(f"  Article types:          {profile['article_types']}")
    print(f"  Top keywords:           {', '.join(profile['top_keywords'][:10])}")
    print(f"  Analyzed at:            {profile['analyzed_at']}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] Profile saved -> {args.output}")

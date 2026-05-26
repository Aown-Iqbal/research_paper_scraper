"""
Paper Fetcher Pipeline
======================
Stage 1 — OpenAlex: discover papers + metadata + abstracts
Stage 2 — Sci-Hub:  download full PDFs (pure requests, no browser needed)

Usage:
    pip install requests

    # Metadata only
    python paper_fetcher.py --query "antioxidant polyphenols fermented foods" --years 2019-2026 --max 100 --no-pdfs

    # Full run with PDF downloads
    python paper_fetcher.py --query "antioxidant polyphenols fermented foods" --years 2019-2026 --max 100

Output:
    papers.json   — metadata for all papers
    pdfs/         — downloaded PDFs named by sanitized DOI
"""

import os
import re
import json
import time
import random
import argparse
from pathlib import Path
from datetime import datetime, timezone

import requests

# ── Config ────────────────────────────────────────────────────────────────────

OPENALEX_BASE  = "https://api.openalex.org/works"
OPENALEX_EMAIL = "research@example.com"

SCIHUB_DOMAINS = [
    "https://sci-hub.red",
    "https://sci-hub.ee",
    "https://sci-hub.st",
]

PDF_DIR     = "./pdfs"
OUTPUT_FILE = "papers.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_dotenv(path: str = ".env"):
    """Load key=value pairs from a .env file into os.environ (no-op if missing)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def sleep():
    time.sleep(random.uniform(2.0, 5.0))


def sanitize(doi: str) -> str:
    return re.sub(r'[^\w\-.]', '_', doi) + ".pdf"


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


# ── Stage 1: OpenAlex ─────────────────────────────────────────────────────────

def fetch_openalex(query: str, year_range: str, max_results: int) -> list[dict]:
    papers   = []
    seen_ids = set()
    page     = 1

    start_year, end_year = year_range.split("-")

    print(f"\n[OpenAlex] '{query}' | {year_range}")

    while len(papers) < max_results:
        params = {
            "search":   query,
            "filter":   f"publication_year:{start_year}-{end_year}",
            "per-page": 100,
            "page":     page,
            "mailto":   OPENALEX_EMAIL,
            "select":   ",".join([
                "id", "doi", "title", "publication_year",   
                "primary_location", "authorships",
                "abstract_inverted_index", "open_access",
                "best_oa_location", "type"
            ])
        }

        try:
            resp = requests.get(OPENALEX_BASE, params=params,
                                headers=HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [!] Request failed: {e}")
            break

        results = data.get("results", [])
        total   = data.get("meta", {}).get("count", 0)

        if page == 1:
            print(f"  Total available : {total:,}")
            print(f"  Fetching up to  : {min(max_results, total)}")

        if not results:
            break

        for item in results:
            if len(papers) >= max_results:
                break

            oa_id = item.get("id", "")
            if oa_id in seen_ids:
                continue
            seen_ids.add(oa_id)

            doi = (item.get("doi") or "").replace("https://doi.org/", "").strip()

            primary_loc = item.get("primary_location") or {}
            source      = primary_loc.get("source") or {}
            journal     = source.get("display_name", "")

            authorships = item.get("authorships") or []
            authors = [
                a.get("author", {}).get("display_name", "")
                for a in authorships
                if a.get("author", {}).get("display_name")
            ]

            oa_info     = item.get("open_access") or {}
            best_oa_loc = item.get("best_oa_location") or {}
            oa_pdf_url  = best_oa_loc.get("pdf_url")

            papers.append({
                "doi":          doi,
                "title":        item.get("title", ""),
                "year":         item.get("publication_year"),
                "journal":      journal,
                "authors":      authors,
                "abstract":     reconstruct_abstract(
                                    item.get("abstract_inverted_index") or {}),
                "article_type": item.get("type", ""),
                "open_access":  oa_info.get("is_oa", False),
                "oa_pdf_url":   oa_pdf_url,
                "pdf_path":     None,
                "fetched_at":   datetime.now(timezone.utc).isoformat(),
            })

        print(f"  Page {page}: {len(results)} results | collected: {len(papers)}")

        if len(results) < 100:
            break

        page += 1
        sleep()

    print(f"[OpenAlex] Done — {len(papers)} papers\n")
    return papers


# ── Stage 2: OA direct download ───────────────────────────────────────────────

def download_direct(url: str, output_path: str) -> bool:
    """Download a PDF directly from an OA URL using requests."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        if resp.status_code != 200:
            return False

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        with open(output_path, "rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            os.remove(output_path)
            return False

        return True

    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


# ── Stage 2b: Unpaywall API ────────────────────────────────────────────────────

def download_unpaywall(doi: str, output_path: str) -> bool:
    """Try Unpaywall API for OA PDF URL, then download directly."""
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email=research@example.com"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return False

        data = resp.json()

        best_loc = data.get("best_oa_location") or {}
        pdf_url = best_loc.get("url_for_pdf")

        if not pdf_url:
            for loc in data.get("oa_locations") or []:
                pdf_url = loc.get("url_for_pdf")
                if pdf_url:
                    break

        if not pdf_url:
            return False

        return download_direct(pdf_url, output_path)

    except Exception:
        return False


# ── Stage 2c: CORE API ─────────────────────────────────────────────────────────

def download_core(doi: str, output_path: str) -> bool:
    """Try CORE API for download URL, then download directly."""
    try:
        url = f"https://api.core.ac.uk/v3/works/doi/{doi}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return False

        data = resp.json()

        pdf_url = data.get("downloadUrl")

        if not pdf_url:
            for link in data.get("links") or []:
                if link.get("type") == "download":
                    pdf_url = link.get("url")
                    if pdf_url:
                        break

        if not pdf_url:
            return False

        return download_direct(pdf_url, output_path)

    except Exception:
        return False


# ── Stage 2d: PMC / E-utilities ────────────────────────────────────────────────

def download_pmc(doi: str, output_path: str) -> bool:
    """Resolve DOI → PMCID via NCBI ID converter, then download from PMC."""
    try:
        conv_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json"
        resp = requests.get(conv_url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return False

        data = resp.json()
        records = data.get("records") or []
        if not records:
            return False

        pmcid = records[0].get("pmcid")
        if not pmcid:
            return False

        pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        return download_direct(pdf_url, output_path)

    except Exception:
        return False


# ── Stage 2e: Elsevier API ────────────────────────────────────────────────────

def download_elsevier(doi: str, api_key: str, output_path: str) -> bool:
    """Download PDF from Elsevier API (only for 10.1016/ DOIs)."""
    try:
        url = f"https://api.elsevier.com/content/article/doi/{doi}"
        headers = {
            **HEADERS,
            "X-ELS-APIKey": api_key,
            "Accept": "application/pdf",
        }
        resp = requests.get(url, headers=headers, timeout=60, stream=True)
        if resp.status_code != 200:
            return False

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        with open(output_path, "rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            os.remove(output_path)
            return False

        return True

    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


# ── Stage 2: Sci-Hub download (pure requests) ────────────────────────────────

_cached_domain: str | None = None


def get_working_domain() -> str | None:
    global _cached_domain
    if _cached_domain:
        return _cached_domain
    for domain in SCIHUB_DOMAINS:
        try:
            r = requests.get(domain, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                _cached_domain = domain
                return domain
        except Exception:
            continue
    return None


def download_scihub(doi: str, domain: str, output_path: str) -> bool:
    """
    Download a PDF from Sci-Hub using pure requests + HTML parsing.
    Fetches the Sci-Hub page, extracts the embedded PDF URL, then downloads it.
    """
    try:
        # Step 1: Fetch the Sci-Hub page
        page_url = f"{domain}/{doi}"
        resp = requests.get(page_url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return False

        html = resp.text

        # Step 2: Extract PDF URL from the HTML
        pdf_url = None

        # Pattern 1: <iframe src="...pdf">
        m = re.search(r'<iframe[^>]+src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)
        if m:
            pdf_url = m.group(1)

        # Pattern 2: <embed src="...pdf">
        if not pdf_url:
            m = re.search(r'<embed[^>]+src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I)
            if m:
                pdf_url = m.group(1)

        # Pattern 3: button onclick="location.href='...pdf'"
        if not pdf_url:
            m = re.search(r"""location\.href\s*=\s*["']([^"']+\.pdf[^"']*)["']""", html, re.I)
            if m:
                pdf_url = m.group(1)

        # Pattern 4: Any link ending in .pdf
        if not pdf_url:
            m = re.search(r"""href\s*=\s*["']([^"']+\.pdf)["']""", html, re.I)
            if m:
                pdf_url = m.group(1)

        if not pdf_url:
            return False

        # Step 3: Make relative URLs absolute
        if pdf_url.startswith("//"):
            pdf_url = "https:" + pdf_url
        elif pdf_url.startswith("/"):
            pdf_url = domain.rstrip("/") + pdf_url
        elif not pdf_url.startswith("http"):
            pdf_url = domain.rstrip("/") + "/" + pdf_url

        # Step 4: Download the PDF
        pdf_resp = requests.get(pdf_url, headers=HEADERS, timeout=60, stream=True)
        if pdf_resp.status_code != 200:
            return False

        with open(output_path, "wb") as f:
            for chunk in pdf_resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # Step 5: Verify it's a real PDF
        with open(output_path, "rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            os.remove(output_path)
            return False

        return True

    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


# ── Main PDF fetcher ──────────────────────────────────────────────────────────

def fetch_pdfs(papers: list[dict], elsevier_api_key: str | None = None) -> list[dict]:
    Path(PDF_DIR).mkdir(exist_ok=True)

    print("[Sci-Hub] Finding working domain...")
    scihub_domain = get_working_domain()
    if scihub_domain:
        print(f"  Using: {scihub_domain}\n")
    else:
        print("  [!] No working Sci-Hub domain found.\n")

    has_doi = [p for p in papers if p.get("doi")]
    no_doi  = [p for p in papers if not p.get("doi")]

    elsevier_count = 0
    scihub_count   = 0
    oa_count       = 0
    failed         = []

    print(f"[PDFs] {len(has_doi)} papers with DOIs | {len(no_doi)} without\n")

    for i, paper in enumerate(has_doi):
        doi      = paper["doi"]
        out_path = os.path.join(PDF_DIR, sanitize(doi))

        print(f"  [{i+1}/{len(has_doi)}] {doi}")

        # Already downloaded
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            print(f"    [OK] Already exists")
            paper["pdf_path"] = out_path
            continue

        success = False

        # Try 1: Elsevier API (only for 10.1016/ DOIs)
        if elsevier_api_key and doi.startswith("10.1016/"):
            print(f"    [->] Elsevier API...")
            success = download_elsevier(doi, elsevier_api_key, out_path)
            if success:
                print(f"    [OK] Elsevier success")
                elsevier_count += 1

        # Try 2: Sci-Hub via pure requests
        if not success and scihub_domain:
            sleep()
            print(f"    [->] Sci-Hub...")
            success = download_scihub(doi, scihub_domain, out_path)
            if success:
                print(f"    [OK] Sci-Hub success")
                scihub_count += 1

        # Try 3: OA direct link via requests
        if not success and paper.get("oa_pdf_url"):
            print(f"    [->] OA direct...")
            success = download_direct(paper["oa_pdf_url"], out_path)
            if success:
                print(f"    [OK] OA direct success")
                oa_count += 1

        if success:
            paper["pdf_path"] = out_path
        else:
            print(f"    [X] Failed")
            failed.append(paper)

        sleep()

    # Summary
    print(f"\n[PDFs] Summary")
    print(f"  Elsevier   : {elsevier_count}")
    print(f"  Sci-Hub    : {scihub_count}")
    print(f"  OA direct  : {oa_count}")
    print(f"  Failed     : {len(failed)}")
    print(f"  No DOI     : {len(no_doi)}")

    if failed:
        print(f"\n[Sci-Net] Request these manually at https://sci-net.xyz")
        for p in failed:
            print(f"  {p['doi']}  |  {(p['title'] or '')[:70]}")

    return papers


# ── Main ──────────────────────────────────────────────────────────────────────

def run(query: str, year_range: str, max_results: int, skip_pdfs: bool, elsevier_api_key: str | None = None):
    papers = fetch_openalex(query, year_range, max_results)

    if not papers:
        print("[!] No papers found.")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    print(f"[OK] Metadata saved -> {OUTPUT_FILE}")

    if skip_pdfs:
        return

    papers = fetch_pdfs(papers, elsevier_api_key)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    print(f"[OK] Updated metadata saved -> {OUTPUT_FILE}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _load_dotenv()

    parser = argparse.ArgumentParser(description="Paper fetcher: OpenAlex + Sci-Hub")
    parser.add_argument("--query",         required=True)
    parser.add_argument("--years",         default="2019-2026")
    parser.add_argument("--max",           type=int, default=100)
    parser.add_argument("--no-pdfs",       action="store_true")
    parser.add_argument("--output",        default="papers.json")
    parser.add_argument("--elsevier-key",  default=os.environ.get("ELSEVIER_API_KEY"),
                        help="Elsevier API key (or set ELSEVIER_API_KEY in .env)")
    args = parser.parse_args()

    OUTPUT_FILE = args.output
    run(args.query, args.years, args.max, args.no_pdfs, args.elsevier_key)
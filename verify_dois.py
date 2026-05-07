"""
DOI Verification Script
========================
Extracts DOIs from a paper draft (JS or JSON reference list or .docx),
cross-references them against collected paper JSONs, and reports any
that are NOT present in the collection.

Usage:
    python verify_dois.py --draft <path-to-draft> --json <path-to-papers-json>

Supports:
    - .js files (extracts DOIs from REFS array or similar)
    - .json files (extracts DOIs from a reference list)
    - Will also work with a directory of JSON files (searches all)
"""

import json
import re
import argparse
import os
from pathlib import Path
from zipfile import ZipFile


def extract_dois_from_js(filepath):
    """Extract DOIs from a JS reference list (d: '10.xxx/...' patterns)."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # Match DOI patterns in JS: d: "10.xxx/..." or d: '10.xxx/...'
    dois = re.findall(r"""d:\s*["'](10\.\d{4,}/[^"']+)["']""", content)
    return dois


def extract_dois_from_docx(filepath):
    """Extract DOIs from a .docx file."""
    dois = []
    with ZipFile(filepath, "r") as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
        # Find all text runs containing DOI
        texts = re.findall(r"<w:t[^>]*>([^<]+)</w:t>", doc_xml)
        for text in texts:
            # Match DOI pattern
            found = re.findall(r"10\.\d{4,}/[^\s]+", text)
            dois.extend(found)
    # Clean trailing punctuation
    dois = [d.rstrip(".,;:") for d in dois]
    return dois


def load_dois_from_json(filepath_or_dir):
    """Load all DOIs from a JSON file or directory of JSON files."""
    all_dois = set()
    paths = []

    if os.path.isdir(filepath_or_dir):
        for f in os.listdir(filepath_or_dir):
            if f.endswith(".json"):
                paths.append(os.path.join(filepath_or_dir, f))
    else:
        paths = [filepath_or_dir]

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Handle both list-of-papers and list-of-values
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        doi = item.get("doi", "").strip().lower()
                        if doi:
                            all_dois.add(doi)
            elif isinstance(data, dict):
                doi = data.get("doi", "").strip().lower()
                if doi:
                    all_dois.add(doi)
        except Exception as e:
            print(f"  [!] Error reading {path}: {e}")

    return all_dois


def main():
    parser = argparse.ArgumentParser(
        description="Verify all DOIs in a draft are present in the collected papers JSON"
    )
    parser.add_argument("--draft", required=True,
                        help="Path to the draft file (.js, .docx, or .json reference list)")
    parser.add_argument("--json", required=True,
                        help="Path to the collected papers JSON (file or directory)")
    args = parser.parse_args()

    # Extract DOIs from draft
    draft_path = args.draft
    ext = Path(draft_path).suffix.lower()

    print(f"[*] Extracting DOIs from: {draft_path}")
    if ext == ".js":
        draft_dois = extract_dois_from_js(draft_path)
    elif ext == ".docx":
        draft_dois = extract_dois_from_docx(draft_path)
    elif ext == ".json":
        with open(draft_path, "r", encoding="utf-8") as f:
            refs = json.load(f)
        draft_dois = [r.get("doi", "") for r in refs if isinstance(r, dict) and r.get("doi")]
    else:
        print(f"[!] Unsupported draft format: {ext}")
        return

    print(f"    Found {len(draft_dois)} DOIs in draft")

    # Load collected DOIs
    print(f"[*] Loading collected DOIs from: {args.json}")
    collected_dois = load_dois_from_json(args.json)
    print(f"    Loaded {len(collected_dois)} unique DOIs from collection")

    # Cross-reference
    missing = []
    present = []
    for doi in draft_dois:
        doi_clean = doi.strip().lower()
        # Try exact match and also normalized (some DOIs have trailing slashes, etc.)
        if doi_clean in collected_dois:
            present.append(doi)
        else:
            # Try matching without trailing slash
            doi_norm = doi_clean.rstrip("/")
            if doi_norm in collected_dois:
                present.append(doi)
            else:
                # Fuzzy: check if any collected DOI contains this one
                found = False
                for cd in collected_dois:
                    if doi_norm in cd or cd in doi_norm:
                        present.append(doi)
                        found = True
                        break
                if not found:
                    missing.append(doi)

    # Report
    print(f"\n{'=' * 60}")
    print(f"RESULTS")
    print(f"{'=' * 60}")
    print(f"  Present in collection:  {len(present)}")
    print(f"  MISSING (NOT in JSON):  {len(missing)}")

    if missing:
        print(f"\n{'-' * 60}")
        print(f"MISSING DOIs — These MUST be removed from the draft:")
        print(f"{'-' * 60}")
        for i, doi in enumerate(missing, 1):
            print(f"  [{i}] {doi}")
        print(f"\n[!] ACTION REQUIRED: Remove these {len(missing)} references")
        print(f"    and adjust all in-text citation numbers accordingly.")
    else:
        print(f"\n[OK] All DOIs verified — every citation is in the collection.")

    return missing


if __name__ == "__main__":
    main()

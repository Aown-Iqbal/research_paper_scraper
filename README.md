# Research Paper Scraper & Generator

A pipeline for collecting research papers via the OpenAlex API and generating formatted .docx manuscripts.

## Quick Start

```bash
# Install dependencies
pip install requests
npm install docx

# Collect papers (metadata + abstracts)
python paper_fetcher.py --query "your search terms" --years 2019-2026 --max 100 --no-pdfs

# Verify citations against collected papers
python verify_dois.py --draft paper/generate.js --json paper/papers.json
```

## Pipeline

### 1. Collect — `paper_fetcher.py`

Searches the [OpenAlex API](https://openalex.org/) for research papers matching your query and year range. Outputs a JSON file with metadata, abstracts, and DOIs.

```bash
# Metadata only (recommended for literature reviews):
python paper_fetcher.py --query "antioxidant polyphenols fermented foods" --years 2019-2026 --max 100 --no-pdfs --output my_papers.json

# With PDF downloads via Sci-Hub:
python paper_fetcher.py --query "antioxidant polyphenols fermented foods" --years 2019-2026 --max 100
```

### 2. Generate — Node.js + `docx`

Write a generation script using the `docx` npm package. See `CLAUDE.md` for the full format spec (fonts, colors, page layout, table styling).

```bash
node paper/generate_paper.js
```

### 3. Verify — `verify_dois.py`

Cross-references every DOI cited in your draft against the collected JSON. Catches slip-in references from training data.

```bash
# Against a .js generation script:
python verify_dois.py --draft paper/generate_paper.js --json paper/papers.json

# Against a .docx file:
python verify_dois.py --draft paper/output.docx --json paper/papers.json
```

## Project Structure

```
paper_1_topic_name/
  papers.json          # collected literature
  generate_paper.js    # docx generation script
  output.docx          # final manuscript

paper_fetcher.py       # OpenAlex API scraper
verify_dois.py         # DOI cross-reference verifier
CLAUDE.md              # full format spec + writing rules
```

## Rules

1. Only cite primary research articles (no reviews)
2. Every fact must come from a collected paper abstract
3. Run DOI verification before finalizing any draft
4. One folder per paper

See `CLAUDE.md` for detailed instructions.

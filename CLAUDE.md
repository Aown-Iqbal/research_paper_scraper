# CLAUDE.md — Research Paper Scraper & Generator

## Project Overview

A pipeline for collecting research papers via the OpenAlex API and generating formatted .docx manuscripts. The workflow: scrape literature → verify sources → write paper → validate output.

## Paper Writing Rules (STRICT — follow in order)

### Rule 1: Only primary research — no review articles

Before citing any paper, check its title and abstract for review indicators. Some examples are as follows:
- Title contains: `review`, `survey`, `overview`, `state of the art`, `bibliometric`, `a guideline`
- Abstract contains: `this review`, `we review`, `this paper reviews`

Only use original research or methods papers that present new experimental results.

### Rule 2: Every fact must come from a collected paper abstract

No assumed facts. No commonly known truths. No training-data knowledge. Every statement must be traceable to a specific paper abstract in the collected JSON. If the abstract doesn't contain the fact, don't state it.

### Rule 3: Mandatory DOI verification before finalizing

Run `verify_dois.py` against every draft before presenting it:
```bash
python verify_dois.py --draft <path-to-draft.js|.docx> --json <path-to-collected-papers.json|dir/>
```
Any DOIs flagged as MISSING must be removed from the draft, with in-text citations renumbered and content adjusted.

### Rule 4: One folder per paper

```
paper_1_topic_name/
  papers_merged.json    # collected literature
  generate_paper.js     # docx generation script
  output.docx           # final manuscript
```

Shared utilities (`paper_fetcher.py`, `verify_dois.py`) live at root.

## Paper Collection

### paper_fetcher.py — OpenAlex API scraper (Stage 1 + 2)

Two-stage pipeline: (1) discover papers + metadata via OpenAlex API, (2) optionally download PDFs via Sci-Hub.

```bash
# Metadata only:
python paper_fetcher.py --query "your search terms" --years 2019-2026 --max 100 --no-pdfs --output topic_papers.json

# With PDF downloads:
python paper_fetcher.py --query "your search terms" --years 2019-2026 --max 100
```

Use `--no-pdfs` for literature searches. PDF downloads use pure `requests` to fetch Sci-Hub pages, extract the embedded PDF URL via HTML parsing, and stream the download — no browser or Playwright needed.

## .docx Output Format

### Stack
- JavaScript (Node.js)
- `docx` npm package (installed globally or locally: `npm install docx`)
- Run via `node generate_paper.js`
- Output: binary `.docx` — no HTML, no PDF conversion

### Fonts & Typography

| Element | Font | Size | Weight | Color |
|---------|------|------|--------|-------|
| Body text | Arial | 12pt (24) | normal | #000000 |
| Heading 1 | Arial | 16pt (32) | bold | #1F3864 |
| Heading 2 | Arial | 14pt (28) | bold | #2E5496 |
| Heading 3 | Arial | 12pt (24) | bold | #000000 |

- Sizes in docx half-points (shown in parentheses)
- Body paragraphs: `spacing: { line: 360, lineRule: "auto" }` (1.5 line spacing)
- Headings: `spacing: { before: 240, after: 120 }` (twips)

### Page Setup (US Letter)
- width: 12240, height: 15840 (DXA units, 1440 = 1 inch)
- margins: 1440 all sides (1 inch)
- Content width: 9360 DXA

### Table Styling
- WidthType: DXA (never percentages — breaks in Google Docs)
- Width set on both table AND each cell individually
- Header row: `ShadingType.CLEAR`, fill `#D5E8F0`, bold text
- Cell margins: `{ top: 80, bottom: 80, left: 120, right: 120 }`
- Borders: `BorderStyle.SINGLE`, size 1, color `#CCCCCC`

### Script Structure

Build with helper functions, not one flat `children: []` array:

```js
function h1(text, num) { /* Arial 16pt bold, #1F3864 */ }
function h2(text, num) { /* Arial 14pt bold, #2E5496 */ }
function body(text)      { /* Arial 12pt, 1.5 spacing */ }
function empty()         { /* blank paragraph */ }
function makeTable(headers, rows) { /* table with borders */ }
function tblCap(text)    { /* bold table caption */ }
```

Each section is a function returning arrays of paragraphs. Final doc concatenates all sections:
```js
const children = [
  ...buildFrontMatter(),
  ...buildSection1_Introduction(),
  ...buildSection2(),
  // ...
];
```

## Verification Script

`verify_dois.py` — cross-references cited DOIs against collected JSON:

```bash
python verify_dois.py --draft paper/generate.js --json paper/papers.json
python verify_dois.py --draft paper/output.docx --json paper/papers.json
```

Supports `.js` (extracts from `d: "doi"` patterns), `.docx` (parses document.xml), and `.json` reference lists.

## Common Pitfalls

1. **Smart quotes in JS strings**: `“` and `”` break JS string parsing. Always use straight quotes or escape them. Run `node -c` before `node generate_paper.js`.
2. **Unicode in print statements**: Windows cp1252 encoding breaks on em-dash, checkmark, etc. Use ASCII-only in print strings.
3. **Global vs local npm**: `npm install -g docx` vs `npm install docx` — local install is more portable.
4. **OpenAlex abstracts are truncated**: API may return partial abstracts. Verify abstract length before relying on content.

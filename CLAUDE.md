# CLAUDE.md — Research Paper Scraper & Generator

## Project Overview

A pipeline for collecting research papers via the OpenAlex API and generating formatted .docx manuscripts. The workflow: brainstorm keywords → scrape literature → verify sources → write paper → validate output.

## Keyword Generation

When given a topic, do NOT immediately run `paper_fetcher.py`. First generate 3-5 Boolean query strings by expanding the topic with synonyms, alternate phrasings, and related domain terms. Then pick the single most effective query for the actual fetch.

### How to build queries

- Identify key concepts in the topic (2-4 noun phrases)
- For each concept, list synonyms and alternate phrasings
- Combine with `AND` between concepts and `OR` within synonyms
- Prefer 2-3 concepts — too many ANDs chokes results; too few loses specificity
- Use OpenAlex syntax (quotes for phrases, `OR` for synonyms)

### Example

User gives: *"antioxidant polyphenols in fermented beverages"*

```
Query 1: "antioxidant" AND "polyphenol" AND "fermented beverage"
Query 2: "antioxidant activity" AND ("polyphenol" OR "phenolic") AND ("fermented drink" OR "fermentation")
Query 3: ("antioxidant capacity" OR "DPPH" OR "ORAC") AND "polyphenol" AND ("fermented" OR "probiotic") AND "beverage"
Query 4: "phenolic compound" AND "antioxidant" AND ("kombucha" OR "kefir" OR "fermented tea")
Query 5: "bioactive" AND ("polyphenol" OR "flavonoid") AND "fermentation" AND ("beverage" OR "drink")
```

Pick the most precise query. If unsure, test the top 2 against OpenAlex (single page, check result count) and use the one with more relevant hits.

### Scope cues

- The topic may include article-type hints: `review`, `meta-analysis`, `clinical trial`. Pass these to `paper_fetcher.py`'s OpenAlex filter if relevant.
- If the topic mentions a year range, use it. If not, default to the last 5 years.
- If the user asks for "comprehensive" or "wide coverage," consider running 2 queries and merging results (dedupe by DOI).

## Paper Writing Rules (STRICT — follow in order)

### Rule 0: Journal requirements MUST be checked before writing

**If the user does not specify a target journal**, suggest one using the journal suggester:
```bash
python journal_suggest.py --topic "the paper topic here" --type review
python journal_suggest.py --topic "the paper topic here" --type review --top 10   # show top 10
```
This queries OpenAlex for 500 papers matching the topic, ranks journals by frequency + citations, and returns the top candidates. Present the top choices to the user and get confirmation before proceeding.

**If the user does specify a journal**, look up its requirements. Check `journal_cache.json` first. If not cached (or cache is incomplete — missing word limits, reference style, etc.), use **web search** to find the author guidelines:

```
WebSearch: "<Journal Name> author guidelines word limit abstract reference style"
WebSearch: "<Journal Name> guide for authors reference format abstract length"
```

Web search is preferred because publisher websites (Elsevier, ACS, Wiley, MDPI) all block direct page fetching (403), but their author guidelines are indexed by search engines and appear in snippets. Extract from search results:
- Word limits per article type (research vs. review)
- Abstract word/character limit
- Reference style (numeric/superscript vs. author-date/Harvard/APA)
- Whether highlights are required
- Whether a graphical abstract is required
- Cover letter requirements
- Figure/table limits
- Formatting requirements (line spacing, line numbers, etc.)
- Significance statement requirements

Save findings to `journal_cache.json` so they persist. Only fall back to `journal_analyzer.py` (the profiling pipeline — downloads PDFs, extracts word counts) if web search returns nothing useful:
```bash
python journal_analyzer.py --journal "Journal Name"
```

If neither web search nor the analyzer can determine the requirements, do NOT write the manuscript. Stop and tell the user that requirements must be provided manually.

Once a profile is obtained, conform the manuscript to every requirement it specifies:
- **Article type** — if the journal publishes only research articles (0 reviews), do not write a review
- **Reference style** — numeric vs. author-date, match exactly
- **Section structure** — IMRaD for research journals, flexible for reviews journals
- **Word count** — target the stated limit; if no limit is stated, target the journal's typical range from search results
- **Abstract length** — match the stated limit
- **Highlights / graphical abstract** — include if required
- **Cover letter / significance statement** — include if required
- **Figure/table count** — respect stated limits

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
  figures.py            # matplotlib/seaborn chart generation
  figure_1.png          # generated figure (300 DPI)
  figure_2.png          # generated figure (300 DPI)
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

## Figure Generation (Python)

All figures, charts, and diagrams must be generated programmatically via Python — no manual screenshots, no AI image generation, no copied images from papers.

### Stack
- Python 3
- `matplotlib` for plotting
- `seaborn` for styled statistical plots (optional)
- Output: PNG at 300 DPI, saved to the paper folder

### Figure Spec

| Property | Value |
|----------|-------|
| Format | PNG |
| DPI | 300 |
| Width | 6.5 inches (fits US Letter with 1" margins) |
| Font family | Arial |
| Font size (labels) | 10pt |
| Font size (title) | 12pt bold |
| Color palette | `#1F3864`, `#2E5496`, `#D5E8F0`, `#CCCCCC` (match docx theme) |
| Background | White, no gridlines |
| Legend | Inside plot area or below, no border |

### Script Conventions

Each figure is a standalone function in `figures.py` that returns the output path:

```python
import matplotlib.pyplot as plt
import seaborn as sns

def build_bar_chart(data: dict, xlabel: str, ylabel: str, title: str, outpath: str):
    fig, ax = plt.subplots(figsize=(6.5, 4))
    # ... plotting logic ...
    fig.tight_layout()
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return outpath
```

### Embedding in .docx

Use the `docx` npm package `ImageRun` to embed PNGs. Helper in `generate_paper.js`:

```js
const { ImageRun } = require("docx");
const fs = require("fs");

function figure(imagePath, caption, widthInches = 6.5) {
    const img = fs.readFileSync(imagePath);
    return [
        new Paragraph({
            children: [new ImageRun({
                data: img,
                transformation: { width: Math.round(widthInches * 1440), height: Math.round(widthInches * 0.6 * 1440) },
                type: "png",
            })],
            alignment: AlignmentType.CENTER,
            spacing: { before: 240, after: 120 },
        }),
        new Paragraph({
            children: [new TextRun({ text: caption, bold: true, size: 20, font: "Arial" })],
            alignment: AlignmentType.CENTER,
            spacing: { after: 240 },
        }),
    ];
}
```

### Figure Quality Rules

- **Chemical structures and molecular diagrams** — use **RDKit** (`rdkit.Chem.Draw`) for 2D molecular structure visualizations, reaction schemes, and chemical pathway diagrams. Output as PNG at 300 DPI with white background, matching the figure color palette. Follow the same figure conventions (Arial labels, 6.5-inch width, `fig.tight_layout()` before save).
- **AI-generated figures and diagrams** — use `gemini_figures.py` for complex scientific illustrations, conceptual diagrams, schematics, and figures that can't be generated from data or code. This calls the Gemini image generation API via nanoapi.poloai.top. Default model is `pro` (7 credits). Usage:
  ```bash
  python gemini_figures.py "A scientific diagram showing polyphenol degradation pathways during fermentation" figure_4_pathways
  ```
  Or from Python:
  ```python
  from gemini_figures import generate_figure, scientific_figure, chemical_structure
  scientific_figure("antioxidant mechanism schematic showing radical scavenging", "fig_mechanism")
  ```
  API key is in `.env` as `GEMINI_API_KEY`. Available models: `banana1` (1 credit), `banana2` (4 credits), `pro` (7 credits), `banana2_hq` (10 credits).
- Every figure must be data-driven — values come from `papers_merged.json`
- No hardcoded numbers in chart code; read from the collected papers JSON
- Captions must be descriptive: include sample size, what's shown, and the key takeaway
- Generate at least 2 figures per manuscript (e.g., year distribution bar chart, keyword frequency, journal breakdown, trend line)
- Run `python figures.py` before running `node generate_paper.js` so PNGs are on disk

## Common Pitfalls

1. **Smart quotes in JS strings**: `“` and `”` break JS string parsing. Always use straight quotes or escape them. Run `node -c` before `node generate_paper.js`.
2. **Unicode in print statements**: Windows cp1252 encoding breaks on em-dash, checkmark, etc. Use ASCII-only in print strings.
3. **Global vs local npm**: `npm install -g docx` vs `npm install docx` — local install is more portable.
4. **OpenAlex abstracts are truncated**: API may return partial abstracts. Verify abstract length before relying on content.

"""
Gemini Image Generation — via nanoapi.poloai.top
================================================
Generates figures, diagrams, and charts using Gemini models.
Place API key in .env as GEMINI_API_KEY=your_key_here.

Default model: pro (gemini-3-pro-image-preview-high, 7 credits)
"""

import os
import base64
import requests
from pathlib import Path

from paper_fetcher import _load_dotenv

_load_dotenv()  # load GEMINI_API_KEY from .env

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY    = os.environ.get("GEMINI_API_KEY", "")
OUTPUT_DIR = "./figures"  # default; override per paper via output_dir param

BASE = "https://nanoapi.poloai.top/v1beta/models"

MODELS = {
    "banana1":    f"{BASE}/gemini-2.5-flash-image-preview:generateContent",       # 1 credit
    "banana2":    f"{BASE}/gemini-3.1-flash-image-preview:generateContent",       # 4 credits
    "pro":        f"{BASE}/gemini-3-pro-image-preview-high:generateContent",      # 7 credits
    "banana2_hq": f"{BASE}/:gemini-3.1-flash-image-preview-high:generateContent", # 10 credits
}

# ── Generate ──────────────────────────────────────────────────────────────────

def generate_figure(prompt: str, filename: str, model: str = "pro",
                    output_dir: str = "") -> str:
    """Generate an image from a text prompt and save it. Returns the file path."""
    out_dir = output_dir or OUTPUT_DIR
    Path(out_dir).mkdir(exist_ok=True)

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"]
        }
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(MODELS[model], json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()

    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            ext      = part["inlineData"]["mimeType"].split("/")[-1]
            out_path = os.path.join(out_dir, f"{filename}.{ext}")
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(part["inlineData"]["data"]))
            print(f"[OK] Saved -> {out_path}")
            return out_path

    raise ValueError(f"No image returned. Full response: {data}")


# ── Convenience helpers ───────────────────────────────────────────────────────

def scientific_figure(prompt: str, filename: str, output_dir: str = "") -> str:
    """Generate a scientific figure — clean white bg, journal style, labeled axes."""
    full_prompt = (
        f"{prompt} Clean white background, professional scientific journal style, "
        f"labeled axes, no gridlines. Use color palette #1F3864, #2E5496, #D5E8F0, #CCCCCC."
    )
    return generate_figure(full_prompt, filename, output_dir=output_dir)

def chemical_structure(prompt: str, filename: str, output_dir: str = "") -> str:
    """Generate a chemical structure or reaction scheme diagram."""
    full_prompt = (
        f"Chemical structure diagram: {prompt} Clean white background, clear bond angles, "
        f"professional journal-quality 2D rendering, 300 DPI equivalent."
    )
    return generate_figure(full_prompt, filename, output_dir=output_dir)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python gemini_figures.py <prompt> <filename> [model] [--dir paper_folder]")
        print(f"Models: {', '.join(MODELS.keys())}")
        sys.exit(1)

    p      = sys.argv[1]
    fn     = sys.argv[2]
    m      = "pro"
    outdir = ""

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == "--dir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
            i += 2
        elif not sys.argv[i].startswith("--"):
            m = sys.argv[i]
            i += 1
        else:
            i += 1

    generate_figure(p, fn, m, output_dir=outdir)

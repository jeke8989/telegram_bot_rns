#!/usr/bin/env python3
"""
One-time script to export dynamic KP page backgrounds from Figma API.
Run: python scripts/export_figma_pages.py

Requires FIGMA_TOKEN in .env or as environment variable.
"""

import os
import sys
import requests
from pathlib import Path

FIGMA_FILE_KEY = "cGseX1c9N3t0jSUMXhuBPG"

FRAMES = {
    "1:3": "page_01_title.png",
    "41:179": "page_08_timeline.png",
    "41:159": "page_09_architecture.png",
    "2:22": "page_10_cost.png",
}

SCALE = 2
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "app" / "assets" / "figma_pages"


def main():
    token = os.environ.get("FIGMA_TOKEN", "")
    if not token:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent / ".env")
            token = os.environ.get("FIGMA_TOKEN", "")
        except ImportError:
            pass

    if not token:
        print("Error: FIGMA_TOKEN not set. Put it in .env or export it.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"X-Figma-Token": token}

    ids = ",".join(FRAMES.keys())
    url = f"https://api.figma.com/v1/images/{FIGMA_FILE_KEY}?ids={ids}&format=png&scale={SCALE}"
    print(f"Requesting exports from Figma API...")
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    if data.get("err"):
        print(f"Figma API error: {data['err']}")
        sys.exit(1)

    for node_id, filename in FRAMES.items():
        image_url = data["images"].get(node_id)
        if not image_url:
            print(f"  SKIP {filename} — no URL returned for {node_id}")
            continue

        print(f"  Downloading {filename}...")
        img_resp = requests.get(image_url)
        img_resp.raise_for_status()

        out_path = OUTPUT_DIR / filename
        out_path.write_bytes(img_resp.content)
        size_kb = len(img_resp.content) / 1024
        print(f"  Saved {out_path} ({size_kb:.0f} KB)")

    print("Done.")


if __name__ == "__main__":
    main()

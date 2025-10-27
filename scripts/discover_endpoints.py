"""CLI to discover ComfyUI endpoints and save results."""
from __future__ import annotations

import argparse
import json
from comfyrest.client import discover_all


def main():
    parser = argparse.ArgumentParser(description="Discover ComfyUI REST endpoints")
    parser.add_argument("--url", default="http://127.0.0.1:8188", help="Base URL of ComfyUI")
    parser.add_argument("--output", default="endpoints.json", help="Output file to write results")
    args = parser.parse_args()

    results = discover_all(args.url)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

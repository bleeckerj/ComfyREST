# ComfyREST_Studies01

A small Python project to experiment with accessing ComfyUI via its REST API.

This repository contains:

- `comfyrest/` - a minimal client package for discovering and calling Comfy endpoints
- `scripts/discover_endpoints.py` - a CLI script that enumerates available endpoints and saves the results
- `tests/` - basic pytest tests for discovery
- `requirements.txt` - runtime dependencies
- `pyproject.toml` - project metadata

Prerequisites

- ComfyUI running on localhost (default http://127.0.0.1:8188)
- Python 3.10+

Quick start

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Discover endpoints:

```bash
python scripts/discover_endpoints.py --url http://127.0.0.1:8188 --output endpoints.json
```

Run tests:

```bash
pytest -q
```

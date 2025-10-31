#!/usr/bin/env python3
"""
ComfyREST Database Package Entry Point
====================================

Default action: Initialize database
Usage: python -m database [args...]

This runs the database initialization script by default.
For other database utilities, import them directly:
- python -m database.incremental_ingestion
- python -m database.migrate_paths
"""

import sys
from .init_database import main

if __name__ == '__main__':
    sys.exit(main())
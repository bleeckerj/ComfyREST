#!/usr/bin/env python3
"""
Example usage of the workflow catalog generator
"""

import subprocess
import sys
from pathlib import Path

def generate_catalogs():
    """Generate catalogs for all JSON workflows in the current directory."""
    
    current_dir = Path(".")
    json_files = list(current_dir.glob("*.json"))
    
    if not json_files:
        print("No JSON files found in current directory")
        return
    
    print(f"Found {len(json_files)} JSON files:")
    
    for json_file in json_files:
        print(f"\n📁 Processing {json_file.name}...")
        
        # Generate detailed catalog
        detailed_output = json_file.stem + "-catalog.md"
        result = subprocess.run([
            sys.executable, "scripts/workflow_catalog.py",
            str(json_file), "--output", detailed_output
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"  ✓ Detailed catalog: {detailed_output}")
        else:
            print(f"  ❌ Error generating detailed catalog: {result.stderr}")
            continue
        
        # Generate table catalog
        table_output = json_file.stem + "-table.md"
        result = subprocess.run([
            sys.executable, "scripts/workflow_catalog.py",
            str(json_file), "--format", "table", "--output", table_output
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"  ✓ Table catalog: {table_output}")
        else:
            print(f"  ❌ Error generating table catalog: {result.stderr}")
            
        # Generate HTML visual catalog
        html_output = json_file.stem + "-visual.html"
        result = subprocess.run([
            sys.executable, "scripts/workflow_catalog.py",
            str(json_file), "--format", "html", "--output", html_output
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"  ✓ HTML visual: {html_output}")
        else:
            print(f"  ❌ Error generating HTML visual: {result.stderr}")

if __name__ == "__main__":
    generate_catalogs()
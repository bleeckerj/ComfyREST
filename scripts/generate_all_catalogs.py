#!/usr/bin/env python3
"""
Enhanced workflow catalog generator - processes both JSON and image files

This script demonstrates the new ComfyREST integration that can handle:
- JSON workflow files (ComfyUI API format)
- PNG images with embedded ComfyUI workflows
- WebP images with embedded workflows
- Automatic image association for JSON workflows
"""

import subprocess
import sys
from pathlib import Path

def generate_enhanced_catalogs():
    """Generate enhanced HTML catalogs for all supported files in the current directory."""
    
    current_dir = Path(".")
    
    # Find all supported files
    json_files = list(current_dir.glob("*.json"))
    image_files = list(current_dir.glob("*.png")) + list(current_dir.glob("*.webp"))
    
    if not json_files and not image_files:
        print("No JSON or image files found in current directory")
        return
    
    print(f"🚀 ComfyREST Enhanced Catalog Generator")
    print(f"Found {len(json_files)} JSON files and {len(image_files)} image files")
    
    success_count = 0
    
    # Process JSON files with enhanced catalog
    for json_file in json_files:
        print(f"\n� Processing JSON: {json_file.name}")
        
        html_output = json_file.stem + "-enhanced.html"
        result = subprocess.run([
            sys.executable, "scripts/enhanced_workflow_catalog.py",
            str(json_file), "--output", html_output
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Generated enhanced HTML: {html_output}")
            success_count += 1
        else:
            print(f"❌ Error processing {json_file.name}: {result.stderr}")
    
    # Process image files  
    for image_file in image_files:
        print(f"\n🖼️  Processing Image: {image_file.name}")
        
        html_output = image_file.stem + "-from-image.html"
        result = subprocess.run([
            sys.executable, "scripts/enhanced_workflow_catalog.py",
            str(image_file), "--output", html_output
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Generated workflow catalog from image: {html_output}")
            success_count += 1
        else:
            print(f"❌ Error processing {image_file.name}: {result.stderr}")


def generate_legacy_catalogs():
    """Generate catalogs using the original workflow_catalog.py (now with image support)."""
    
    current_dir = Path(".")
    json_files = list(current_dir.glob("*.json"))
    image_files = list(current_dir.glob("*.png")) + list(current_dir.glob("*.webp"))
    
    all_files = json_files + image_files
    
    if not all_files:
        print("No JSON or image files found in current directory")
        return
    
    print(f"📋 Legacy Catalog Generator (with image support)")
    print(f"Found {len(all_files)} supported files")
    
    success_count = 0
    
    for file_path in all_files:
        print(f"\n📁 Processing {file_path.name}...")
        
        # Generate HTML catalog (default format is now HTML)
        html_output = file_path.stem + "-legacy.html"
        result = subprocess.run([
            sys.executable, "scripts/workflow_catalog.py",
            str(file_path), "--output", html_output, "--format", "html"
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
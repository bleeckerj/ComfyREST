# ComfyREST

A comprehensive Python toolkit for automating ComfyUI workflows via REST API with programmable parameter overrides and real-time monitoring.

## 🎯 Project Overview

This project enables you to:
- **Execute ComfyUI workflows programmatically** via REST API
- **Override any workflow parameter** from command line (seeds, image paths, text prompts, etc.)
- **Monitor execution in real-time** via WebSocket or reliable HTTP polling
- **Auto-convert file paths** for cross-platform compatibility (WSL/Windows)
- **Generate human-readable workflow catalogs** for easy parameter reference
- **Batch process workflows** with different parameter sets

## 📁 Project Structure

```
ComfyREST/
├── comfyrest/                    # Core API client package
│   ├── __init__.py
│   └── client.py                 # ComfyClient with REST/WebSocket support
├── scripts/                      # Automation and utility tools
│   ├── run_workflow_with_params.py    # 🌟 Universal workflow runner
│   ├── workflow_catalog.py            # 📖 Generate workflow documentation  
│   ├── generate_all_catalogs.py       # 📚 Batch catalog generator
│   ├── discover_endpoints.py          # 🔍 API endpoint discovery
│   └── convert_workflow_to_api.py     # 🔄 UI→API format converter
├── tests/                        # Test suite
│   └── test_discover.py
├── McMaster-Carr-Futures.json   # Example workflow (API format)
├── McMaster-Carr-Futures-catalog.md   # Generated workflow reference
└── requirements.txt
```

## 🚀 Quick Start

### 1. Setup Environment

```bash
# Clone and setup
git clone https://github.com/bleeckerj/ComfyREST.git
cd ComfyREST
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: Enhanced WebP support (recommended)
# macOS
brew install exiftool

# Ubuntu/Debian
sudo apt install libimage-exiftool-perl

# Windows (with Chocolatey)
choco install exiftool
```

### 2. Basic Workflow Execution

```bash
# Run with default parameters
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json

# Override seed parameter
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json --node 3 --param seed 12345

# Real-world example with Windows path and multiple parameters (HTTP polling)
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json \
  --node 3 --param seed 700 \
  --node 116 --param image "F:\ComfyUI_Output\2025-10-24\ComfyUI_00027_.png"

# Use WebSocket for real-time progress updates  
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json \
  --node 3 --param seed 700 \
  --node 116 --param image "my_image.png" \
  --websocket

# Custom server (if not running on localhost)
python3 scripts/run_workflow_with_params.py workflow.json \
  --server http://192.168.1.100:8188 \
  --node 3 --param seed 42
```

## 📖 Workflow Documentation

Generate human-readable catalogs from your workflows or images:

```bash
# FROM JSON WORKFLOWS
# Generate detailed workflow reference (Markdown)
python3 scripts/workflow_catalog.py workflow.json --output my-workflow-ref.md

# Generate compact table format (Markdown)
python3 scripts/workflow_catalog.py workflow.json --format table

# Generate interactive HTML visualization 🆕
python3 scripts/workflow_catalog.py workflow.json --format html --output workflow.html

# FROM IMAGES WITH EMBEDDED WORKFLOWS 🆕
# Extract workflow from PNG and generate catalog
python3 scripts/workflow_catalog.py generated_image.png --output catalog.html

# Extract workflow from WebP and generate catalog
python3 scripts/workflow_catalog.py output.webp --output catalog.html

# Extract workflow from JPEG and generate catalog
python3 scripts/workflow_catalog.py photo.jpg --output catalog.html

# BATCH PROCESSING
# Process all JSON workflows and images in directory (generates all formats)
python3 scripts/generate_all_catalogs.py
```

### 🖼️ **NEW: Image Workflow Extraction**

ComfyREST now supports extracting ComfyUI workflows directly from images with embedded metadata:

- **📷 PNG Support**: Extracts from tEXt/iTXt metadata chunks
- **🌐 WebP Support**: Uses EXIF data + exiftool fallback
- **📸 JPEG Support**: EXIF metadata extraction
- **🔄 Format Conversion**: Automatically converts UI format to API format
- **🎨 Visual Integration**: Generated catalogs include the original image

**Supported metadata fields**: `workflow`, `prompt`, `comfy_workflow`, `workflow_json`, `ComfyUI`

The generated catalogs include:
- **📝 Markdown formats**: Detailed docs and quick reference tables
- **🌐 Interactive HTML**: Visual node cards with expandable details, color-coded by type
- **🖼️ Image Display**: Hero section showing the generated image (when available)
- **📊 Node overview** with types, connections, and statistics
- **🔧 Parameter reference** showing what can be modified via command line
- **📈 Data flow visualization** (Mermaid diagrams in Markdown)  
- **⚡ Quick reference** for easy parameter discovery

## 🔄 Monitoring Options

### HTTP Polling (Default - Reliable)
✅ Simple and stable  
✅ No extra dependencies  
✅ Perfect for automation  
❌ 1-second poll intervals  

### WebSocket (Real-time)
✅ Instant progress updates  
✅ Immediate completion detection  
✅ Live node execution status  
❌ Requires `websocket-client`

**Recommendation**: Use WebSocket for development, HTTP for production automation.

## 🔧 Advanced Usage

### WSL Path Conversion

When running ComfyUI on Windows but calling from WSL:

```bash
# Get Windows path for WSL file
wslpath -w /path/to/file.png
# Output: \\wsl.localhost\Ubuntu\path\to\file.png

# The script automatically handles path conversion
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json \
  --node 116 --param image "/home/user/image.png"  # Automatically converted
```

### Programmatic API Usage

```python
from comfyrest.client import ComfyClient
import json

# Initialize client (defaults to localhost:8188)
client = ComfyClient("http://172.29.144.1:8188")

# Load and modify workflow
with open("workflow.json") as f:
    workflow = json.load(f)

# Submit workflow
response = client.post_prompt(workflow)
prompt_id = response["prompt_id"]

# Option 1: WebSocket real-time monitoring
result = client.wait_for_prompt_with_ws(prompt_id, timeout=300)

# Option 2: HTTP polling (more reliable)
result = client.wait_for_prompt(prompt_id, timeout=300)

# Check results
if result.get("status") == "completed":
    outputs = result.get("outputs", {})
    print(f"Generated {len(outputs)} outputs")
```

### Batch Processing

```bash
# Process multiple seeds
for seed in 100 200 300; do
  python3 scripts/run_workflow_with_params.py workflow.json \
    --node 3 --param seed $seed
done

# Save modified workflow instead of running
python3 scripts/run_workflow_with_params.py workflow.json \
  --node 3 --param seed 42 \
  --save modified_workflow.json
```

### Parameter Discovery

```bash
# List all modifiable parameters
python3 scripts/run_workflow_with_params.py workflow.json --list-params

# Generate comprehensive documentation (Markdown)
python3 scripts/workflow_catalog.py workflow.json --output workflow-reference.md

# Generate interactive visual documentation (HTML)
python3 scripts/workflow_catalog.py workflow.json --format html --output workflow-visual.html
```

### 🌐 Interactive HTML Visualization

The HTML format creates a beautiful, interactive workflow visualization:

- **🎨 Color-coded node cards** (Input: Blue, Processing: Orange, Output: Green, Special: Pink)
- **📱 Responsive grid layout** adapts to screen size
- **🔍 Expandable details** click to see parameters and connections
- **📊 Live statistics** showing node counts and connection info
- **🎯 Quick parameter reference** with command-line examples
- **✨ Modern UI** powered by Tailwind CSS

Open the generated `.html` file in any web browser for an interactive workflow explorer!

## 🛠 Troubleshooting

### Common Issues

**Path Problems**
```bash
# ❌ Wrong: Raw Linux path when ComfyUI is on Windows
--param image "/home/user/image.png"

# ✅ Correct: Let script auto-convert OR use wslpath manually
wslpath -w /home/user/image.png  # Get proper Windows path
--param image "$(wslpath -w /home/user/image.png)"
```

**WebSocket Connection Issues**
```bash
# Install WebSocket support
pip install websocket-client

# Test fallback to HTTP if WebSocket fails
python3 scripts/run_workflow_with_params.py workflow.json --node 3 --param seed 42
# (Automatically falls back if WebSocket unavailable)
```

**Server Connection**
```bash
# Check if ComfyUI server is running
curl http://127.0.0.1:8188/

# Use custom server
python3 scripts/run_workflow_with_params.py workflow.json \
  --server http://192.168.1.100:8188 \
  --node 3 --param seed 42
```

**Image Processing Issues** 🆕
```bash
# ❌ "No ComfyUI workflow found in image"
# Make sure the image was saved with workflow metadata in ComfyUI
# Use "Save (API format)" option in ComfyUI when saving images

# ❌ "Pillow not available"
pip install pillow

# ❌ Enhanced WebP support
# Install exiftool for better WebP metadata extraction
brew install exiftool  # macOS
sudo apt install libimage-exiftool-perl  # Ubuntu

# ✅ Check what metadata is available in an image
python3 -c "
from PIL import Image
img = Image.open('your_image.png')
print('Available metadata keys:', list(img.info.keys()))
"

# ✅ Test image workflow extraction
python3 scripts/workflow_catalog.py your_image.png --format html
```

### Requirements

- **ComfyUI server** running and accessible
- **Python 3.10+**
- **Pillow (PIL)**: For image metadata extraction (PNG/WebP/JPEG)
- **Optional**: `websocket-client` for real-time monitoring
- **Optional**: `exiftool` for enhanced WebP metadata extraction

## 📝 Examples

### Complete Workflow Examples

```bash
# Basic: Change seed only
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json \
  --node 3 --param seed 12345

# Advanced: Multiple parameters with WebSocket monitoring
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json \
  --node 3 --param seed 42 --param steps 20 \
  --node 116 --param image "my_reference_image.jpg" \
  --websocket

# Cross-platform: WSL calling Windows ComfyUI  
python3 scripts/run_workflow_with_params.py McMaster-Carr-Futures.json \
  --server http://172.29.144.1:8188 \
  --node 116 --param image "/mnt/c/Users/user/Pictures/image.png" \
  --websocket
```

### Image Workflow Processing Examples 🆕

```bash
# Extract workflow from ComfyUI-generated PNG and create interactive catalog
python3 scripts/workflow_catalog.py ComfyUI_00042_.png --output workflow-from-image.html

# Process WebP image with embedded workflow
python3 scripts/workflow_catalog.py output.webp --format html --output webp-workflow.html

# Extract workflow from JPEG and generate markdown documentation
python3 scripts/workflow_catalog.py generated.jpg --format detailed --output workflow-docs.md

# Batch process directory containing both JSON workflows and images
python3 scripts/generate_all_catalogs.py
# This will now process:
# - All .json workflow files  
# - All .png images with embedded workflows
# - All .webp images with embedded workflows
# - All .jpg/.jpeg images with embedded workflows

# Process image and save extracted workflow as JSON
python3 scripts/workflow_catalog.py image.png --output extracted-workflow.html
# Also creates: extracted-workflow.json (the extracted API-format workflow)
```

## 🚀 Development & Contributing

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/bleeckerj/ComfyREST.git
cd ComfyREST

# Setup virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install websocket-client

# Run tests
python -m pytest tests/

# Install in development mode
pip install -e .
```

### Project Architecture

- **`comfyrest.client.ComfyClient`**: Core API client with REST and WebSocket support
- **`scripts/run_workflow_with_params.py`**: Universal workflow automation tool
- **`scripts/workflow_catalog.py`**: Documentation generation for workflows
- **Parameter override system**: Command-line interface for workflow customization
- **Cross-platform path handling**: Automatic WSL/Windows path conversion

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make changes and add tests
4. Run tests: `python -m pytest`
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **ComfyUI** team for the excellent workflow automation platform
- **WebSocket** real-time monitoring capabilities
- **WSL** integration for cross-platform development

---

**Happy automating! 🚀**
# Run tests
pytest -q

# Discover available API endpoints
python scripts/discover_endpoints.py --url http://172.29.144.1:8188 --output endpoints.json

# Convert UI workflow to API format
python scripts/convert_workflow_to_api.py ui_workflow.json api_workflow.json
```

# ComfyREST Enhanced Workflow Catalog Integration

This integration brings the powerful workflow extraction and visualization capabilities from `comfy-cataloger` into ComfyREST, enabling ComfyREST to process both PNG/WebP images with embedded ComfyUI workflows and standalone JSON workflow files.

## Features

### 🖼️ Image-to-Workflow Processing
- **PNG Support**: Extract workflows from PNG tEXt/iTXt metadata chunks
- **WebP Support**: Extract workflows from WebP EXIF data with exiftool fallback
- **Automatic Detection**: Scans all metadata fields for JSON workflow data
- **Visual Integration**: Generated HTML includes the original image prominently

### 📄 JSON Workflow Processing  
- **API Format**: Handles ComfyUI API format (node dictionary keyed by IDs)
- **UI Format**: Converts ComfyUI UI format (nodes array + links) to API format
- **Format Normalization**: Consistent internal representation for analysis
- **Associated Images**: Automatically finds related images by filename patterns

### 🎨 Rich HTML Output
- **Hero Image Section**: Prominently displays the generated image
- **Interactive Graphs**: Mermaid.js flowcharts showing workflow structure
- **Responsive Design**: Tailwind CSS for mobile and desktop
- **Node Analysis**: Detailed tables and statistics
- **Model Detection**: Automatic highlighting of AI models used
- **Self-Contained**: Base64 embedded images for portable HTML files

## Usage

### Enhanced Workflow Catalog (Recommended)

The new `enhanced_workflow_catalog.py` provides the most comprehensive functionality:

```bash
# Process a single image with embedded workflow
python scripts/enhanced_workflow_catalog.py image.png

# Process a JSON workflow file
python scripts/enhanced_workflow_catalog.py workflow.json

# Process JSON with explicit associated image
python scripts/enhanced_workflow_catalog.py workflow.json --image generated_image.png

# Process entire directory recursively
python scripts/enhanced_workflow_catalog.py /path/to/workflows --recursive --output catalog_output/

# Verbose output for debugging
python scripts/enhanced_workflow_catalog.py workflow.png --verbose
```

### Updated Legacy Script

The original `workflow_catalog.py` now also supports images:

```bash
# Process image (extracts workflow automatically)
python scripts/workflow_catalog.py image.png --format html

# Process JSON with image
python scripts/workflow_catalog.py workflow.json --image image.png --format html

# Generate markdown instead of HTML
python scripts/workflow_catalog.py workflow.json --format detailed
```

## Architecture

### Core Components

1. **WorkflowExtractor**: Handles metadata extraction from PNG/WebP images
2. **WorkflowConverter**: Converts between UI format and API format
3. **WorkflowAnalyzer**: Analyzes workflow structure and extracts metadata
4. **HTMLGenerator**: Creates rich, interactive HTML output

### Workflow Processing Pipeline

```
Input (Image/JSON) → Extract/Load → Normalize → Analyze → Generate HTML
```

1. **Extract/Load**: 
   - Images: Extract JSON from metadata using Pillow + optional exiftool
   - JSON: Load and validate workflow structure

2. **Normalize**: 
   - Convert UI format (nodes array) to API format (node dictionary)
   - Create consistent internal representation

3. **Analyze**: 
   - Count nodes and connections
   - Identify node types and patterns
   - Detect AI models in use
   - Find input/output nodes

4. **Generate**: 
   - Create interactive HTML with Mermaid graphs
   - Embed images as base64 data URLs
   - Include comprehensive workflow details

### Image Metadata Extraction Strategy

**PNG Files (Pillow)**:
- Check common keys: `workflow`, `prompt`, `comfy_workflow`, `workflow_json`, `ComfyUI`
- Fallback: Scan all tEXt/iTXt chunks for valid JSON
- Handle both string and bytes values

**WebP Files (Pillow + exiftool)**:
- Primary: Use Pillow's `getexif()` to read EXIF data
- Fallback: Use exiftool CLI for comprehensive metadata extraction
- Scan all string fields for embedded JSON workflows

## Dependencies

### Required
- **Pillow (PIL)**: Image metadata extraction
- **Python 3.8+**: Core functionality

### Optional
- **exiftool**: Enhanced WebP metadata extraction (graceful fallback)
- **WeasyPrint**: PDF generation (for future print features)

### Installation

```bash
# Required dependencies
pip install pillow

# Optional: Install exiftool (macOS)
brew install exiftool

# Optional: PDF generation support
pip install weasyprint
```

## File Structure

```
ComfyREST/
├── scripts/
│   ├── enhanced_workflow_catalog.py    # New comprehensive solution
│   ├── workflow_catalog.py             # Updated legacy script with image support
│   ├── test_integration.py             # Integration testing script
│   └── ...
└── README_INTEGRATION.md               # This documentation
```

## Testing

Run the integration test to verify functionality:

```bash
python scripts/test_integration.py
```

This will:
1. Create sample test data if needed
2. Test JSON workflow processing
3. Test image workflow extraction (if images available)
4. Test batch directory processing
5. Generate HTML outputs for inspection

## Output Examples

### Generated HTML Features

- **Hero Section**: Large image display with metadata overlay
- **Statistics Cards**: Node count, connections, types, models detected
- **Interactive Graph**: Mermaid.js workflow visualization
- **Detailed Tables**: Complete node information
- **Raw JSON**: Formatted API-compatible workflow data
- **Responsive Layout**: Works on all screen sizes

### File Outputs

For each processed workflow, the system generates:
- `workflow_name.html`: Rich interactive HTML catalog
- `workflow_name.json`: Normalized API-format JSON workflow

## Integration Benefits

### For ComfyREST Users
1. **Unified Interface**: Process images and JSON with the same tools
2. **Visual Context**: See the generated image alongside workflow details
3. **Better Analysis**: Enhanced workflow visualization and statistics
4. **Portable Output**: Self-contained HTML files work anywhere

### For Workflow Management
1. **Format Conversion**: Automatic UI-to-API format conversion
2. **Model Tracking**: Identify which AI models are used
3. **Workflow Documentation**: Rich, shareable documentation
4. **Batch Processing**: Handle entire directories of workflows

## Error Handling

The integration includes robust error handling:
- **Missing Dependencies**: Graceful degradation with helpful messages
- **Invalid Files**: Clear error messages for unsupported formats
- **Extraction Failures**: Continue processing other files in batch mode
- **Metadata Issues**: Fallback extraction methods for difficult files

## Future Enhancements

Planned improvements include:
- **PDF Generation**: Print-ready workflow books
- **Multiple Images**: Support for workflows generating multiple outputs
- **Advanced Graphs**: Cytoscape.js for complex workflow visualization
- **Workflow Comparison**: Side-by-side analysis of different workflows
- **Search Integration**: Full-text search across workflow catalogs

## Troubleshooting

### Common Issues

**"No workflow found in image"**:
- Verify the image contains ComfyUI metadata
- Try saving the image with "Save (API format)" in ComfyUI
- Use `--verbose` flag to see extraction attempts

**"Pillow not available"**:
- Install with `pip install pillow`
- Ensure you're using a compatible Python version

**"exiftool not found"**:
- Install exiftool for enhanced WebP support
- System will work without it, with reduced WebP compatibility

### Debug Mode

Use the verbose flag for detailed debugging:

```bash
python scripts/enhanced_workflow_catalog.py problem_file.png --verbose
```

This shows:
- Metadata extraction attempts
- JSON parsing details  
- Conversion steps
- File generation process
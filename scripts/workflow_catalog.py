#!/usr/bin/env python3
"""
ComfyUI Workflow Catalog Generator

This script analyzes ComfyUI workflows from either JSON files or images with embedded
metadata, and generates rich HTML catalogs with workflow visualization.

Usage:
    python workflow_catalog.py workflow.json
    python workflow_catalog.py image.png 
    python workflow_catalog.py workflow.json --output catalog.html --format html
    python workflow_catalog.py workflow.json --image associated_image.png
    
Note: For the most advanced features, use enhanced_workflow_catalog.py instead.
"""

import argparse
import json
import sys
import os
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import hashlib

# Import image processing if available
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Import database functionality if available
try:
    # Add parent directory to path to import database package
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from database import get_database_manager, WorkflowFileManager, initialize_database, DatabaseManager
    from database.models import WorkflowFile
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False


@dataclass
class WorkflowImageData:
    """Data structure for ComfyUI image with embedded workflow."""
    image_path: Path
    workflow: Dict  # API format (for compatibility)
    metadata: Dict
    original_workflow: Optional[Dict] = None  # UI format (for model extraction)
    
    @property
    def workflow_summary(self) -> Dict:
        """Quick summary for master catalog."""
        if not self.workflow:
            return {"total_nodes": 0, "node_types": [], "connections": 0}
            
        analysis = analyze_workflow(self.workflow)
        return {
            "total_nodes": analysis["total_nodes"],
            "node_types": list(analysis["node_types"].keys()),
            "connections": len(analysis["connections"])
        }
    
    @property
    def file_info(self) -> Dict:
        """File metadata information."""
        stat = self.image_path.stat()
        return {
            "filename": self.image_path.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "relative_path": str(self.image_path.resolve())
        }


@dataclass
class FileAnalysisResult:
    """Result of analyzing a file for ComfyUI workflow."""
    file_path: Path
    success: bool
    workflow: Optional[Dict] = None
    metadata: Optional[Dict] = None
    error_message: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    thumbnail_path: Optional[Path] = None
    catalog_path: Optional[Path] = None
    models: Optional[Dict[str, List[str]]] = None
    node_types: Optional[List[str]] = None
    
    def __post_init__(self):
        """Clean up file_type and extract workflow metadata."""
        # Clean up file_type for better display
        if self.file_type and self.file_type.startswith('image/'):
            self.file_type = 'image'
        elif not self.file_type or self.file_type == 'unknown':
            # Determine if this is an image file
            image_extensions = {'.png', '.webp', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'}
            if self.file_path.suffix.lower() in image_extensions:
                self.file_type = 'image'
            else:
                ext = self.file_path.suffix.lower()
                type_map = {
                    '.json': 'json',
                    '.txt': 'text',
                    '.pdf': 'pdf',
                    '.doc': 'document',
                    '.docx': 'document',
                    '.xls': 'spreadsheet',
                    '.xlsx': 'spreadsheet',
                    '.ppt': 'presentation',
                    '.pptx': 'presentation'
                }
                self.file_type = type_map.get(ext, 'unknown')
        
        # Extract models and node types from workflow if present
        if self.workflow:
            self.models = extract_models_from_workflow(self.workflow)
            analysis = analyze_workflow(self.workflow)
            self.node_types = list(analysis["node_types"].keys())
    
    @property
    def workflow_summary(self) -> Dict:
        """Quick summary for master catalog."""
        if not self.workflow:
            return {"total_nodes": 0, "node_types": {}, "key_params": []}
            
        analysis = analyze_workflow(self.workflow)
        return {
            "total_nodes": analysis["total_nodes"],
            "node_types": list(analysis["node_types"].keys()),
            "connections": len(analysis["connections"])
        }
    
    @property
    def file_info(self) -> Dict:
        """File metadata information."""
        stat = self.image_path.stat()
        return {
            "filename": self.image_path.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "relative_path": str(self.image_path.relative_to(self.image_path.parent.parent))
        }


    
    @property
    def has_workflow(self) -> bool:
        """Check if this file contains a valid ComfyUI workflow."""
        return self.workflow is not None and len(self.workflow) > 0
    
    @property
    def is_image(self) -> bool:
        """Check if this is an image file by extension."""
        image_extensions = {'.png', '.webp', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'}
        return self.file_path.suffix.lower() in image_extensions
    
    @property
    def workflow_summary(self) -> Dict:
        """Quick summary for master catalog (backward compatibility)."""
        if not self.has_workflow:
            return {"total_nodes": 0, "node_types": {}, "connections": 0}
            
        analysis = analyze_workflow(self.workflow)
        return {
            "total_nodes": analysis["total_nodes"],
            "node_types": list(analysis["node_types"].keys()),
            "connections": len(analysis["connections"])
        }
    
    @property
    def file_info(self) -> Dict:
        """File metadata information (backward compatibility)."""
        stat = self.file_path.stat()
        return {
            "filename": self.file_path.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "relative_path": str(self.file_path.relative_to(self.file_path.parent.parent))
        }
    
# Note: WorkflowImageData and FileAnalysisResult are separate classes


def scan_directory_for_all_files(directory: Path, extensions: List[str] = None) -> List[Path]:
    """Recursively find all files in directory hierarchy."""
    if extensions is None:
        extensions = ['.png', '.webp', '.jpg', '.jpeg', '.json', '.txt', '.md', '.py']  # Include more file types
    
    extensions = [ext.lower() for ext in extensions]
    all_files = []
    
    print(f"🔍 Scanning directory: {directory}")
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = Path(root) / file
            # Include all files, not just those with specific extensions
            all_files.append(file_path)
    
    print(f"📁 Found {len(all_files)} total files")
    return sorted(all_files)


def scan_directory_for_images(directory: Path, extensions: List[str] = None) -> List[Path]:
    """Recursively find all image files in directory hierarchy."""
    if extensions is None:
        extensions = ['.png', '.webp', '.jpg', '.jpeg']
    
    extensions = [ext.lower() for ext in extensions]
    image_paths = []
    
    print(f"🔍 Scanning directory: {directory}")
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in extensions:
                image_paths.append(file_path)
    
    print(f"📁 Found {len(image_paths)} image files")
    return sorted(image_paths)


def detect_comfyui_images(image_paths: List[Path]) -> List[WorkflowImageData]:
    """Batch process images to find ones with ComfyUI workflows."""
    workflow_images = []
    
    print(f"🔬 Analyzing {len(image_paths)} images for ComfyUI workflows...")
    
    # Progress tracking
    processed_count = 0
    found_count = 0
    
    for i, image_path in enumerate(image_paths, 1):
        # Show progress with percentage
        progress = f"({i}/{len(image_paths)} - {i/len(image_paths)*100:.1f}%)"
        print(f"  📊 Processing {progress}: {image_path.name}")
        
        # Extract workflow from image
        workflow = extract_workflow_from_image(image_path)
        
        if workflow:
            # Extract additional metadata
            metadata = extract_image_metadata(image_path)
            
            # Also get the original format for model extraction
            original_workflow = extract_workflow_from_image(image_path, preserve_original_format=True)
            
            workflow_data = WorkflowImageData(
                image_path=image_path,
                workflow=workflow,
                metadata=metadata,
                original_workflow=original_workflow
            )
            workflow_images.append(workflow_data)
            found_count += 1
            print(f"    ✅ Found workflow with {len(workflow)} nodes")
        else:
            print(f"    ❌ No ComfyUI workflow found")
        
        processed_count += 1
        
        # Show summary every 10 images for large batches
        if processed_count % 10 == 0 and len(image_paths) > 20:
            hit_rate = found_count / processed_count * 100
            print(f"  📈 Progress update: {found_count}/{processed_count} workflows found ({hit_rate:.1f}% hit rate)")
    
    hit_rate = found_count / len(image_paths) * 100 if image_paths else 0
    print(f"🎯 Found {len(workflow_images)} images with ComfyUI workflows ({hit_rate:.1f}% hit rate)")
    return workflow_images


def analyze_all_files(file_paths: List[Path]) -> List[FileAnalysisResult]:
    """Comprehensively analyze all files to categorize and extract information."""
    results = []
    
    # Categorize files by type
    image_extensions = {'.png', '.webp', '.jpg', '.jpeg'}
    json_extensions = {'.json'}
    
    print(f"🔬 Analyzing {len(file_paths)} files...")
    
    for i, file_path in enumerate(file_paths, 1):
        print(f"  📊 Processing {i}/{len(file_paths)}: {file_path.name}")
        
        suffix = file_path.suffix.lower()
        error_info = {}
        
        try:
            # Determine file type and process accordingly
            if suffix in image_extensions:
                result = analyze_image_file(file_path, error_info)
            elif suffix in json_extensions:
                result = analyze_json_file(file_path, error_info)
            else:
                result = analyze_other_file(file_path, error_info)
            
            results.append(result)
            
        except Exception as e:
            # Handle any unexpected errors
            error_info['unexpected_error'] = str(e)
            result = FileAnalysisResult(
                file_path=file_path,
                file_type='error',
                metadata=extract_basic_file_metadata(file_path),
                error_info=error_info
            )
            results.append(result)
            print(f"    ❌ Error analyzing file: {e}")
    
    # Summary statistics
    workflow_count = sum(1 for r in results if r.has_workflow)
    image_count = sum(1 for r in results if r.is_image)
    total_count = len(results)
    
    print(f"\n📊 Analysis Summary:")
    print(f"   🎯 {workflow_count} files with ComfyUI workflows")
    print(f"   🖼️ {image_count} image files total")
    print(f"   📁 {total_count} files analyzed")
    print(f"   📈 {workflow_count/total_count*100:.1f}% overall workflow hit rate")
    
    return results


def analyze_image_file(file_path: Path, error_info: Dict) -> FileAnalysisResult:
    """Analyze an image file for ComfyUI workflows."""
    try:
        # Try to extract workflow
        workflow = extract_workflow_from_image(file_path)
        
        if workflow and len(workflow) > 0:
            print(f"    ✅ Found workflow with {len(workflow)} nodes")
            return FileAnalysisResult(
                file_path=file_path,
                file_type='workflow_image',
                workflow=workflow,
                metadata=extract_image_metadata(file_path)
            )
        else:
            # Image exists but no workflow found - provide diagnostics
            diagnostics = diagnose_image_failure(file_path)
            error_info.update(diagnostics)
            
            print(f"    ❌ No workflow found - {diagnostics.get('reason', 'Unknown')}")
            return FileAnalysisResult(
                file_path=file_path,
                file_type='image_no_workflow',
                metadata=extract_image_metadata(file_path),
                error_info=error_info
            )
    
    except Exception as e:
        error_info['extraction_error'] = str(e)
        print(f"    ❌ Error processing image: {e}")
        return FileAnalysisResult(
            file_path=file_path,
            file_type='image_no_workflow',
            metadata=extract_basic_file_metadata(file_path),
            error_info=error_info
        )


def analyze_json_file(file_path: Path, error_info: Dict) -> FileAnalysisResult:
    """Analyze a JSON file to see if it's a ComfyUI workflow."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Check if it looks like a ComfyUI workflow
        if isinstance(data, dict):
            # API format workflow
            if all(str(k).isdigit() or isinstance(k, int) for k in data.keys()):
                node_count = len(data)
                print(f"    ✅ JSON workflow with {node_count} nodes")
                return FileAnalysisResult(
                    file_path=file_path,
                    file_type='workflow_json',
                    workflow=data,
                    metadata=extract_basic_file_metadata(file_path)
                )
            # UI format workflow
            elif 'nodes' in data and 'links' in data:
                converted = ui_to_api_format(data)
                if converted:
                    print(f"    ✅ UI format JSON workflow (converted)")
                    return FileAnalysisResult(
                        file_path=file_path,
                        file_type='workflow_json',
                        workflow=converted,
                        metadata=extract_basic_file_metadata(file_path)
                    )
        
        # Not a workflow JSON
        error_info['reason'] = 'Not a ComfyUI workflow format'
        print(f"    ❌ JSON file but not a ComfyUI workflow")
        return FileAnalysisResult(
            file_path=file_path,
            file_type='json_other',
            metadata=extract_basic_file_metadata(file_path),
            error_info=error_info
        )
        
    except json.JSONDecodeError as e:
        error_info['json_error'] = str(e)
        print(f"    ❌ Invalid JSON: {e}")
        return FileAnalysisResult(
            file_path=file_path,
            file_type='json_invalid',
            metadata=extract_basic_file_metadata(file_path),
            error_info=error_info
        )


def analyze_other_file(file_path: Path, error_info: Dict) -> FileAnalysisResult:
    """Analyze non-image, non-JSON files."""
    suffix = file_path.suffix.lower()
    
    file_type_map = {
        '.txt': 'text_file',
        '.md': 'markdown_file', 
        '.py': 'python_file',
        '.js': 'javascript_file',
        '.html': 'html_file',
        '.css': 'css_file',
        '.yaml': 'yaml_file',
        '.yml': 'yaml_file',
        '.xml': 'xml_file',
        '': 'no_extension'
    }
    
    file_type = file_type_map.get(suffix, 'other_file')
    print(f"    📄 {file_type.replace('_', ' ').title()}")
    
    return FileAnalysisResult(
        file_path=file_path,
        file_type=file_type,
        metadata=extract_basic_file_metadata(file_path)
    )


def diagnose_image_failure(file_path: Path) -> Dict:
    """Provide detailed diagnostics for why an image didn't contain a workflow."""
    diagnostics = {}
    
    if not PIL_AVAILABLE:
        diagnostics['reason'] = 'PIL/Pillow not available for image processing'
        return diagnostics
    
    try:
        with Image.open(file_path) as img:
            # Check image format
            diagnostics['format'] = img.format
            diagnostics['size'] = f"{img.width}x{img.height}"
            
            # Check for any metadata at all
            metadata_count = len(img.info) if img.info else 0
            diagnostics['metadata_entries'] = metadata_count
            
            if metadata_count == 0:
                diagnostics['reason'] = 'No metadata found in image'
            else:
                # List metadata keys for debugging
                diagnostics['metadata_keys'] = list(img.info.keys()) if img.info else []
                
                # Check if any keys contain JSON-like data
                json_like_keys = []
                for key, value in img.info.items():
                    if isinstance(value, (str, bytes)) and ('{' in str(value) or '[' in str(value)):
                        json_like_keys.append(key)
                
                if json_like_keys:
                    diagnostics['json_like_keys'] = json_like_keys
                    diagnostics['reason'] = 'Found JSON-like metadata but failed to parse as ComfyUI workflow'
                else:
                    diagnostics['reason'] = 'No JSON-like metadata found'
                    
    except Exception as e:
        diagnostics['reason'] = f'Error opening image: {e}'
    
    return diagnostics


def extract_basic_file_metadata(file_path: Path) -> Dict:
    """Extract basic file metadata for any file type."""
    metadata = {}
    
    try:
        stat = file_path.stat()
        metadata.update({
            "file_size": stat.st_size,
            "modified_time": stat.st_mtime,
            "created_time": stat.st_ctime if hasattr(stat, 'st_ctime') else stat.st_mtime,
            "extension": file_path.suffix.lower(),
            "is_executable": os.access(file_path, os.X_OK)
        })
        
        # Generate file hash for duplicate detection
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5()
            chunk = f.read(8192)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(8192)
            metadata["file_hash"] = file_hash.hexdigest()
                
    except Exception as e:
        metadata["metadata_error"] = str(e)
    
    return metadata


def extract_image_metadata(image_path: Path) -> Dict:
    """Extract comprehensive metadata beyond just workflow."""
    metadata = {}
    
    try:
        stat = image_path.stat()
        metadata.update({
            "file_size": stat.st_size,
            "modified_time": stat.st_mtime,
            "created_time": stat.st_ctime if hasattr(stat, 'st_ctime') else stat.st_mtime
        })
        
        # Get image dimensions if possible
        if PIL_AVAILABLE:
            try:
                with Image.open(image_path) as img:
                    metadata.update({
                        "width": img.width,
                        "height": img.height,
                        "format": img.format,
                        "mode": img.mode
                    })
            except Exception as e:
                metadata["image_error"] = str(e)
        
        # Generate file hash for duplicate detection
        with open(image_path, 'rb') as f:
            file_hash = hashlib.md5()
            chunk = f.read(8192)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(8192)
            metadata["file_hash"] = file_hash.hexdigest()
                
    except Exception as e:
        metadata["metadata_error"] = str(e)
    
    return metadata


def extract_from_png(image_path: Path) -> Optional[Dict]:
    """Extract workflow JSON from PNG metadata using Pillow."""
    try:
        with Image.open(image_path) as img:
            # Common keys where ComfyUI stores workflow data
            workflow_keys = ['workflow', 'prompt', 'comfy_workflow', 'workflow_json', 'ComfyUI']
            
            # First, try known keys
            for key in workflow_keys:
                if key in img.info:
                    try:
                        if isinstance(img.info[key], str):
                            return json.loads(img.info[key])
                        elif isinstance(img.info[key], bytes):
                            return json.loads(img.info[key].decode('utf-8'))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
            
            # Fallback: scan all string values for JSON
            for key, value in img.info.items():
                if isinstance(value, (str, bytes)):
                    try:
                        text = value.decode('utf-8') if isinstance(value, bytes) else value
                        data = json.loads(text)
                        # Check if it looks like a ComfyUI workflow
                        if isinstance(data, dict) and ('nodes' in data or 'class_type' in str(data)):
                            return data
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                        
    except Exception as e:
        print(f"PNG extraction failed: {e}")
    
    return None


def extract_from_webp(image_path: Path) -> Optional[Dict]:
    """Extract workflow JSON from WebP metadata using Pillow and optional exiftool."""
    # Try Pillow first
    try:
        with Image.open(image_path) as img:
            # Try EXIF data
            exif = img.getexif()
            if exif:
                for tag_id, value in exif.items():
                    if isinstance(value, (str, bytes)):
                        try:
                            text = value.decode('utf-8') if isinstance(value, bytes) else value
                            data = json.loads(text)
                            if isinstance(data, dict) and ('nodes' in data or 'class_type' in str(data)):
                                return data
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
    except Exception as e:
        print(f"WebP Pillow extraction failed: {e}")
    
    # Fallback to exiftool if available
    return extract_with_exiftool(image_path)


def extract_with_exiftool(image_path: Path) -> Optional[Dict]:
    """Extract metadata using exiftool command-line tool."""
    try:
        import subprocess
        result = subprocess.run(
            ['exiftool', '-j', '-G', str(image_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            exiftool_data = json.loads(result.stdout)
            if exiftool_data:
                # Scan all string fields for JSON
                for item in exiftool_data:
                    for key, value in item.items():
                        if isinstance(value, str):
                            try:
                                data = json.loads(value)
                                if isinstance(data, dict) and ('nodes' in data or 'class_type' in str(data)):
                                    return data
                            except json.JSONDecodeError:
                                continue
                                
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        pass
    
    return None


def ui_to_api_format(ui_workflow: Dict) -> Dict[str, Any]:
    """Convert ComfyUI's UI workflow format to API format."""
    if not ui_workflow:
        return {}
        
    # If it's already in API format (dict keyed by node IDs), return as-is
    if isinstance(ui_workflow, dict) and all(str(k).isdigit() or isinstance(k, int) for k in ui_workflow.keys()):
        return ui_workflow
    
    # Handle UI format with nodes array
    if 'nodes' in ui_workflow and 'links' in ui_workflow:
        api_workflow = {}
        nodes = ui_workflow['nodes']
        links = ui_workflow.get('links', [])
        
        # Create node mapping first
        for node in nodes:
            node_id = str(node.get('id'))
            class_type = node.get('type', 'Unknown')
            
            # Extract inputs from node properties
            inputs = {}
            
            # Get widget values (parameters)
            if 'widgets_values' in node and node['widgets_values']:
                # Map widget values to input names - this is approximate
                widget_values = node['widgets_values']
                if isinstance(widget_values, list):
                    # For common node types, we know the input names
                    if class_type == 'CheckpointLoaderSimple' and len(widget_values) > 0:
                        inputs['ckpt_name'] = widget_values[0]
                    elif class_type == 'CLIPTextEncode' and len(widget_values) > 0:
                        inputs['text'] = widget_values[0]
                    elif class_type == 'EmptyLatentImage' and len(widget_values) >= 3:
                        inputs['width'] = widget_values[0]
                        inputs['height'] = widget_values[1]
                        inputs['batch_size'] = widget_values[2]
                    elif class_type == 'KSampler' and len(widget_values) >= 6:
                        inputs['seed'] = widget_values[0]
                        inputs['steps'] = widget_values[1]
                        inputs['cfg'] = widget_values[2]
                        inputs['sampler_name'] = widget_values[3]
                        inputs['scheduler'] = widget_values[4]
                        inputs['denoise'] = widget_values[5]
                    else:
                        # Generic mapping for unknown node types
                        for i, value in enumerate(widget_values):
                            inputs[f'input_{i}'] = value
            
            api_workflow[node_id] = {
                "class_type": class_type,
                "inputs": inputs
            }
            
            # Add metadata if available
            if 'title' in node:
                api_workflow[node_id]["_meta"] = {"title": node['title']}
        
        # Process links to add connections to inputs
        for link in links:
            if len(link) >= 5:
                link_id, from_node, from_output, to_node, to_input = link[:5]
                to_node_id = str(to_node)
                from_node_id = str(from_node)
                
                if to_node_id in api_workflow:
                    # Map output socket numbers to input names for common connections
                    input_name = f'input_{to_input}' if isinstance(to_input, int) else str(to_input)
                    
                    # For known node types, use proper input names
                    to_class = api_workflow[to_node_id].get('class_type', '')
                    if to_class == 'CLIPTextEncode' and to_input == 0:
                        input_name = 'clip'
                    elif to_class == 'KSampler':
                        if to_input == 0:
                            input_name = 'model'
                        elif to_input == 1:
                            input_name = 'positive'
                        elif to_input == 2:
                            input_name = 'negative'  
                        elif to_input == 3:
                            input_name = 'latent_image'
                    elif to_class == 'VAEDecode':
                        if to_input == 0:
                            input_name = 'samples'
                        elif to_input == 1:
                            input_name = 'vae'
                    elif to_class == 'SaveImage' and to_input == 0:
                        input_name = 'images'
                    
                    api_workflow[to_node_id]["inputs"][input_name] = [from_node_id, from_output]
        
        return api_workflow
    
    # If we can't convert, return as-is
    return ui_workflow


# Database helper functions
def get_database_workflow_manager(database_url: str = None) -> Optional[WorkflowFileManager]:
    """Get database workflow manager if available."""
    if not DATABASE_AVAILABLE:
        return None
    
    try:
        # Initialize database if needed
        if database_url:
            # Check if it's just a filename (assume SQLite)
            if not database_url.startswith(('sqlite://', 'postgresql://', 'mysql://', 'oracle://')):
                # It's just a filename, convert to SQLite URL
                from pathlib import Path
                if not database_url.startswith('/'):
                    # Relative path, make it absolute from current directory
                    database_url = str(Path(database_url).resolve())
                database_url = f"sqlite:///{database_url}"
            
            # Create a new database manager with custom URL
            db_manager = DatabaseManager(database_url)
        else:
            # Use the default database manager
            db_manager = get_database_manager()
        
        # Ensure tables are created
        db_manager.create_tables()
        
        return WorkflowFileManager(db_manager)
    except Exception as e:
        print(f"⚠️ Database not available: {e}")
        return None


def store_workflow_in_database(workflow_manager: WorkflowFileManager, 
                              workflow_data: WorkflowImageData,
                              tags: List[str] = None,
                              collections: List[str] = None,
                              notes: str = None) -> bool:
    """Store workflow in database if manager is available."""
    if not workflow_manager:
        return False
    
    try:
        # Extract models from workflow for auto-tagging
        analysis = analyze_workflow(workflow_data.workflow)
        models_info = analysis.get('models', {})
        
        # Auto-generate tags from models - DISABLED to avoid tag clutter
        # auto_tags = []
        # if models_info.get('checkpoints'):
        #     auto_tags.extend(f"checkpoint:{model}" for model in models_info['checkpoints'])
        # if models_info.get('loras'):
        #     auto_tags.extend(f"lora:{model}" for model in models_info['loras'])
        # if models_info.get('embeddings'):
        #     auto_tags.extend(f"embedding:{model}" for model in models_info['embeddings'])
        
        # Use only provided tags
        all_tags = tags or []
        
        # Add default collection if none provided
        if not collections:
            collections = ["workflow-catalog-import"]
        
        # Store in database
        workflow_manager.add_workflow_file(
            file_path=workflow_data.image_path,
            workflow_data=workflow_data.workflow,
            image_metadata=workflow_data.metadata,
            tags=all_tags,
            collections=collections,
            notes=notes
        )
        return True
        
    except Exception as e:
        print(f"⚠️ Failed to store workflow in database: {e}")
        return False


def extract_workflow_from_image(image_path: Path, preserve_original_format: bool = False) -> Optional[Dict[str, Any]]:
    """Extract ComfyUI workflow from image based on file extension."""
    if not PIL_AVAILABLE:
        print("Warning: Pillow not available. Cannot extract workflows from images.")
        return None
    
    suffix = image_path.suffix.lower()
    
    if suffix == '.png':
        raw_workflow = extract_from_png(image_path)
    elif suffix in {'.webp', '.jpg', '.jpeg'}:
        raw_workflow = extract_from_webp(image_path)
    else:
        print(f"Unsupported image format: {suffix}")
        return None
    
    if raw_workflow:
        if preserve_original_format:
            # Return the original format (for model extraction)
            return raw_workflow
        else:
            # Convert UI format to API format that ComfyREST expects
            return ui_to_api_format(raw_workflow)
    
    return None


def analyze_workflow(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze workflow structure and extract metadata."""
    analysis = {
        "total_nodes": len(workflow),
        "node_types": {},
        "connections": [],
        "input_nodes": [],
        "output_nodes": [],
        "parameters": {}
    }
    
    # Handle both old format (nodes as dict keys) and new format (nodes array)
    nodes = []
    if 'nodes' in workflow and isinstance(workflow['nodes'], list):
        # New format: nodes array
        nodes = workflow['nodes']
    else:
        # Old format: nodes as dict keys
        nodes_dict = {k: v for k, v in workflow.items() if isinstance(v, dict)}
        nodes = [(node_id, node_data) for node_id, node_data in nodes_dict.items()]
    
    # Count node types and analyze connections
    for item in nodes:
        if isinstance(item, tuple):
            # Old format: (node_id, node_data)
            node_id, node_data = item
            class_type = node_data.get("class_type", "Unknown")
        else:
            # New format: node object
            node_data = item
            node_id = node_data.get("id", "unknown")
            class_type = node_data.get("type", node_data.get("class_type", "Unknown"))
            
        analysis["node_types"][class_type] = analysis["node_types"].get(class_type, 0) + 1
        
        # Check inputs for connections (handle both formats)
        inputs = node_data.get("inputs", {})
        if isinstance(inputs, list):
            # New format: inputs is an array of input objects
            for input_obj in inputs:
                if isinstance(input_obj, dict) and "link" in input_obj:
                    analysis["connections"].append({
                        "from": "unknown",
                        "to": node_id,
                        "type": "connection"
                    })
        else:
            # Old format: inputs is a dict
            has_connections = False
            
            for param_name, param_value in inputs.items():
                # Check if this is a connection (array with node_id and output_index)
                if isinstance(param_value, list) and len(param_value) == 2:
                    source_node = param_value[0]
                    output_index = param_value[1]
                    analysis["connections"].append({
                        "from": source_node,
                        "to": node_id,
                        "output_index": output_index,
                        "input_param": param_name
                    })
                    has_connections = True
            
            # Identify input/output nodes (only for old format)
            if not has_connections:
                analysis["input_nodes"].append(node_id)
        
        # Identify common output node types
        if class_type in ["SaveImage", "PreviewImage", "Griptape Display: Text"]:
            analysis["output_nodes"].append(node_id)
    
    return analysis


def extract_models_from_workflow(workflow: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract model file references from loader nodes in ComfyUI workflows."""
    models = {
        'checkpoints': [],
        'loras': [],
        'vaes': [],
        'controlnets': [],
        'embeddings': [],
        'upscalers': []
    }
    
    # Handle both old format (nodes as dict keys) and new format (nodes array)
    nodes = []
    if 'nodes' in workflow and isinstance(workflow['nodes'], list):
        # New format: nodes array
        nodes = workflow['nodes']
    else:
        # Old format: nodes as dict keys
        nodes = [node_data for node_data in workflow.values() if isinstance(node_data, dict)]
    
    # Map node types to model categories
    loader_type_mapping = {
        'checkpoints': [
            'CheckpointLoaderSimple', 'CheckpointLoader', 'UNETLoader', 
            'DiffusionModelLoader', 'ModelLoader', 'CheckpointLoaderSD'
        ],
        'loras': [
            'LoraLoader', 'LoRALoader', 'LoraLoaderModelOnly',
            'LycorisLoader', 'AdaLORALoader'
        ],
        'vaes': [
            'VAELoader', 'VAELoaderSimple', 'VAEDecoder', 'VAEEncoder'
        ],
        'controlnets': [
            'ControlNetLoader', 'ControlNetLoaderSimple', 
            'ControlNetApply', 'ControlNetPreprocessor'
        ],
        'embeddings': [
            'EmbeddingLoader', 'TextualInversionLoader',
            'CLIPTextEncoder', 'CLIPLoader'
        ],
        'upscalers': [
            'UpscaleModelLoader', 'ESRGANLoader', 'RealESRGANLoader'
        ]
    }
    
    for node in nodes:
        node_type = node.get('type', '') or node.get('class_type', '')
        widget_values = node.get('widgets_values', [])
        inputs = node.get('inputs', {})
        
        # Only process loader nodes with model files
        for category, loader_types in loader_type_mapping.items():
            if any(loader in node_type for loader in loader_types):
                # Extract model filenames from widget_values (UI format)
                for value in widget_values:
                    if isinstance(value, str) and any(ext in value.lower() for ext in ['.safetensors', '.ckpt', '.pt', '.pth', '.bin']):
                        # Clean up the model name
                        model_name = value
                        if '/' in model_name:
                            model_name = model_name.split('/')[-1]
                        if '\\' in model_name:
                            model_name = model_name.split('\\')[-1]
                        
                        if model_name and model_name not in models[category]:
                            models[category].append(model_name)
                
                # Also extract from inputs (API format)
                for key, value in inputs.items():
                    if isinstance(value, str) and any(ext in value.lower() for ext in ['.safetensors', '.ckpt', '.pt', '.pth', '.bin']):
                        # Clean up the model name
                        model_name = value
                        if '/' in model_name:
                            model_name = model_name.split('/')[-1]
                        if '\\' in model_name:
                            model_name = model_name.split('\\')[-1]
                        
                        if model_name and model_name not in models[category]:
                            models[category].append(model_name)
                break  # Only categorize once per node
    
    # Remove empty categories and return
    return {k: v for k, v in models.items() if v}


def format_parameter_value(value: Any, indent: int = 0) -> str:
    """Format parameter values for display."""
    spaces = "  " * indent
    
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
            # This is a connection
            return f"**→ Node {value[0]}** (output {value[1]})"
        else:
            # Regular list
            if len(value) <= 5:
                return f"[{', '.join(str(v) for v in value)}]"
            else:
                return f"[{', '.join(str(v) for v in value[:3])}, ... (+{len(value)-3} more)]"
    elif isinstance(value, dict):
        if not value:
            return "{}"
        lines = [f"{spaces}  - **{k}**: {format_parameter_value(v, indent+1)}" for k, v in value.items()]
        return "\n" + "\n".join(lines)
    elif isinstance(value, str):
        if len(value) > 100:
            return f'"{value[:97]}..."'
        else:
            return f'"{value}"'
    else:
        return str(value)


def find_associated_image(json_path: str, search_dirs: List[str] = None, explicit_image: str = None) -> Optional[str]:
    """Find image associated with workflow JSON file."""
    import os
    from pathlib import Path
    
    # If explicit image provided, use it
    if explicit_image and os.path.exists(explicit_image):
        return explicit_image
    
    if search_dirs is None:
        search_dirs = [os.path.dirname(json_path)]
    
    json_stem = Path(json_path).stem
    image_extensions = ['.png', '.webp', '.jpg', '.jpeg']
    
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
            
        for ext in image_extensions:
            # Try exact match
            candidate = os.path.join(search_dir, f"{json_stem}{ext}")
            if os.path.exists(candidate):
                return candidate
            
            # Try pattern matching
            try:
                for img_file in os.listdir(search_dir):
                    if img_file.lower().endswith(tuple(image_extensions)):
                        img_stem = Path(img_file).stem
                        if json_stem.lower() in img_stem.lower() or img_stem.lower() in json_stem.lower():
                            return os.path.join(search_dir, img_file)
            except (OSError, PermissionError):
                continue
    
    return None


def generate_html_visual(workflow: Dict[str, Any], workflow_name: str = "Unknown Workflow", 
                        server_address: str = None, image_path: str = None) -> str:
    """Generate an interactive HTML visualization of the workflow using Tailwind CSS."""
    # Sort nodes by ID for consistent layout
    sorted_nodes = sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
    
    # Generate timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Prepare image section if image is provided
    import os
    import base64
    image_section = ""
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # Determine MIME type
            ext = os.path.splitext(image_path)[1].lower()
            mime_type = {
                '.png': 'image/png',
                '.webp': 'image/webp', 
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg'
            }.get(ext, 'image/png')
            
            image_data_url = f"data:{mime_type};base64,{image_data}"
            image_filename = os.path.basename(image_path)
            
            image_section = f'''
        <!-- Hero Image Section -->
        <div class="mb-8 bg-white rounded-lg shadow-sm border overflow-hidden">
            <div class="relative">
                <img src="{image_data_url}" 
                     alt="Generated Output" 
                     class="w-full max-h-96 object-contain bg-gray-50">
                <div class="absolute top-4 right-4">
                    <span class="bg-black bg-opacity-50 text-white px-2 py-1 rounded text-sm">
                        🖼️ Generated Output
                    </span>
                </div>
            </div>
            <div class="p-4 bg-gradient-to-r from-blue-50 to-purple-50">
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-lg font-semibold text-gray-900">Visual Result</h2>
                        <p class="text-sm text-gray-600">📁 {image_filename}</p>
                    </div>
                    <div class="text-right text-xs text-gray-500">
                        <div>This image was generated</div>
                        <div>using the workflow below</div>
                    </div>
                </div>
            </div>
        </div>
            '''
        except Exception as e:
            print(f"Warning: Could not load image {image_path}: {e}")
            image_section = f'''
        <!-- Image Load Error -->
        <div class="mb-8 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div class="flex items-center gap-2">
                <span class="text-yellow-600">⚠️</span>
                <div>
                    <h3 class="font-medium text-yellow-800">Image Not Available</h3>
                    <p class="text-sm text-yellow-700">Could not load: {os.path.basename(image_path)}</p>
                </div>
            </div>
        </div>
            '''
    
    # Try to get real dropdown values from server if available
    server_object_info = None
    if server_address:
        try:
            import requests
            response = requests.get(f"{server_address}/object_info", timeout=5)
            if response.status_code == 200:
                server_object_info = response.json()
                print(f"✓ Retrieved object info from {server_address}")
        except Exception as e:
            print(f"⚠️ Could not query server {server_address}: {e}")
    
    def get_dropdown_values(class_type: str, param_name: str) -> list:
        """Get actual dropdown values from server object info if available"""
        if not server_object_info:
            return []
        
        node_info = server_object_info.get(class_type, {})
        if not node_info:
            return []
            
        input_info = node_info.get("input", {})
        if not input_info:
            return []
            
        required_inputs = input_info.get("required", {})
        optional_inputs = input_info.get("optional", {})
        
        param_info = required_inputs.get(param_name) or optional_inputs.get(param_name)
        if not param_info or not isinstance(param_info, list) or len(param_info) == 0:
            return []
            
        # Check if first element is a list (dropdown options)
        if isinstance(param_info[0], list):
            return param_info[0]
            
        return []
    
    # Build HTML using simple string concatenation
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{workflow_name} - 💡 Comfy Light Table</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .copy-btn {{ 
            transition: all 0.2s; 
        }}
        .copy-btn:hover {{ 
            background-color: #3b82f6; 
            color: white; 
        }}
        .copy-success {{ 
            background-color: #10b981 !important; 
            color: white !important; 
        }}
        .dropdown-values {{ 
            max-height: 120px; 
            overflow-y: auto; 
        }}
    </style>
</head>
<body class="bg-gray-50 p-6">
    <div class="max-w-7xl mx-auto">
        <header class="mb-8">
            <div class="flex justify-between items-start mb-4">
                <div>
                    <h1 class="text-4xl font-bold text-gray-900 mb-2">{workflow_name}</h1>
                    <p class="text-lg text-gray-600">💡 Comfy Light Table</p>
                </div>
                <div class="text-right text-sm text-gray-500">
                    <div>Generated: {timestamp}</div>
                    <div class="mt-1">Quality of Life Improvements</div>
                </div>
            </div>
        </header>

        {image_section}

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
'''
    
    for node_id in sorted_nodes:
        node_data = workflow[node_id]
        class_type = node_data.get("class_type", "Unknown")
        title = node_data.get("_meta", {}).get("title", class_type)
        inputs = node_data.get("inputs", {})
        
        # Count parameters
        params = [k for k, v in inputs.items() if not (isinstance(v, list) and len(v) == 2)]
        connections = [k for k, v in inputs.items() if isinstance(v, list) and len(v) == 2]
        
        # Get key params for preview
        key_params = []
        for param in params[:3]:
            if param in inputs:
                value = str(inputs[param])
                if len(value) > 20:
                    value = value[:17] + "..."
                key_params.append(f"{param}: {value}")
        
        html += f'''
            <div class="bg-white rounded-lg shadow-sm border p-4 hover:shadow-md transition-shadow">
                <div class="flex items-center gap-2 mb-3">
                    <span class="text-2xl">⚙️</span>
                    <div>
                        <h3 class="font-bold text-lg text-gray-900">Node {node_id}</h3>
                        <p class="text-sm text-gray-600">{class_type}</p>
                    </div>
                </div>
                
                <h4 class="font-medium text-gray-800 mb-2">{title}</h4>
                
                <div class="text-xs text-gray-500 mb-3">
                    🔗 {len(connections)} inputs • ⚙️ {len(params)} params
                </div>
                '''
                
        if key_params:
            html += '<div class="bg-gray-50 rounded p-2 text-xs"><div class="font-medium mb-1">Key Parameters:</div>'
            for kp in key_params:
                html += f'<div>{kp}</div>'
            html += '</div>'
        
        html += '''
                <details class="mt-3">
                    <summary class="text-xs text-gray-600 cursor-pointer">All parameters</summary>
                    <div class="mt-2 text-xs space-y-1">
'''
        
        # Add all parameters with enhanced features
        for param_name, param_value in inputs.items():
            if isinstance(param_value, list) and len(param_value) == 2:
                # Connection parameter
                html += f'                        <div class="bg-blue-50 p-1 rounded flex justify-between"><span class="text-blue-700 font-medium">{param_name}:</span><span class="text-blue-600">→ Node {param_value[0]}</span></div>\n'
            else:
                # Direct parameter - add copy functionality
                value_str = str(param_value)
                full_value_str = value_str
                if len(value_str) > 30:
                    value_str = value_str[:27] + "..."

                # Escape display value for HTML attributes
                escaped_value = str(full_value_str).replace('"', '&quot;').replace("'", '&#39;')

                # Build the CLI copy command and ensure it is HTML-escaped for safe insertion
                copy_command = f'--node {node_id} --param {param_name} "{full_value_str}"'
                import html as _html
                escaped_copy_command = _html.escape(copy_command, quote=True)

                # Get real dropdown values from server if available
                dropdown_hint = ""
                dropdown_values = get_dropdown_values(class_type, param_name)
                
                if dropdown_values:
                    # We have real dropdown values from the server
                    values_preview = ', '.join(str(v) for v in dropdown_values[:5])
                    if len(dropdown_values) > 5:
                        values_preview += f', ... ({len(dropdown_values)} total)'
                    dropdown_hint = f' <span class="text-xs text-green-600 cursor-help" title="Valid options: {values_preview}">🔽</span>'
                elif param_name.endswith('_name') and param_name in ['sampler_name', 'scheduler', 'model_name', 'vae_name', 'lora_name']:
                    dropdown_hint = ' <span class="text-xs text-orange-600 cursor-help" title="Dropdown parameter - server query needed for valid options">⚠️</span>'
                elif param_name.endswith('_mode') or param_name.endswith('_method') or param_name.endswith('_type'):
                    dropdown_hint = ' <span class="text-xs text-orange-600 cursor-help" title="Parameter likely has predefined options">⚠️</span>'
                
                # Use data attributes instead of inline JavaScript to avoid quote issues
                copy_id = f"copy_{node_id}_{param_name.replace(' ', '_')}"
                html += f'''                        <div class="bg-gray-50 p-1 rounded">
                            <div class="flex justify-between items-center">
                                <span class="font-medium">{param_name}:</span>
                                <div class="flex items-center gap-1">
                                    <span class="text-gray-600 break-all" title="{escaped_value}">{value_str}</span>{dropdown_hint}
                                    <button class="copy-btn ml-1 px-1 py-0.5 text-xs bg-gray-200 rounded hover:bg-blue-500 hover:text-white transition-colors" 
                                            data-copy-text="{escaped_copy_command}"
                                            id="{copy_id}"
                                            aria-label="Copy command line argument">
                                        📋
                                    </button>
                                </div>
                            </div>
                        </div>
'''
        
        html += '''                    </div>
                </details>
            </div>
'''
    
    html += f'''
        </div>
        
        <div class="mt-8 p-6 bg-white rounded-lg shadow-sm border">
            <h3 class="text-xl font-semibold mb-4">Command Line Reference</h3>
            <div class="mb-4 p-3 bg-blue-50 rounded-lg">
                <div class="text-sm text-blue-800 font-medium mb-2">💡 Pro Tips:</div>
                <ul class="text-xs text-blue-700 space-y-1">
                    <li>• Click the 📋 button next to any parameter to copy its command line argument</li>
                    <li>• Look for 🔽 icons to see dropdown/enum parameter options</li>
                    <li>• Parameters with → symbols are connections to other nodes (not modifiable via CLI)</li>
                    <li>• Use "All parameters" details to see the full parameter name and value</li>
                </ul>
            </div>
            <div class="text-sm text-gray-600 mb-4">Example commands for key nodes:</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm font-mono">
'''
    
    # Add command reference
    for node_id in sorted_nodes[:10]:  # Show first 10 nodes
        node_data = workflow[node_id]
        class_type = node_data.get("class_type", "Unknown")
        inputs = node_data.get("inputs", {})
        params = [k for k, v in inputs.items() if not (isinstance(v, list) and len(v) == 2)]
        
        if params:
            html += f'''
                <div class="bg-gray-50 p-3 rounded">
                    <div class="text-gray-900 font-bold mb-1">Node {node_id} ({class_type})</div>
                    <div class="text-blue-600">--node {node_id} --param {params[0]} value</div>
                    <div class="text-xs text-gray-500 mt-1">Available: {', '.join(params[:3])}</div>
                </div>'''
    
    html += '''
            </div>
        </div>
    </div>

    <!-- Copy Success Toast -->
    <div id="copyToast" class="fixed top-4 right-4 bg-green-500 text-white px-4 py-2 rounded shadow-lg transform translate-x-full transition-transform duration-300 z-50">
        <div class="flex items-center gap-2">
            <span>✓</span>
            <span>Copied to clipboard!</span>
        </div>
    </div>

    <script>
        function copyToClipboard(text, button) {
            console.log('Copying text:', text);  // Debug log
            
            // Try modern clipboard API first
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(() => {
                    showCopySuccess(button);
                }).catch((err) => {
                    console.error('Clipboard API failed:', err);
                    fallbackCopy(text, button);
                });
            } else {
                // Use fallback method
                fallbackCopy(text, button);
            }
        }
        
        function fallbackCopy(text, button) {
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            
            try {
                const successful = document.execCommand('copy');
                if (successful) {
                    showCopySuccess(button);
                } else {
                    showCopyError(button);
                }
            } catch (err) {
                console.error('Fallback copy failed:', err);
                showCopyError(button);
            }
            
            document.body.removeChild(textArea);
        }
        
        function showCopySuccess(button) {
            const originalText = button.innerHTML;
            const originalClass = button.className;
            
            button.innerHTML = '✓';
            button.className = button.className.replace('bg-gray-200', 'bg-green-500 text-white');
            
            // Show toast
            const toast = document.getElementById('copyToast');
            if (toast) {
                toast.style.transform = 'translateX(0)';
                setTimeout(() => {
                    toast.style.transform = 'translateX(100%)';
                }, 2000);
            }
            
            setTimeout(() => {
                button.innerHTML = originalText;
                button.className = originalClass;
            }, 2000);
        }
        
        function showCopyError(button) {
            const originalText = button.innerHTML;
            button.innerHTML = '✗';
            button.style.backgroundColor = '#ef4444';
            button.style.color = 'white';
            
            setTimeout(() => {
                button.innerHTML = originalText;
                button.style.backgroundColor = '';
                button.style.color = '';
            }, 2000);
        }

        // Set up clipboard functionality for all copy buttons
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Setting up clipboard functionality...');
            
            // Add click handlers to all copy buttons
            document.querySelectorAll('.copy-btn').forEach(button => {
                button.addEventListener('click', function(e) {
                    e.preventDefault();
                    const textToCopy = this.getAttribute('data-copy-text');
                    console.log('Copy button clicked, text:', textToCopy);
                    copyToClipboard(textToCopy, this);
                });
            });
            
            console.log(`Found ${document.querySelectorAll('.copy-btn').length} copy buttons`);
        });
    </script>
    
    <!-- Footer -->
    <footer class="mt-16 py-8 border-t border-gray-200 text-center text-gray-500">
        <div class="flex items-center justify-center space-x-2">
            <span class="text-xl">💡</span>
            <span class="font-medium">Comfy Light Table</span>
            <span>•</span>
            <span class="text-sm">Quality of Life Improvements</span>
        </div>
        <div class="mt-2 text-xs">
            Built In Venice Beach • Workflow Analysis
        </div>
    </footer>
</body>
</html>'''
    
    return html


def generate_markdown_catalog(workflow: Dict[str, Any], output_format: str = "detailed") -> str:
    """Generate a Markdown catalog of the workflow."""
    analysis = analyze_workflow(workflow)
    
    # Header
    md = ["# ComfyUI Workflow Catalog\n"]
    
    # Overview section
    md.append("## Overview\n")
    md.append(f"- **Total Nodes**: {analysis['total_nodes']}")
    md.append(f"- **Input Nodes**: {len(analysis['input_nodes'])} ({', '.join(analysis['input_nodes'])})")
    md.append(f"- **Output Nodes**: {len(analysis['output_nodes'])} ({', '.join(analysis['output_nodes'])})")
    md.append(f"- **Connections**: {len(analysis['connections'])}")
    md.append("")
    
    # Node types summary
    md.append("### Node Types\n")
    for node_type, count in sorted(analysis["node_types"].items()):
        md.append(f"- **{node_type}**: {count} node{'s' if count > 1 else ''}")
    md.append("")
    
    if output_format == "table":
        # Table format
        md.append("## Nodes (Table Format)\n")
        md.append("| Node ID | Type | Title | Key Parameters |")
        md.append("|---------|------|-------|----------------|")
        
        for node_id in sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else float('inf')):
            node_data = workflow[node_id]
            class_type = node_data.get("class_type", "Unknown")
            title = node_data.get("_meta", {}).get("title", class_type)
            
            # Get key parameters (non-connection inputs)
            inputs = node_data.get("inputs", {})
            key_params = []
            for param_name, param_value in inputs.items():
                if not (isinstance(param_value, list) and len(param_value) == 2):
                    if isinstance(param_value, str) and len(param_value) > 50:
                        key_params.append(f"{param_name}: {param_value[:47]}...")
                    else:
                        key_params.append(f"{param_name}: {param_value}")
            
            params_str = "; ".join(key_params[:3])  # Limit to first 3 params
            if len(key_params) > 3:
                params_str += f" (+{len(key_params)-3} more)"
            
            md.append(f"| {node_id} | {class_type} | {title} | {params_str} |")
        
        md.append("")
    
    else:
        # Detailed format
        md.append("## Node Details\n")
        
        # Sort nodes by ID (numeric first, then others)
        sorted_nodes = sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
        
        for node_id in sorted_nodes:
            node_data = workflow[node_id]
            class_type = node_data.get("class_type", "Unknown")
            title = node_data.get("_meta", {}).get("title", class_type)
            
            md.append(f"### Node {node_id}: {title}")
            md.append(f"**Type**: `{class_type}`\n")
            
            # Inputs section
            inputs = node_data.get("inputs", {})
            if inputs:
                md.append("**Inputs**:")
                
                # Separate connections from parameters
                connections = []
                parameters = []
                
                for param_name, param_value in inputs.items():
                    if isinstance(param_value, list) and len(param_value) == 2:
                        connections.append((param_name, param_value))
                    else:
                        parameters.append((param_name, param_value))
                
                # Show connections first
                if connections:
                    md.append("  - *Connections*:")
                    for param_name, param_value in connections:
                        md.append(f"    - **{param_name}**: {format_parameter_value(param_value)}")
                
                # Then show parameters
                if parameters:
                    if connections:
                        md.append("  - *Parameters*:")
                    for param_name, param_value in parameters:
                        formatted_value = format_parameter_value(param_value)
                        md.append(f"    - **{param_name}**: {formatted_value}")
            else:
                md.append("**Inputs**: None")
            
            md.append("")
    
    # Connection flow section
    if analysis["connections"]:
        md.append("## Data Flow\n")
        md.append("```mermaid")
        md.append("graph TD")
        
        # Add nodes
        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "Unknown")
            title = node_data.get("_meta", {}).get("title", class_type)
            # Simplify title for mermaid
            simple_title = title.replace(" ", "_").replace(":", "").replace("(", "").replace(")", "")
            md.append(f"    {node_id}[\"{node_id}: {simple_title}\"]")
        
        # Add connections
        for conn in analysis["connections"]:
            md.append(f"    {conn['from']} -->|{conn['input_param']}| {conn['to']}")
        
        md.append("```\n")
    
    # Quick reference section
    md.append("## Quick Reference\n")
    md.append("### Parameterizable Nodes\n")
    md.append("Nodes that can be modified via command line:\n")
    
    for node_id in sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else float('inf')):
        node_data = workflow[node_id]
        class_type = node_data.get("class_type", "Unknown")
        inputs = node_data.get("inputs", {})
        
        # Find non-connection parameters
        params = []
        for param_name, param_value in inputs.items():
            if not (isinstance(param_value, list) and len(param_value) == 2):
                params.append(param_name)
        
        if params:
            md.append(f"- **Node {node_id}** ({class_type}): `{', '.join(params)}`")
    
    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a human-readable catalog of a ComfyUI workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file mode
  %(prog)s workflow.json
  %(prog)s image.png --format html --output workflow.html
  
  # Directory scanning mode (default: shows ALL files)
  %(prog)s --directory /path/to/comfyui/outputs --output-dir ./web_catalog
  %(prog)s --ingest ./test-images --extensions .png .webp --master-catalog gallery.html
  %(prog)s -d ./test-images --extensions .png .webp --master-catalog gallery.html
  
  # Show only files with workflows
  %(prog)s --ingest ./test-images --workflows-only --output-dir ./workflows-catalog
  
  # Database integration (generates catalogs AND stores in database)
  %(prog)s --directory ./outputs --database --tags "batch-import,project-alpha"
  %(prog)s --directory ./outputs --database "my_catalog.db" --collections "personal-art"
  %(prog)s --directory ./outputs --database "sqlite:///full/path/catalog.db" --tags "archived"
        """
    )
    
    parser.add_argument('input', nargs='?', help='Path to workflow JSON file or PNG/WebP image with embedded workflow')
    parser.add_argument('--directory', '-d', '--ingest', help='Scan directory hierarchy for ComfyUI images')
    parser.add_argument('--output', '-o', help='Output file (default: print to stdout for single file mode)')
    parser.add_argument('--output-dir', help='Output directory for generated catalogs (default: ./catalogs)')
    parser.add_argument('--master-catalog', help='Name for master catalog HTML (default: index.html)')
    parser.add_argument('--extensions', nargs='+', default=['.png', '.webp', '.jpg', '.jpeg'], 
                       help='Image extensions to scan (default: .png .webp .jpg .jpeg)')
    parser.add_argument('--workflows-only', action='store_true',
                       help='Only show files with workflows (default: show all files including failures)')
    parser.add_argument('--comprehensive-diagnostics', action='store_true', 
                       help='[DEPRECATED] Use default behavior instead - comprehensive mode is now default')
    parser.add_argument('--format', choices=['detailed', 'table', 'html'], default='html',
                       help='Output format: detailed (markdown), table (markdown), html (interactive)')
    parser.add_argument('--server', help='ComfyUI server address (e.g., http://127.0.0.1:8188) for querying real dropdown values')
    parser.add_argument('--image', help='Associated image file to display with workflow (for JSON inputs)')
    parser.add_argument('--image-dir', help='Directory to search for associated images')
    parser.add_argument('--database', '--db', nargs='?', const=True, help='Store workflows in database (provide filename for SQLite, full URL for other databases, or use default)')
    parser.add_argument('--tags', help='Comma-separated tags to add to database entries')
    parser.add_argument('--collections', help='Comma-separated collections to add to database entries')
    parser.add_argument('--notes', help='Notes to add to database entries')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.directory and not args.input:
        parser.error("Must specify either input file or --directory")
    
    if args.directory and args.input:
        parser.error("Cannot specify both input file and --directory")
    
    if args.directory:
        return directory_scan_mode(args)
    else:
        return single_file_mode(args)


def load_workflow_cache(output_dir: Path) -> Dict:
    """Load workflow cache to avoid reprocessing unchanged images."""
    cache_file = output_dir / ".workflow_cache.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Could not load cache: {e}")
    return {}


def save_workflow_cache(output_dir: Path, cache_data: Dict):
    """Save workflow cache for future runs."""
    cache_file = output_dir / ".workflow_cache.json"
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save cache: {e}")


def detect_comfyui_images_with_cache(image_paths: List[Path], cache: Dict) -> List[WorkflowImageData]:
    """Batch process images with caching support."""
    workflow_images = []
    cache_updated = False
    
    print(f"🔬 Analyzing {len(image_paths)} images for ComfyUI workflows...")
    
    # Progress tracking
    processed_count = 0
    found_count = 0
    cached_count = 0
    
    for i, image_path in enumerate(image_paths, 1):
        # Show progress with percentage
        progress = f"({i}/{len(image_paths)} - {i/len(image_paths)*100:.1f}%)"
        print(f"  📊 Processing {progress}: {image_path.name}")
        
        # Check cache first
        image_key = str(image_path)
        image_stat = image_path.stat()
        image_mtime = image_stat.st_mtime
        
        if image_key in cache:
            cached_entry = cache[image_key]
            if cached_entry.get('mtime') == image_mtime and cached_entry.get('workflow'):
                # Use cached workflow
                try:
                    metadata = extract_image_metadata(image_path)
                    workflow_data = WorkflowImageData(
                        image_path=image_path,
                        workflow=cached_entry['workflow'],
                        metadata=metadata
                    )
                    workflow_images.append(workflow_data)
                    found_count += 1
                    cached_count += 1
                    print(f"    ♻️ Used cached workflow with {len(cached_entry['workflow'])} nodes")
                    processed_count += 1
                    continue
                except Exception as e:
                    print(f"    ⚠️ Cache entry corrupted, reprocessing: {e}")
        
        # Extract workflow from image
        workflow = extract_workflow_from_image(image_path)
        
        # Update cache
        cache[image_key] = {
            'mtime': image_mtime,
            'workflow': workflow,
            'processed_at': datetime.now().isoformat()
        }
        cache_updated = True
        
        if workflow:
            # Extract additional metadata
            metadata = extract_image_metadata(image_path)
            
            workflow_data = WorkflowImageData(
                image_path=image_path,
                workflow=workflow,
                metadata=metadata
            )
            workflow_images.append(workflow_data)
            found_count += 1
            print(f"    ✅ Found workflow with {len(workflow)} nodes")
        else:
            print(f"    ❌ No ComfyUI workflow found")
        
        processed_count += 1
        
        # Show summary every 10 images for large batches
        if processed_count % 10 == 0 and len(image_paths) > 20:
            hit_rate = found_count / processed_count * 100
            print(f"  📈 Progress: {found_count}/{processed_count} workflows ({hit_rate:.1f}% hit rate, {cached_count} cached)")
    
    hit_rate = found_count / len(image_paths) * 100 if image_paths else 0
    print(f"🎯 Found {len(workflow_images)} images with ComfyUI workflows ({hit_rate:.1f}% hit rate)")
    if cached_count > 0:
        print(f"♻️ Used {cached_count} cached results, processed {processed_count - cached_count} new images")
    
    return workflow_images, cache_updated


def comprehensive_batch_analysis(image_paths: List[Path], cache: Dict) -> Tuple[List[FileAnalysisResult], Dict]:
    """Comprehensive analysis including both successful and failed workflow extractions."""
    analysis_results = []
    found_count = 0
    processed_count = 0
    cached_count = 0
    cache_updated = False
    
    print(f"🔬 Comprehensive analysis of {len(image_paths)} images...")
    
    for i, image_path in enumerate(image_paths, 1):
        progress = (i / len(image_paths)) * 100
        print(f"  📊 Processing ({i}/{len(image_paths)} - {progress:.1f}%): {image_path.name}")
        
        try:
            file_size = image_path.stat().st_size
            file_type = mimetypes.guess_type(str(image_path))[0] or "unknown"
            
            # Check cache first
            image_key = f"{image_path}:{file_size}"
            image_mtime = image_path.stat().st_mtime
            
            workflow = None
            metadata = None
            error_message = None
            
            if image_key in cache:
                cached_entry = cache[image_key]
                if cached_entry.get('mtime') == image_mtime:
                    workflow = cached_entry.get('workflow')
                    cached_count += 1
                    if workflow:
                        print(f"    ♻️ Used cached workflow with {len(workflow)} nodes")
                    else:
                        print(f"    ♻️ Used cached result: No workflow found")
                        error_message = "No ComfyUI workflow found in image metadata (cached result)"
                else:
                    # Cache entry is stale, need to reprocess
                    workflow = None
            
            if workflow is None and (image_key not in cache or cache[image_key].get('mtime') != image_mtime):
                # Extract workflow from image
                try:
                    workflow = extract_workflow_from_image(image_path)
                    if workflow:
                        metadata = extract_image_metadata(image_path)
                        print(f"    ✅ Found workflow with {len(workflow)} nodes")
                    else:
                        error_message = "No ComfyUI workflow found in image metadata"
                        print(f"    ❌ No ComfyUI workflow found")
                except Exception as e:
                    error_message = f"Error extracting workflow: {str(e)}"
                    print(f"    ❌ Error: {error_message}")
                
                # Update cache
                cache[image_key] = {
                    'mtime': image_mtime,
                    'workflow': workflow,
                    'processed_at': datetime.now().isoformat()
                }
                cache_updated = True
            
            # Create analysis result
            analysis_result = FileAnalysisResult(
                file_path=image_path,
                success=workflow is not None,
                workflow=workflow,
                metadata=metadata,
                error_message=error_message,
                file_size=file_size,
                file_type=file_type
            )
            analysis_results.append(analysis_result)
            
            if workflow:
                found_count += 1
                
        except Exception as e:
            error_message = f"Error processing file: {str(e)}"
            print(f"    ❌ Error: {error_message}")
            
            analysis_result = FileAnalysisResult(
                file_path=image_path,
                success=False,
                error_message=error_message,
                file_size=0,
                file_type="unknown"
            )
            analysis_results.append(analysis_result)
        
        processed_count += 1
        
        # Show progress every 10 images or every 25%
        if i % 10 == 0 or i % max(1, len(image_paths) // 4) == 0:
            hit_rate = (found_count / processed_count) * 100 if processed_count > 0 else 0
            print(f"  📈 Progress: {found_count}/{processed_count} workflows ({hit_rate:.1f}% hit rate, {cached_count} cached)")
    
    hit_rate = (found_count / len(image_paths)) * 100 if image_paths else 0
    success_count = sum(1 for r in analysis_results if r.success)
    print(f"🎯 Analysis complete: {success_count}/{len(analysis_results)} files with workflows ({hit_rate:.1f}% hit rate)")
    if cached_count > 0:
        print(f"♻️ Used {cached_count} cached results, processed {processed_count - cached_count} new files")
    
    return analysis_results, cache


def directory_scan_mode(args):
    """Handle directory scanning and catalog generation."""
    directory = Path(args.directory)
    if not directory.exists() or not directory.is_dir():
        print(f"Error: Directory not found: {directory}", file=sys.stderr)
        return 1
    
    # Set up output directory
    output_dir = Path(args.output_dir) if args.output_dir else Path("./catalogs")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"🚀 Starting directory scan mode")
    print(f"📂 Input directory: {directory}")
    print(f"📁 Output directory: {output_dir}")
    if args.workflows_only:
        print("🎯 Workflows-only mode: showing only files with embedded workflows")
    else:
        print("🔬 Comprehensive mode: showing all files (including those without workflows)")
    
    # Handle deprecated flag
    if args.comprehensive_diagnostics:
        print("⚠️  --comprehensive-diagnostics is deprecated (comprehensive mode is now default)")
    
    # Load cache
    cache = load_workflow_cache(output_dir)
    print(f"♻️ Loaded cache with {len(cache)} entries")
    
    # Initialize database if requested or available
    workflow_manager = None
    database_enabled = False
    
    # Check for explicit --database flag
    if hasattr(args, 'database') and args.database is not None:
        database_url = args.database if args.database != True else None
        workflow_manager = get_database_workflow_manager(database_url)
        database_enabled = workflow_manager is not None
        if database_enabled:
            print(f"💾 Database enabled: storing workflows in database")
        else:
            print(f"⚠️ Database requested but not available")
    
    # Auto-detect database if not explicitly disabled
    elif DATABASE_AVAILABLE:
        workflow_manager = get_database_workflow_manager()
        database_enabled = workflow_manager is not None
        if database_enabled:
            print(f"💾 Database auto-detected: storing workflows in database")
    
    # Parse additional database metadata
    tags = []
    if hasattr(args, 'tags') and args.tags:
        tags = [tag.strip() for tag in args.tags.split(',')]
    
    collections = []
    if hasattr(args, 'collections') and args.collections:
        collections = [col.strip() for col in args.collections.split(',')]
    
    notes = getattr(args, 'notes', None)
    
    # Phase 1: Scan for images
    image_paths = scan_directory_for_images(directory, args.extensions)
    if not image_paths:
        print("❌ No images found in directory")
        return 1
    
    # Phase 2: Extract workflows with caching
    if args.workflows_only:
        # Limited mode - only successful extractions
        workflow_images, cache_updated = detect_comfyui_images_with_cache(image_paths, cache)
        if not workflow_images:
            print("❌ No ComfyUI workflows found in any images")
            return 1
        analysis_results = None
        
    else:
        # Default: Comprehensive analysis including failed extractions
        analysis_results, cache = comprehensive_batch_analysis(image_paths, cache)
        
        # Extract successful workflows for individual catalog generation
        workflow_images = []
        for result in analysis_results:
            if result.success and result.workflow:
                workflow_data = WorkflowImageData(
                    image_path=result.file_path,
                    workflow=result.workflow,
                    metadata=result.metadata or {}
                )
                workflow_images.append(workflow_data)
        
        cache_updated = True  # comprehensive_batch_analysis updates cache
        
        # In comprehensive mode, continue even if no workflows found (to show all files)
        # This allows us to see the files that failed workflow extraction
    
    # Save cache if updated
    if cache_updated:
        save_workflow_cache(output_dir, cache)
    
    # Phase 2.5: Store workflows in database if enabled
    if database_enabled and workflow_images:
        print(f"\n💾 Storing {len(workflow_images)} workflows in database...")
        stored_count = 0
        for workflow_data in workflow_images:
            success = store_workflow_in_database(
                workflow_manager=workflow_manager,
                workflow_data=workflow_data,
                tags=tags,
                collections=collections,
                notes=notes
            )
            if success:
                stored_count += 1
        
        print(f"✅ Stored {stored_count}/{len(workflow_images)} workflows in database")
        if stored_count < len(workflow_images):
            print(f"⚠️ {len(workflow_images) - stored_count} workflows failed to store (possibly duplicates)")
    
    # Phase 3: Generate individual catalogs for successful workflows
    individual_pages = generate_individual_catalogs(workflow_images, output_dir, args.server)
    
    # Phase 4: Generate master catalog
    master_catalog_name = args.master_catalog or "index.html"
    
    # Choose catalog type based on database availability
    if database_enabled and workflow_images:
        # NEW: Generate database-powered interactive catalog
        print(f"\n💾 Generating database-powered interactive catalog...")
        try:
            from database_catalog_generator import generate_database_catalog_from_cli_args
            return generate_database_catalog_from_cli_args(args)
        except ImportError:
            print(f"⚠️ Database catalog generator not available, falling back to static catalog")
            # Fall through to static catalog generation
    
    # LEGACY: Generate static HTML catalog
    if args.workflows_only or not analysis_results:
        # Limited catalog with only successful workflows
        master_path = generate_master_catalog(workflow_images, individual_pages, output_dir, master_catalog_name)
    else:
        # Default: Comprehensive catalog with all files
        master_path = generate_comprehensive_master_catalog(analysis_results, individual_pages, output_dir, master_catalog_name)
    
    print(f"\n🎉 Catalog generation complete!")
    print(f"📊 Processed {len(workflow_images)} workflows")
    print(f"🌐 Master catalog: {master_path}")
    print(f"📁 Individual catalogs: {len(individual_pages)} files")
    
    return 0


def generate_individual_catalogs(workflow_images: List[WorkflowImageData], output_dir: Path, server_address: str = None) -> List[str]:
    """Generate individual HTML catalog pages for each workflow."""
    workflows_dir = output_dir / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    
    individual_pages = []
    
    print(f"📄 Generating individual workflow catalogs...")
    
    for i, workflow_data in enumerate(workflow_images, 1):
        # Generate safe filename
        base_name = workflow_data.image_path.stem
        safe_name = "".join(c for c in base_name if c.isalnum() or c in ('-', '_'))
        catalog_filename = f"{safe_name}_workflow.html"
        catalog_path = workflows_dir / catalog_filename
        
        print(f"  📝 {i}/{len(workflow_images)}: {catalog_filename}")
        
        # Generate workflow name
        workflow_name = base_name.replace('_', ' ').replace('-', ' ').title()
        
        # Generate HTML catalog
        html_content = generate_html_visual(
            workflow_data.workflow,
            workflow_name,
            server_address,
            str(workflow_data.image_path)
        )
        
        # Add navigation back to master catalog
        html_content = add_navigation_to_catalog(html_content)
        
        # Write to file
        with open(catalog_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Store relative path for master catalog
        relative_path = f"workflows/{catalog_filename}"
        individual_pages.append(relative_path)
        workflow_data.catalog_path = catalog_path
    
    print(f"✅ Generated {len(individual_pages)} individual catalogs")
    return individual_pages


def add_navigation_to_catalog(html_content: str) -> str:
    """Add navigation breadcrumb to individual catalog pages."""
    nav_html = '''
    <!-- Navigation Breadcrumb -->
    <nav class="mb-6 p-4 bg-white rounded-lg shadow-sm border">
        <div class="flex items-center gap-2 text-sm">
            <a href="../index.html" class="text-blue-600 hover:text-blue-800 flex items-center gap-1">
                ← Back to Catalog
            </a>
            <span class="text-gray-400">/</span>
            <span class="text-gray-600">Workflow Details</span>
        </div>
    </nav>
    '''
    
    # Insert navigation after the header
    header_end = html_content.find('</header>')
    if header_end != -1:
        return html_content[:header_end + 9] + nav_html + html_content[header_end + 9:]
    
    # Fallback: insert after opening body tag
    body_start = html_content.find('<div class="max-w-7xl mx-auto">')
    if body_start != -1:
        return html_content[:body_start] + nav_html + html_content[body_start:]
    
    return html_content


def generate_master_catalog(workflow_images: List[WorkflowImageData], individual_pages: List[str], 
                          output_dir: Path, master_catalog_name: str) -> Path:
    """Generate master catalog with masonry grid layout."""
    master_path = output_dir / master_catalog_name
    
    print(f"🏗️ Generating master catalog: {master_catalog_name}")
    
    # Generate HTML content
    html_content = generate_master_catalog_html(workflow_images, individual_pages)
    
    # Write to file
    with open(master_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Master catalog created: {master_path}")
    return master_path


def generate_comprehensive_master_catalog(analysis_results: List[FileAnalysisResult], individual_pages: List[str], 
                                        output_dir: Path, master_catalog_name: str) -> Path:
    """Generate comprehensive master catalog showing all files with diagnostic information."""
    master_path = output_dir / master_catalog_name
    
    print(f"🏗️ Generating comprehensive master catalog: {master_catalog_name}")
    
    # Generate HTML content
    html_content = generate_comprehensive_master_catalog_html(analysis_results, individual_pages)
    
    # Write to file
    with open(master_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Comprehensive master catalog created: {master_path}")
    return master_path


def generate_master_catalog_html(workflow_images: List[WorkflowImageData], individual_pages: List[str]) -> str:
    """Generate the HTML content for the master catalog."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Collect all unique models, LoRAs, and node types for filter dropdowns
    all_checkpoints = set()
    all_loras = set()
    all_node_types = set()
    
    for workflow_data in workflow_images:
        if workflow_data.workflow:
            # Extract models and node types (use same logic as card generation)
            if hasattr(workflow_data, 'original_workflow') and workflow_data.original_workflow:
                workflow_for_models = workflow_data.original_workflow
            else:
                workflow_for_models = extract_workflow_from_image(workflow_data.image_path, preserve_original_format=True)
                if not workflow_for_models:
                    workflow_for_models = workflow_data.workflow
            
            models = extract_models_from_workflow(workflow_for_models)
            analysis = analyze_workflow(workflow_data.workflow)
            
            # Separate checkpoints and LoRAs
            all_checkpoints.update(models.get('checkpoints', []))
            all_loras.update(models.get('loras', []))
            
            # Add all node types
            all_node_types.update(analysis["node_types"].keys())
    
    # Sort for consistent display
    sorted_models = sorted(all_checkpoints)
    sorted_loras = sorted(all_loras)
    sorted_node_types = sorted(all_node_types)
    
    # Pre-generate filter options to avoid nested f-string issues
    checkpoint_options = ''.join(f'<option value="{model}">{model}</option>' for model in sorted_models)
    lora_options = ''.join(f'<option value="{lora}">{lora}</option>' for lora in sorted_loras)
    node_type_options = ''.join(f'<option value="{node_type}">{node_type}</option>' for node_type in sorted_node_types)
    
    # Generate cards HTML with model and node type data
    cards_html = ""
    for workflow_data, page_path in zip(workflow_images, individual_pages):
        cards_html += generate_master_catalog_card(workflow_data, page_path)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ComfyUI Workflow Catalog</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .masonry-grid {{
            column-count: 4;
            column-gap: 1.5rem;
            column-fill: balance;
        }}
        
        .masonry-item {{
            break-inside: avoid;
            margin-bottom: 1.5rem;
        }}
        
        @media (max-width: 1024px) {{
            .masonry-grid {{ column-count: 3; }}
        }}
        
        @media (max-width: 768px) {{
            .masonry-grid {{ column-count: 2; }}
        }}
        
        @media (max-width: 640px) {{
            .masonry-grid {{ column-count: 1; }}
        }}
        
        .card-hover {{
            transition: all 0.3s ease;
        }}
        
        .card-hover:hover {{
            transform: translateY(-4px);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        }}
    </style>
</head>
<body class="bg-gray-50 p-6">
    <div class="max-w-7xl mx-auto">
        <!-- Header -->
        <header class="mb-8 text-center">
            <h1 class="text-4xl font-bold text-gray-900 mb-2">ComfyUI Workflow Catalog</h1>
            <div class="flex justify-center items-center gap-6 text-sm text-gray-500">
                <div class="flex items-center gap-2">
                    <span class="text-2xl">🖼️</span>
                    <span>{len(workflow_images)} Workflows</span>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-2xl">📅</span>
                    <span>Generated: {timestamp}</span>
                </div>
            </div>
        </header>
        
        <!-- Statistics Dashboard -->
        <div class="mb-6 grid grid-cols-1 md:grid-cols-4 gap-4">
            <div class="bg-white rounded-lg shadow-sm border p-4 text-center">
                <div class="text-2xl font-bold text-blue-600">{len(workflow_images)}</div>
                <div class="text-sm text-gray-600">Workflows</div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border p-4 text-center">
                <div class="text-2xl font-bold text-green-600">{sum(len(w.workflow) for w in workflow_images)}</div>
                <div class="text-sm text-gray-600">Total Nodes</div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border p-4 text-center">
                <div class="text-2xl font-bold text-purple-600">{len(set(nt for w in workflow_images for nt in w.workflow_summary["node_types"]))}</div>
                <div class="text-sm text-gray-600">Node Types</div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border p-4 text-center">
                <div class="text-2xl font-bold text-orange-600">{sum(w.workflow_summary["connections"] for w in workflow_images)}</div>
                <div class="text-sm text-gray-600">Connections</div>
            </div>
        </div>

        <!-- Search and Filter Bar -->
        <div class="mb-8 bg-white rounded-lg shadow-sm border p-4">
            <div class="flex flex-wrap gap-4 items-center">
                <div class="flex-1 min-w-64">
                    <input type="text" id="searchInput" placeholder="Search workflows by name or node type..." 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>
                <div class="flex gap-2">
                    <select id="checkpointFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All Checkpoints</option>
                        {checkpoint_options}
                    </select>
                    <select id="loraFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All LoRAs</option>
                        {lora_options}
                    </select>
                    <select id="nodeTypeFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All Node Types</option>
                        {node_type_options}
                    </select>
                    <button onclick="resetFilters()" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200">
                        Reset
                    </button>
                </div>
            </div>
        </div>
        
        <!-- Masonry Grid -->
        <div class="masonry-grid" id="workflowGrid">
            {cards_html}
        </div>
        
        <!-- No Results Message -->
        <div id="noResults" class="hidden text-center py-12">
            <div class="text-gray-400 text-6xl mb-4">🔍</div>
            <h3 class="text-xl font-semibold text-gray-600 mb-2">No workflows found</h3>
            <p class="text-gray-500">Try adjusting your search terms or filters</p>
        </div>
    </div>

    <script>
        // Search and filter functionality
        const searchInput = document.getElementById('searchInput');
        const checkpointFilter = document.getElementById('checkpointFilter');
        const loraFilter = document.getElementById('loraFilter');
        const nodeTypeFilter = document.getElementById('nodeTypeFilter');
        const workflowGrid = document.getElementById('workflowGrid');
        const noResults = document.getElementById('noResults');
        
        let allCards = Array.from(document.querySelectorAll('.masonry-item'));
        
        function filterCards() {{
            const searchTerm = searchInput.value.toLowerCase();
            const checkpointFilter_value = checkpointFilter.value;
            const loraFilter_value = loraFilter.value;
            const nodeTypeFilter_value = nodeTypeFilter.value;
            
            // Filter cards
            let visibleCards = allCards.filter(card => {{
                const text = card.textContent.toLowerCase();
                const cardCheckpoints = (card.dataset.checkpoints || '').split(',').filter(c => c.trim());
                const cardLoras = (card.dataset.loras || '').split(',').filter(l => l.trim());
                const cardNodeTypes = (card.dataset.nodeTypes || '').split(',');
                
                const matchesSearch = text.includes(searchTerm);
                const matchesCheckpoint = !checkpointFilter_value || cardCheckpoints.includes(checkpointFilter_value);
                const matchesLora = !loraFilter_value || cardLoras.includes(loraFilter_value);
                const matchesNodeType = !nodeTypeFilter_value || cardNodeTypes.includes(nodeTypeFilter_value);
                
                return matchesSearch && matchesCheckpoint && matchesLora && matchesNodeType;
            }});
            
            // Update display (no sorting needed)
            allCards.forEach(card => card.style.display = 'none');
            visibleCards.forEach(card => card.style.display = 'block');
            
            // Show/hide no results message
            if (visibleCards.length === 0) {{
                noResults.classList.remove('hidden');
                workflowGrid.style.display = 'none';
            }} else {{
                noResults.classList.add('hidden');
                workflowGrid.style.display = 'block';
            }}
        }}
        
        function resetFilters() {{
            searchInput.value = '';
            checkpointFilter.value = '';
            loraFilter.value = '';
            nodeTypeFilter.value = '';
            filterCards();
        }}
        
        // Event listeners
        searchInput.addEventListener('input', filterCards);
        checkpointFilter.addEventListener('change', filterCards);
        loraFilter.addEventListener('change', filterCards);
        nodeTypeFilter.addEventListener('change', filterCards);
    </script>
    
    <!-- Footer -->
    <footer class="mt-16 py-8 border-t border-gray-200 text-center text-gray-500">
        <div class="flex items-center justify-center space-x-2">
            <span class="text-xl">💡</span>
            <span class="font-medium">Comfy Light Table</span>
            <span>•</span>
            <span class="text-sm">Quality of Life Improvements</span>
        </div>
        <div class="mt-2 text-xs">
            Built In Venice Beach • Workflow Analysis
        </div>
    </footer>
</body>
</html>'''
    
    return html


def generate_comprehensive_master_catalog_html(analysis_results: List[FileAnalysisResult], individual_pages: List[str]) -> str:
    """Generate comprehensive HTML content showing all files with diagnostics."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Categorize results
    workflow_files = [r for r in analysis_results if r.has_workflow]
    image_no_workflow = [r for r in analysis_results if r.is_image and not r.has_workflow]
    other_files = [r for r in analysis_results if not r.is_image]
    
    # Generate cards HTML for all files
    all_cards_html = ""
    
    # Add workflow files first (with links to individual pages)
    for i, result in enumerate(workflow_files):
        page_path = individual_pages[i] if i < len(individual_pages) else "#"
        all_cards_html += generate_comprehensive_catalog_card(result, page_path, 'workflow')
    
    # Add images without workflows (with diagnostic info)
    for result in image_no_workflow:
        all_cards_html += generate_comprehensive_catalog_card(result, None, 'image_no_workflow')
    
    # Add other files
    for result in other_files:
        all_cards_html += generate_comprehensive_catalog_card(result, None, 'other_file')
    
    # Collect all models and node types from workflow files for filtering
    all_checkpoints = set()
    all_loras = set()
    all_node_types = set()
    
    for result in workflow_files:
        if result.models:
            all_checkpoints.update(result.models.get('checkpoints', []))
            all_loras.update(result.models.get('loras', []))
        
        if result.node_types:
            all_node_types.update(result.node_types)
    
    # Generate filter options HTML
    checkpoint_options = ''.join([f'<option value="{model}">{model}</option>' for model in sorted(all_checkpoints)])
    lora_options = ''.join([f'<option value="{lora}">{lora}</option>' for lora in sorted(all_loras)])
    node_options = ''.join([f'<option value="{node_type}">{node_type}</option>' for node_type in sorted(all_node_types)])
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ComfyUI Light Table</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .masonry-grid {{
            column-count: 4;
            column-gap: 1.5rem;
            column-fill: balance;
        }}
        
        .masonry-item {{
            break-inside: avoid;
            margin-bottom: 1.5rem;
        }}
        
        @media (max-width: 1024px) {{
            .masonry-grid {{ column-count: 3; }}
        }}
        
        @media (max-width: 768px) {{
            .masonry-grid {{ column-count: 2; }}
        }}
        
        @media (max-width: 640px) {{
            .masonry-grid {{ column-count: 1; }}
        }}
        
        .card-hover {{
            transition: all 0.3s ease;
        }}
        
        .card-hover:hover {{
            transform: translateY(-4px);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        }}
        
        .diagnostic-tooltip {{
            max-width: 300px;
        }}
    </style>
</head>
<body class="bg-gray-50 p-6">
    <div class="max-w-7xl mx-auto">
        <!-- Header -->
        <header class="mb-8 text-center">
            <h1 class="text-4xl font-bold text-gray-900 mb-2">ComfyUI Light Table</h1>
            <p class="text-lg text-gray-600 mb-4">Complete analysis of all files with diagnostic information</p>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm text-gray-600 max-w-2xl mx-auto">
                <div class="flex items-center gap-2 justify-center">
                    <span class="w-3 h-3 bg-green-500 rounded-full"></span>
                    <span>{len(workflow_files)} With Workflows</span>
                </div>
                <div class="flex items-center gap-2 justify-center">
                    <span class="w-3 h-3 bg-yellow-500 rounded-full"></span>
                    <span>{len(image_no_workflow)} Images (No Workflow)</span>
                </div>
                <div class="flex items-center gap-2 justify-center">
                    <span class="w-3 h-3 bg-blue-500 rounded-full"></span>
                    <span>{len(other_files)} Other Files</span>
                </div>
                <div class="flex items-center gap-2 justify-center">
                    <span class="text-2xl">📅</span>
                    <span>Generated: {timestamp}</span>
                </div>
            </div>
        </header>
        
        <!-- Filter and Search -->
        <div class="mb-8 bg-white rounded-lg shadow-sm border p-4">
            <div class="flex flex-wrap gap-4 items-center">
                <div class="flex-1 min-w-64">
                    <input type="text" id="searchInput" placeholder="Search files..." 
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                </div>
                <div class="flex gap-2">
                    <select id="checkpointFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All Checkpoints</option>
                        {checkpoint_options}
                    </select>
                    <select id="loraFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All LoRAs</option>
                        {lora_options}
                    </select>
                    <select id="nodeFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All Node Types</option>
                        {node_options}
                    </select>
                    <select id="typeFilter" class="px-4 py-2 border border-gray-300 rounded-lg">
                        <option value="">All Types</option>
                        <option value="workflow">With Workflows</option>
                        <option value="image_no_workflow">Images (No Workflow)</option>
                        <option value="other_file">Other Files</option>
                    </select>
                    <button onclick="resetFilters()" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200">
                        Reset
                    </button>
                </div>
            </div>
        </div>
        
        <!-- Masonry Grid -->
        <div class="masonry-grid" id="fileGrid">
            {all_cards_html}
        </div>
        
        <!-- No Results Message -->
        <div id="noResults" class="hidden text-center py-12">
            <div class="text-gray-400 text-6xl mb-4">🔍</div>
            <h3 class="text-xl font-semibold text-gray-600 mb-2">No files found</h3>
            <p class="text-gray-500">Try adjusting your search terms or filters</p>
        </div>
    </div>

    <script>
        // Search and filter functionality
        const searchInput = document.getElementById('searchInput');
        const checkpointFilter = document.getElementById('checkpointFilter');
        const loraFilter = document.getElementById('loraFilter');
        const nodeFilter = document.getElementById('nodeFilter');
        const typeFilter = document.getElementById('typeFilter');
        const fileGrid = document.getElementById('fileGrid');
        const noResults = document.getElementById('noResults');
        
        let allCards = Array.from(document.querySelectorAll('.masonry-item'));
        
        function filterCards() {{
            const searchTerm = searchInput.value.toLowerCase();
            const checkpointFilter_value = checkpointFilter.value;
            const loraFilter_value = loraFilter.value;
            const nodeFilter_value = nodeFilter.value;
            const typeFilterValue = typeFilter.value;
            
            // Filter cards (no sorting needed)
            let visibleCards = allCards.filter(card => {{
                const text = card.textContent.toLowerCase();
                const matchesSearch = text.includes(searchTerm);
                
                const cardCheckpoints = (card.dataset.checkpoints || '').split(',').filter(c => c.trim());
                const cardLoras = (card.dataset.loras || '').split(',').filter(l => l.trim());
                const cardNodeTypes = (card.dataset.nodeTypes || '').split(',').filter(n => n.trim());
                
                const matchesCheckpoint = !checkpointFilter_value || cardCheckpoints.includes(checkpointFilter_value);
                const matchesLora = !loraFilter_value || cardLoras.includes(loraFilter_value);
                const matchesNodeType = !nodeFilter_value || cardNodeTypes.includes(nodeFilter_value);
                const matchesType = !typeFilterValue || card.dataset.type === typeFilterValue;
                
                return matchesSearch && matchesCheckpoint && matchesLora && matchesNodeType && matchesType;
            }});
            
            // Update display
            allCards.forEach(card => card.style.display = 'none');
            visibleCards.forEach(card => card.style.display = 'block');
            
            // Show/hide no results message
            if (visibleCards.length === 0) {{
                noResults.classList.remove('hidden');
                fileGrid.style.display = 'none';
            }} else {{
                noResults.classList.add('hidden');
                fileGrid.style.display = 'block';
            }}
        }}
        
        function resetFilters() {{
            searchInput.value = '';
            checkpointFilter.value = '';
            loraFilter.value = '';
            nodeFilter.value = '';
            typeFilter.value = '';
            filterCards();
        }}
        
        // Event listeners
        searchInput.addEventListener('input', filterCards);
        checkpointFilter.addEventListener('change', filterCards);
        loraFilter.addEventListener('change', filterCards);
        nodeFilter.addEventListener('change', filterCards);
        typeFilter.addEventListener('change', filterCards);
    </script>
    
    <!-- Footer -->
    <footer class="mt-16 py-8 border-t border-gray-200 text-center text-gray-500">
        <div class="flex items-center justify-center space-x-2">
            <span class="text-xl">💡</span>
            <span class="font-medium">Comfy Light Table</span>
            <span>•</span>
            <span class="text-sm">Quality of Life Improvements</span>
        </div>
        <div class="mt-2 text-xs">
            Built In Venice Beach • Workflow Analysis
        </div>
    </footer>
</body>
</html>'''
    
    return html


def generate_comprehensive_catalog_card(file_result: FileAnalysisResult, page_path: Optional[str], card_type: str) -> str:
    """Generate HTML card for comprehensive catalog showing all file types."""
    import base64
    from datetime import datetime
    
    # Generate file info from available data
    try:
        stat = file_result.file_path.stat()
        file_size_mb = round(stat.st_size / (1024 * 1024), 2)
        modified_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        file_size_mb = file_result.file_size / (1024 * 1024) if file_result.file_size else 0
        file_size_mb = round(file_size_mb, 2)
        modified_time = "Unknown"
    
    file_info = {
        'size_mb': file_size_mb,
        'modified': modified_time
    }
    
    # Determine card styling based on type
    if card_type == 'workflow':
        border_color = "border-green-200"
        bg_color = "bg-green-50"
        icon = "🎯"  # Only used for non-image files
        status_text = f"{len(file_result.workflow)} nodes"
        status_color = "text-green-700"
    elif card_type == 'image_no_workflow':
        border_color = "border-yellow-200"
        bg_color = "bg-yellow-50"
        icon = "⚠️"  # Only used for non-image files
        status_text = file_result.error_message[:50] if file_result.error_message else 'No workflow found'
        status_color = "text-yellow-700"
    else:
        border_color = "border-blue-200"
        bg_color = "bg-blue-50"
        icon = get_file_type_icon(file_result.file_type)
        status_text = file_result.file_type.replace('_', ' ').title()
        status_color = "text-blue-700"
    
    # Generate thumbnail or icon - ALWAYS show images as images, not icons
    thumbnail_html = ""
    
    # Check if it's an image file by extension
    is_image_file = file_result.file_path.suffix.lower() in ['.png', '.webp', '.jpg', '.jpeg']
    
    if is_image_file:
        # For image files, always show the actual image
        try:
            with open(file_result.file_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            ext = file_result.file_path.suffix.lower()
            mime_type = {
                '.png': 'image/png',
                '.webp': 'image/webp', 
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg'
            }.get(ext, 'image/png')
            
            thumbnail_data = f"data:{mime_type};base64,{image_data}"
            thumbnail_html = f'<img src="{thumbnail_data}" alt="{file_result.file_path.name}" class="w-full h-32 object-cover bg-gray-100">'
        except Exception as e:
            # If image loading fails, show error icon
            thumbnail_html = f'<div class="w-full h-32 bg-red-100 flex items-center justify-center"><span class="text-red-400 text-4xl">❌</span><div class="text-xs text-red-600 mt-1">Image Error</div></div>'
    else:
        # For non-image files, show appropriate icon
        thumbnail_html = f'<div class="w-full h-32 {bg_color} flex items-center justify-center"><span class="text-gray-600 text-4xl">{icon}</span></div>'
    
    # Create card content
    card_class = "card-hover" if page_path else ""
    link_start = f'<a href="{page_path}" class="block">' if page_path else '<div class="block cursor-default">'
    link_end = '</a>' if page_path else '</div>'
    
    # Diagnostic information
    diagnostic_info = ""
    if file_result.error_message:
        # Truncate long error messages for display
        error_display = file_result.error_message[:100] + "..." if len(file_result.error_message) > 100 else file_result.error_message
        diagnostic_info = f'''
            <div class="mt-2 p-2 bg-gray-100 rounded text-xs">
                <div class="font-medium mb-1">Error Details:</div>
                {error_display}
            </div>'''
    
    # Add model data attributes for workflow files
    model_attributes = ""
    if card_type == 'workflow' and file_result.workflow and file_result.models:
        checkpoints_json = ','.join(file_result.models.get('checkpoints', []))
        loras_json = ','.join(file_result.models.get('loras', []))
        node_types_json = ','.join(file_result.node_types or [])
        model_attributes = f'''data-checkpoints="{checkpoints_json}" data-loras="{loras_json}" data-node-types="{node_types_json}"'''

    card_html = f'''
    <div class="masonry-item {card_class} bg-white rounded-lg shadow-sm border {border_color} overflow-hidden"
         data-type="{card_type}" 
         data-size="{file_info['size_mb']}" 
         data-date="{file_info['modified']}"
         {model_attributes}>
        {link_start}
            {thumbnail_html}
            
            <!-- Content -->
            <div class="p-4">
                <div class="flex items-start gap-2 mb-2">
                    <span class="text-lg">{icon}</span>
                    <div class="flex-1">
                        <h3 class="font-bold text-sm text-gray-900 line-clamp-2">
                            {file_result.file_path.name}
                        </h3>
                        <div class="text-xs {status_color} mt-1">
                            {status_text}
                        </div>
                    </div>
                </div>
                
                <div class="text-xs text-gray-500">
                    <div>📁 {file_info['size_mb']} MB</div>
                    <div>📅 {file_info['modified']}</div>
                </div>
                
                {diagnostic_info}
            </div>
        {link_end}
    </div>'''
    
    return card_html


def get_file_type_icon(file_type: str) -> str:
    """Get appropriate icon for file type."""
    icons = {
        'workflow_json': '⚙️',
        'json_other': '📄',
        'json_invalid': '❌',
        'text_file': '📝',
        'markdown_file': '📖',
        'python_file': '🐍',
        'javascript_file': '📜',
        'html_file': '🌐',
        'css_file': '🎨',
        'yaml_file': '⚙️',
        'xml_file': '📋',
        'other_file': '📄',
        'no_extension': '❓',
        'error': '💥'
    }
    return icons.get(file_type, '📄')


def generate_master_catalog_card(workflow_data: WorkflowImageData, page_path: str) -> str:
    """Generate HTML card for masonry grid."""
    import base64
    
    # Get workflow summary
    summary = workflow_data.workflow_summary
    file_info = workflow_data.file_info
    
    # Generate thumbnail (base64 encoded)
    thumbnail_data = ""
    try:
        with open(workflow_data.image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Determine MIME type
        ext = workflow_data.image_path.suffix.lower()
        mime_type = {
            '.png': 'image/png',
            '.webp': 'image/webp', 
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg'
        }.get(ext, 'image/png')
        
        thumbnail_data = f"data:{mime_type};base64,{image_data}"
    except Exception as e:
        print(f"Warning: Could not encode image {workflow_data.image_path}: {e}")
    
    # Generate node types badge
    node_types_display = ", ".join(summary["node_types"][:3])
    if len(summary["node_types"]) > 3:
        node_types_display += f" (+{len(summary['node_types']) - 3} more)"
    
    # Extract models and node types for filtering
    # Use original workflow format for model extraction (preserves widget_values)
    if hasattr(workflow_data, 'original_workflow') and workflow_data.original_workflow:
        workflow_for_models = workflow_data.original_workflow
    else:
        # Fallback: re-extract original format from image
        workflow_for_models = extract_workflow_from_image(workflow_data.image_path, preserve_original_format=True)
        if not workflow_for_models:
            workflow_for_models = workflow_data.workflow
    
    models = extract_models_from_workflow(workflow_for_models)
    
    # Separate checkpoints and LoRAs
    checkpoints_json = ','.join(models.get('checkpoints', []))
    loras_json = ','.join(models.get('loras', []))
    node_types_json = ','.join(summary["node_types"])
    
    # Get relative file path for display
    try:
        relative_path = str(workflow_data.image_path.resolve())
    except:
        relative_path = str(workflow_data.image_path)
    
    card_html = f'''
    <div class="masonry-item card-hover bg-white rounded-lg shadow-sm border overflow-hidden"
         data-nodes="{summary['total_nodes']}" 
         data-date="{file_info['modified']}"
         data-size="{file_info['size_mb']}"
         data-checkpoints="{checkpoints_json}"
         data-loras="{loras_json}"
         data-node-types="{node_types_json}">
        <a href="{page_path}" class="block">
            <!-- Image -->
            {f'<img src="{thumbnail_data}" alt="Generated Image" class="w-full h-48 object-cover bg-gray-100">' if thumbnail_data else '<div class="w-full h-48 bg-gray-100 flex items-center justify-center"><span class="text-gray-400 text-4xl">🖼️</span></div>'}
            
            <!-- Content -->
            <div class="p-4">
                <h3 class="font-bold text-lg text-gray-900 mb-2 line-clamp-2">
                    {workflow_data.image_path.stem.replace('_', ' ').replace('-', ' ').title()}
                </h3>
                
                <div class="space-y-2 text-sm text-gray-600">
                    <div class="flex items-center justify-between">
                        <span class="flex items-center gap-1">
                            ⚙️ {summary['total_nodes']} nodes
                        </span>
                        <span class="flex items-center gap-1">
                            🔗 {summary['connections']} connections
                        </span>
                    </div>
                    
                    <div class="text-xs text-gray-500">
                        <div class="truncate" title="{node_types_display}">
                            Types: {node_types_display}
                        </div>
                        <div class="mt-1 truncate" title="{relative_path}">
                            📁 {file_info['size_mb']} MB • {file_info['modified']}
                        </div>
                        <div class="mt-1 truncate text-blue-600" title="{relative_path}">
                            📂 {relative_path}
                        </div>
                    </div>
                </div>
            </div>
        </a>
    </div>'''
    
    return card_html


def single_file_mode(args):
    """Handle single file processing (existing functionality)."""
    
    # Determine input type and load workflow
    input_path = Path(args.input)
    workflow = None
    source_image_path = None
    
    if input_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
        # Extract workflow from image
        print(f"Extracting workflow from image: {input_path}")
        workflow = extract_workflow_from_image(input_path)
        source_image_path = str(input_path)
        
        if not workflow:
            print(f"Error: No ComfyUI workflow found in image {input_path}", file=sys.stderr)
            return 1
            
    elif input_path.suffix.lower() == '.json':
        # Load workflow from JSON
        try:
            with open(input_path, 'r') as f:
                workflow = json.load(f)
        except Exception as e:
            print(f"Error loading workflow JSON: {e}", file=sys.stderr)
            return 1
    else:
        print(f"Error: Unsupported file type {input_path.suffix}. Use .json, .png, or .webp files.", file=sys.stderr)
        return 1
    
    # Find associated image
    import os
    associated_image = None
    if source_image_path:
        # We extracted from an image, use that
        associated_image = source_image_path
    elif args.image:
        # Explicit image provided
        associated_image = args.image
    elif args.image_dir:
        # Search in specified directory
        associated_image = find_associated_image(str(input_path), [args.image_dir])
    else:
        # Try to find image in same directory as workflow
        associated_image = find_associated_image(str(input_path))
    
    if associated_image:
        print(f"✓ Found associated image: {os.path.basename(associated_image)}")
    
    # Store in database if enabled
    workflow_manager = None
    database_enabled = False
    
    # Check for explicit --database flag
    if hasattr(args, 'database') and args.database is not None:
        database_url = args.database if args.database != True else None
        workflow_manager = get_database_workflow_manager(database_url)
        database_enabled = workflow_manager is not None
        if database_enabled:
            print(f"💾 Database enabled: storing workflow in database")
        else:
            print(f"⚠️ Database requested but not available")
    
    # Auto-detect database if not explicitly disabled
    elif DATABASE_AVAILABLE:
        workflow_manager = get_database_workflow_manager()
        database_enabled = workflow_manager is not None
        if database_enabled:
            print(f"💾 Database auto-detected: storing workflow in database")
    
    # Store workflow in database
    if database_enabled:
        # Parse additional database metadata
        tags = []
        if hasattr(args, 'tags') and args.tags:
            tags = [tag.strip() for tag in args.tags.split(',')]
        
        collections = []
        if hasattr(args, 'collections') and args.collections:
            collections = [col.strip() for col in args.collections.split(',')]
        
        notes = getattr(args, 'notes', None)
        
        # Create WorkflowImageData for storage
        workflow_data = WorkflowImageData(
            image_path=input_path,
            workflow=workflow,
            metadata={'source': 'single-file-import', 'associated_image': associated_image}
        )
        
        success = store_workflow_in_database(
            workflow_manager=workflow_manager,
            workflow_data=workflow_data,
            tags=tags,
            collections=collections,
            notes=notes
        )
        
        if success:
            print(f"✅ Workflow stored in database")
        else:
            print(f"⚠️ Failed to store workflow in database")
    
    # Generate catalog
    try:
        if args.format == 'html':
            workflow_name = input_path.stem.replace('-', ' ').replace('_', ' ').title()
            catalog = generate_html_visual(workflow, workflow_name, args.server, associated_image)
        else:
            catalog = generate_markdown_catalog(workflow, args.format)
    except Exception as e:
        print(f"Error generating catalog: {e}", file=sys.stderr)
        return 1
    
    # Write output
    if args.output:
        try:
            with open(args.output, 'w') as f:
                f.write(catalog)
            print(f"✓ Catalog written to {args.output}")
        except Exception as e:
            print(f"Error writing output: {e}", file=sys.stderr)
            return 1
    else:
        print(catalog)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
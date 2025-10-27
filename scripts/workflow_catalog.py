#!/usr/bin/env python3
"""
ComfyUI Workflow Catalog Generator

This script analyzes a ComfyUI workflow JSON file and generates a human-readable
catalog in Markdown format, showing all nodes, their connections, and parameters.

Usage:
    python workflow_catalog.py workflow.json
    python workflow_catalog.py workflow.json --output catalog.md
    python workflow_catalog.py workflow.json --format table
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


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
    
    # Count node types and analyze connections
    for node_id, node_data in workflow.items():
        class_type = node_data.get("class_type", "Unknown")
        analysis["node_types"][class_type] = analysis["node_types"].get(class_type, 0) + 1
        
        # Check inputs for connections
        inputs = node_data.get("inputs", {})
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
        
        # Identify input/output nodes
        if not has_connections:
            analysis["input_nodes"].append(node_id)
        
        # Check if this node has outputs (connected to other nodes)
        is_output = True
        for other_id, other_data in workflow.items():
            if other_id == node_id:
                continue
            other_inputs = other_data.get("inputs", {})
            for param_value in other_inputs.values():
                if isinstance(param_value, list) and len(param_value) == 2 and param_value[0] == node_id:
                    is_output = False
                    break
            if not is_output:
                break
        
        if is_output and class_type in ["SaveImage", "PreviewImage", "Griptape Display: Text"]:
            analysis["output_nodes"].append(node_id)
    
    return analysis


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


def generate_html_visual(workflow: Dict[str, Any], workflow_name: str = "Unknown Workflow", server_address: str = None) -> str:
    """Generate an interactive HTML visualization of the workflow using Tailwind CSS."""
    # Sort nodes by ID for consistent layout
    sorted_nodes = sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
    
    # Generate timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
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
    <title>{workflow_name} - ComfyUI Workflow</title>
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
                    <p class="text-lg text-gray-600">ComfyUI Workflow Visualization</p>
                </div>
                <div class="text-right text-sm text-gray-500">
                    <div>Generated: {timestamp}</div>
                    <div class="mt-1">ComfyREST Catalog v1.0</div>
                </div>
            </div>
        </header>

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
                
                # Escape quotes for JavaScript and HTML
                escaped_value = full_value_str.replace('"', '&quot;').replace("'", '&#39;')
                copy_command = f'--node {node_id} --param {param_name} "{full_value_str}"'
                # For the onclick attribute, we need to escape differently
                js_escaped_command = copy_command.replace('"', "'").replace("'", "\\''")
                
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
                                            data-copy-text="{copy_command}"
                                            id="{copy_id}"
                                            title="Copy command line argument">
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
  %(prog)s workflow.json
  %(prog)s workflow.json --output catalog.md
  %(prog)s workflow.json --format table
  %(prog)s workflow.json --format html --output workflow.html
  %(prog)s workflow.json --format detailed --output my_workflow_ref.md
        """
    )
    
    parser.add_argument('workflow', help='Path to workflow JSON file')
    parser.add_argument('--output', '-o', help='Output markdown file (default: print to stdout)')
    parser.add_argument('--format', choices=['detailed', 'table', 'html'], default='detailed',
                       help='Output format: detailed (markdown), table (markdown), html (interactive)')
    parser.add_argument('--server', help='ComfyUI server address (e.g., http://127.0.0.1:8188) for querying real dropdown values')
    
    args = parser.parse_args()
    
    # Load workflow
    try:
        with open(args.workflow, 'r') as f:
            workflow = json.load(f)
    except Exception as e:
        print(f"Error loading workflow: {e}", file=sys.stderr)
        return 1
    
    # Generate catalog
    try:
        if args.format == 'html':
            workflow_name = Path(args.workflow).stem.replace('-', ' ').replace('_', ' ').title()
            catalog = generate_html_visual(workflow, workflow_name, args.server)
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
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


def generate_html_visual(workflow: Dict[str, Any], workflow_name: str = "Unknown Workflow") -> str:
    """Generate an interactive HTML visualization of the workflow using Tailwind CSS."""
    # Sort nodes by ID for consistent layout
    sorted_nodes = sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
    
    # Generate timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Build HTML using simple string concatenation
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{workflow_name} - ComfyUI Workflow</title>
    <script src="https://cdn.tailwindcss.com"></script>
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
        
        # Add all parameters
        for param_name, param_value in inputs.items():
            if isinstance(param_value, list) and len(param_value) == 2:
                html += f'                        <div class="bg-blue-50 p-1 rounded flex justify-between"><span class="text-blue-700 font-medium">{param_name}:</span><span class="text-blue-600">→ Node {param_value[0]}</span></div>\n'
            else:
                value_str = str(param_value)
                if len(value_str) > 30:
                    value_str = value_str[:27] + "..."
                html += f'                        <div class="bg-gray-50 p-1 rounded flex justify-between"><span class="font-medium">{param_name}:</span><span class="text-gray-600 break-all">{value_str}</span></div>\n'
        
        html += '''                    </div>
                </details>
            </div>
'''
    
    html += f'''
        </div>
        
        <div class="mt-8 p-6 bg-white rounded-lg shadow-sm border">
            <h3 class="text-xl font-semibold mb-4">Command Line Reference</h3>
            <div class="text-sm text-gray-600 mb-4">Use these commands to modify parameters:</div>
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
            catalog = generate_html_visual(workflow, workflow_name)
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
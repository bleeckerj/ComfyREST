#!/usr/bin/env python3
"""
Universal ComfyUI Workflow Runner with Parameter Override

This script allows you to run any ComfyUI workflow and override node parameters
via command-line arguments, making workflows fully programmable.

Usage:
    python run_workflow_with_params.py workflow.json --node 3 --param seed 42 --param steps 20
    python run_workflow_with_params.py workflow.json --node 116 --param image "my_photo.jpg" --node 6 --param text "A red car"
    python run_workflow_with_params.py workflow.json --params "3.seed=42,3.steps=20,116.image=photo.jpg"
"""

import argparse
import json
import sys
import time
import importlib
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Add the project root to the path so we can import comfyrest
sys.path.insert(0, str(Path(__file__).parent.parent))

import comfyrest.client
importlib.reload(comfyrest.client)
from comfyrest.client import ComfyClient


def parse_parameter_overrides(raw_args: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Parse parameter overrides from raw argument list.
    
    Returns a dict like:
    {
        "node_id": {
            "param_name": value,
            "param_name2": value2
        }
    }
    """
    overrides = {}
    
    # Handle --node/--param pairs from raw args
    current_node = None
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        
        if arg == '--node' and i + 1 < len(raw_args):
            current_node = raw_args[i + 1]
            if current_node not in overrides:
                overrides[current_node] = {}
            i += 2
        elif arg == '--param' and current_node and i + 2 < len(raw_args):
            param_name = raw_args[i + 1]
            param_value = raw_args[i + 2]
            overrides[current_node][param_name] = convert_value(param_value)
            i += 3
        else:
            i += 1
    
    return overrides


def parse_params_string(params_str: str) -> Dict[str, Dict[str, Any]]:
    """Parse --params format: "node.param=value,node.param=value" """
    overrides = {}
    
    if not params_str:
        return overrides
        
    for param_spec in params_str.split(','):
        if '=' not in param_spec:
            continue
        key, value = param_spec.split('=', 1)
        if '.' not in key:
            continue
        node_id, param_name = key.split('.', 1)
        
        if node_id not in overrides:
            overrides[node_id] = {}
        
        # Try to convert value to appropriate type
        overrides[node_id][param_name] = convert_value(value)
    
    return overrides


def convert_value(value_str: str) -> Any:
    """Convert string value to appropriate Python type."""
    value_str = value_str.strip()
    
    # Try boolean
    if value_str.lower() in ('true', 'false'):
        return value_str.lower() == 'true'
    
    # Try integer
    try:
        return int(value_str)
    except ValueError:
        pass
    
    # Try float
    try:
        return float(value_str)
    except ValueError:
        pass
    
    # Return as string
    return value_str


def convert_image_path(image_path: str) -> str:
    """Convert image path to format ComfyUI can access."""
    from pathlib import Path
    import os
    
    # If it's already a Windows path, return as-is
    if '\\' in image_path or image_path.startswith(('C:', 'D:', 'F:')):
        return image_path
    
    # If it's a relative path, try to convert to absolute
    if not os.path.isabs(image_path):
        abs_path = os.path.abspath(image_path)
    else:
        abs_path = image_path
    
    # If running in WSL, convert Linux path to Windows WSL path
    if abs_path.startswith('/') and os.path.exists('/proc/version'):
        try:
            # Check if we're in WSL
            with open('/proc/version', 'r') as f:
                content = f.read()
                if 'Microsoft' in content or 'WSL' in content:
                    # Use wslpath command for accurate conversion
                    import subprocess
                    result = subprocess.run(['wslpath', '-w', abs_path], 
                                          capture_output=True, text=True)
                    if result.returncode == 0:
                        converted_path = result.stdout.strip()
                        print(f"🔄 Converted path: {image_path} → {converted_path}")
                        return converted_path
        except Exception as e:
            print(f"⚠ Path conversion warning: {e}")
    
    return abs_path


def apply_parameter_overrides(workflow: Dict[str, Any], overrides: Dict[str, Dict[str, Any]], client=None) -> Dict[str, Any]:
    """Apply parameter overrides to workflow."""
    modified_workflow = workflow.copy()
    
    for node_id, params in overrides.items():
        if node_id not in modified_workflow:
            print(f"Warning: Node {node_id} not found in workflow")
            continue
        
        if 'inputs' not in modified_workflow[node_id]:
            modified_workflow[node_id]['inputs'] = {}
        
        for param_name, param_value in params.items():
            old_value = modified_workflow[node_id]['inputs'].get(param_name, "not set")
            
            # Special handling for image parameters
            if param_name == 'image' and isinstance(param_value, str):
                param_value = convert_image_path(param_value)

            modified_workflow[node_id]['inputs'][param_name] = param_value
            print(f"✓ Node {node_id}.{param_name}: {old_value} → {param_value}")
    
    return modified_workflow


def print_workflow_parameters(workflow: Dict[str, Any]):
    """Print all parameterizable values in the workflow."""
    print("\n=== Available Parameters ===")
    
    for node_id, node in workflow.items():
        class_type = node.get('class_type', 'Unknown')
        inputs = node.get('inputs', {})
        
        if inputs:
            print(f"\nNode {node_id} ({class_type}):")
            for param_name, param_value in inputs.items():
                # Skip connections (arrays like ['66', 0])
                if not isinstance(param_value, list):
                    value_str = str(param_value)[:50] + "..." if len(str(param_value)) > 50 else str(param_value)
                    print(f"  --node {node_id} --param {param_name} \"{value_str}\"")


def main():
    # Parse known args first to separate workflow runner args from node/param args
    parser = argparse.ArgumentParser(
        description="Run ComfyUI workflow with parameter overrides",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Override seed and steps for node 3
  %(prog)s workflow.json --node 3 --param seed 42 --param steps 20
  
  # Override image for node 116 and text for node 6
  %(prog)s workflow.json --node 116 --param image "photo.jpg" --node 6 --param text "A red car"
  
  # Use compact parameter syntax
  %(prog)s workflow.json --params "3.seed=42,3.steps=20,116.image=photo.jpg"
  
  # List available parameters
  %(prog)s workflow.json --list-params
        """
    )
    
    parser.add_argument('workflow', help='Path to workflow JSON file')
    parser.add_argument('--server', default='http://127.0.0.1:8188', 
                       help='ComfyUI server URL (default: http://127.0.0.1:8188)')
    parser.add_argument('--params', help='Parameter overrides in format "node.param=value,node.param=value"')
    parser.add_argument('--list-params', action='store_true', 
                       help='List all available parameters and exit')
    parser.add_argument('--save', help='Save modified workflow to file instead of running')
    parser.add_argument('--timeout', type=int, default=300, 
                       help='Timeout in seconds (default: 300)')
    parser.add_argument('--websocket', action='store_true',
                       help='Use WebSocket for real-time progress updates instead of HTTP polling')
    
    # Use all args since parse_known_args doesn't work well with --node/--param
    all_args = sys.argv[1:]
    
    # Find just the workflow file and use everything else as remaining
    if not all_args:
        parser.print_help()
        return 1
        
    workflow_file = all_args[0]
    remaining_args = all_args[1:]  # Everything after workflow file
    
    # Create minimal args object with defaults
    class Args:
        def __init__(self):
            self.workflow = workflow_file
            self.server = 'http://127.0.0.1:8188'
            self.params = None
            self.list_params = False
            self.save = None
            self.timeout = 300
            self.websocket = False
    
    args = Args()
    
    # Parse any standard flags from remaining_args
    i = 0
    final_remaining = []
    while i < len(remaining_args):
        arg = remaining_args[i]
        if arg == '--server' and i + 1 < len(remaining_args):
            args.server = remaining_args[i + 1]
            i += 2
        elif arg == '--save' and i + 1 < len(remaining_args):
            args.save = remaining_args[i + 1]
            i += 2
        elif arg == '--list-params':
            args.list_params = True
            i += 1
        elif arg == '--websocket':
            args.websocket = True
            i += 1
        else:
            final_remaining.append(arg)
            i += 1
    
    remaining_args = final_remaining
    
    # Load workflow
    try:
        with open(args.workflow, 'r') as f:
            workflow = json.load(f)
    except Exception as e:
        print(f"Error loading workflow: {e}")
        return 1
    
    print(f"Loaded workflow with {len(workflow)} nodes")
    
    # List parameters if requested
    if args.list_params:
        print_workflow_parameters(workflow)
        return 0
    
    # Parse parameter overrides from both sources
    overrides = {}
    
    # Parse --params format
    if args.params:
        overrides.update(parse_params_string(args.params))
    
    # Parse --node/--param pairs from remaining args
    node_param_overrides = parse_parameter_overrides(remaining_args)
    
    # Merge the overrides
    for node_id, params in node_param_overrides.items():
        if node_id not in overrides:
            overrides[node_id] = {}
        overrides[node_id].update(params)
    
    # Create client for potential image uploads
    client = ComfyClient(args.server)
    
    if overrides:
        print(f"\n=== Applying {sum(len(params) for params in overrides.values())} parameter overrides ===")
        workflow = apply_parameter_overrides(workflow, overrides, client)
    
    # Save modified workflow if requested
    if args.save:
        with open(args.save, 'w') as f:
            json.dump(workflow, f, indent=2)
        print(f"\n✓ Saved modified workflow to {args.save}")
        return 0
    
    # Run the workflow
    print(f"\n=== Running workflow on {args.server} ===")
    
    try:
        # Submit workflow
        response = client.post_prompt(workflow)
        prompt_id = response.get('prompt_id')
        
        if not prompt_id:
            print(f"Error: No prompt_id received. Response: {response}")
            return 1
        
        print(f"✓ Submitted workflow, prompt_id: {prompt_id}")
        
        # Wait for completion
        if args.websocket:
            print("Waiting for completion (WebSocket real-time updates)...")
            try:
                result = client.wait_for_prompt_with_ws(prompt_id, timeout=args.timeout)
            except AttributeError:
                print("⚠ WebSocket method not available, falling back to HTTP polling")
                result = client.wait_for_prompt(prompt_id, timeout=args.timeout)
        else:
            print("Waiting for completion (HTTP polling)...")
            result = client.wait_for_prompt(prompt_id, timeout=args.timeout)
        
        status = result.get('status', 'unknown')
        print(f"\nFinal status: {status}")
        
        # Handle different status formats
        if status == 'completed' or (isinstance(status, dict) and status.get('completed')):
            # Show outputs
            outputs = result.get('outputs', {})
            if outputs:
                print(f"\n🎉 Generated outputs from {len(outputs)} nodes:")
                for node_id, output in outputs.items():
                    if 'images' in output:
                        images = output['images']
                        print(f"  Node {node_id}: {len(images)} image(s)")
                        for img in images:
                            print(f"    - {img.get('filename', 'unknown')}")
            else:
                # Check if execution was cached (still successful)
                if isinstance(status, dict) and any('execution_cached' in str(msg) for msg in status.get('messages', [])):
                    print("✅ Workflow completed successfully (all nodes were cached)")
                else:
                    print("✅ Workflow completed (no image outputs)")
        elif status == 'error' or (isinstance(status, dict) and 'error' in status):
            error_msg = result.get('error', status.get('error', 'unknown error'))
            print(f"❌ Workflow failed: {error_msg}")
            return 1
        else:
            print(f"⚠ Unexpected workflow status: {status}")
            return 1
            
    except Exception as e:
        print(f"Error running workflow: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
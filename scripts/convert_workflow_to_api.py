#!/usr/bin/env python3
"""
Convert ComfyUI GUI workflow to API format

Usage:
    python convert_workflow_to_api.py input_workflow.json output_workflow.json
"""

import json
import sys
from pathlib import Path


def convert_gui_to_api_format(gui_workflow):
    """
    Convert ComfyUI GUI workflow format to API format.
    
    GUI format: nodes have 'type' and 'widgets_values'
    API format: nodes have 'class_type' and 'inputs' 
    """
    api_workflow = {}
    
    for node in gui_workflow.get('nodes', []):
        node_id = str(node['id'])
        
        # Create API format node
        api_node = {
            "class_type": node.get('type'),  # Copy type to class_type
            "inputs": {}
        }
        
        # Map widgets_values to named inputs
        if 'widgets_values' in node and node['widgets_values']:
            inputs_list = node.get('inputs', [])
            widget_index = 0
            
            # For each input that has a widget, map the widget value
            for inp in inputs_list:
                if inp.get('widget') and widget_index < len(node['widgets_values']):
                    input_name = inp['name']
                    widget_value = node['widgets_values'][widget_index]
                    api_node['inputs'][input_name] = widget_value
                    widget_index += 1
        
        # Handle node connections (links between nodes)
        for inp in node.get('inputs', []):
            if 'link' in inp and inp['link'] is not None:
                # Find the source node for this link
                link_id = inp['link']
                source_info = find_link_source(gui_workflow, link_id)
                if source_info:
                    source_node_id, source_slot = source_info
                    api_node['inputs'][inp['name']] = [str(source_node_id), source_slot]
        
        api_workflow[node_id] = api_node
    
    return api_workflow


def find_link_source(workflow, link_id):
    """Find the source node and output slot for a given link ID."""
    for link in workflow.get('links', []):
        if len(link) >= 6 and link[0] == link_id:
            # Link format: [link_id, source_node_id, source_slot, target_node_id, target_slot, type]
            return link[1], link[2]  # source_node_id, source_slot
    return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python convert_workflow_to_api.py input_workflow.json output_workflow.json")
        print("")
        print("Converts ComfyUI GUI workflow format to API format for REST API use.")
        return 1
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # Load GUI workflow
    try:
        with open(input_file, 'r') as f:
            gui_workflow = json.load(f)
        print(f"✓ Loaded GUI workflow from {input_file}")
    except Exception as e:
        print(f"Error loading {input_file}: {e}")
        return 1
    
    # Convert to API format
    try:
        api_workflow = convert_gui_to_api_format(gui_workflow)
        print(f"✓ Converted {len(api_workflow)} nodes to API format")
    except Exception as e:
        print(f"Error converting workflow: {e}")
        return 1
    
    # Save API workflow
    try:
        with open(output_file, 'w') as f:
            json.dump(api_workflow, f, indent=2)
        print(f"✅ Saved API workflow to {output_file}")
    except Exception as e:
        print(f"Error saving {output_file}: {e}")
        return 1
    
    # Show summary
    print(f"\nSummary:")
    print(f"  Input:  {input_file} (GUI format, {len(gui_workflow.get('nodes', []))} nodes)")
    print(f"  Output: {output_file} (API format, {len(api_workflow)} nodes)")
    print(f"\nYou can now use {output_file} with the ComfyUI REST API!")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
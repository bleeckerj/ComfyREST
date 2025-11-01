#!/usr/bin/env python3
"""
💡 Comfy Light Table

A web-based drag-and-drop interface for illuminating ComfyUI workflows from images and JSON files.
Features real-time processing, interactive visualization, and batch operations.

Like a photographer's light table for reviewing film, Comfy Light Table helps you examine, 
analyze, and understand your ComfyUI workflows with clarity and ease.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Import our existing ComfyREST functionality
import sys
sys.path.append('scripts')
from workflow_catalog import (
    extract_workflow_from_image, 
    analyze_workflow, 
    generate_html_visual,
    ui_to_api_format
)

# Import database functionality
try:
    from database.database import get_database_manager, WorkflowFileManager
    from database.models import WorkflowFile, Tag, Collection, Client, Project
    DATABASE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Database not available: {e}")
    DATABASE_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_workflow_detail_html(workflow, workflow_json, checkpoints, loras):
    """Generate detailed HTML page for a workflow with rich editing features."""
    import html as html_escape
    
    # Build tags
    tags = []
    if workflow.style_tags:
        try:
            if isinstance(workflow.style_tags, str):
                import json
                style_tags = json.loads(workflow.style_tags)
            else:
                style_tags = workflow.style_tags
            tags.extend(style_tags)
        except Exception:
            pass
    
    # Add checkpoint and lora tags
    for checkpoint in checkpoints:
        tags.append(f"checkpoint:{checkpoint}")
    for lora in loras:
        tags.append(f"lora:{lora}")
    
    # Format file size
    file_size_str = f"{workflow.file_size / 1024:.1f} KB" if workflow.file_size else "Unknown"
    
    # Check if has image
    has_image = (workflow.image_width is not None and workflow.image_height is not None) or (
        workflow.filename and workflow.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
    )
    
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Workflow: {html_escape.escape(workflow.filename or "Unknown")}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .node-card {{ transition: all 0.2s ease-in-out; }}
        .node-card:hover {{ transform: translateY(-2px); }}
        .copy-btn {{ font-size: 10px; }}
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <!-- Header -->
    <header class="bg-white shadow-sm border-b sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between items-center py-4">
                <div class="flex items-center space-x-4">
                    <a href="/catalogs/database_catalog.html" class="text-blue-600 hover:text-blue-800 font-medium">← Back to Catalog</a>
                    <h1 class="text-2xl font-bold text-gray-900">💡 {html_escape.escape(workflow.filename or "Unknown Workflow")}</h1>
                </div>
                <div class="flex items-center space-x-4">
                    {f'<a href="/api/workflows/{workflow.id}/thumbnail" target="_blank" class="bg-green-500 text-white px-4 py-2 rounded text-sm hover:bg-green-600 transition-colors">🖼️ View Image</a>' if has_image else ''}
                    <a href="/api/workflows/{workflow.id}" class="bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600 transition-colors">📥 Download JSON</a>
                </div>
            </div>
        </div>
    </header>

    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Workflow Info -->
        <div class="bg-white rounded-lg shadow-sm border p-6 mb-8">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                    <h2 class="text-xl font-semibold mb-4">Workflow Information</h2>
                    <div class="space-y-3">
                        <div class="flex justify-between">
                            <span class="font-medium text-gray-700">File:</span>
                            <span class="text-gray-900">{html_escape.escape(workflow.filename or "Unknown")}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium text-gray-700">Size:</span>
                            <span class="text-gray-900">{file_size_str}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium text-gray-700">Nodes:</span>
                            <span class="text-gray-900">{workflow.node_count or 0}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium text-gray-700">File Date:</span>
                            <span class="text-gray-900">TODO: Get from file system</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium text-gray-700">Ingested:</span>
                            <span class="text-gray-900 text-xs">{workflow.created_at.strftime("%Y-%m-%d %H:%M") if workflow.created_at else "Unknown"}</span>
                        </div>
                    </div>
                    
                    <!-- Editable Description -->
                    <div class="mt-6">
                        <label class="block font-medium text-gray-700 mb-2">Description:</label>
                        <textarea id="description" class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" 
                                  rows="3" placeholder="Add a description for this workflow...">{html_escape.escape(workflow.notes or "")}</textarea>
                        <button onclick="saveDescription()" class="mt-2 bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600 transition-colors">
                            💾 Save Description
                        </button>
                    </div>
                </div>
                
                <div>
                    <!-- Workflow Image -->
                    {f'''
                    <div class="mb-6">
                        <h3 class="text-lg font-medium mb-3">Workflow Output</h3>
                        <div class="border border-gray-200 rounded-lg overflow-hidden">
                            <img src="/api/workflows/{workflow.id}/thumbnail" alt="Workflow output" 
                                 class="w-full h-auto max-h-64 object-contain bg-gray-50"
                                 onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
                            <div class="text-center text-gray-500 text-sm p-8 hidden">
                                No image available
                            </div>
                        </div>
                    </div>''' if has_image else '''
                    <div class="mb-6">
                        <div class="border border-gray-200 rounded-lg p-8 text-center text-gray-500">
                            <span class="text-4xl">🖼️</span>
                            <p class="text-sm mt-2">No image available</p>
                        </div>
                    </div>'''}
                    
                    <!-- RUN WORKFLOW Button -->
                    <div class="mb-6">
                        <button onclick="runWorkflow()" class="w-full bg-green-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-green-700 transition-colors flex items-center justify-center gap-2">
                            <span class="text-xl">▶️</span>
                            RUN WORKFLOW
                        </button>
                        <p class="text-xs text-gray-500 mt-2 text-center">Execute this workflow in ComfyUI</p>
                    </div>
                    
                    <!-- Checkpoints & LoRAs -->
                    <h3 class="text-lg font-medium mb-3">Resources</h3>
                    {f'''
                    <div class="mb-4">
                        <h4 class="font-medium text-gray-700 mb-2">Checkpoints ({len(checkpoints)}):</h4>
                        <div class="space-y-1">
                            {chr(10).join(f'<div class="bg-blue-50 px-3 py-2 rounded text-sm text-blue-800">🔷 {html_escape.escape(cp)}</div>' for cp in checkpoints)}
                        </div>
                    </div>''' if checkpoints else ''}
                    
                    {f'''
                    <div class="mb-4">
                        <h4 class="font-medium text-gray-700 mb-2">LoRAs ({len(loras)}):</h4>
                        <div class="space-y-1">
                            {chr(10).join(f'<div class="bg-purple-50 px-3 py-2 rounded text-sm text-purple-800">🎭 {html_escape.escape(lora)}</div>' for lora in loras)}
                        </div>
                    </div>''' if loras else ''}
                    
                    <!-- Tags with editing capabilities -->
                    <div class="mb-4">
                        <div class="flex justify-between items-center mb-2">
                            <h4 class="font-medium text-gray-700">Tags ({len(tags)}):</h4>
                            <button onclick="addNewTag()" class="bg-green-500 text-white px-2 py-1 rounded text-xs hover:bg-green-600 transition-colors">
                                + Add Tag
                            </button>
                        </div>
                        <div id="tags-container" class="flex flex-wrap gap-2 mb-2">
                            {' '.join(f'''
                            <span class="tag-item-wrapper relative">
                                <span class="tag-item bg-gray-200 text-gray-800 px-2 py-1 rounded text-xs flex items-center gap-1 group">
                                    <span class="tag-text cursor-pointer" onclick="editTag(this, '{html_escape.escape(tag)}')" title="Click to edit">{html_escape.escape(tag)}</span>
                                    <button onclick="showDeleteConfirm(this, '{html_escape.escape(tag)}')" class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity ml-1" title="Delete tag">×</button>
                                </span>
                                <div class="delete-confirm hidden absolute top-full left-0 mt-1 bg-white border border-red-300 rounded-md shadow-lg p-2 z-10 whitespace-nowrap">
                                    <div class="text-xs text-gray-700 mb-2">Delete "{html_escape.escape(tag)}"?</div>
                                    <div class="flex gap-1">
                                        <button onclick="confirmDelete(this, '{html_escape.escape(tag)}')" class="bg-red-500 text-white px-2 py-1 rounded text-xs hover:bg-red-600">Delete</button>
                                        <button onclick="cancelDelete(this)" class="bg-gray-300 text-gray-700 px-2 py-1 rounded text-xs hover:bg-gray-400">Cancel</button>
                                    </div>
                                </div>
                            </span>
                            ''' for tag in tags)}
                        </div>
                        <div id="add-tag-form" class="hidden">
                            <input type="text" id="new-tag-input" placeholder="Enter new tag..." class="px-2 py-1 text-xs border border-gray-300 rounded mr-2">
                            <button onclick="saveNewTag()" class="bg-blue-500 text-white px-2 py-1 rounded text-xs hover:bg-blue-600">Save</button>
                            <button onclick="cancelAddTag()" class="bg-gray-500 text-white px-2 py-1 rounded text-xs hover:bg-gray-600 ml-1">Cancel</button>
                        </div>
                    </div>
                    
                    <!-- Client and Project Fields -->
                    <div class="mb-4">
                        <h4 class="font-medium text-gray-700 mb-2">Project Information:</h4>
                        <div class="space-y-2">
                            <div>
                                <label class="block text-xs font-medium text-gray-600">Client:</label>
                                <input type="text" id="client-name" placeholder="Enter client name..." 
                                       class="w-full px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                                       value="{html_escape.escape('TODO: Load from database')}">
                            </div>
                            <div>
                                <label class="block text-xs font-medium text-gray-600">Project:</label>
                                <input type="text" id="project-name" placeholder="Enter project name..." 
                                       class="w-full px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                                       value="{html_escape.escape('TODO: Load from database')}">
                            </div>
                            <button onclick="saveProjectInfo()" class="bg-blue-500 text-white px-3 py-1 rounded text-xs hover:bg-blue-600 transition-colors">
                                💾 Save Project Info
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>'''
    
    # Generate node details if we have workflow JSON
    if workflow_json:
        html_content += generate_nodes_section_html(workflow_json)
    
    # Add JavaScript and closing tags
    html_content += '''
    </div>

    <!-- Copy Success Toast -->
    <div id="copyToast" class="fixed top-4 right-4 bg-green-500 text-white px-4 py-2 rounded shadow-lg transform translate-x-full transition-transform duration-300 z-50">
        <div class="flex items-center gap-2">
            <span>✓</span>
            <span>Copied to clipboard!</span>
        </div>
    </div>

    <script>
        // Define workflow ID for JavaScript
        const workflowId = '{{WORKFLOW_ID_PLACEHOLDER}}';
        
        // Copy functionality
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('.copy-btn').forEach(button => {
                button.addEventListener('click', function() {
                    const copyText = this.getAttribute('data-copy-text');
                    copyToClipboard(copyText, this);
                });
            });
            
            // Hide delete confirmations when clicking outside
            document.addEventListener('click', function(event) {
                if (!event.target.closest('.tag-item-wrapper')) {
                    document.querySelectorAll('.delete-confirm').forEach(confirm => {
                        confirm.classList.add('hidden');
                    });
                }
            });
        });

        function copyToClipboard(text, button) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(() => {
                    showCopySuccess(button);
                }).catch((err) => {
                    console.error('Clipboard API failed:', err);
                    fallbackCopy(text, button);
                });
            } else {
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
            const originalClass = button.className;
            
            button.innerHTML = '✗';
            button.className = button.className.replace('bg-gray-200', 'bg-red-500 text-white');
            
            setTimeout(() => {
                button.innerHTML = originalText;
                button.className = originalClass;
            }, 2000);
        }

        // Save description functionality  
        async function saveDescription() {
            const description = document.getElementById('description').value;
            await updateWorkflowField('description', description, event.target);
        }

        // Tag management functions
        function addNewTag() {
            document.getElementById('add-tag-form').classList.remove('hidden');
            document.getElementById('new-tag-input').focus();
        }

        function cancelAddTag() {
            document.getElementById('add-tag-form').classList.add('hidden');
            document.getElementById('new-tag-input').value = '';
        }

        async function saveNewTag() {
            const tagInput = document.getElementById('new-tag-input');
            const tagValue = tagInput.value.trim();
            
            if (!tagValue) return;
            
            try {
                const response = await fetch(`/api/workflows/${workflowId}/tags`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag: tagValue })
                });
                
                if (response.ok) {
                    // Add tag to UI
                    addTagToUI(tagValue);
                    cancelAddTag();
                    showSuccessToast('Tag added successfully');
                } else {
                    alert('Failed to add tag');
                }
            } catch (error) {
                console.error('Error adding tag:', error);
                alert('Error adding tag');
            }
        }

        function showDeleteConfirm(button, tagValue) {
            // Hide any other open confirmations
            document.querySelectorAll('.delete-confirm').forEach(confirm => {
                confirm.classList.add('hidden');
            });
            
            // Show confirmation for this tag
            const tagWrapper = button.closest('.tag-item-wrapper');
            const confirmDiv = tagWrapper.querySelector('.delete-confirm');
            confirmDiv.classList.remove('hidden');
        }

        function cancelDelete(button) {
            const confirmDiv = button.closest('.delete-confirm');
            confirmDiv.classList.add('hidden');
        }

        async function confirmDelete(button, tagValue) {
            try {
                const response = await fetch(`/api/workflows/${workflowId}/tags`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag: tagValue })
                });
                
                if (response.ok) {
                    // Remove tag from UI
                    removeTagFromUI(tagValue);
                    showSuccessToast('Tag deleted successfully');
                } else {
                    alert('Failed to delete tag');
                }
            } catch (error) {
                console.error('Error deleting tag:', error);
                alert('Error deleting tag');
            }
        }

        function editTag(tagElement, originalTag) {
            const input = document.createElement('input');
            input.type = 'text';
            input.value = originalTag;
            input.className = 'px-1 text-xs border border-gray-300 rounded';
            input.style.width = Math.max(50, originalTag.length * 8) + 'px';
            
            const saveEdit = async () => {
                const newTag = input.value.trim();
                if (newTag && newTag !== originalTag) {
                    try {
                        const response = await fetch(`/api/workflows/${workflowId}/tags`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ oldTag: originalTag, newTag: newTag })
                        });
                        
                        if (response.ok) {
                            tagElement.textContent = newTag;
                            tagElement.onclick = () => editTag(tagElement, newTag);
                            showSuccessToast('Tag updated successfully');
                        } else {
                            alert('Failed to update tag');
                            tagElement.textContent = originalTag;
                        }
                    } catch (error) {
                        console.error('Error updating tag:', error);
                        alert('Error updating tag');
                        tagElement.textContent = originalTag;
                    }
                } else {
                    tagElement.textContent = originalTag;
                }
                tagElement.style.display = 'inline';
            };
            
            input.addEventListener('blur', saveEdit);
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    saveEdit();
                }
            });
            
            tagElement.style.display = 'none';
            tagElement.parentNode.insertBefore(input, tagElement.nextSibling);
            input.focus();
            input.select();
        }

        // Project info saving
        async function saveProjectInfo() {
            const clientName = document.getElementById('client-name').value.trim();
            const projectName = document.getElementById('project-name').value.trim();
            
            try {
                const response = await fetch(`/api/workflows/${workflowId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        client_name: clientName,
                        project_name: projectName
                    })
                });
                
                if (response.ok) {
                    showSuccessMessage('Project information saved successfully');
                } else {
                    alert('Failed to save project information');
                }
            } catch (error) {
                console.error('Error saving project info:', error);
                alert('Error saving project information');
            }
        }

        // Workflow execution (placeholder)
        function runWorkflow() {
            alert('🚀 Workflow execution feature coming soon!\\n\\nThis will integrate with ComfyUI API to run the workflow with current parameters.');
        }

        // Utility functions
        async function updateWorkflowField(field, value, button) {
            try {
                const response = await fetch(`/api/workflows/${workflowId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ [field]: value })
                });
                
                if (response.ok) {
                    showSuccessMessage('Saved successfully', button);
                } else {
                    alert(`Failed to save ${field}`);
                }
            } catch (error) {
                console.error(`Error saving ${field}:`, error);
                alert(`Error saving ${field}`);
            }
        }

        function showSuccessMessage(message, button = null) {
            if (button) {
                const originalText = button.textContent;
                const originalClass = button.className;
                button.textContent = '✓ Saved!';
                button.className = button.className.replace('bg-blue-500', 'bg-green-500');
                
                setTimeout(() => {
                    button.textContent = originalText;
                    button.className = originalClass;
                }, 2000);
            } else {
                showSuccessToast(message);
            }
        }

        function showSuccessToast(message) {
            const toast = document.getElementById('copyToast');
            const messageSpan = toast.querySelector('span:last-child');
            messageSpan.textContent = message;
            toast.style.transform = 'translateX(0)';
            setTimeout(() => {
                toast.style.transform = 'translateX(100%)';
            }, 2000);
        }

        function addTagToUI(tagValue) {
            const container = document.getElementById('tags-container');
            const tagHtml = `
                <span class="tag-item-wrapper relative">
                    <span class="tag-item bg-gray-200 text-gray-800 px-2 py-1 rounded text-xs flex items-center gap-1 group">
                        <span class="tag-text cursor-pointer" onclick="editTag(this, '${tagValue.replace(/'/g, "\\'")}')" title="Click to edit">${tagValue}</span>
                        <button onclick="showDeleteConfirm(this, '${tagValue.replace(/'/g, "\\'")}')" class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity ml-1" title="Delete tag">×</button>
                    </span>
                    <div class="delete-confirm hidden absolute top-full left-0 mt-1 bg-white border border-red-300 rounded-md shadow-lg p-2 z-10 whitespace-nowrap">
                        <div class="text-xs text-gray-700 mb-2">Delete "${tagValue}"?</div>
                        <div class="flex gap-1">
                            <button onclick="confirmDelete(this, '${tagValue.replace(/'/g, "\\'")}')" class="bg-red-500 text-white px-2 py-1 rounded text-xs hover:bg-red-600">Delete</button>
                            <button onclick="cancelDelete(this)" class="bg-gray-300 text-gray-700 px-2 py-1 rounded text-xs hover:bg-gray-400">Cancel</button>
                        </div>
                    </div>
                </span>
            `;
            container.insertAdjacentHTML('beforeend', tagHtml);
        }

        function removeTagFromUI(tagValue) {
            const tagWrappers = document.querySelectorAll('.tag-item-wrapper');
            tagWrappers.forEach(wrapper => {
                const textSpan = wrapper.querySelector('.tag-text');
                if (textSpan && textSpan.textContent === tagValue) {
                    wrapper.remove();
                }
            });
        }
    </script>
</body>
</html>'''
    
    # Replace the workflow ID placeholder
    html_content = html_content.replace('{{WORKFLOW_ID_PLACEHOLDER}}', workflow.id)
    
    return html_content


def generate_nodes_section_html(workflow_json):
    """Generate the detailed nodes analysis section HTML."""
    import html as html_escape
    
    if not workflow_json:
        return '<div class="bg-white rounded-lg shadow-sm border p-6"><p class="text-gray-500">No workflow data available.</p></div>'
    
    # Sort nodes by ID for consistent display
    sorted_nodes = sorted(workflow_json.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
    
    html = '''
        <!-- Node Analysis -->
        <div class="bg-white rounded-lg shadow-sm border p-6 mb-8">
            <h2 class="text-xl font-semibold mb-6">Node Analysis</h2>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    '''
    
    for node_id in sorted_nodes:
        node_data = workflow_json[node_id]
        class_type = node_data.get("class_type", "Unknown")
        inputs = node_data.get("inputs", {})
        
        # Get node title from _meta if available
        meta = node_data.get("_meta", {})
        title = meta.get("title", f"{class_type}")
        
        # Categorize parameters
        connections = []
        params = []
        key_params = []
        
        for param_name, param_value in inputs.items():
            if isinstance(param_value, list) and len(param_value) == 2:
                connections.append((param_name, param_value))
            else:
                params.append((param_name, param_value))
                # Mark key parameters (shorter values, commonly modified)
                if isinstance(param_value, (int, float, str)) and len(str(param_value)) <= 20:
                    key_params.append((param_name, param_value))
        
        html += f'''
            <div class="node-card bg-white rounded-lg shadow-sm border p-4 hover:shadow-md transition-shadow">
                <div class="flex items-center gap-2 mb-3">
                    <span class="text-2xl">⚙️</span>
                    <div>
                        <h3 class="font-bold text-lg text-gray-900">Node {node_id}</h3>
                        <p class="text-sm text-gray-600">{html_escape.escape(class_type)}</p>
                    </div>
                </div>
                
                <h4 class="font-medium text-gray-800 mb-2">{html_escape.escape(title)}</h4>
                
                <div class="text-xs text-gray-500 mb-3">
                    🔗 {len(connections)} inputs • ⚙️ {len(params)} params
                </div>
        '''
        
        # Show key parameters
        if key_params:
            html += '<div class="bg-gray-50 rounded p-2 text-xs mb-3"><div class="font-medium mb-1">Key Parameters:</div>'
            for param_name, param_value in key_params[:3]:  # Show first 3
                value_str = str(param_value)
                if len(value_str) > 20:
                    value_str = value_str[:17] + "..."
                html += f'<div>{html_escape.escape(param_name)}: {html_escape.escape(value_str)}</div>'
            html += '</div>'
        
        # Expandable all parameters section
        html += '''
                <details class="mt-3">
                    <summary class="text-xs text-gray-600 cursor-pointer hover:text-gray-800">All parameters & CLI commands</summary>
                    <div class="mt-2 text-xs space-y-1">
        '''
        
        # Add all parameters with copy functionality
        for param_name, param_value in params:
            if isinstance(param_value, (str, int, float, bool)):
                value_str = str(param_value)
                full_value_str = value_str
                if len(value_str) > 30:
                    value_str = value_str[:27] + "..."
                
                # Escape values for HTML attributes
                escaped_value = html_escape.escape(str(full_value_str))
                copy_command = f'--node {node_id} --param {param_name} "{full_value_str}"'
                escaped_copy_command = html_escape.escape(copy_command)
                
                # Parameter type hints
                dropdown_hint = ""
                if param_name.endswith('_name') and param_name in ['sampler_name', 'scheduler', 'model_name', 'vae_name', 'lora_name']:
                    dropdown_hint = ' <span class="text-xs text-orange-600 cursor-help" title="Dropdown parameter - values depend on installed models">⚠️</span>'
                elif param_name.endswith(('_mode', '_method', '_type')):
                    dropdown_hint = ' <span class="text-xs text-orange-600 cursor-help" title="Parameter likely has predefined options">⚠️</span>'
                
                copy_id = f"copy_{node_id}_{param_name.replace(' ', '_')}"
                html += f'''
                        <div class="bg-gray-50 p-2 rounded">
                            <div class="flex justify-between items-center">
                                <span class="font-medium">{html_escape.escape(param_name)}:</span>
                                <div class="flex items-center gap-1">
                                    <span class="text-gray-600 break-all" title="{escaped_value}">{html_escape.escape(value_str)}</span>{dropdown_hint}
                                    <button class="copy-btn ml-1 px-1 py-0.5 text-xs bg-gray-200 rounded hover:bg-blue-500 hover:text-white transition-colors" 
                                            data-copy-text="{escaped_copy_command}"
                                            id="{copy_id}"
                                            title="Copy CLI command"
                                            aria-label="Copy command line argument">
                                        📋
                                    </button>
                                </div>
                            </div>
                        </div>
                '''
        
        # Add connection parameters
        for param_name, param_value in connections:
            source_node, output_index = param_value
            html += f'''
                        <div class="bg-blue-50 p-2 rounded">
                            <div class="flex justify-between">
                                <span class="text-blue-700 font-medium">{html_escape.escape(param_name)}:</span>
                                <span class="text-blue-600">→ Node {source_node}[{output_index}]</span>
                            </div>
                        </div>
            '''
        
        html += '''
                    </div>
                </details>
            </div>
        '''
    
    # Add command line reference
    html += f'''
            </div>
            
            <!-- Command Line Reference -->
            <div class="mt-8 p-6 bg-blue-50 rounded-lg">
                <h3 class="text-xl font-semibold mb-4">💡 Command Line Reference</h3>
                <div class="mb-4 p-3 bg-white rounded-lg">
                    <div class="text-sm text-blue-800 font-medium mb-2">Pro Tips:</div>
                    <ul class="text-xs text-blue-700 space-y-1">
                        <li>• Click the 📋 button next to any parameter to copy its CLI command</li>
                        <li>• Look for ⚠️ icons to identify dropdown/enum parameters</li>
                        <li>• Parameters with → symbols are node connections (not CLI modifiable)</li>
                        <li>• Use the copied commands with your ComfyUI CLI tools</li>
                    </ul>
                </div>
                
                <div class="text-sm text-gray-700 mb-4">Example commands for key nodes:</div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm font-mono">
    '''
    
    # Show example commands for first few nodes
    for node_id in sorted_nodes[:6]:
        node_data = workflow_json[node_id]
        class_type = node_data.get("class_type", "Unknown")
        inputs = node_data.get("inputs", {})
        
        # Get non-connection parameters
        params = [k for k, v in inputs.items() if not (isinstance(v, list) and len(v) == 2)]
        
        if params:
            first_param = params[0]
            html += f'''
                <div class="bg-white p-3 rounded shadow-sm">
                    <div class="text-gray-900 font-bold mb-1">Node {node_id}</div>
                    <div class="text-blue-600 text-xs">--node {node_id} --param {first_param} value</div>
                    <div class="text-xs text-gray-500 mt-1">{html_escape.escape(class_type)}</div>
                    <div class="text-xs text-gray-400 mt-1">Params: {", ".join(params[:3])}</div>
                </div>
            '''
    
    html += '''
                </div>
            </div>
        </div>
    '''
    
    return html

app = FastAPI(
    title="💡 Comfy Light Table",
    description="Quality of Life Improvements with drag-and-drop processing",
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    global DATABASE_AVAILABLE
    if DATABASE_AVAILABLE:
        try:
            db_manager = get_database_manager()
            logger.info(f"📁 Using database: {db_manager.database_url}")
            db_manager.create_tables()
            
            # Show database stats
            with db_manager.get_session() as session:
                workflow_count = session.query(WorkflowFile).count()
                logger.info(f"📊 Database contains {workflow_count} workflows")
            
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            DATABASE_AVAILABLE = False

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (for generated catalogs)
import os
catalogs_dir = Path("./catalogs")
if catalogs_dir.exists():
    app.mount("/catalogs", StaticFiles(directory="catalogs"), name="catalogs")

# Global state for managing processing tasks
processing_tasks: Dict[str, Dict] = {}
connected_clients: List[WebSocket] = []

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        if self.active_connections:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)
            
            # Clean up disconnected clients
            for conn in disconnected:
                self.disconnect(conn)

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def get_interface():
    """Serve the main web interface."""
    return HTMLResponse(content=get_interface_html(), status_code=200)

@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Handle file uploads (images or JSON workflows)."""
    results = []
    
    for file in files:
        try:
            # Generate unique task ID
            task_id = str(uuid.uuid4())
            
            # Read file content
            content = await file.read()
            file_path = Path(f"temp/{task_id}_{file.filename}")
            file_path.parent.mkdir(exist_ok=True)
            
            # Save uploaded file temporarily
            with open(file_path, "wb") as f:
                f.write(content)
            
            # Initialize task tracking
            task_info = {
                "id": task_id,
                "filename": file.filename,
                "status": "processing",
                "file_path": str(file_path),
                "workflow": None,
                "analysis": None,
                "html_content": None,
                "error": None
            }
            
            processing_tasks[task_id] = task_info
            
            # Broadcast task started
            await manager.broadcast({
                "type": "task_started",
                "task_id": task_id,
                "filename": file.filename
            })
            
            # Process file asynchronously
            asyncio.create_task(process_file_async(task_id, file_path))
            
            results.append({
                "task_id": task_id,
                "filename": file.filename,
                "status": "queued"
            })
            
        except Exception as e:
            logger.error(f"Error uploading {file.filename}: {e}")
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e)
            })
    
    return JSONResponse(content={"results": results})

async def process_file_async(task_id: str, file_path: Path):
    """Process uploaded file asynchronously."""
    task_info = processing_tasks[task_id]
    
    try:
        # Update status
        task_info["status"] = "extracting"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "extracting",
            "message": "Extracting workflow from file..."
        })
        
        # Extract workflow based on file type
        workflow = None
        if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
            # Extract from image
            workflow = extract_workflow_from_image(file_path)
        elif file_path.suffix.lower() == '.json':
            # Load JSON workflow
            with open(file_path, 'r') as f:
                raw_workflow = json.load(f)
            workflow = ui_to_api_format(raw_workflow)
        
        if not workflow:
            raise ValueError("No ComfyUI workflow found in file")
        
        task_info["workflow"] = workflow
        
        # Update status
        task_info["status"] = "analyzing"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "analyzing",
            "message": "Analyzing workflow structure..."
        })
        
        # Analyze workflow
        analysis = analyze_workflow(workflow)
        task_info["analysis"] = analysis
        
        # Update status
        task_info["status"] = "generating"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "generating",
            "message": "Generating visualization..."
        })
        
        # Generate HTML visualization
        workflow_name = file_path.stem
        associated_image = str(file_path) if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'} else None
        
        html_content = generate_html_visual(
            workflow=workflow,
            workflow_name=workflow_name,
            server_address=None,
            image_path=associated_image
        )
        
        task_info["html_content"] = html_content
        task_info["status"] = "completed"
        
        # Broadcast completion
        await manager.broadcast({
            "type": "task_completed",
            "task_id": task_id,
            "filename": task_info["filename"],
            "analysis": {
                "total_nodes": analysis["total_nodes"],
                "node_types": len(analysis["node_types"]),
                "connections": len(analysis["connections"]),
                "input_nodes": len(analysis["input_nodes"]),
                "output_nodes": len(analysis["output_nodes"])
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {e}")
        task_info["status"] = "error"
        task_info["error"] = str(e)
        
        await manager.broadcast({
            "type": "task_error",
            "task_id": task_id,
            "filename": task_info["filename"],
            "error": str(e)
        })
    
    finally:
        # Clean up temporary file
        try:
            if file_path.exists():
                file_path.unlink()
        except:
            pass

@app.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Get status of a processing task."""
    if task_id not in processing_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_info = processing_tasks[task_id]
    return JSONResponse(content={
        "id": task_id,
        "filename": task_info["filename"],
        "status": task_info["status"],
        "error": task_info.get("error"),
        "analysis": task_info.get("analysis")
    })

@app.get("/task/{task_id}/html")
async def get_task_html(task_id: str):
    """Get generated HTML visualization for a task."""
    if task_id not in processing_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_info = processing_tasks[task_id]
    if task_info["status"] != "completed" or not task_info["html_content"]:
        raise HTTPException(status_code=400, detail="Task not completed or no HTML available")
    
    return HTMLResponse(content=task_info["html_content"])

@app.get("/task/{task_id}/workflow")
async def get_task_workflow(task_id: str):
    """Get extracted workflow JSON for a task."""
    if task_id not in processing_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task_info = processing_tasks[task_id]
    if not task_info["workflow"]:
        raise HTTPException(status_code=400, detail="No workflow available")
    
    return JSONResponse(content=task_info["workflow"])


# Database-powered catalog routes
@app.get("/api/workflows")
async def get_workflows(
    tag: Optional[str] = None,
    node_type: Optional[str] = None,
    collection: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """Get workflows from database with optional filtering."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        logger.info(f"Using database: {db_manager.database_url}")
        with db_manager.get_session() as session:
            # Query only the columns we need to avoid schema issues
            query = session.query(
                WorkflowFile.id,
                WorkflowFile.filename, 
                WorkflowFile.file_path,
                WorkflowFile.file_hash,
                WorkflowFile.file_size,
                WorkflowFile.node_count,
                WorkflowFile.node_types,
                WorkflowFile.style_tags,
                WorkflowFile.workflow_data,
                WorkflowFile.image_width,
                WorkflowFile.image_height,
                WorkflowFile.notes,
                WorkflowFile.created_at,
                WorkflowFile.updated_at
            )
            
            # Apply search filter (simplified - no joins for now)
            if search:
                query = query.filter(
                    WorkflowFile.filename.contains(search) |
                    WorkflowFile.notes.contains(search)
                )
            
            # Apply tag filter (for checkpoint/LoRA filtering)
            if tag:
                # For checkpoint/LoRA tags, we need to check the workflow_data JSON
                if tag.startswith('checkpoint:'):
                    checkpoint_name = tag[11:]  # Remove 'checkpoint:' prefix
                    query = query.filter(WorkflowFile.workflow_data.contains(checkpoint_name))
                elif tag.startswith('lora:'):
                    lora_name = tag[5:]  # Remove 'lora:' prefix
                    query = query.filter(WorkflowFile.workflow_data.contains(lora_name))
                else:
                    # Generic tag search in style_tags
                    query = query.filter(WorkflowFile.style_tags.contains(tag))
            
            # Apply node type filter
            if node_type:
                query = query.filter(WorkflowFile.node_types.contains(node_type))
            
            # Get total count for pagination
            total = query.count()
            logger.info(f"Found {total} workflows in database")
            
            # Apply pagination
            workflow_rows = query.offset(offset).limit(limit).all()
            logger.info(f"Retrieved {len(workflow_rows)} workflow rows after pagination")
            
            # Convert to JSON-serializable format
            results = []
            for row in workflow_rows:
                # Check if workflow has image data (PNG/JPEG files typically have image metadata)
                has_image = (row.image_width is not None and row.image_height is not None) or (
                    row.filename and row.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                )
                
                # Extract checkpoints and LoRAs from workflow data
                checkpoints = []
                loras = []
                try:
                    if row.workflow_data:
                        import json
                        if isinstance(row.workflow_data, str):
                            workflow_json = json.loads(row.workflow_data)
                        else:
                            workflow_json = row.workflow_data
                        
                        logger.info(f"Processing workflow {row.id} with {len(workflow_json)} nodes")
                        
                        # Look through all nodes to find checkpoints and LoRAs
                        if isinstance(workflow_json, dict):
                            for node_id, node in workflow_json.items():
                                if isinstance(node, dict) and "inputs" in node:
                                    inputs = node.get("inputs", {})
                                    class_type = node.get("class_type", "")
                                    
                                    # Check for checkpoint loaders
                                    if class_type in ["CheckpointLoaderSimple", "CheckpointLoader"]:
                                        if "ckpt_name" in inputs:
                                            checkpoints.append(inputs["ckpt_name"])
                                            logger.info(f"Found checkpoint: {inputs['ckpt_name']}")
                                    
                                    # Check for UNET loaders (modern checkpoint loaders)
                                    elif class_type in ["UnetLoaderGGUF", "UNETLoader"]:
                                        if "input_0" in inputs:
                                            checkpoints.append(inputs["input_0"])
                                            logger.info(f"Found UNET: {inputs['input_0']}")
                                        elif "unet_name" in inputs:
                                            checkpoints.append(inputs["unet_name"])
                                            logger.info(f"Found UNET: {inputs['unet_name']}")
                                    
                                    # Check for LoRA loaders
                                    elif class_type in ["LoraLoader", "LoRALoader"]:
                                        if "lora_name" in inputs:
                                            loras.append(inputs["lora_name"])
                                            logger.info(f"Found LoRA: {inputs['lora_name']}")
                                    
                                    # Check for Power LoRA loader (rgthree)
                                    elif class_type == "Power Lora Loader (rgthree)":
                                        # This node has complex input structure: input_2: {lora: "name", strength: 1, ...}
                                        if "input_2" in inputs and isinstance(inputs["input_2"], dict):
                                            lora_config = inputs["input_2"]
                                            if "lora" in lora_config and lora_config.get("on", True):
                                                loras.append(lora_config["lora"])
                                                logger.info(f"Found Power LoRA: {lora_config['lora']}")
                        
                        logger.info(f"Extracted {len(checkpoints)} checkpoints and {len(loras)} LoRAs")
                except Exception as e:
                    logger.error(f"Could not extract checkpoints/loras from workflow {row.id}: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Build tags from various sources
                tags = []
                if row.style_tags:
                    try:
                        if isinstance(row.style_tags, str):
                            import json
                            style_tags = json.loads(row.style_tags)
                        else:
                            style_tags = row.style_tags
                        tags.extend(style_tags)
                    except Exception:
                        pass
                
                # Add checkpoint and lora tags
                for checkpoint in checkpoints:
                    tags.append(f"checkpoint:{checkpoint}")
                for lora in loras:
                    tags.append(f"lora:{lora}")
                
                workflow_data = {
                    "id": row.id,
                    "name": row.filename,  # Use filename as name
                    "filename": row.filename,
                    "description": row.notes or "",  # Use notes as description
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "file_size": row.file_size,
                    "checksum": row.file_hash,  # Use file_hash as checksum
                    "has_image": has_image,
                    "node_count": row.node_count,
                    "node_types": row.node_types if row.node_types else [],
                    "checkpoints": checkpoints,
                    "loras": loras,
                    "tags": tags,
                    "collections": [],  # Temporarily disabled - would require separate query
                    "clients": [],  # Temporarily disabled until schema sync fixed
                    "projects": [],  # Temporarily disabled until schema sync fixed
                    "thumbnail_path": f"/api/workflows/{row.id}/thumbnail" if has_image else None
                }
                results.append(workflow_data)
            
            return {
                "workflows": results,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(results) < total
            }
            
    except Exception as e:
        logger.error(f"Error fetching workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workflows/{workflow_id}")
async def get_workflow_detail(workflow_id: str):
    """Get detailed workflow information."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            # Get workflow JSON from database
            workflow_json = workflow.workflow_data
            
            # If not in database, try reading from file
            if not workflow_json and workflow.file_path and Path(workflow.file_path).exists():
                try:
                    with open(workflow.file_path, 'r') as f:
                        content = f.read()
                    workflow_json = json.loads(content)
                except Exception as e:
                    logger.warning(f"Could not read workflow JSON for {workflow.filename}: {e}")
            
            # Check if workflow has image data
            has_image = (workflow.image_width is not None and workflow.image_height is not None) or (
                workflow.filename and workflow.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
            )
            
            return {
                "id": workflow.id,
                "name": workflow.filename,  # Use filename as name
                "filename": workflow.filename,
                "description": workflow.notes or "",  # Use notes as description
                "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
                "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
                "file_size": workflow.file_size,
                "checksum": workflow.file_hash,  # Use file_hash as checksum
                "has_image": has_image,
                "node_count": workflow.node_count,
                "tags": [tag.name for tag in workflow.tags],
                "collections": [collection.name for collection in workflow.collections],
                "clients": [],  # Temporarily disabled until schema sync fixed
                "projects": [],  # Temporarily disabled until schema sync fixed
                "file_path": workflow.file_path,
                "workflow": workflow_json
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflows/{workflow_id}")
async def get_workflow_detail_html(workflow_id: str):
    """Get workflow detail as HTML page with rich editing features."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            # Get workflow JSON
            workflow_json = None
            if workflow.workflow_data:
                try:
                    if isinstance(workflow.workflow_data, str):
                        workflow_json = json.loads(workflow.workflow_data)
                    else:
                        workflow_json = workflow.workflow_data
                except Exception as e:
                    logger.error(f"Error parsing workflow JSON for {workflow_id}: {e}")
            
            # Extract checkpoints and LoRAs
            checkpoints = []
            loras = []
            if workflow_json:
                for node_id, node in workflow_json.items():
                    if isinstance(node, dict) and "inputs" in node:
                        inputs = node.get("inputs", {})
                        class_type = node.get("class_type", "")
                        
                        # Extract checkpoints
                        if class_type in ["CheckpointLoaderSimple", "CheckpointLoader"]:
                            if "ckpt_name" in inputs:
                                checkpoints.append(inputs["ckpt_name"])
                        elif class_type in ["UnetLoaderGGUF", "UNETLoader"]:
                            if "input_0" in inputs:
                                checkpoints.append(inputs["input_0"])
                        
                        # Extract LoRAs
                        elif class_type in ["LoraLoader", "LoRALoader"]:
                            if "lora_name" in inputs:
                                loras.append(inputs["lora_name"])
                        elif class_type == "Power Lora Loader (rgthree)":
                            if "input_2" in inputs and isinstance(inputs["input_2"], dict):
                                lora_config = inputs["input_2"]
                                if "lora" in lora_config and lora_config.get("on", True):
                                    loras.append(lora_config["lora"])
            
            # Generate the HTML page
            html_content = generate_workflow_detail_html(workflow, workflow_json, checkpoints, loras)
            
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=html_content)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating workflow detail HTML for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/workflows/{workflow_id}")
async def update_workflow_metadata(workflow_id: str, request: dict):
    """Update workflow metadata (description, tags, etc.)."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            # Update description if provided
            if "description" in request:
                workflow.notes = request["description"]
                workflow.updated_at = datetime.utcnow()
            
            # Update client/project info if provided
            if "client_name" in request:
                # TODO: Store in proper client table when schema is synced
                workflow.updated_at = datetime.utcnow()
            
            if "project_name" in request:
                # TODO: Store in proper project table when schema is synced
                workflow.updated_at = datetime.utcnow()
            
            session.commit()
            
            return {"success": True, "message": "Workflow updated successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workflows/{workflow_id}/tags")
async def add_workflow_tag(workflow_id: str, request: dict):
    """Add a tag to a workflow."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        tag_name = request.get("tag", "").strip()
        if not tag_name:
            raise HTTPException(status_code=400, detail="Tag name is required")
        
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            # For now, we'll add tags to the style_tags JSON field
            # TODO: Use proper Tag table when schema is synced
            current_tags = []
            if workflow.style_tags:
                try:
                    if isinstance(workflow.style_tags, str):
                        current_tags = json.loads(workflow.style_tags)
                    else:
                        current_tags = workflow.style_tags
                except Exception:
                    current_tags = []
            
            # Deduplicate existing tags and add new tag if not present
            current_tags = list(dict.fromkeys(current_tags))  # Remove duplicates while preserving order
            if tag_name not in current_tags:
                current_tags.append(tag_name)
            workflow.style_tags = json.dumps(current_tags)
            workflow.updated_at = datetime.utcnow()
            session.commit()
            
            return {"success": True, "message": "Tag added successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding tag to workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/workflows/{workflow_id}/tags")
async def delete_workflow_tag(workflow_id: str, request: dict):
    """Delete a tag from a workflow."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        tag_name = request.get("tag", "").strip()
        if not tag_name:
            raise HTTPException(status_code=400, detail="Tag name is required")
        
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            current_tags = []
            if workflow.style_tags:
                try:
                    if isinstance(workflow.style_tags, str):
                        current_tags = json.loads(workflow.style_tags)
                    else:
                        current_tags = workflow.style_tags
                except Exception:
                    current_tags = []
            
            if tag_name in current_tags:
                # Remove ALL occurrences of the tag (in case of duplicates)
                current_tags = [tag for tag in current_tags if tag != tag_name]
                workflow.style_tags = json.dumps(current_tags)
                workflow.updated_at = datetime.utcnow()
                session.commit()
            
            return {"success": True, "message": "Tag deleted successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting tag from workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/workflows/{workflow_id}/tags")
async def update_workflow_tag(workflow_id: str, request: dict):
    """Update a tag in a workflow."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        old_tag = request.get("oldTag", "").strip()
        new_tag = request.get("newTag", "").strip()
        
        if not old_tag or not new_tag:
            raise HTTPException(status_code=400, detail="Both oldTag and newTag are required")
        
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            current_tags = []
            if workflow.style_tags:
                try:
                    if isinstance(workflow.style_tags, str):
                        current_tags = json.loads(workflow.style_tags)
                    else:
                        current_tags = workflow.style_tags
                except Exception:
                    current_tags = []
            
            if old_tag in current_tags:
                # Replace ALL occurrences of old tag with new tag, then deduplicate
                current_tags = [new_tag if tag == old_tag else tag for tag in current_tags]
                # Remove duplicates while preserving order
                current_tags = list(dict.fromkeys(current_tags))
                workflow.style_tags = json.dumps(current_tags)
                workflow.updated_at = datetime.utcnow()
                session.commit()
            
            return {"success": True, "message": "Tag updated successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tag in workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/deduplicate-tags")
async def deduplicate_all_tags():
    """Admin endpoint to remove duplicate tags from all workflows."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        updated_count = 0
        
        with db_manager.get_session() as session:
            workflows = session.query(WorkflowFile).filter(WorkflowFile.style_tags.isnot(None)).all()
            
            for workflow in workflows:
                current_tags = []
                if workflow.style_tags:
                    try:
                        if isinstance(workflow.style_tags, str):
                            current_tags = json.loads(workflow.style_tags)
                        else:
                            current_tags = workflow.style_tags
                    except Exception:
                        continue
                
                # Deduplicate tags while preserving order
                deduplicated_tags = list(dict.fromkeys(current_tags))
                
                if len(deduplicated_tags) != len(current_tags):
                    workflow.style_tags = json.dumps(deduplicated_tags)
                    workflow.updated_at = datetime.utcnow()
                    updated_count += 1
            
            session.commit()
        
        return {
            "success": True, 
            "message": f"Deduplicated tags for {updated_count} workflows",
            "updated_count": updated_count
        }
        
    except Exception as e:
        logger.error(f"Error deduplicating tags: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workflows/{workflow_id:path}/thumbnail")
async def get_workflow_thumbnail(workflow_id: str):
    """Get workflow thumbnail image."""
    print(f"🔍 THUMBNAIL ENDPOINT CALLED: '{workflow_id}'")
    logger.info(f"🔍 Thumbnail request for workflow_id: '{workflow_id}'")
    
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            logger.info(f"Searching for workflow with ID: {workflow_id}")
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            logger.info(f"Query result: {workflow}")
            
            if not workflow:
                # Debug: Check if any workflows exist
                total_count = session.query(WorkflowFile).count()
                logger.info(f"Total workflows in database: {total_count}")
                # Check first few IDs for comparison
                sample_ids = session.query(WorkflowFile.id).limit(3).all()
                logger.info(f"Sample workflow IDs: {[id[0] for id in sample_ids]}")
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            # Check if workflow has image data
            has_image = (workflow.image_width is not None and workflow.image_height is not None) or (
                workflow.filename and workflow.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
            )
            
            if not has_image or not workflow.file_path:
                raise HTTPException(status_code=404, detail="No thumbnail available")
            
            # Try to serve the image file directly
            try:
                file_path = Path(workflow.file_path)
                if not file_path.exists():
                    raise HTTPException(status_code=404, detail="Image file not found")
                    
                if file_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']:
                    # Return the image file directly
                    media_type = "image/png" if file_path.suffix.lower() == '.png' else "image/jpeg"
                    if file_path.suffix.lower() == '.webp':
                        media_type = "image/webp"
                    return FileResponse(workflow.file_path, media_type=media_type)
                else:
                    raise HTTPException(status_code=404, detail="Unsupported image format")
                    
            except Exception as e:
                logger.error(f"Error serving thumbnail for workflow {workflow_id}: {e}")
                raise HTTPException(status_code=500, detail="Could not serve thumbnail")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching thumbnail for workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tags")
async def get_tags():
    """Get all available tags."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Temporarily return empty list to avoid schema conflicts
    return {"tags": []}


@app.get("/api/collections")
async def get_collections():
    """Get all available collections."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Temporarily return empty list to avoid schema conflicts
    return {"collections": []}


# Temporarily disabled until schema sync is fixed
# @app.get("/api/clients")
# async def get_clients():
#     """Get all available clients."""
#     if not DATABASE_AVAILABLE:
#         raise HTTPException(status_code=503, detail="Database not available")
#     
#     try:
#         db_manager = get_database_manager()
#         with db_manager.get_session() as session:
#             clients = session.query(Client).filter(Client.is_active == True).all()
#             return {
#                 "clients": [{
#                     "id": client.id,
#                     "name": client.name,
#                     "client_code": client.client_code,
#                     "industry": client.industry,
#                     "workflow_count": len(client.files)
#                 } for client in clients]
#             }
#     except Exception as e:
#         logger.error(f"Error fetching clients: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# @app.get("/api/projects")
# async def get_projects():
#     """Get all available projects."""
#     if not DATABASE_AVAILABLE:
#         raise HTTPException(status_code=503, detail="Database not available")
#     
#     try:
#         db_manager = get_database_manager()
#         with db_manager.get_session() as session:
#             projects = session.query(Project).all()
#             return {
#                 "projects": [{
#                     "id": project.id,
#                     "name": project.name,
#                     "project_code": project.project_code,
#                     "client_name": project.client.name if project.client else None,
#                     "status": project.status,
#                     "deadline": project.deadline.isoformat() if project.deadline else None,
#                     "workflow_count": len(project.files)
#                 } for project in projects]
#             }
#     except Exception as e:
#         logger.error(f"Error fetching projects: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


@app.get("/catalog", response_class=HTMLResponse)
async def catalog_page():
    """Serve the enhanced database-powered workflow catalog page with comprehensive tag management."""
    if not DATABASE_AVAILABLE:
        return HTMLResponse("""
        <html>
        <head><title>Catalog Unavailable</title></head>
        <body>
            <div style="padding: 2rem; text-align: center;">
                <h1>📚 Workflow Catalog</h1>
                <p>Database is not available. Please ensure the database is properly configured.</p>
                <a href="/" style="color: blue;">← Back to Upload Interface</a>
            </div>
        </body>
        </html>
        """)
    
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ComfyUI Workflow Light Table</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .workflow-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 1.5rem;
                padding: 0;
            }
            .workflow-card {
                transition: all 0.3s ease;
                width: 100%;
            }
            .workflow-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(0,0,0,0.1);
            }
            .tag {
                display: inline-block;
                padding: 0.25rem 0.5rem;
                margin: 0.125rem;
                background: #e5e7eb;
                border-radius: 0.375rem;
                font-size: 0.75rem;
                font-weight: 500;
                color: #374151;
            }
            .checkpoint-tag { background: #dbeafe; color: #1e40af; }
            .lora-tag { background: #fef3c7; color: #92400e; }
            .node-tag { background: #f3e8ff; color: #7c3aed; }
            .thumbnail {
                width: 100%;
                height: 200px;
                object-fit: cover;
                border-radius: 0.5rem;
            }
            .no-thumbnail {
                width: 100%;
                height: 200px;
                background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
                border-radius: 0.5rem;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 3rem;
                color: #9ca3af;
            }
        </style>
    </head>
    <body class="bg-gray-50 min-h-screen">
        <!-- Header -->
        <header class="bg-white shadow-sm border-b">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center py-4">
                    <div class="flex items-center space-x-4">
                        <h1 class="text-3xl font-bold text-gray-900">� ComfyUI Workflow Light Table</h1>
                        <span id="workflow-count" class="bg-blue-100 text-blue-800 text-sm font-medium px-2.5 py-0.5 rounded">
                            Loading...
                        </span>
                    </div>
                    <div class="flex items-center space-x-4">
                        <a href="/" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">
                            📤 Upload Workflows
                        </a>
                    </div>
                </div>
                
                <!-- Search and Filters -->
                <div class="pb-4 border-t pt-4">
                    <div class="flex flex-wrap gap-4 items-center">
                        <!-- Search -->
                        <div class="flex-1 min-w-64">
                            <input type="text" id="search-input" placeholder="Search workflows..." 
                                   class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                        </div>
                        
                        <!-- Checkpoint Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">Checkpoint:</label>
                            <select id="checkpoint-filter" class="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                                <option value="">All Checkpoints</option>
                            </select>
                        </div>
                        
                        <!-- LoRA Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">LoRA:</label>
                            <select id="lora-filter" class="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                                <option value="">All LoRAs</option>
                            </select>
                        </div>
                        
                        <!-- Node Type Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">Node Type:</label>
                            <select id="node-type-filter" class="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                                <option value="">All Node Types</option>
                            </select>
                        </div>
                        
                        <!-- Clear Filters -->
                        <button id="clear-filters" class="text-sm text-gray-500 hover:text-gray-700 underline">
                            Clear All
                        </button>
                    </div>
                </div>
            </div>
        </header>

        <!-- Main Content -->
        <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <!-- Loading State -->
            <div id="loading" class="text-center py-12">
                <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                <p class="mt-2 text-gray-600">Loading workflows...</p>
            </div>
            
            <!-- Error State -->
            <div id="error" class="hidden text-center py-12">
                <div class="text-red-500 text-6xl mb-4">⚠️</div>
                <h2 class="text-xl font-semibold text-gray-900 mb-2">Error Loading Workflows</h2>
                <p id="error-message" class="text-gray-600 mb-4"></p>
                <button onclick="loadWorkflows()" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                    Try Again
                </button>
            </div>
            
            <!-- Empty State -->
            <div id="empty" class="hidden text-center py-12">
                <div class="text-gray-400 text-6xl mb-4">📁</div>
                <h2 class="text-xl font-semibold text-gray-900 mb-2">No Workflows Found</h2>
                <p class="text-gray-600 mb-4">Try adjusting your filters or upload some workflows to get started.</p>
                <a href="/" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                    Upload Workflows
                </a>
            </div>
            
            <!-- Workflow Grid -->
            <div id="workflow-grid" class="workflow-grid hidden">
                <!-- Workflow items will be inserted here -->
            </div>
            
            <!-- Load More -->
            <div id="load-more-container" class="hidden text-center mt-8">
                <button id="load-more" class="bg-gray-500 text-white px-6 py-2 rounded hover:bg-gray-600 transition-colors">
                    Load More Workflows
                </button>
            </div>
        </main>

        <script>
            // Configuration
            const API_BASE = '/api';
            
            // State management
            let currentWorkflows = [];
            let allCheckpoints = [];
            let allLoras = [];
            let allNodeTypes = [];
            let currentFilters = {
                search: '',
                checkpoint: '',
                lora: '',
                nodeType: '',
                offset: 0,
                limit: 50
            };
            let hasMore = true;

            // Initialize page
            document.addEventListener('DOMContentLoaded', function() {
                loadFilters();
                loadWorkflows();
                setupEventListeners();
            });

            function setupEventListeners() {
                // Search input with debounce
                let searchTimeout;
                document.getElementById('search-input').addEventListener('input', function(e) {
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(() => {
                        currentFilters.search = e.target.value;
                        resetAndReload();
                    }, 300);
                });

                // Filter dropdowns
                document.getElementById('checkpoint-filter').addEventListener('change', function(e) {
                    currentFilters.checkpoint = e.target.value;
                    resetAndReload();
                });

                document.getElementById('lora-filter').addEventListener('change', function(e) {
                    currentFilters.lora = e.target.value;
                    resetAndReload();
                });

                document.getElementById('node-type-filter').addEventListener('change', function(e) {
                    currentFilters.nodeType = e.target.value;
                    resetAndReload();
                });

                // Clear filters
                document.getElementById('clear-filters').addEventListener('click', function() {
                    document.getElementById('search-input').value = '';
                    document.getElementById('checkpoint-filter').value = '';
                    document.getElementById('lora-filter').value = '';
                    document.getElementById('node-type-filter').value = '';
                    currentFilters = {
                        search: '',
                        checkpoint: '',
                        lora: '',
                        nodeType: '',
                        offset: 0,
                        limit: 50
                    };
                    resetAndReload();
                });

                // Load more button
                document.getElementById('load-more').addEventListener('click', function() {
                    currentFilters.offset += currentFilters.limit;
                    loadWorkflows(true);
                });
            }

            async function loadFilters() {
                try {
                    const response = await fetch(`${API_BASE}/workflows?limit=1000`);
                    if (!response.ok) return;
                    
                    const data = await response.json();
                    const workflows = data.workflows;

                    // Extract unique values
                    const checkpointSet = new Set();
                    const loraSet = new Set();
                    const nodeTypeSet = new Set();

                    workflows.forEach(workflow => {
                        workflow.tags.forEach(tag => {
                            if (tag.startsWith('checkpoint:')) {
                                checkpointSet.add(tag.substring(11));
                            } else if (tag.startsWith('lora:')) {
                                loraSet.add(tag.substring(5));
                            }
                        });
                        
                        if (workflow.node_types) {
                            workflow.node_types.forEach(nodeType => {
                                nodeTypeSet.add(nodeType);
                            });
                        }
                    });

                    // Populate checkpoints
                    allCheckpoints = Array.from(checkpointSet).sort();
                    const checkpointSelect = document.getElementById('checkpoint-filter');
                    checkpointSelect.innerHTML = '<option value="">All Checkpoints</option>';
                    allCheckpoints.forEach(checkpoint => {
                        const option = document.createElement('option');
                        option.value = checkpoint;
                        option.textContent = checkpoint;
                        checkpointSelect.appendChild(option);
                    });

                    // Populate LoRAs
                    allLoras = Array.from(loraSet).sort();
                    const loraSelect = document.getElementById('lora-filter');
                    loraSelect.innerHTML = '<option value="">All LoRAs</option>';
                    allLoras.forEach(lora => {
                        const option = document.createElement('option');
                        option.value = lora;
                        option.textContent = lora;
                        loraSelect.appendChild(option);
                    });

                    // Populate node types
                    allNodeTypes = Array.from(nodeTypeSet).sort();
                    const nodeTypeSelect = document.getElementById('node-type-filter');
                    nodeTypeSelect.innerHTML = '<option value="">All Node Types</option>';
                    allNodeTypes.forEach(nodeType => {
                        const option = document.createElement('option');
                        option.value = nodeType;
                        option.textContent = nodeType;
                        nodeTypeSelect.appendChild(option);
                    });

                } catch (error) {
                    console.error('Error loading filters:', error);
                }
            }

            async function loadWorkflows(append = false) {
                try {
                    showLoading(!append);
                    
                    // Build query parameters
                    const params = new URLSearchParams();
                    if (currentFilters.search) params.append('search', currentFilters.search);
                    params.append('limit', currentFilters.limit);
                    params.append('offset', currentFilters.offset);

                    console.log('Loading workflows with params:', params.toString());
                    
                    const response = await fetch(`${API_BASE}/workflows?${params}`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }
                    
                    const data = await response.json();
                    console.log('Received workflows data:', data);
                    
                    let workflows = data.workflows;

                    // Apply client-side filters
                    if (currentFilters.checkpoint) {
                        workflows = workflows.filter(w => 
                            w.tags.some(tag => tag === `checkpoint:${currentFilters.checkpoint}`)
                        );
                    }
                    if (currentFilters.lora) {
                        workflows = workflows.filter(w => 
                            w.tags.some(tag => tag === `lora:${currentFilters.lora}`)
                        );
                    }
                    if (currentFilters.nodeType) {
                        workflows = workflows.filter(w => 
                            w.node_types && w.node_types.includes(currentFilters.nodeType)
                        );
                    }
                    
                    if (append) {
                        currentWorkflows = currentWorkflows.concat(workflows);
                    } else {
                        currentWorkflows = workflows;
                    }
                    
                    hasMore = data.has_more;
                    
                    renderWorkflows(append);
                    updateWorkflowCount(workflows.length);
                    
                    hideLoading();
                    
                } catch (error) {
                    console.error('Error loading workflows:', error);
                    showError(error.message);
                }
            }

            function resetAndReload() {
                currentFilters.offset = 0;
                hasMore = true;
                loadWorkflows(false);
            }

            function renderWorkflows(append = false) {
                const grid = document.getElementById('workflow-grid');
                
                if (!append) {
                    grid.innerHTML = '';
                }
                
                if (currentWorkflows.length === 0) {
                    showEmpty();
                    return;
                }
                
                const workflowsToRender = append ? 
                    currentWorkflows.slice(currentFilters.offset) : 
                    currentWorkflows;
                
                workflowsToRender.forEach(workflow => {
                    const workflowCard = createWorkflowCard(workflow);
                    grid.appendChild(workflowCard);
                });
                
                // Show/hide load more button
                const loadMoreContainer = document.getElementById('load-more-container');
                if (hasMore) {
                    loadMoreContainer.classList.remove('hidden');
                } else {
                    loadMoreContainer.classList.add('hidden');
                }
                
                grid.classList.remove('hidden');
            }

            function createWorkflowCard(workflow) {
                const div = document.createElement('div');
                div.className = 'workflow-card bg-white rounded-lg shadow-md overflow-hidden';
                
                const createdAt = workflow.created_at ? new Date(workflow.created_at).toLocaleDateString() : 'Unknown';
                
                // Separate tags by type
                const checkpointTags = workflow.tags.filter(tag => tag.startsWith('checkpoint:')).map(tag => tag.substring(11));
                const loraTags = workflow.tags.filter(tag => tag.startsWith('lora:')).map(tag => tag.substring(5));
                const otherTags = workflow.tags.filter(tag => !tag.startsWith('checkpoint:') && !tag.startsWith('lora:'));
                
                const checkpointTagsHtml = checkpointTags.map(tag => `<span class="tag checkpoint-tag">📁 ${tag}</span>`).join('');
                const loraTagsHtml = loraTags.map(tag => `<span class="tag lora-tag">🎯 ${tag}</span>`).join('');
                const otherTagsHtml = otherTags.map(tag => 
                    `<span class="tag-item-wrapper-catalog relative inline-block">
                        <span class="tag tag-editable bg-blue-100 text-blue-800 px-2 py-1 rounded text-xs flex items-center gap-1 group" style="display: inline-flex;">
                            <span class="tag-text">🏷️ ${tag}</span>
                            <button onclick="showDeleteConfirmCatalog(this, '${tag}', '${workflow.id}')" class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity ml-1" title="Delete tag">×</button>
                        </span>
                        <div class="delete-confirm hidden absolute top-full left-0 mt-1 bg-white border border-red-300 rounded-md shadow-lg p-2 z-50 whitespace-nowrap">
                            <div class="text-xs text-gray-700 mb-2">Delete "${tag}"?</div>
                            <div class="flex gap-1">
                                <button onclick="confirmDeleteCatalog(this, '${tag}', '${workflow.id}')" class="bg-red-500 text-white px-2 py-1 rounded text-xs hover:bg-red-600">Delete</button>
                                <button onclick="cancelDeleteCatalog(this)" class="bg-gray-300 text-gray-700 px-2 py-1 rounded text-xs hover:bg-gray-400">Cancel</button>
                            </div>
                        </div>
                    </span>`
                ).join(' ');
                
                div.innerHTML = `
                    ${workflow.has_image ? 
                        `<div class="thumbnail-container">
                            <img src="${API_BASE}/workflows/${workflow.id}/thumbnail" alt="${workflow.name}" class="thumbnail" 
                                 onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                            <div class="no-thumbnail" style="display: none;">🖼️</div>
                         </div>`
                        : '<div class="no-thumbnail">📄</div>'
                    }
                        
                    <div class="p-4">
                        <h3 class="font-semibold text-lg text-gray-900 mb-2">${workflow.name || workflow.filename || 'Untitled'}</h3>
                        
                        ${workflow.description ? 
                            `<p class="text-gray-600 text-sm mb-3">${workflow.description}</p>` 
                            : ''
                        }
                        
                        <div class="flex items-center justify-between text-xs text-gray-500 mb-3">
                            <span>📊 ${workflow.node_count || 0} nodes</span>
                            <span>📅 ${createdAt}</span>
                        </div>
                        
                        ${checkpointTagsHtml ? `<div class="mb-2">${checkpointTagsHtml}</div>` : ''}
                        ${loraTagsHtml ? `<div class="mb-2">${loraTagsHtml}</div>` : ''}
                        
                        <div class="mb-3">
                            <div class="flex items-center justify-between mb-1">
                                <span class="text-xs font-medium text-gray-600">Tags:</span>
                                <button onclick="showAddTagForm('${workflow.id}')" class="text-green-600 hover:text-green-800 text-xs" title="Add tag">+ Add</button>
                            </div>
                            <div id="tags-container-${workflow.id}" class="flex flex-wrap gap-1 mb-1">
                                ${otherTagsHtml || '<span class="text-xs text-gray-400">No tags</span>'}
                            </div>
                            <div id="add-tag-form-${workflow.id}" class="hidden">
                                <input type="text" id="new-tag-input-${workflow.id}" placeholder="Enter tag..." class="px-2 py-1 text-xs border border-gray-300 rounded mr-1 w-full mb-1">
                                <div class="flex gap-1">
                                    <button onclick="saveNewTagCatalog('${workflow.id}')" class="bg-blue-500 text-white px-2 py-1 rounded text-xs hover:bg-blue-600">Save</button>
                                    <button onclick="cancelAddTagCatalog('${workflow.id}')" class="bg-gray-300 text-gray-700 px-2 py-1 rounded text-xs hover:bg-gray-400">Cancel</button>
                                </div>
                            </div>
                        </div>
                        
                        <div class="flex space-x-2">
                            <button onclick="viewWorkflow('${workflow.id}')" 
                                    class="flex-1 bg-blue-500 text-white px-3 py-2 rounded text-sm hover:bg-blue-600 transition-colors">
                                👁️ View Details
                            </button>
                            <button onclick="downloadWorkflow('${workflow.id}', '${workflow.name || workflow.filename}')" 
                                    class="flex-1 bg-gray-500 text-white px-3 py-2 rounded text-sm hover:bg-gray-600 transition-colors">
                                📥 Download
                            </button>
                        </div>
                    </div>
                `;
                
                return div;
            }

            function updateWorkflowCount(total) {
                document.getElementById('workflow-count').textContent = `${total} workflows`;
            }

            function showLoading(show = true) {
                document.getElementById('loading').classList.toggle('hidden', !show);
            }

            function hideLoading() {
                document.getElementById('loading').classList.add('hidden');
            }

            function showError(message) {
                hideLoading();
                document.getElementById('error-message').textContent = message;
                document.getElementById('error').classList.remove('hidden');
                document.getElementById('workflow-grid').classList.add('hidden');
            }

            function showEmpty() {
                document.getElementById('empty').classList.remove('hidden');
                document.getElementById('workflow-grid').classList.add('hidden');
            }

            function viewWorkflow(workflowId) {
                // Open detailed HTML page in new tab - much richer than modal
                window.open(`/workflows/${workflowId}`, '_blank');
            }

            function downloadWorkflow(workflowId, filename) {
                // Download workflow JSON
                const link = document.createElement('a');
                link.href = `${API_BASE}/workflows/${workflowId}/download`;
                link.download = `${filename}_workflow.json`;
                link.click();
            }

            // Tag management functions
            function showAddTagForm(workflowId) {
                const form = document.getElementById(`add-tag-form-${workflowId}`);
                const input = document.getElementById(`new-tag-input-${workflowId}`);
                form.classList.remove('hidden');
                input.focus();
            }

            function cancelAddTagCatalog(workflowId) {
                const form = document.getElementById(`add-tag-form-${workflowId}`);
                const input = document.getElementById(`new-tag-input-${workflowId}`);
                form.classList.add('hidden');
                input.value = '';
            }

            async function saveNewTagCatalog(workflowId) {
                const input = document.getElementById(`new-tag-input-${workflowId}`);
                const tagValue = input.value.trim();
                
                if (!tagValue) return;
                
                try {
                    const response = await fetch(`${API_BASE}/workflows/${workflowId}/tags`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ tag: tagValue })
                    });
                    
                    if (response.ok) {
                        addTagToUICatalog(workflowId, tagValue);
                        cancelAddTagCatalog(workflowId);
                        showToast('Tag added successfully', 'success');
                    } else {
                        alert('Failed to add tag');
                    }
                } catch (error) {
                    console.error('Error adding tag:', error);
                    alert('Error adding tag');
                }
            }

            function showDeleteConfirmCatalog(button, tagValue, workflowId) {
                // Hide any other open confirmations
                document.querySelectorAll('.delete-confirm').forEach(confirm => {
                    confirm.classList.add('hidden');
                });
                
                // Show confirmation for this tag
                const tagWrapper = button.closest('.tag-item-wrapper-catalog');
                const confirmDiv = tagWrapper.querySelector('.delete-confirm');
                confirmDiv.classList.remove('hidden');
            }

            function cancelDeleteCatalog(button) {
                const confirmDiv = button.closest('.delete-confirm');
                confirmDiv.classList.add('hidden');
            }

            async function confirmDeleteCatalog(button, tagValue, workflowId) {
                try {
                    const response = await fetch(`${API_BASE}/workflows/${workflowId}/tags`, {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ tag: tagValue })
                    });
                    
                    if (response.ok) {
                        removeTagFromUICatalog(workflowId, tagValue);
                        showToast('Tag deleted successfully', 'success');
                    } else {
                        alert('Failed to delete tag');
                    }
                } catch (error) {
                    console.error('Error deleting tag:', error);
                    alert('Error deleting tag');
                }
            }

            function addTagToUICatalog(workflowId, tagValue) {
                const container = document.getElementById(`tags-container-${workflowId}`);
                
                // Remove "No tags" placeholder if present
                const noTagsSpan = container.querySelector('.text-gray-400');
                if (noTagsSpan) {
                    noTagsSpan.remove();
                }
                
                const tagHtml = `
                    <span class="tag-item-wrapper-catalog relative inline-block">
                        <span class="tag tag-editable bg-blue-100 text-blue-800 px-2 py-1 rounded text-xs flex items-center gap-1 group" style="display: inline-flex;">
                            <span class="tag-text">🏷️ ${tagValue}</span>
                            <button onclick="showDeleteConfirmCatalog(this, '${tagValue.replace(/'/g, "\\'")}', '${workflowId}')" class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity ml-1" title="Delete tag">×</button>
                        </span>
                        <div class="delete-confirm hidden absolute top-full left-0 mt-1 bg-white border border-red-300 rounded-md shadow-lg p-2 z-50 whitespace-nowrap">
                            <div class="text-xs text-gray-700 mb-2">Delete "${tagValue}"?</div>
                            <div class="flex gap-1">
                                <button onclick="confirmDeleteCatalog(this, '${tagValue.replace(/'/g, "\\'")}', '${workflowId}')" class="bg-red-500 text-white px-2 py-1 rounded text-xs hover:bg-red-600">Delete</button>
                                <button onclick="cancelDeleteCatalog(this)" class="bg-gray-300 text-gray-700 px-2 py-1 rounded text-xs hover:bg-gray-400">Cancel</button>
                            </div>
                        </div>
                    </span>
                `;
                container.insertAdjacentHTML('beforeend', tagHtml);
            }

            function removeTagFromUICatalog(workflowId, tagValue) {
                const container = document.getElementById(`tags-container-${workflowId}`);
                const tagWrappers = container.querySelectorAll('.tag-item-wrapper-catalog');
                
                tagWrappers.forEach(wrapper => {
                    const textSpan = wrapper.querySelector('.tag-text');
                    if (textSpan && textSpan.textContent === `🏷️ ${tagValue}`) {
                        wrapper.remove();
                    }
                });
                
                // Add "No tags" placeholder if container is empty
                if (container.children.length === 0) {
                    container.innerHTML = '<span class="text-xs text-gray-400">No tags</span>';
                }
            }

            function showToast(message, type = 'info') {
                const toast = document.createElement('div');
                toast.className = `fixed top-4 right-4 px-4 py-2 rounded-md text-white z-50 ${
                    type === 'success' ? 'bg-green-500' : 
                    type === 'error' ? 'bg-red-500' : 'bg-blue-500'
                }`;
                toast.textContent = message;
                document.body.appendChild(toast);
                
                setTimeout(() => {
                    toast.remove();
                }, 3000);
            }

            // Hide delete confirmations when clicking outside
            document.addEventListener('click', function(event) {
                if (!event.target.closest('.tag-item-wrapper-catalog')) {
                    document.querySelectorAll('.delete-confirm').forEach(confirm => {
                        confirm.classList.add('hidden');
                    });
                }
            });
        </script>
    </body>
    </html>
    """)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle any incoming messages
            data = await websocket.receive_text()
            # Echo back for heartbeat
            await websocket.send_json({"type": "heartbeat", "message": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)

def get_interface_html() -> str:
    """Generate the main web interface HTML."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>💡 Comfy Light Table</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .drop-zone {
            border: 2px dashed #cbd5e0;
            transition: all 0.3s ease;
        }
        .drop-zone.dragover {
            border-color: #4299e1;
            background-color: #ebf8ff;
        }
        .task-card {
            transition: all 0.3s ease;
        }
        .task-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        }
        .progress-bar {
            background: linear-gradient(90deg, #4299e1, #667eea);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <header class="text-center mb-8">
            <h1 class="text-5xl font-bold text-gray-900 mb-4">
                💡 Comfy Light Table
            </h1>
            <p class="text-xl text-gray-600 max-w-2xl mx-auto mb-6">
                Drag and drop your ComfyUI images or workflow JSON files to extract, analyze, and visualize workflows instantly
            </p>
            
            <!-- Navigation -->
            <div class="flex justify-center space-x-4">
                <a href="/catalog" 
                   class="inline-flex items-center px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors font-medium">
                    📚 Browse Workflow Catalog
                </a>
                <a href="#" onclick="document.getElementById('fileInput').click()" 
                   class="inline-flex items-center px-6 py-3 bg-gray-500 text-white rounded-lg hover:bg-gray-600 transition-colors font-medium">
                    📤 Upload New Workflows
                </a>
            </div>
        </header>

        <!-- Drop Zone -->
        <div id="dropZone" class="drop-zone bg-white rounded-xl border-2 border-dashed border-gray-300 p-12 text-center mb-8 cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-all">
            <div class="space-y-4">
                <div class="text-6xl">📁</div>
                <div class="space-y-2">
                    <p class="text-2xl font-semibold text-gray-700">Drop files here</p>
                    <p class="text-gray-500">or click to browse</p>
                </div>
                <div class="flex justify-center space-x-4 text-sm text-gray-400">
                    <span class="bg-gray-100 px-3 py-1 rounded-full">PNG</span>
                    <span class="bg-gray-100 px-3 py-1 rounded-full">WebP</span>
                    <span class="bg-gray-100 px-3 py-1 rounded-full">JPEG</span>
                    <span class="bg-gray-100 px-3 py-1 rounded-full">JSON</span>
                </div>
            </div>
            <input type="file" id="fileInput" multiple accept=".png,.webp,.jpg,.jpeg,.json" class="hidden">
        </div>

        <!-- Status Display -->
        <div id="statusDisplay" class="mb-8"></div>

        <!-- Tasks Grid -->
        <div id="tasksGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <!-- Task cards will be inserted here -->
        </div>
    </div>

    <!-- Footer -->
    <footer class="mt-16 py-8 border-t border-gray-200 text-center text-gray-500">
        <div class="flex items-center justify-center space-x-2">
            <span class="text-2xl">💡</span>
            <span class="font-medium">Comfy Light Table</span>
            <span>•</span>
            <span class="text-sm">Quality of Life Improvements</span>
        </div>
        <div class="mt-2 text-xs">
            Built In Venice Beach • Open Source Workflow Analysis
        </div>
    </footer>

    <script>
        // WebSocket connection for real-time updates
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        
        ws.onopen = function(event) {
            console.log('WebSocket connected');
            showStatus('🟢 Connected to server', 'success');
        };
        
        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        };
        
        ws.onclose = function(event) {
            console.log('WebSocket disconnected');
            showStatus('🔴 Disconnected from server', 'error');
        };

        // File handling
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        
        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', handleDragOver);
        dropZone.addEventListener('dragleave', handleDragLeave);
        dropZone.addEventListener('drop', handleDrop);
        fileInput.addEventListener('change', handleFileSelect);
        
        function handleDragOver(e) {
            e.preventDefault();
            dropZone.classList.add('dragover');
        }
        
        function handleDragLeave(e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
        }
        
        function handleDrop(e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files);
            uploadFiles(files);
        }
        
        function handleFileSelect(e) {
            const files = Array.from(e.target.files);
            uploadFiles(files);
        }
        
        async function uploadFiles(files) {
            const formData = new FormData();
            files.forEach(file => formData.append('files', file));
            
            showStatus(`📤 Uploading ${files.length} file(s)...`, 'processing');
            
            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                console.log('Upload result:', result);
                
                // Clear file input
                fileInput.value = '';
                
            } catch (error) {
                console.error('Upload error:', error);
                showStatus('❌ Upload failed', 'error');
            }
        }
        
        function handleWebSocketMessage(data) {
            console.log('WebSocket message:', data);
            
            switch(data.type) {
                case 'task_started':
                    addTaskCard(data.task_id, data.filename);
                    showStatus(`🚀 Started processing: ${data.filename}`, 'processing');
                    break;
                    
                case 'task_update':
                    updateTaskCard(data.task_id, data.status, data.message);
                    break;
                    
                case 'task_completed':
                    completeTaskCard(data.task_id, data.analysis);
                    showStatus(`✅ Completed: ${data.filename}`, 'success');
                    break;
                    
                case 'task_error':
                    errorTaskCard(data.task_id, data.error);
                    showStatus(`❌ Error processing: ${data.filename}`, 'error');
                    break;
            }
        }
        
        function showStatus(message, type) {
            const statusDisplay = document.getElementById('statusDisplay');
            const colorClass = type === 'success' ? 'bg-green-100 text-green-800' : 
                              type === 'error' ? 'bg-red-100 text-red-800' : 
                              'bg-blue-100 text-blue-800';
            
            statusDisplay.innerHTML = `
                <div class="${colorClass} px-4 py-2 rounded-lg text-center font-medium">
                    ${message}
                </div>
            `;
            
            // Auto-hide after 3 seconds for non-error messages
            if (type !== 'error') {
                setTimeout(() => statusDisplay.innerHTML = '', 3000);
            }
        }
        
        function addTaskCard(taskId, filename) {
            const tasksGrid = document.getElementById('tasksGrid');
            const taskCard = document.createElement('div');
            taskCard.id = `task-${taskId}`;
            taskCard.className = 'task-card bg-white rounded-lg shadow-md p-6';
            
            taskCard.innerHTML = `
                <div class="flex items-center justify-between mb-4">
                    <h3 class="font-semibold text-gray-900 truncate">${filename}</h3>
                    <div class="w-4 h-4 bg-blue-500 rounded-full animate-pulse"></div>
                </div>
                <div class="space-y-2">
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-600">Status:</span>
                        <span id="status-${taskId}" class="font-medium text-blue-600">Processing...</span>
                    </div>
                    <div class="w-full bg-gray-200 rounded-full h-2">
                        <div id="progress-${taskId}" class="progress-bar h-2 rounded-full w-1/4"></div>
                    </div>
                    <div id="message-${taskId}" class="text-sm text-gray-500">Starting...</div>
                </div>
                <div id="actions-${taskId}" class="mt-4 space-x-2 hidden">
                    <!-- Action buttons will be added when complete -->
                </div>
            `;
            
            tasksGrid.insertBefore(taskCard, tasksGrid.firstChild);
        }
        
        function updateTaskCard(taskId, status, message) {
            const statusElement = document.getElementById(`status-${taskId}`);
            const messageElement = document.getElementById(`message-${taskId}`);
            const progressElement = document.getElementById(`progress-${taskId}`);
            
            if (statusElement) statusElement.textContent = status;
            if (messageElement) messageElement.textContent = message;
            
            // Update progress bar
            if (progressElement) {
                const progressWidth = status === 'extracting' ? '33%' : 
                                    status === 'analyzing' ? '66%' : 
                                    status === 'generating' ? '90%' : '25%';
                progressElement.style.width = progressWidth;
            }
        }
        
        function completeTaskCard(taskId, analysis) {
            const statusElement = document.getElementById(`status-${taskId}`);
            const messageElement = document.getElementById(`message-${taskId}`);
            const progressElement = document.getElementById(`progress-${taskId}`);
            const actionsElement = document.getElementById(`actions-${taskId}`);
            
            if (statusElement) {
                statusElement.textContent = 'Completed';
                statusElement.className = 'font-medium text-green-600';
            }
            
            if (messageElement) {
                messageElement.innerHTML = `
                    <div class="text-sm space-y-1">
                        <div>📊 ${analysis.total_nodes} nodes</div>
                        <div>🔗 ${analysis.connections} connections</div>
                        <div>🎯 ${analysis.node_types} node types</div>
                    </div>
                `;
            }
            
            if (progressElement) {
                progressElement.style.width = '100%';
                progressElement.className = 'bg-green-500 h-2 rounded-full w-full';
            }
            
            if (actionsElement) {
                actionsElement.className = 'mt-4 space-x-2 flex';
                actionsElement.innerHTML = `
                    <button onclick="viewVisualization('${taskId}')" 
                            class="flex-1 bg-blue-500 text-white px-3 py-2 rounded text-sm hover:bg-blue-600 transition-colors">
                        📊 View Visualization
                    </button>
                    <button onclick="downloadJSON('${taskId}')" 
                            class="flex-1 bg-gray-500 text-white px-3 py-2 rounded text-sm hover:bg-gray-600 transition-colors">
                        📥 Download JSON
                    </button>
                `;
            }
        }
        
        function errorTaskCard(taskId, error) {
            const statusElement = document.getElementById(`status-${taskId}`);
            const messageElement = document.getElementById(`message-${taskId}`);
            const progressElement = document.getElementById(`progress-${taskId}`);
            
            if (statusElement) {
                statusElement.textContent = 'Error';
                statusElement.className = 'font-medium text-red-600';
            }
            
            if (messageElement) {
                messageElement.innerHTML = `<div class="text-sm text-red-600">${error}</div>`;
            }
            
            if (progressElement) {
                progressElement.className = 'bg-red-500 h-2 rounded-full';
            }
        }
        
        function viewVisualization(taskId) {
            window.open(`/task/${taskId}/html`, '_blank');
        }
        
        async function downloadJSON(taskId) {
            try {
                const response = await fetch(`/task/${taskId}/workflow`);
                const workflow = await response.json();
                
                const blob = new Blob([JSON.stringify(workflow, null, 2)], {
                    type: 'application/json'
                });
                
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `workflow-${taskId}.json`;
                a.click();
                URL.revokeObjectURL(url);
                
            } catch (error) {
                console.error('Download error:', error);
                showStatus('❌ Download failed', 'error');
            }
        }
        
        // Heartbeat to keep WebSocket alive
        setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'ping'}));
            }
        }, 30000);

        // Catalog tag management functions
        function showAddTagForm(workflowId) {
            const form = document.getElementById(`add-tag-form-${workflowId}`);
            const input = document.getElementById(`new-tag-input-${workflowId}`);
            form.classList.remove('hidden');
            input.focus();
        }

        function cancelAddTagCatalog(workflowId) {
            const form = document.getElementById(`add-tag-form-${workflowId}`);
            const input = document.getElementById(`new-tag-input-${workflowId}`);
            form.classList.add('hidden');
            input.value = '';
        }

        async function saveNewTagCatalog(workflowId) {
            const input = document.getElementById(`new-tag-input-${workflowId}`);
            const tagValue = input.value.trim();
            
            if (!tagValue) return;
            
            try {
                const response = await fetch(`/api/workflows/${workflowId}/tags`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag: tagValue })
                });
                
                if (response.ok) {
                    addTagToUICatalog(workflowId, tagValue);
                    cancelAddTagCatalog(workflowId);
                    showToast('Tag added successfully', 'success');
                } else {
                    alert('Failed to add tag');
                }
            } catch (error) {
                console.error('Error adding tag:', error);
                alert('Error adding tag');
            }
        }

        function showDeleteConfirmCatalog(button, tagValue, workflowId) {
            // Hide any other open confirmations
            document.querySelectorAll('.delete-confirm').forEach(confirm => {
                confirm.classList.add('hidden');
            });
            
            // Show confirmation for this tag
            const tagWrapper = button.closest('.tag-item-wrapper-catalog');
            const confirmDiv = tagWrapper.querySelector('.delete-confirm');
            confirmDiv.classList.remove('hidden');
        }

        function cancelDeleteCatalog(button) {
            const confirmDiv = button.closest('.delete-confirm');
            confirmDiv.classList.add('hidden');
        }

        async function confirmDeleteCatalog(button, tagValue, workflowId) {
            try {
                const response = await fetch(`/api/workflows/${workflowId}/tags`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tag: tagValue })
                });
                
                if (response.ok) {
                    removeTagFromUICatalog(workflowId, tagValue);
                    showToast('Tag deleted successfully', 'success');
                } else {
                    alert('Failed to delete tag');
                }
            } catch (error) {
                console.error('Error deleting tag:', error);
                alert('Error deleting tag');
            }
        }

        function addTagToUICatalog(workflowId, tagValue) {
            const container = document.getElementById(`tags-container-${workflowId}`);
            
            // Remove "No tags" placeholder if present
            const noTagsSpan = container.querySelector('.text-gray-400');
            if (noTagsSpan) {
                noTagsSpan.remove();
            }
            
            const tagHtml = `
                <span class="tag-item-wrapper-catalog relative inline-block">
                    <span class="tag tag-editable bg-blue-100 text-blue-800 px-2 py-1 rounded text-xs flex items-center gap-1 group">
                        <span class="tag-text">${tagValue}</span>
                        <button onclick="showDeleteConfirmCatalog(this, '${tagValue.replace(/'/g, "\\'")}', '${workflowId}')" class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity ml-1" title="Delete tag">×</button>
                    </span>
                    <div class="delete-confirm hidden absolute top-full left-0 mt-1 bg-white border border-red-300 rounded-md shadow-lg p-2 z-50 whitespace-nowrap">
                        <div class="text-xs text-gray-700 mb-2">Delete "${tagValue}"?</div>
                        <div class="flex gap-1">
                            <button onclick="confirmDeleteCatalog(this, '${tagValue.replace(/'/g, "\\'")}', '${workflowId}')" class="bg-red-500 text-white px-2 py-1 rounded text-xs hover:bg-red-600">Delete</button>
                            <button onclick="cancelDeleteCatalog(this)" class="bg-gray-300 text-gray-700 px-2 py-1 rounded text-xs hover:bg-gray-400">Cancel</button>
                        </div>
                    </div>
                </span>
            `;
            container.insertAdjacentHTML('beforeend', tagHtml);
        }

        function removeTagFromUICatalog(workflowId, tagValue) {
            const container = document.getElementById(`tags-container-${workflowId}`);
            const tagWrappers = container.querySelectorAll('.tag-item-wrapper-catalog');
            
            tagWrappers.forEach(wrapper => {
                const textSpan = wrapper.querySelector('.tag-text');
                if (textSpan && textSpan.textContent === tagValue) {
                    wrapper.remove();
                }
            });
            
            // Add "No tags" placeholder if container is empty
            if (container.children.length === 0) {
                container.innerHTML = '<span class="text-xs text-gray-400">No tags</span>';
            }
        }

        function showToast(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = `fixed top-4 right-4 px-4 py-2 rounded-md text-white z-50 ${
                type === 'success' ? 'bg-green-500' : 
                type === 'error' ? 'bg-red-500' : 'bg-blue-500'
            }`;
            toast.textContent = message;
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.remove();
            }, 3000);
        }

        // Hide delete confirmations when clicking outside
        document.addEventListener('click', function(event) {
            if (!event.target.closest('.tag-item-wrapper-catalog')) {
                document.querySelectorAll('.delete-confirm').forEach(confirm => {
                    confirm.classList.add('hidden');
                });
            }
        });
        
    </script>
</body>
</html>
    """

if __name__ == "__main__":
    # Create temp directory for uploads
    Path("temp").mkdir(exist_ok=True)
    
    # Start the web server
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8080,
        log_level="info"
    )
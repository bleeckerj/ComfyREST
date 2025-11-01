#!/usr/bin/env python3
"""
Comfy Light Table

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
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException, Request
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import database functionality
try:
    from database.database import get_database_manager, WorkflowFileManager
    from database.models import WorkflowFile, Tag, Collection, Client, Project
    DATABASE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Database not available: {e}")
    DATABASE_AVAILABLE = False

def generate_workflow_detail_html(workflow, workflow_json, checkpoints, loras):
    """Generate detailed HTML page for a workflow with rich editing features."""
    import html as html_escape
    
    # Build tags from proper relationship + legacy JSON field
    tags = []
    
    # Get tags from proper Tag relationship (preferred)
    if hasattr(workflow, 'tags') and workflow.tags:
        tags.extend([tag.name for tag in workflow.tags])
    
    # Also check legacy style_tags JSON field for backwards compatibility
    elif workflow.style_tags:  # Only use if no proper tags exist
        try:
            if isinstance(workflow.style_tags, str):
                import json
                style_tags = json.loads(workflow.style_tags)
            else:
                style_tags = workflow.style_tags
            tags.extend(style_tags)
        except Exception:
            pass
    
    # Add checkpoint and lora tags (but only if not already present)
    for checkpoint in checkpoints:
        checkpoint_tag = f"checkpoint:{checkpoint}"
        if checkpoint_tag not in tags:
            tags.append(checkpoint_tag)
    for lora in loras:
        lora_tag = f"lora:{lora}"
        if lora_tag not in tags:
            tags.append(lora_tag)
    
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
        :root {{
            --nasa-red: #fc3d21;
            --nasa-blue: #105bd8;
            --nasa-gray: #aeb0b5;
            --nasa-white: #ffffff;
            --nasa-dark: #212121;
            --nasa-orange: #ff9d1e;
        }}
        
        * {{
            font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
        }}
        
        body {{
            background: var(--nasa-white);
            color: var(--nasa-dark);
            font-weight: 400;
        }}
        
        .neo-brutalist-card {{
            background: var(--nasa-white);
            color: var(--nasa-dark);
            border: 1px solid var(--nasa-dark);
            font-weight: 400;
            border-radius: 2px;
        }}
        
        .node-card {{ 
            background: var(--nasa-white);
            border: 1px solid var(--nasa-dark);
            border-radius: 2px;
        }}
        .copy-btn {{ 
            font-size: 10px;
            background: transparent;
            color: var(--nasa-dark);
            border: 1px solid var(--nasa-dark);
            font-weight: 400;
            padding: 0.2rem 0.4rem;
            border-radius: 2px;
            cursor: pointer;
            transition: all 0.1s ease;
        }}
        
        .copy-btn:hover {{
            background: var(--nasa-dark);
            color: var(--nasa-white);
        }}
        
        .copy-btn.shift-hover:hover {{
            background: var(--nasa-orange);
            color: var(--nasa-white);
            border-color: var(--nasa-orange);
        }}
        
        .tag-custom {{
            background: transparent;
            color: var(--nasa-dark);
            border: 1px solid var(--nasa-dark);
            font-weight: 400;
            padding: 0.2rem 0.4rem;
            font-size: 0.65rem;
            border-radius: 2px;
        }}
        
        .tag-collection {{
            background: transparent;
            color: var(--nasa-blue);
            border: 1px solid var(--nasa-blue);
            font-weight: 400;
            padding: 0.2rem 0.4rem;
            font-size: 0.65rem;
            border-radius: 2px;
            display: inline-block;
            margin-right: 0.25rem;
            margin-bottom: 0.25rem;
        }}
        
        .btn-primary {{
            background: transparent;
            color: var(--nasa-orange);
            border: 1px solid var(--nasa-orange);
            font-weight: 400;
            padding: 0.5rem 1rem;
            font-size: 0.75rem;
            border-radius: 2px;
            text-transform: uppercase;
            letter-spacing: 0.025em;
            cursor: pointer;
            transition: all 0.1s ease;
        }}
        
        .btn-primary:hover {{
            background: var(--nasa-orange);
            color: var(--nasa-white);
            border-color: var(--nasa-orange);
        }}
        
        .btn-secondary {{
            background: transparent;
            color: var(--nasa-blue);
            border: 1px solid var(--nasa-dark);
            font-weight: 400;
            padding: 0.5rem 1rem;
            font-size: 0.75rem;
            border-radius: 2px;
            text-transform: uppercase;
            letter-spacing: 0.025em;
            cursor: pointer;
            transition: all 0.1s ease;
        }}
        
        .btn-secondary:hover {{
            background: var(--nasa-blue);
            color: var(--nasa-white);
            border-color: var(--nasa-blue);
        }}
        
        .btn-path {{
            background: transparent;
            color: var(--nasa-dark);
            border: 1px solid var(--nasa-dark);
            font-weight: 400;
            padding: 0.25rem 0.5rem;
            border-radius: 2px;
            cursor: pointer;
            font-size: 0.45rem;
            transition: all 0.1s ease;
        }}
        
        .btn-path:hover {{
            background: var(--nasa-dark);
            color: var(--nasa-white);
            border-color: var(--nasa-dark);
        }}
        
        .filename-truncated {{
            max-width: 400px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
    </style>
</head>
<body class="min-h-screen" style="background: var(--nasa-white); color: var(--nasa-dark);">
    <!-- Header -->
    <header class="neo-brutalist-card sticky top-0 z-40" style="border-radius: 0; border-left: none; border-right: none; border-top: none;">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between items-center py-4">
                <div class="flex items-center space-x-4">
                    <a href="/catalog" class="btn-secondary" style="text-decoration: none;">← Back to Catalog</a>
                    <h1 class="text-xl font-bold filename-truncated" style="color: var(--nasa-dark);" title="{html_escape.escape(workflow.filename or 'Unknown Workflow')}">{html_escape.escape(workflow.filename or "Unknown Workflow")}</h1>
                    <div class="flex items-center space-x-2">
                        <button onclick="copyToClipboard('{workflow.file_path.replace("'", "\\'")}', this)" class="btn-path" title="Copy file path">CPY</button>
                        <button onclick="openFileLocation('{workflow.file_path.replace("'", "\\'")}', this)" class="btn-path" title="Open file location">GTO</button>
                    </div>
                </div>
                <div class="flex items-center space-x-4">
                    {f'<a href="/api/workflows/{workflow.id}/thumbnail" target="_blank" class="btn-primary" style="text-decoration: none;">View Image</a>' if has_image else ''}
                    <a href="/api/workflows/{workflow.id}" class="btn-secondary" style="text-decoration: none;">Download JSON</a>
                </div>
            </div>
        </div>
    </header>

    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Workflow Info -->
        <div class="neo-brutalist-card p-6 mb-8">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                    <h2 class="text-xl font-semibold mb-4" style="color: var(--nasa-dark);">Workflow Information</h2>
                    <div class="space-y-3">
                        <div class="flex justify-between">
                            <span class="font-medium" style="color: var(--nasa-gray);">File:</span>
                            <span style="color: var(--nasa-dark);">{html_escape.escape(workflow.filename or "Unknown")}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium" style="color: var(--nasa-gray);">Size:</span>
                            <span style="color: var(--nasa-dark);">{file_size_str}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium" style="color: var(--nasa-gray);">Nodes:</span>
                            <span style="color: var(--nasa-dark);">{workflow.node_count or 0}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium" style="color: var(--nasa-gray);">File Date:</span>
                            <span style="color: var(--nasa-dark);">{workflow.file_modified_at.strftime("%Y-%m-%d %H:%M") if workflow.file_modified_at else "Unknown"}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="font-medium" style="color: var(--nasa-gray);">Ingested:</span>
                            <span class="text-xs" style="color: var(--nasa-dark);">{workflow.created_at.strftime("%Y-%m-%d %H:%M") if workflow.created_at else "Unknown"}</span>
                        </div>
                    </div>
                    
                    <!-- Editable Description -->
                    <div class="mt-6">
                        <label class="block font-medium mb-2" style="color: var(--nasa-gray);">Description:</label>
                        <textarea id="description" class="w-full px-3 py-2 border focus:outline-none" 
                                  style="border-color: var(--nasa-gray); border-radius: 2px; background: var(--nasa-white); color: var(--nasa-dark);"
                                  rows="3" placeholder="Add a description for this workflow...">{html_escape.escape(workflow.notes or "")}</textarea>
                        <button onclick="saveDescription()" class="mt-2 btn-secondary" style="text-decoration: none;">
                            Save Description
                        </button>
                    </div>
                </div>
                
                <div>
                    <!-- Workflow Image -->
                    {f'''
                    <div class="mb-6">
                        <h3 class="text-lg font-medium mb-3" style="color: var(--nasa-dark);">Workflow Output</h3>
                        <div class="neo-brutalist-card overflow-hidden">
                            <img src="/api/workflows/{workflow.id}/thumbnail" alt="Workflow output" 
                                 class="w-full h-auto max-h-64 object-contain"
                                 style="background: var(--nasa-white);"
                                 onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
                            <div class="text-center text-sm p-8 hidden" style="color: var(--nasa-gray);">
                                No image available
                            </div>
                        </div>
                    </div>''' if has_image else '''
                    <div class="mb-6">
                        <div class="neo-brutalist-card p-8 text-center" style="color: var(--nasa-gray);">
                            <span class="text-4xl" style="color: var(--nasa-gray);">[IMG]</span>
                            <p class="text-sm mt-2">No image available</p>
                        </div>
                    </div>'''}
                    
                    <!-- RUN WORKFLOW Button -->
                    <div class="mb-6">
                        <button onclick="runWorkflow()" class="w-full btn-primary flex items-center justify-center gap-2" style="text-decoration: none; padding: 0.75rem 1.5rem;">
                            RUN WORKFLOW
                        </button>
                        <p class="text-xs mt-2 text-center" style="color: var(--nasa-gray);">Execute this workflow in ComfyUI</p>
                    </div>

                    <!-- REMOVE WORKFLOW Button -->
                    <div class="mb-6">
                        <button onclick="removeWorkflow()" class="w-full btn-danger flex items-center justify-center gap-2" style="text-decoration: none; padding: 0.75rem 1.5rem;">
                            REMOVE FROM DATABASE
                        </button>
                        <p class="text-xs mt-2 text-center" style="color: var(--nasa-gray);">Remove catalog entry (files preserved)</p>
                    </div>
                    
                    <!-- Checkpoints & LoRAs -->
                    <h3 class="text-lg font-medium mb-3" style="color: var(--nasa-dark);">Resources</h3>
                    {f'''
                    <div class="mb-4">
                        <h4 class="font-medium mb-2" style="color: var(--nasa-gray);">Checkpoints ({len(checkpoints)}):</h4>
                        <div class="space-y-1">
                            {chr(10).join(f'<div class="neo-brutalist-card px-3 py-2 text-sm" style="border-color: var(--nasa-blue); color: var(--nasa-blue);">{html_escape.escape(cp)}</div>' for cp in checkpoints)}
                        </div>
                    </div>''' if checkpoints else ''}
                    
                    {f'''
                    <div class="mb-4">
                        <h4 class="font-medium mb-2" style="color: var(--nasa-gray);">LoRAs ({len(loras)}):</h4>
                        <div class="space-y-1">
                            {chr(10).join(f'<div class="neo-brutalist-card px-3 py-2 text-sm" style="border-color: var(--nasa-orange); color: var(--nasa-orange);">{html_escape.escape(lora)}</div>' for lora in loras)}
                        </div>
                    </div>''' if loras else ''}
                    
                    <!-- Tags with editing capabilities -->
                    <div class="mb-4">
                        <div class="flex justify-between items-center mb-2">
                            <h4 class="font-medium" style="color: var(--nasa-gray);">Tags ({len(tags)}):</h4>
                            <button onclick="addNewTag()" class="btn-primary" style="text-decoration: none; padding: 0.25rem 0.5rem; font-size: 0.75rem;">
                                Add Tag
                            </button>
                        </div>
                        <div id="tags-container" class="flex flex-wrap gap-2 mb-2">
                            {' '.join(f'''
                            <span class="tag-item-wrapper relative">
                                <span class="tag-custom flex items-center gap-1 group">
                                    <span class="tag-text cursor-pointer" onclick="editTag(this, '{html_escape.escape(tag)}')" title="Click to edit">{html_escape.escape(tag)}</span>
                                    <button onclick="showDeleteConfirm(this, '{html_escape.escape(tag)}')" class="opacity-0 group-hover:opacity-100 transition-opacity ml-1" style="color: var(--nasa-red);" title="Delete tag">×</button>
                                </span>
                                <div class="delete-confirm hidden absolute top-full left-0 mt-1 neo-brutalist-card p-2 z-10 whitespace-nowrap">
                                    <div class="text-xs mb-2" style="color: var(--nasa-dark);">Delete "{html_escape.escape(tag)}"?</div>
                                    <div class="flex gap-1">
                                        <button onclick="confirmDelete(this, '{html_escape.escape(tag)}')" class="btn-secondary" style="text-decoration: none; padding: 0.25rem 0.5rem; font-size: 0.75rem; background: var(--nasa-red); color: var(--nasa-white); border-color: var(--nasa-red);">Delete</button>
                                        <button onclick="cancelDelete(this)" class="btn-secondary" style="text-decoration: none; padding: 0.25rem 0.5rem; font-size: 0.75rem;">Cancel</button>
                                    </div>
                                </div>
                            </span>
                            ''' for tag in tags)}
                        </div>
                        <div id="add-tag-form" class="hidden">
                            <input type="text" id="new-tag-input" placeholder="Enter new tag..." class="px-2 py-1 text-xs mr-2" style="border: 1px solid var(--nasa-gray); border-radius: 2px; background: var(--nasa-white); color: var(--nasa-dark);">
                            <button onclick="saveNewTag()" class="btn-secondary" style="text-decoration: none; padding: 0.25rem 0.5rem; font-size: 0.75rem;">Save</button>
                            <button onclick="cancelAddTag()" class="bg-gray-500 text-white px-2 py-1 rounded text-xs hover:bg-gray-600 ml-1">Cancel</button>
                        </div>
                    </div>
                    
                    <!-- Collections -->
                    <div class="mb-4">
                        <h4 class="font-medium mb-2" style="color: var(--nasa-gray);">Collections:</h4>
                        <div id="workflow-collections" class="mb-2">
                            {''.join(f'''<span class="tag-collection" style="margin-right: 0.25rem; margin-bottom: 0.25rem; display: inline-flex; align-items: center; gap: 4px;">
                                {html_escape.escape(collection.name)}
                                <button onclick="removeFromCollection('{collection.id}', '{html_escape.escape(collection.name)}')" class="text-xs" style="color: var(--nasa-white); background: transparent; border: none; cursor: pointer;" title="Remove from collection">×</button>
                            </span>''' 
                                    for collection in workflow.collections) if workflow.collections else '<span class="text-xs" style="color: var(--nasa-gray);">No collections assigned</span>'}
                        </div>
                        <button onclick="addToCollections()" class="btn-secondary" style="text-decoration: none; padding: 0.25rem 0.75rem; font-size: 0.75rem;">
                            📚 Add to Collections
                        </button>
                    </div>
                    
                    <!-- Client and Project Fields -->
                    <div class="mb-4">
                        <h4 class="font-medium mb-2" style="color: var(--nasa-gray);">Project Information:</h4>
                        <div class="space-y-2">
                            <div>
                                <label class="block text-xs font-medium" style="color: var(--nasa-gray);">Client:</label>
                                <input type="text" id="client-name" placeholder="Enter client name..." 
                                       class="w-full px-2 py-1 text-xs focus:outline-none"
                                       style="border: 1px solid var(--nasa-gray); border-radius: 2px; background: var(--nasa-white); color: var(--nasa-dark);"
                                       value="{html_escape.escape('TODO: Load from database')}">
                            </div>
                            <div>
                                <label class="block text-xs font-medium" style="color: var(--nasa-gray);">Project:</label>
                                <input type="text" id="project-name" placeholder="Enter project name..." 
                                       class="w-full px-2 py-1 text-xs focus:outline-none"
                                       style="border: 1px solid var(--nasa-gray); border-radius: 2px; background: var(--nasa-white); color: var(--nasa-dark);"
                                       value="{html_escape.escape('TODO: Load from database')}">
                            </div>
                            <button onclick="saveProjectInfo()" class="btn-secondary" style="text-decoration: none; padding: 0.25rem 0.75rem; font-size: 0.75rem;">
                                Save Project Info
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
                button.addEventListener('click', function(event) {
                    let copyText;
                    let copyMode;
                    
                    if (event.shiftKey) {
                        // SHIFT + Click: Copy full CLI command
                        copyText = this.getAttribute('data-copy-text');
                        copyMode = 'command';
                    } else {
                        // Normal Click: Copy just the value
                        copyText = this.getAttribute('data-value') || this.getAttribute('data-copy-text');
                        copyMode = 'value';
                    }
                    
                    copyToClipboard(copyText, this, copyMode);
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
            
            // Shift key detection for copy buttons hover state
            document.addEventListener('keydown', function(event) {
                if (event.key === 'Shift') {
                    document.querySelectorAll('.copy-btn').forEach(button => {
                        button.classList.add('shift-hover');
                    });
                }
            });
            
            document.addEventListener('keyup', function(event) {
                if (event.key === 'Shift') {
                    document.querySelectorAll('.copy-btn').forEach(button => {
                        button.classList.remove('shift-hover');
                    });
                }
            });
        });

        function copyToClipboard(text, button, copyMode) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(() => {
                    showCopySuccess(button, copyMode);
                }).catch((err) => {
                    console.error('Clipboard API failed:', err);
                    fallbackCopy(text, button, copyMode);
                });
            } else {
                fallbackCopy(text, button, copyMode);
            }
        }
        
        function fallbackCopy(text, button, copyMode) {
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
                    showCopySuccess(button, copyMode);
                } else {
                    showCopyError(button);
                }
            } catch (err) {
                console.error('Fallback copy failed:', err);
                showCopyError(button);
            }
            
            document.body.removeChild(textArea);
        }
        
        function showCopySuccess(button, copyMode) {
            const originalText = button.innerHTML;
            const originalClass = button.className;
            
            button.innerHTML = '✓';
            button.className = button.className.replace('bg-gray-200', 'bg-green-500 text-white');
            
            // Show toast with different messages based on copy mode
            const toast = document.getElementById('copyToast');
            if (toast) {
                const messageSpan = toast.querySelector('span:last-child');
                if (copyMode === 'command') {
                    messageSpan.textContent = 'CLI command copied!';
                } else if (copyMode === 'value') {
                    messageSpan.textContent = 'Parameter value copied!';
                } else {
                    messageSpan.textContent = 'Copied to clipboard!';
                }
                
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

        // Remove workflow from database
        async function removeWorkflow() {
            const workflowName = document.querySelector('h1').textContent;
            
            if (!confirm(`Remove "${workflowName}" from the database?\\n\\nThis will delete the catalog entry but preserve all original files.`)) {
                return;
            }
            
            try {
                const response = await fetch(`/api/workflows/${workflowId}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    const result = await response.json();
                    alert(result.message + '\\n\\n' + result.note);
                    // Redirect to catalog
                    window.location.href = '/catalog';
                } else {
                    const error = await response.json();
                    alert('Failed to remove workflow: ' + (error.detail || 'Unknown error'));
                }
            } catch (error) {
                console.error('Error removing workflow:', error);
                alert('Failed to remove workflow: Network error');
            }
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

        function openFileLocation(filePath) {
            if (!filePath) {
                const toast = document.createElement('div');
                toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-orange);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                toast.textContent = 'No file path available';
                document.body.appendChild(toast);
                setTimeout(() => document.body.removeChild(toast), 2000);
                return;
            }

            // Try different methods based on platform/browser
            if (navigator.platform.indexOf('Mac') !== -1) {
                // macOS - try to open in Finder
                fetch('/api/open-file-location', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ file_path: filePath })
                }).then(response => {
                    if (response.ok) {
                        const toast = document.createElement('div');
                        toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-blue);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                        toast.textContent = 'Opening file location...';
                        document.body.appendChild(toast);
                        setTimeout(() => document.body.removeChild(toast), 2000);
                    } else {
                        throw new Error('Failed to open file location');
                    }
                }).catch(error => {
                    // Fallback: copy path to clipboard
                    copyToClipboard(filePath);
                    const toast = document.createElement('div');
                    toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-orange);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                    toast.textContent = 'Could not open location, path copied instead';
                    document.body.appendChild(toast);
                    setTimeout(() => document.body.removeChild(toast), 3000);
                });
            } else {
                // For other platforms, just copy to clipboard for now
                copyToClipboard(filePath);
                const toast = document.createElement('div');
                toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-blue);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                toast.textContent = 'File path copied to clipboard';
                document.body.appendChild(toast);
                setTimeout(() => document.body.removeChild(toast), 2000);
            }
        }

        function addToCollections() {
            const workflowId = '{{WORKFLOW_ID_PLACEHOLDER}}';
            // Open collection picker for this single workflow
            openCollectionPicker([workflowId]);
        }

        async function removeFromCollection(collectionId, collectionName) {
            if (!confirm(`Remove this workflow from collection "${collectionName}"?`)) {
                return;
            }
            
            const workflowId = '{{WORKFLOW_ID_PLACEHOLDER}}';
            
            try {
                // Get current collections for this workflow
                const response = await fetch(`/api/workflows/${workflowId}`);
                if (!response.ok) throw new Error('Failed to fetch workflow');
                
                const workflow = await response.json();
                const currentCollectionIds = workflow.collections?.map(c => c.id) || [];
                
                // Remove the specified collection
                const updatedCollectionIds = currentCollectionIds.filter(id => id !== collectionId);
                
                // Update workflow collections
                const updateResponse = await fetch(`/api/workflows/${workflowId}/collections`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ collection_ids: updatedCollectionIds })
                });
                
                if (!updateResponse.ok) throw new Error('Failed to update collections');
                
                // Reload page to show updated collections
                location.reload();
                
            } catch (error) {
                console.error('Error removing from collection:', error);
                alert('Failed to remove from collection');
            }
        }

        // Collection Picker Functions (same as catalog page)
        let collectionPickerWorkflows = [];

        function openCollectionPicker(workflowIds) {
            collectionPickerWorkflows = workflowIds;
            
            // Create modal if it doesn't exist
            if (!document.getElementById('collection-picker-modal')) {
                const modal = document.createElement('div');
                modal.id = 'collection-picker-modal';
                modal.className = 'fixed inset-0 z-50 hidden';
                modal.innerHTML = `
                    <div class="fixed inset-0 bg-black bg-opacity-50" onclick="closeCollectionPicker()"></div>
                    <div class="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-full max-w-lg">
                        <div class="confirmation-dialog p-6 m-4">
                            <div class="flex justify-between items-center mb-4">
                                <h2 class="text-xl font-bold" style="color: var(--nasa-dark);">📚 ADD TO COLLECTIONS</h2>
                                <button onclick="closeCollectionPicker()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
                            </div>
                            
                            <div class="mb-4 p-3 border border-gray-200 rounded" style="border-color: var(--nasa-gray);">
                                <div class="flex space-x-2">
                                    <input type="text" id="quick-collection-name" class="search-input flex-1" placeholder="Create new collection...">
                                    <button onclick="createQuickCollection()" class="btn-primary" style="padding: 0.5rem;">➕</button>
                                </div>
                            </div>
                            
                            <div class="mb-4">
                                <div id="collection-picker-list" class="space-y-2 max-h-60 overflow-y-auto">
                                    <!-- Collections will be loaded here -->
                                </div>
                            </div>
                            
                            <div class="flex justify-end space-x-2">
                                <button onclick="closeCollectionPicker()" class="btn-secondary">Cancel</button>
                                <button onclick="saveCollectionAssignments()" class="btn-primary">Save</button>
                            </div>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            
            document.getElementById('collection-picker-modal').classList.remove('hidden');
            loadCollectionPickerList();
        }

        function closeCollectionPicker() {
            const modal = document.getElementById('collection-picker-modal');
            if (modal) {
                modal.classList.add('hidden');
                const quickName = document.getElementById('quick-collection-name');
                if (quickName) quickName.value = '';
            }
            collectionPickerWorkflows = [];
        }

        async function loadCollectionPickerList() {
            try {
                const response = await fetch('/api/collections');
                if (!response.ok) return;
                
                const data = await response.json();
                const collections = data.collections || [];
                
                const container = document.getElementById('collection-picker-list');
                if (!container) return;
                
                container.innerHTML = '';
                
                if (collections.length === 0) {
                    container.innerHTML = '<p class="filter-label text-center py-4">No collections yet. Create one above.</p>';
                    return;
                }
                
                collections.forEach(collection => {
                    const item = document.createElement('div');
                    item.className = 'collection-picker-item';
                    item.setAttribute('data-collection-id', collection.id);
                    
                    item.innerHTML = `
                        <div class="collection-color-dot" style="background-color: ${collection.color || '#105bd8'}"></div>
                        <div class="flex-1">
                            <div class="filter-label">${collection.name}</div>
                            ${collection.description ? `<div class="text-xs" style="color: var(--nasa-gray);">${collection.description}</div>` : ''}
                        </div>
                        <div class="text-xs" style="color: var(--nasa-gray);">${collection.file_count || 0} workflows</div>
                    `;
                    
                    item.addEventListener('click', function() {
                        item.classList.toggle('selected');
                    });
                    
                    container.appendChild(item);
                });
                
            } catch (error) {
                console.error('Error loading collections:', error);
            }
        }

        async function createQuickCollection() {
            const nameInput = document.getElementById('quick-collection-name');
            if (!nameInput) return;
            
            const name = nameInput.value.trim();
            if (!name) return;
            
            try {
                const response = await fetch('/api/collections', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        name: name,
                        description: '',
                        color: '#105bd8'
                    })
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    alert(error.detail || 'Failed to create collection');
                    return;
                }
                
                nameInput.value = '';
                await loadCollectionPickerList();
                
            } catch (error) {
                console.error('Error creating collection:', error);
                alert('Failed to create collection');
            }
        }

        async function saveCollectionAssignments() {
            const selectedCollectionIds = Array.from(
                document.querySelectorAll('.collection-picker-item.selected')
            ).map(item => item.getAttribute('data-collection-id'));
            
            if (collectionPickerWorkflows.length === 0) {
                closeCollectionPicker();
                return;
            }
            
            try {
                for (const workflowId of collectionPickerWorkflows) {
                    const response = await fetch(`/api/workflows/${workflowId}/collections`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ collection_ids: selectedCollectionIds })
                    });
                    
                    if (!response.ok) {
                        console.error(`Failed to update workflow ${workflowId}`);
                    }
                }
                
                closeCollectionPicker();
                
                // Reload page to show updated collections
                location.reload();
                
            } catch (error) {
                console.error('Error saving collection assignments:', error);
                alert('Failed to update collections');
            }
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
        return '<div class="neo-brutalist-card p-6"><p style="color: var(--nasa-gray);">No workflow data available.</p></div>'
    
    # Sort nodes by ID for consistent display
    sorted_nodes = sorted(workflow_json.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
    
    html = '''
        <!-- Node Analysis -->
        <div class="neo-brutalist-card p-6 mb-8">
            <h2 class="text-xl font-semibold mb-6" style="color: var(--nasa-dark);">Node Analysis</h2>
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
            <div class="node-card p-4">
                <div class="flex items-center gap-2 mb-3">
                    <div>
                        <h3 class="font-bold text-lg" style="color: var(--nasa-dark);">Node {node_id}</h3>
                        <p class="text-sm" style="color: var(--nasa-gray);">{html_escape.escape(class_type)}</p>
                    </div>
                </div>
                
                <h4 class="font-medium mb-2" style="color: var(--nasa-dark);">{html_escape.escape(title)}</h4>
                
                <div class="text-xs mb-3" style="color: var(--nasa-gray);">
                    {len(connections)} inputs • {len(params)} params
                </div>
        '''
        
        # Show key parameters
        if key_params:
            html += '<div class="neo-brutalist-card p-2 text-xs mb-3" style="border: 1px solid var(--nasa-gray);"><div class="font-medium mb-1" style="color: var(--nasa-dark);">Key Parameters:</div>'
            for param_name, param_value in key_params[:3]:  # Show first 3
                value_str = str(param_value)
                if len(value_str) > 20:
                    value_str = value_str[:17] + "..."
                html += f'<div style="color: var(--nasa-dark);">{html_escape.escape(param_name)}: {html_escape.escape(value_str)}</div>'
            html += '</div>'
        
        # Expandable all parameters section
        html += '''
                <details class="mt-3">
                    <summary class="text-xs cursor-pointer" style="color: var(--nasa-gray);">All parameters & CLI commands</summary>
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
                                    <button class="copy-btn ml-1" 
                                            data-copy-text="{escaped_copy_command}"
                                            data-value="{escaped_value}"
                                            id="{copy_id}"
                                            title="Copy value (SHIFT+Click for CLI command)"
                                            aria-label="Copy parameter value or command">
                                        CPY
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
                <h3 class="text-xl font-semibold mb-4" style="color: var(--nasa-dark);">Command Line Reference</h3>
                
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
    title="Comfy Light Table",
    description="Quality of Life Improvements with workflow catalog indexing",
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

@app.post("/scan-directory")
async def scan_directory(request: Request):
    """Scan a directory for workflow files and add them to the catalog."""
    logger.info("🔍 Scan directory endpoint called")
    try:
        # Log raw request details
        logger.info(f"Content-Type: {request.headers.get('content-type')}")
        logger.info(f"Request method: {request.method}")
        
        # Try to get the JSON data
        try:
            data = await request.json()
            logger.info(f"✅ Successfully parsed JSON: {data}")
        except Exception as json_error:
            logger.error(f"❌ JSON parsing error: {json_error}")
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(json_error)}")
            
        logger.info(f"Scan directory request data: {data}")
        directory_path = data.get('directory') or data.get('directory_path')  # Support both field names
        recursive = data.get('recursive', True)
        
        if not directory_path:
            raise HTTPException(status_code=400, detail="directory is required")
        
        directory = Path(directory_path)
        
        # Validate directory exists and is accessible
        if not directory.exists():
            raise HTTPException(status_code=404, detail=f"Directory not found: {directory}")
        
        if not directory.is_dir():
            raise HTTPException(status_code=400, detail=f"Path is not a directory: {directory}")
        
        # Generate unique task ID for tracking
        task_id = str(uuid.uuid4())
        
        # Initialize task tracking
        task_info = {
            "id": task_id,
            "type": "directory_scan",
            "directory": str(directory),
            "status": "scanning",
            "files_found": 0,
            "files_processed": 0,
            "errors": []
        }
        
        processing_tasks[task_id] = task_info
        
        # Broadcast scan started
        await manager.broadcast({
            "type": "scan_started",
            "task_id": task_id,
            "directory": str(directory)
        })
        
        # Start directory scanning asynchronously
        asyncio.create_task(scan_directory_async(task_id, directory, recursive))
        
        return JSONResponse(content={
            "task_id": task_id,
            "directory": str(directory),
            "status": "scanning"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting directory scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-file-path")
async def process_file_path(request: Request):
    """Process a workflow file from a local file path."""
    try:
        data = await request.json()
        file_path_str = data.get('file_path')
        
        if not file_path_str:
            raise HTTPException(status_code=400, detail="file_path is required")
        
        file_path = Path(file_path_str)
        
        # Validate file exists and is accessible
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {file_path}")
        
        # Check if it's a supported file type
        if file_path.suffix.lower() not in {'.png', '.webp', '.jpg', '.jpeg', '.json'}:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use PNG, WEBP, JPG, JPEG, or JSON files.")
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Initialize task tracking
        task_info = {
            "id": task_id,
            "filename": file_path.name,
            "status": "processing", 
            "file_path": str(file_path),
            "workflow": None,
            "analysis": None,
            "error": None
        }
        
        processing_tasks[task_id] = task_info
        
        # Broadcast task started
        await manager.broadcast({
            "type": "task_started",
            "task_id": task_id,
            "filename": file_path.name
        })
        
        # Process file asynchronously
        asyncio.create_task(process_file_path_async(task_id, file_path))
        
        return JSONResponse(content={
            "task_id": task_id,
            "filename": file_path.name,
            "status": "queued"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file path request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        task_info["status"] = "storing"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "storing",
            "message": "Storing workflow in database..."
        })
        
        # Store in database if available
        workflow_id = None
        if DATABASE_AVAILABLE:
            try:
                db_manager = get_database_manager()
                workflow_manager = WorkflowFileManager(db_manager)
                
                # For web uploads, we'll store the workflow data without requiring a permanent file
                workflow_name = file_path.stem
                
                # Get image metadata if it's an image file
                image_metadata = None
                if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
                    try:
                        from PIL import Image
                        with Image.open(file_path) as img:
                            image_metadata = {
                                "width": img.width,
                                "height": img.height,
                                "format": img.format
                            }
                    except Exception:
                        image_metadata = {"width": None, "height": None, "format": file_path.suffix[1:].upper()}
                
                # Store workflow data like ComfyUI does - just extract and save the workflow
                workflow_manager = WorkflowFileManager(db_manager)
                
                # Generate a descriptive name for the workflow entry
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                workflow_display_name = f"{workflow_name}_{timestamp}"
                
                # Store using the workflow manager (which expects a file path but we'll use a virtual one)
                import tempfile
                import os
                
                # Create a temporary file to satisfy the workflow manager's file path requirement
                with tempfile.NamedTemporaryFile(suffix=file_path.suffix, delete=False) as temp_file:
                    if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
                        # Copy the image content to temp file
                        with open(file_path, 'rb') as source:
                            temp_file.write(source.read())
                    else:
                        # Write the JSON workflow
                        temp_file.write(json.dumps(workflow, indent=2).encode())
                    
                    temp_path = Path(temp_file.name)
                
                try:
                    # Store in database using the workflow manager
                    workflow_file = workflow_manager.add_workflow_file(
                        file_path=temp_path,
                        workflow_data=workflow,
                        image_metadata=image_metadata,
                        tags=[],  # Auto-tagging will happen
                        collections=["web-imported"],  # Mark as web imported
                        notes=f"Imported via web interface on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        auto_analyze=True
                    )
                    
                    # Update the file path to be more descriptive
                    with db_manager.get_session() as session:
                        db_workflow = session.query(WorkflowFile).filter_by(id=workflow_file.id).first()
                        if db_workflow:
                            db_workflow.file_path = f"Imported/{workflow_display_name}{file_path.suffix}"
                            db_workflow.filename = f"{workflow_display_name}{file_path.suffix}"
                            session.commit()
                    
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                    
                    # Add image metadata if available
                    if image_metadata:
                        workflow_file.image_width = image_metadata.get('width')
                        workflow_file.image_height = image_metadata.get('height')
                        workflow_file.image_format = image_metadata.get('format')
                    
                    session.add(workflow_file)
                    session.commit()
                    
                    workflow_id = workflow_file.id
                    task_info["workflow_id"] = workflow_id
                
                logger.info(f"✅ Stored uploaded workflow '{workflow_name}' in database with ID {workflow_id}")
                logger.info(f"� Workflow processed from web upload (no permanent file created)")
                
            except Exception as db_error:
                logger.error(f"Error storing in database: {db_error}")
                # Continue with HTML generation as fallback
        
        # Update status
        task_info["status"] = "generating"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "generating",
            "message": "Generating visualization..."
        })
        
        # Generate HTML visualization (as backup/legacy support)
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
        completion_data = {
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
        }
        
        # Include workflow ID if stored in database
        if task_info.get("workflow_id"):
            completion_data["workflow_id"] = task_info["workflow_id"]
            completion_data["redirect_url"] = f"/catalog"  # Redirect to catalog to see the new workflow
        
        await manager.broadcast(completion_data)
        
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

async def process_file_path_async(task_id: str, file_path: Path):
    """Process a workflow file from a local file path without uploading."""
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
        task_info["status"] = "storing"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "storing",
            "message": "Storing workflow in database..."
        })
        
        # Store in database if available
        workflow_id = None
        if DATABASE_AVAILABLE:
            try:
                db_manager = get_database_manager()
                workflow_manager = WorkflowFileManager(db_manager)
                
                # Process the file in place - no copying or moving
                workflow_name = file_path.stem
                
                # Get image metadata if it's an image file
                image_metadata = None
                if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
                    try:
                        from PIL import Image
                        with Image.open(file_path) as img:
                            image_metadata = {
                                "width": img.width,
                                "height": img.height,
                                "format": img.format
                            }
                    except Exception:
                        image_metadata = {"width": None, "height": None, "format": file_path.suffix[1:].upper()}
                
                # Store in database using the original file path
                workflow_file = workflow_manager.add_workflow_file(
                    file_path=file_path,  # Use the original file path
                    workflow_data=workflow,
                    image_metadata=image_metadata,
                    auto_analyze=True
                )
                
                workflow_id = workflow_file.id
                task_info["workflow_id"] = workflow_id
                
                logger.info(f"✅ Stored workflow '{workflow_name}' in database with ID {workflow_id}")
                logger.info(f"📁 Using original file path: {file_path}")
                
            except Exception as db_error:
                logger.error(f"Error storing in database: {db_error}")
                # Continue with HTML generation as fallback
        
        # Update status
        task_info["status"] = "generating"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "generating",
            "message": "Generating visualization..."
        })
        
        # Generate HTML visualization (as backup/legacy support)
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
        completion_data = {
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
        }
        
        # Include workflow ID if stored in database
        if task_info.get("workflow_id"):
            completion_data["workflow_id"] = task_info["workflow_id"]
            completion_data["redirect_url"] = f"/catalog"
        
        await manager.broadcast(completion_data)
        
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

async def scan_directory_async(task_id: str, directory: Path, recursive: bool = True):
    """Scan a directory for workflow files and add them to the catalog."""
    task_info = processing_tasks[task_id]
    
    try:
        if not DATABASE_AVAILABLE:
            raise ValueError("Database not available for directory scanning")
            
        db_manager = get_database_manager()
        workflow_manager = WorkflowFileManager(db_manager)
        
        # Update status
        task_info["status"] = "scanning"
        await manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": "scanning",
            "message": f"Scanning directory: {directory}"
        })
        
        # Find workflow files
        file_patterns = ['*.png', '*.webp', '*.jpg', '*.jpeg', '*.json']
        workflow_files = []
        
        for pattern in file_patterns:
            if recursive:
                workflow_files.extend(directory.rglob(pattern))
            else:
                workflow_files.extend(directory.glob(pattern))
        
        task_info["files_found"] = len(workflow_files)
        logger.info(f"Found {len(workflow_files)} potential workflow files in {directory}")
        
        # Process each file
        processed = 0
        for file_path in workflow_files:
            try:
                # Update progress
                await manager.broadcast({
                    "type": "task_update", 
                    "task_id": task_id,
                    "status": "processing",
                    "message": f"Processing {file_path.name} ({processed + 1}/{len(workflow_files)})"
                })
                
                # Extract workflow based on file type
                workflow = None
                if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
                    # Try to extract workflow from image
                    try:
                        workflow = extract_workflow_from_image(file_path)
                    except:
                        continue  # Skip images without workflows
                elif file_path.suffix.lower() == '.json':
                    # Load JSON workflow
                    try:
                        with open(file_path, 'r') as f:
                            raw_workflow = json.load(f)
                        workflow = ui_to_api_format(raw_workflow)
                    except:
                        continue  # Skip invalid JSON files
                
                if workflow:
                    # Get image metadata if it's an image file
                    image_metadata = None
                    if file_path.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}:
                        try:
                            from PIL import Image
                            with Image.open(file_path) as img:
                                image_metadata = {
                                    "width": img.width,
                                    "height": img.height,
                                    "format": img.format
                                }
                        except Exception:
                            image_metadata = None
                    
                    # Add to database using the actual file path
                    workflow_file = workflow_manager.add_workflow_file(
                        file_path=file_path,
                        workflow_data=workflow,
                        image_metadata=image_metadata,
                        collections=["directory-scan"],
                        auto_analyze=True
                    )
                    
                    processed += 1
                    task_info["files_processed"] = processed
                    logger.info(f"✅ Added {file_path.name} to catalog (ID: {workflow_file.id})")
                
            except Exception as e:
                error_msg = f"Error processing {file_path.name}: {str(e)}"
                task_info["errors"].append(error_msg)
                logger.error(error_msg)
        
        # Completion
        task_info["status"] = "completed"
        completion_data = {
            "type": "scan_completed",
            "task_id": task_id,
            "directory": str(directory),
            "files_found": task_info["files_found"],
            "files_processed": task_info["files_processed"],
            "errors": len(task_info["errors"])
        }
        
        await manager.broadcast(completion_data)
        logger.info(f"✅ Directory scan completed: {processed}/{len(workflow_files)} files added to catalog")
        
    except Exception as e:
        logger.error(f"Error scanning directory {directory}: {e}")
        task_info["status"] = "error"
        task_info["error"] = str(e)
        
        await manager.broadcast({
            "type": "scan_error",
            "task_id": task_id,
            "directory": str(directory),
            "error": str(e)
        })

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
    sort_field: str = "ingest_date",
    sort_direction: str = "desc",
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
            # Query WorkflowFile objects to access relationships
            query = session.query(WorkflowFile)
            
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
            
            # Apply collection filter
            if collection:
                # Join with collections to filter by collection name
                query = query.join(WorkflowFile.collections).filter(Collection.name == collection)
            
            # Apply sorting
            sort_column = None
            if sort_field == "ingest_date":
                sort_column = WorkflowFile.created_at
            elif sort_field == "file_date":
                sort_column = WorkflowFile.file_modified_at
            elif sort_field == "name":
                sort_column = WorkflowFile.filename
            elif sort_field == "file_size":
                sort_column = WorkflowFile.file_size
            else:
                sort_column = WorkflowFile.created_at  # Default fallback
            
            if sort_direction == "asc":
                query = query.order_by(sort_column.asc())
            else:
                query = query.order_by(sort_column.desc())
            
            # Get total count for pagination
            total = query.count()
            logger.info(f"Found {total} workflows in database")
            
            # Apply pagination
            workflows = query.offset(offset).limit(limit).all()
            logger.info(f"Retrieved {len(workflows)} workflows after pagination")
            
            # Convert to JSON-serializable format
            results = []
            for workflow in workflows:
                # Check if workflow has image data (PNG/JPEG files typically have image metadata)
                has_image = (workflow.image_width is not None and workflow.image_height is not None) or (
                    workflow.filename and workflow.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
                )
                
                # Extract checkpoints and LoRAs from workflow data
                checkpoints = []
                loras = []
                try:
                    if workflow.workflow_data:
                        import json
                        if isinstance(workflow.workflow_data, str):
                            workflow_json = json.loads(workflow.workflow_data)
                        else:
                            workflow_json = workflow.workflow_data
                        
                        logger.info(f"Processing workflow {workflow.id} with {len(workflow_json)} nodes")
                        
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
                    logger.error(f"Could not extract checkpoints/loras from workflow {workflow.id}: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Build tags from proper relationship + legacy JSON field
                tags = []
                
                # Get tags from proper Tag relationship (preferred)
                if workflow.tags:
                    tags.extend([tag.name for tag in workflow.tags])
                
                # Also check legacy style_tags JSON field for backwards compatibility
                if workflow.style_tags and not tags:  # Only use if no proper tags exist
                    try:
                        if isinstance(workflow.style_tags, str):
                            import json
                            style_tags = json.loads(workflow.style_tags)
                        else:
                            style_tags = workflow.style_tags
                        tags.extend(style_tags)
                    except Exception:
                        pass
                
                # Add checkpoint and lora tags (but only if not already present)
                for checkpoint in checkpoints:
                    checkpoint_tag = f"checkpoint:{checkpoint}"
                    if checkpoint_tag not in tags:
                        tags.append(checkpoint_tag)
                for lora in loras:
                    lora_tag = f"lora:{lora}"
                    if lora_tag not in tags:
                        tags.append(lora_tag)
                
                workflow_data = {
                    "id": workflow.id,
                    "name": workflow.filename,  # Use filename as name
                    "filename": workflow.filename,
                    "description": workflow.notes or "",  # Use notes as description
                    "created_at": workflow.file_modified_at.isoformat() if workflow.file_modified_at else (workflow.created_at.isoformat() if workflow.created_at else None),
                    "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
                    "file_size": workflow.file_size,
                    "checksum": workflow.file_hash,  # Use file_hash as checksum
                    "has_image": has_image,
                    "node_count": workflow.node_count,
                    "node_types": workflow.node_types if workflow.node_types else [],
                    "checkpoints": checkpoints,
                    "loras": loras,
                    "tags": tags,
                    "collections": [collection.name for collection in workflow.collections],
                    "clients": [],  # Temporarily disabled until schema sync fixed
                    "projects": [],  # Temporarily disabled until schema sync fixed
                    "file_path": workflow.file_path,  # Add the missing file path field
                    "thumbnail_path": f"/api/workflows/{workflow.id}/thumbnail" if has_image else None
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
                "created_at": workflow.file_modified_at.isoformat() if workflow.file_modified_at else (workflow.created_at.isoformat() if workflow.created_at else None),
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
            
            # Use proper Tag relationship (database prevents duplicates automatically)
            from database.models import Tag
            
            # Find or create the tag
            tag = session.query(Tag).filter_by(name=tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                session.add(tag)
                session.flush()
            
            # Add tag to workflow if not already present (SQLAlchemy handles deduplication)
            if tag not in workflow.tags:
                workflow.tags.append(tag)
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
            
            # Use proper Tag relationship
            from database.models import Tag
            
            # Find the tag
            tag = session.query(Tag).filter_by(name=tag_name).first()
            if tag and tag in workflow.tags:
                # Remove tag from workflow
                workflow.tags.remove(tag)
                workflow.updated_at = datetime.utcnow()
                session.commit()
            
            return {"success": True, "message": "Tag deleted successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting tag from workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow from the database (files remain untouched)."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            filename = workflow.filename
            logger.info(f"Removing workflow '{filename}' from database (files preserved)")
            
            # Delete the workflow record (cascading will handle relationships)
            session.delete(workflow)
            session.commit()
            
            return {
                "success": True, 
                "message": f"Workflow '{filename}' removed from database",
                "note": "Original files remain untouched"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workflow {workflow_id}: {e}")
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
            
            # Use proper Tag relationship
            from database.models import Tag
            
            # Find the old tag
            old_tag_obj = session.query(Tag).filter_by(name=old_tag).first()
            if old_tag_obj and old_tag_obj in workflow.tags:
                # Remove old tag
                workflow.tags.remove(old_tag_obj)
                
                # Find or create new tag
                new_tag_obj = session.query(Tag).filter_by(name=new_tag).first()
                if not new_tag_obj:
                    new_tag_obj = Tag(name=new_tag)
                    session.add(new_tag_obj)
                    session.flush()
                
                # Add new tag if not already present
                if new_tag_obj not in workflow.tags:
                    workflow.tags.append(new_tag_obj)
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
            workflows = session.query(WorkflowFile).all()
            
            for workflow in workflows:
                if workflow.style_tags:
                    try:
                        if isinstance(workflow.style_tags, str):
                            current_tags = json.loads(workflow.style_tags)
                        else:
                            current_tags = workflow.style_tags
                        
                        # Remove duplicates while preserving order
                        original_count = len(current_tags)
                        deduplicated_tags = list(dict.fromkeys(current_tags))
                        
                        if len(deduplicated_tags) != original_count:
                            workflow.style_tags = json.dumps(deduplicated_tags)
                            workflow.updated_at = datetime.utcnow()
                            updated_count += 1
                            logger.info(f"Deduped tags for {workflow.filename}: {original_count} -> {len(deduplicated_tags)}")
                    
                    except Exception as e:
                        logger.error(f"Error processing tags for {workflow.filename}: {e}")
            
            session.commit()
        
        return {
            "success": True, 
            "message": f"Deduplicated tags for {updated_count} workflows"
        }
        
    except Exception as e:
        logger.error(f"Error deduplicating tags: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/clean-auto-tags")
async def clean_auto_generated_tags():
    """Admin endpoint to remove common auto-generated tags that create clutter."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Common auto-generated tags that might be causing clutter
    auto_tag_patterns = [
        'simple', 'moderate', 'complex',  # Complexity tags
        'lora', 'controlnet', 'upscaling', 'checkpoint',  # Generic node type tags
        'text-to-image', 'image-to-image'  # Generic workflow type tags
    ]
    
    try:
        db_manager = get_database_manager()
        updated_count = 0
        removed_tags_count = 0
        
        with db_manager.get_session() as session:
            workflows = session.query(WorkflowFile).all()
            
            for workflow in workflows:
                if workflow.style_tags:
                    try:
                        if isinstance(workflow.style_tags, str):
                            current_tags = json.loads(workflow.style_tags)
                        else:
                            current_tags = workflow.style_tags
                        
                        # Remove auto-generated tags
                        original_count = len(current_tags)
                        cleaned_tags = [tag for tag in current_tags if tag not in auto_tag_patterns]
                        
                        if len(cleaned_tags) != original_count:
                            workflow.style_tags = json.dumps(cleaned_tags)
                            workflow.updated_at = datetime.utcnow()
                            updated_count += 1
                            removed_tags_count += (original_count - len(cleaned_tags))
                            logger.info(f"Cleaned auto-tags for {workflow.filename}: {original_count} -> {len(cleaned_tags)}")
                    
                    except Exception as e:
                        logger.error(f"Error cleaning tags for {workflow.filename}: {e}")
            
            session.commit()
        
        return {
            "success": True, 
            "message": f"Cleaned auto-generated tags from {updated_count} workflows, removed {removed_tags_count} tags"
        }
        
    except Exception as e:
        logger.error(f"Error cleaning auto-generated tags: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/status")
async def admin_status():
    """Simple admin status check endpoint."""
    return {
        "status": "ok",
        "database_available": DATABASE_AVAILABLE,
        "endpoints": ["deduplicate-tags", "clean-auto-tags", "migrate-tags-to-relations", "bulk-remove-workflows"]
    }


@app.post("/api/admin/migrate-tags-to-relations")
async def migrate_tags_to_relations():
    """Admin endpoint to migrate JSON tags to proper Tag relationships."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        migrated_count = 0
        
        from database.models import Tag
        
        with db_manager.get_session() as session:
            workflows = session.query(WorkflowFile).all()
            
            for workflow in workflows:
                if workflow.style_tags and not workflow.tags:  # Only migrate if no proper tags exist
                    try:
                        if isinstance(workflow.style_tags, str):
                            tag_names = json.loads(workflow.style_tags)
                        else:
                            tag_names = workflow.style_tags
                        
                        if tag_names:
                            # Create/find tags and add to workflow
                            for tag_name in tag_names:
                                if tag_name.strip():  # Skip empty tags
                                    tag = session.query(Tag).filter_by(name=tag_name.strip()).first()
                                    if not tag:
                                        tag = Tag(name=tag_name.strip())
                                        session.add(tag)
                                        session.flush()
                                    
                                    if tag not in workflow.tags:
                                        workflow.tags.append(tag)
                            
                            migrated_count += 1
                            logger.info(f"Migrated {len(tag_names)} tags for {workflow.filename}")
                    
                    except Exception as e:
                        logger.error(f"Error migrating tags for {workflow.filename}: {e}")
            
            session.commit()
        
        return {
            "success": True, 
            "message": f"Migrated tags for {migrated_count} workflows to proper relationships"
        }
        
    except Exception as e:
        logger.error(f"Error migrating tags to relations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/bulk-remove-workflows")
async def admin_bulk_remove_workflows(request: dict):
    """Admin endpoint to bulk remove workflows from database (files preserved)."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        workflow_ids = request.get("workflow_ids", [])
        if not workflow_ids:
            raise HTTPException(status_code=400, detail="workflow_ids array is required")
        
        db_manager = get_database_manager()
        removed_count = 0
        failed_count = 0
        
        with db_manager.get_session() as session:
            for workflow_id in workflow_ids:
                try:
                    workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
                    if workflow:
                        filename = workflow.filename
                        session.delete(workflow)
                        removed_count += 1
                        logger.info(f"Admin removed workflow '{filename}' from database (files preserved)")
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error removing workflow {workflow_id}: {e}")
                    failed_count += 1
            
            session.commit()
        
        return {
            "success": True,
            "removed_count": removed_count,
            "failed_count": failed_count,
            "message": f"Bulk removal complete: {removed_count} removed, {failed_count} failed",
            "note": "Original files remain untouched"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk workflow removal: {e}")
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


@app.get("/fonts/{font_file}")
async def get_font(font_file: str):
    """Serve font files for offline embedding."""
    import os
    from fastapi.responses import FileResponse
    
    # Security: only allow specific font files
    allowed_fonts = [
        "3270NerdFontMono-Regular.woff2",
        "3270NerdFontMono-Condensed.woff2", 
        "3270NerdFontMono-SemiCondensed.woff2",
        "3270NerdFont-Regular.woff2",
        "3270NerdFont-Condensed.woff2",
        "3270NerdFont-SemiCondensed.woff2",
        "3270NerdFontPropo-Regular.woff2",
        "3270NerdFontPropo-Condensed.woff2",
        "3270NerdFontPropo-SemiCondensed.woff2"
    ]
    
    if font_file not in allowed_fonts:
        raise HTTPException(status_code=404, detail="Font not found")
    
    font_path = os.path.join("fonts", "3270", font_file)
    if not os.path.exists(font_path):
        raise HTTPException(status_code=404, detail="Font file not found")
    
    return FileResponse(
        font_path, 
        media_type="font/woff2",
        headers={
            "Cache-Control": "public, max-age=31536000",  # Cache for 1 year
            "Access-Control-Allow-Origin": "*"
        }
    )


@app.post("/api/open-file-location")
async def open_file_location(request: dict):
    """Open file location in system file manager."""
    import subprocess
    import platform
    import os
    from pathlib import Path
    
    file_path = request.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="No file path provided")
    
    # Security check: ensure file exists and is accessible
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        system = platform.system()
        
        if system == "Darwin":  # macOS
            # Open in Finder and select the file
            subprocess.run(["open", "-R", file_path], check=True)
        elif system == "Windows":
            # Open in Explorer and select the file  
            subprocess.run(["explorer", "/select,", file_path], check=True)
        elif system == "Linux":
            # Open directory in default file manager
            directory = os.path.dirname(file_path)
            subprocess.run(["xdg-open", directory], check=True)
        else:
            raise HTTPException(status_code=501, detail="Platform not supported")
            
        return {"success": True, "message": "File location opened"}
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to open file location: {e}")
        raise HTTPException(status_code=500, detail="Failed to open file location")
    except Exception as e:
        logger.error(f"Error opening file location: {e}")
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
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            collections = session.query(Collection).order_by(Collection.sort_order, Collection.name).all()
            
            result = []
            for collection in collections:
                file_count = len(collection.files) if collection.files else 0
                result.append({
                    "id": collection.id,
                    "name": collection.name,
                    "description": collection.description,
                    "color": collection.color,
                    "is_system": collection.is_system,
                    "sort_order": collection.sort_order,
                    "file_count": file_count,
                    "created_at": collection.created_at.isoformat() if collection.created_at else None
                })
            
            return {"collections": result}
        
    except Exception as e:
        logger.error(f"Error fetching collections: {e}")
        return {"collections": []}


@app.post("/api/collections")
async def create_collection(request: Request):
    """Create a new collection."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        description = data.get("description", "").strip()
        color = data.get("color", "#105bd8")  # Default NASA blue
        
        if not name:
            raise HTTPException(status_code=400, detail="Collection name is required")
        
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            # Check if collection name already exists
            existing = session.query(Collection).filter(Collection.name == name).first()
            if existing:
                raise HTTPException(status_code=400, detail="Collection name already exists")
            
            # Create new collection
            collection = Collection(
                name=name,
                description=description,
                color=color,
                is_system=False,
                sort_order=0
            )
            
            session.add(collection)
            session.commit()
            
            return {
                "success": True,
                "collection": {
                    "id": collection.id,
                    "name": collection.name,
                    "description": collection.description,
                    "color": collection.color,
                    "file_count": 0
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to create collection")


@app.put("/api/collections/{collection_id}")
async def update_collection(collection_id: str, request: Request):
    """Update an existing collection."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        data = await request.json()
        
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            collection = session.query(Collection).filter(Collection.id == collection_id).first()
            if not collection:
                raise HTTPException(status_code=404, detail="Collection not found")
            
            # Update fields if provided
            if "name" in data:
                name = data["name"].strip()
                if not name:
                    raise HTTPException(status_code=400, detail="Collection name cannot be empty")
                
                # Check if new name already exists (except for this collection)
                existing = session.query(Collection).filter(
                    Collection.name == name, 
                    Collection.id != collection_id
                ).first()
                if existing:
                    raise HTTPException(status_code=400, detail="Collection name already exists")
                
                collection.name = name
            
            if "description" in data:
                collection.description = data["description"].strip()
            
            if "color" in data:
                collection.color = data["color"]
            
            session.commit()
            
            file_count = len(collection.files) if collection.files else 0
            return {
                "success": True,
                "collection": {
                    "id": collection.id,
                    "name": collection.name,
                    "description": collection.description,
                    "color": collection.color,
                    "file_count": file_count
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to update collection")


@app.delete("/api/collections/{collection_id}")
async def delete_collection(collection_id: str):
    """Delete a collection."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            collection = session.query(Collection).filter(Collection.id == collection_id).first()
            if not collection:
                raise HTTPException(status_code=404, detail="Collection not found")
            
            if collection.is_system:
                raise HTTPException(status_code=400, detail="Cannot delete system collections")
            
            session.delete(collection)
            session.commit()
            
            return {"success": True, "message": "Collection deleted"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete collection")


@app.post("/api/workflows/{workflow_id}/collections")
async def assign_workflow_to_collection(workflow_id: str, request: Request):
    """Assign a workflow to collections."""
    if not DATABASE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        data = await request.json()
        collection_ids = data.get("collection_ids", [])
        
        db_manager = get_database_manager()
        with db_manager.get_session() as session:
            workflow = session.query(WorkflowFile).filter(WorkflowFile.id == workflow_id).first()
            if not workflow:
                raise HTTPException(status_code=404, detail="Workflow not found")
            
            # Clear existing collections
            workflow.collections.clear()
            
            # Add new collections
            if collection_ids:
                collections = session.query(Collection).filter(Collection.id.in_(collection_ids)).all()
                for collection in collections:
                    workflow.collections.append(collection)
            
            session.commit()
            
            return {
                "success": True,
                "collections": [collection.name for collection in workflow.collections]
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning workflow to collections: {e}")
        raise HTTPException(status_code=500, detail="Failed to assign collections")


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
                <a href="/" style="color: blue;">← Back to Directory Scanner</a>
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
        <title>COMFYUI LIGHT TABLE</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @font-face {
                font-family: '3270 Nerd Font Mono';
                src: url('/fonts/3270NerdFontMono-Regular.woff2') format('woff2');
                font-weight: 400;
                font-style: normal;
                font-display: swap;
            }
            
            :root {
                --nasa-blue: #105bd8;
                --nasa-gray: #aeb0b5;
                --nasa-white: #ffffff;
                --nasa-dark: #212121;
                --nasa-orange: #ff9d1e;
            }
            
            * {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
            }
            
            body {
                background: var(--nasa-white);
                color: var(--nasa-dark);
                font-weight: 400;
            }
            
            .neo-brutalist-card {
                background: var(--nasa-white);
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                display: flex;
                flex-direction: column;
                height: 100%;
            }
            
            .card-flex-container {
                display: flex;
                flex-direction: column;
                height: 100%;
            }
            
            .card-content {
                flex-grow: 1;
                display: flex;
                flex-direction: column;
            }
            
            .card-buttons {
                margin-top: auto;
            }
            
            .workflow-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
                gap: 2rem;
                padding: 0;
            }
            
            .btn-primary {
                background: var(--nasa-blue);
                color: var(--nasa-white);
                border: 1px solid var(--nasa-blue);
                font-weight: 400;
                padding: 0.5rem 1rem;
                border-radius: 2px;
                cursor: pointer;
                transition: transform 0.1s ease;
            }
            
            .btn-primary:hover {
                transform: translateY(1px);
            }
            
            .btn-secondary {
                background: transparent;
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                font-weight: 400;
                padding: 0.5rem 1rem;
                border-radius: 2px;
                cursor: pointer;
                transition: transform 0.1s ease;
            }
            
            .btn-secondary:hover {
                background: var(--nasa-gray);
                color: var(--nasa-white);
                transform: translateY(1px);
            }
            
            .btn-danger {
                background: transparent;
                color: var(--nasa-orange);
                border: 1px solid var(--nasa-orange);
                font-weight: 400;
                padding: 0.25rem 0.5rem;
                border-radius: 2px;
                cursor: pointer;
                transition: transform 0.1s ease;
            }
            
            .btn-danger:hover {
                background: var(--nasa-orange);
                color: var(--nasa-white);
                transform: translateY(1px);
            }
            
            .mission-header {
                background: var(--nasa-white);
                border-bottom: 1px solid var(--nasa-gray);
                color: var(--nasa-dark);
            }
            
            .mission-title {
                font-weight: 500;
                font-size: 2rem;
                color: var(--nasa-dark);
            }
            
            .status-badge {
                background: transparent;
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                font-weight: 400;
                padding: 0.5rem 1rem;
                border-radius: 2px;
            }
            
            .filter-section {
                background: var(--nasa-white);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
            }
            
            .input-field {
                background: var(--nasa-white);
                border: 1px solid var(--nasa-dark);
                color: var(--nasa-dark);
                font-weight: 500;
                padding: 0.5rem;
                border-radius: 2px;
            }
            
            .input-field:focus {
                outline: none;
                border-color: var(--nasa-blue);
            }
            
            .tag-checkpoint {
                background: transparent;
                color: var(--nasa-blue);
                border: 1px solid var(--nasa-blue);
                font-weight: 400;
                padding: 0.2rem 0.4rem;
                border-radius: 2px;
                font-size: 0.65rem;
            }
            
            .tag-lora {
                background: transparent;
                color: var(--nasa-orange);
                border: 1px solid var(--nasa-orange);
                font-weight: 400;
                padding: 0.2rem 0.4rem;
                border-radius: 2px;
                font-size: 0.65rem;
            }
            
            .tag-custom {
                background: transparent;
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                font-weight: 400;
                padding: 0.2rem 0.4rem;
                font-size: 0.65rem;
                border-radius: 2px;
            }
            
            .thumbnail {
                width: 100%;
                height: 220px;
                object-fit: cover;
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
            }
            
            .no-thumbnail {
                width: 100%;
                height: 220px;
                background: #f8f9fa;
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 3rem;
                color: var(--nasa-gray);
                font-weight: 400;
            }
            
            .loading-indicator {
                border: 2px solid var(--nasa-gray);
                border-top: 2px solid var(--nasa-blue);
                border-radius: 50%;
                width: 2rem;
                height: 2rem;
                animation: spin 1s linear infinite;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .mission-stats {
                font-weight: 400;
                color: var(--nasa-dark);
            }
            
            .confirmation-dialog {
                background: var(--nasa-white);
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            
            .file-path-container {
                margin-top: 4px;
                display: flex;
                align-items: flex-start;
                gap: 8px;
            }
            
            .file-path-buttons {
                display: flex;
                flex-direction: column;
                gap: 2px;
                width: 20%;
                flex-shrink: 0;
            }
            
            .file-path-text {
                width: 80%;
                flex-grow: 1;
            }
            
            .file-path {
                font-size: 10px;
                color: var(--nasa-gray);
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                word-break: break-all;
                line-height: 1.2;
            }
            
            .btn-path {
                background: transparent;
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                font-weight: 400;
                padding: 0.25rem 0.5rem;
                border-radius: 2px;
                cursor: pointer;
                font-size: 0.45rem;
                transition: all 0.1s;
            }
            
            .btn-path:hover {
                background: var(--nasa-gray);
                color: var(--nasa-white);
                transform: translateY(1px);
            }
            
            /* Filter and Sort Controls */
            .filter-label {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                font-size: 0.75rem;
                font-weight: 400;
                color: var(--nasa-dark);
                text-transform: uppercase;
                letter-spacing: 0.025em;
            }
            
            .filter-select {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                background: var(--nasa-white);
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                padding: 0.5rem;
                font-size: 0.75rem;
                font-weight: 400;
                text-transform: uppercase;
                letter-spacing: 0.025em;
                cursor: pointer;
                transition: all 0.1s ease;
                min-width: 120px;
            }
            
            .filter-select:hover {
                background: var(--nasa-gray);
                color: var(--nasa-white);
                transform: translateY(1px);
            }
            
            .filter-select:focus {
                outline: none;
                border-color: var(--nasa-blue);
                box-shadow: 0 0 0 2px var(--nasa-blue);
            }
            
            .filter-select option {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                background: var(--nasa-white);
                color: var(--nasa-dark);
                padding: 0.5rem;
            }
            
            .clear-filters {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                color: var(--nasa-gray);
                font-size: 0.75rem;
                text-decoration: underline;
                cursor: pointer;
                transition: color 0.1s ease;
                text-transform: uppercase;
                letter-spacing: 0.025em;
            }
            
            .clear-filters:hover {
                color: var(--nasa-dark);
            }
            
            .search-input {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                background: var(--nasa-white);
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                padding: 0.5rem;
                font-size: 0.75rem;
                font-weight: 400;
                width: 100%;
                transition: all 0.1s ease;
            }
            
            .search-input:hover {
                border-color: var(--nasa-blue);
            }
            
            .search-input:focus {
                outline: none;
                border-color: var(--nasa-blue);
                box-shadow: 0 0 0 2px var(--nasa-blue);
            }
            
            .search-input::placeholder {
                color: var(--nasa-gray);
                text-transform: uppercase;
                letter-spacing: 0.025em;
            }
            
            /* Custom Dropdown Component */
            .custom-dropdown {
                position: relative;
                display: inline-block;
                min-width: 120px;
            }
            
            .dropdown-button {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                background: var(--nasa-white);
                color: var(--nasa-dark);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                padding: 0.5rem;
                font-size: 0.75rem;
                font-weight: 400;
                text-transform: uppercase;
                letter-spacing: 0.025em;
                cursor: pointer;
                transition: all 0.1s ease;
                width: 100%;
                text-align: left;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .dropdown-button:hover {
                background: var(--nasa-gray);
                color: var(--nasa-white);
                transform: translateY(1px);
            }
            
            .dropdown-button:focus {
                outline: none;
                border-color: var(--nasa-blue);
                box-shadow: 0 0 0 2px var(--nasa-blue);
            }
            
            .dropdown-arrow {
                font-size: 0.6rem;
                transition: transform 0.1s ease;
            }
            
            .dropdown-button.open .dropdown-arrow {
                transform: rotate(180deg);
            }
            
            .dropdown-menu {
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                background: var(--nasa-white);
                border: 1px solid var(--nasa-dark);
                border-radius: 2px;
                border-top: none;
                z-index: 1000;
                max-height: 200px;
                overflow-y: auto;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                display: none;
            }
            
            .dropdown-menu.open {
                display: block;
            }
            
            .dropdown-option {
                font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace;
                padding: 0.5rem;
                font-size: 0.75rem;
                font-weight: 400;
                text-transform: uppercase;
                letter-spacing: 0.025em;
                cursor: pointer;
                color: var(--nasa-dark);
                transition: all 0.1s ease;
                border-bottom: 1px solid var(--nasa-gray);
            }
            
            .dropdown-option:last-child {
                border-bottom: none;
            }
            
            .dropdown-option:hover {
                background: var(--nasa-gray);
                color: var(--nasa-white);
            }
            
            .dropdown-option.selected {
                background: var(--nasa-blue);
                color: var(--nasa-white);
            }
            
            /* Bulk Selection */
            .workflow-card {
                position: relative;
                transition: all 0.1s ease;
            }
            
            .workflow-card.bulk-select-mode {
                cursor: pointer;
            }
            
            .workflow-card.selected {
                border-color: var(--nasa-blue);
                box-shadow: 0 0 0 2px var(--nasa-blue);
            }
            
            .workflow-checkbox {
                position: absolute;
                top: 8px;
                left: 8px;
                z-index: 10;
                opacity: 0;
                transition: opacity 0.1s ease;
            }
            
            .bulk-select-mode .workflow-checkbox {
                opacity: 1;
            }
            
            .workflow-checkbox input[type="checkbox"] {
                width: 20px;
                height: 20px;
                border: 2px solid var(--nasa-dark);
                border-radius: 2px;
                background: var(--nasa-white);
                cursor: pointer;
            }
            
            .workflow-checkbox input[type="checkbox"]:checked {
                background: var(--nasa-blue);
                border-color: var(--nasa-blue);
            }
            
            /* Collection tags in picker */
            .collection-picker-item {
                display: flex;
                align-items: center;
                padding: 0.5rem;
                border: 1px solid var(--nasa-gray);
                border-radius: 2px;
                cursor: pointer;
                transition: all 0.1s ease;
            }
            
            .collection-picker-item:hover {
                background: var(--nasa-gray);
                color: var(--nasa-white);
            }
            
            .collection-picker-item.selected {
                background: var(--nasa-blue);
                color: var(--nasa-white);
                border-color: var(--nasa-blue);
            }
            
            .collection-color-dot {
                width: 12px;
                height: 12px;
                border-radius: 50%;
                margin-right: 0.5rem;
                border: 1px solid var(--nasa-dark);
            }
        </style>
    </head>
    <body>
        <!-- Header -->
        <header class="mission-header">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center py-4">
                    <div class="flex items-center space-x-4">
                        <h1 class="text-3xl font-bold text-gray-900">� ComfyUI Workflow Light Table</h1>
                        <span id="workflow-count" class="status-badge">
                            LOADING...
                        </span>
                    </div>
                    <div class="flex items-center space-x-4">
                        <a href="/" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors">
                            Scan Directory
                        </a>
                    </div>
                </div>
                
                <!-- Search and Filters -->
                <div class="pb-4 border-t pt-4">
                    <div class="flex flex-wrap gap-4 items-center">
                        <!-- Search -->
                        <div class="flex-1 min-w-64">
                            <input type="text" id="search-input" placeholder="Search workflows..." 
                                   class="search-input">
                        </div>
                        
                        <!-- Checkpoint Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="filter-label">Checkpoint:</label>
                            <select id="checkpoint-filter" class="filter-select">
                                <option value="">All Checkpoints</option>
                            </select>
                        </div>
                        
                        <!-- LoRA Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="filter-label">LoRA:</label>
                            <select id="lora-filter" class="filter-select">
                                <option value="">All LoRAs</option>
                            </select>
                        </div>
                        
                        <!-- Node Type Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="filter-label">Node Type:</label>
                            <select id="node-type-filter" class="filter-select">
                                <option value="">All Node Types</option>
                            </select>
                        </div>
                        
                        <!-- Collection Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="filter-label">Collection:</label>
                            <div id="collection-dropdown" class="custom-dropdown">
                                <button id="collection-filter-button" class="dropdown-button" type="button">
                                    <span id="collection-filter-text">All Collections</span>
                                    <span class="dropdown-arrow">▼</span>
                                </button>
                                <div id="collection-filter-menu" class="dropdown-menu">
                                    <div class="dropdown-option selected" data-value="">All Collections</div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Sort Widget -->
                        <div class="flex items-center space-x-2">
                            <label class="filter-label">Sort by:</label>
                            <div id="sort-dropdown" class="custom-dropdown">
                                <button id="sort-field-button" class="dropdown-button" type="button">
                                    <span id="sort-field-text">Ingest Date</span>
                                    <span class="dropdown-arrow">▼</span>
                                </button>
                                <div id="sort-field-menu" class="dropdown-menu">
                                    <div class="dropdown-option selected" data-value="ingest_date">Ingest Date</div>
                                    <div class="dropdown-option" data-value="file_date">File Date</div>
                                    <div class="dropdown-option" data-value="name">Name</div>
                                    <div class="dropdown-option" data-value="file_size">File Size</div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Sort Direction -->
                        <div class="flex items-center space-x-2">
                            <button id="sort-direction" class="btn-secondary flex items-center space-x-1" title="Click to toggle sort direction">
                                <span id="sort-direction-text">Newest First</span>
                                <span id="sort-direction-icon">↓</span>
                            </button>
                        </div>
                        
                        <!-- Bulk Actions Toggle -->
                        <button id="toggle-bulk-select" class="btn-secondary">
                            SELECT WORKFLOWS
                        </button>
                        
                        <!-- Clear Filters -->
                        <button id="clear-filters" class="clear-filters">
                            Clear All
                        </button>
                    </div>
                </div>
            </div>
        </header>

        <!-- Mission Operations -->
        <main class="max-w-7xl mx-auto px-6 py-8">
            <!-- Loading State -->
            <div id="loading" class="text-center py-12">
                <div class="loading-indicator mx-auto mb-4"></div>
                <p class="text-white font-bold uppercase tracking-wider">INITIALIZING WORKFLOW DATA...</p>
            </div>
            
            <!-- Error State -->
            <div id="error" class="hidden text-center py-12">
                <div class="text-6xl mb-6" style="color: var(--nasa-orange);">⚠️</div>
                <h2 class="text-2xl font-bold text-white mb-4 uppercase tracking-wider">CRITICAL ERROR</h2>
                <p id="error-message" class="text-white mb-6 font-mono"></p>
                <button onclick="loadWorkflows()" class="btn-danger">
                    RETRY INGESTION
                </button>
            </div>
            
            <!-- Empty State -->
            <div id="empty" class="hidden text-center py-12">
                <div class="text-6xl mb-6" style="color: var(--nasa-gray);">�</div>
                <h2 class="text-2xl font-medium text-white mb-4">No workflows found</h2>
                <p class="text-white mb-6 font-mono">ADJUST WORKFLOW PARAMETERS OR SCAN NEW DIRECTORIES</p>
                <a href="/" class="btn-primary">
                    Scan Directory
                </a>
            </div>
            
            <!-- Workflow Grid -->
            <div id="workflow-grid" class="workflow-grid hidden">
                <!-- Workflow items will be inserted here -->
            </div>
            
            <!-- Load More -->
            <div id="load-more-container" class="hidden text-center mt-8">
                <button id="load-more" class="btn-secondary">
                    Load More
                </button>
            </div>
        </main>

        <!-- Collection Picker Modal -->
        <div id="collection-picker-modal" class="fixed inset-0 z-50 hidden">
            <!-- Backdrop -->
            <div class="fixed inset-0 bg-black bg-opacity-50" onclick="closeCollectionPicker()"></div>
            
            <!-- Modal Content -->
            <div class="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-full max-w-lg">
                <div class="confirmation-dialog p-6 m-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-xl font-bold" style="color: var(--nasa-dark);">📚 ADD TO COLLECTIONS</h2>
                        <button onclick="closeCollectionPicker()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
                    </div>
                    
                    <!-- Create New Collection -->
                    <div class="mb-4 p-3 border border-gray-200 rounded" style="border-color: var(--nasa-gray);">
                        <div class="flex space-x-2">
                            <input type="text" id="quick-collection-name" class="search-input flex-1" placeholder="Create new collection...">
                            <button onclick="createQuickCollection()" class="btn-primary" style="padding: 0.5rem;">
                                ➕
                            </button>
                        </div>
                    </div>
                    
                    <!-- Collection List -->
                    <div class="mb-4">
                        <div id="collection-picker-list" class="space-y-2 max-h-60 overflow-y-auto">
                            <!-- Collections will be loaded here -->
                        </div>
                    </div>
                    
                    <!-- Actions -->
                    <div class="flex justify-end space-x-2">
                        <button onclick="closeCollectionPicker()" class="btn-secondary">Cancel</button>
                        <button onclick="saveCollectionAssignments()" class="btn-primary">Save</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Bulk Actions Bar (appears when workflows are selected) -->
        <div id="bulk-actions-bar" class="fixed bottom-4 left-1/2 transform -translate-x-1/2 z-40 hidden">
            <div class="confirmation-dialog p-4 flex items-center space-x-4">
                <span id="selected-count" class="filter-label">0 workflows selected</span>
                <button onclick="bulkAddToCollection()" class="btn-primary">
                    ADD TO COLLECTION
                </button>
                <button onclick="bulkRemoveWorkflows()" class="btn-danger">
                    REMOVE SELECTED
                </button>
                <button onclick="clearSelection()" class="btn-secondary">
                    Clear Selection
                </button>
            </div>
        </div>

        <script>
            // Configuration
            const API_BASE = '/api';
            
            // State management
            let currentWorkflows = [];
            let allCheckpoints = [];
            let allLoras = [];
            let allNodeTypes = [];
            let allCollections = [];
            let currentFilters = {
                search: '',
                checkpoint: '',
                lora: '',
                nodeType: '',
                collection: '',
                sortField: 'ingest_date',
                sortDirection: 'desc', // desc = newest first, asc = oldest first
                offset: 0,
                limit: 50
            };
            let hasMore = true;

            // Initialize page
            document.addEventListener('DOMContentLoaded', function() {
                initializeCustomDropdowns(); // Initialize custom dropdowns
                updateSortDirectionText(); // Initialize sort UI
                loadFilters();
                loadWorkflows();
                setupEventListeners();
            });

            // Custom Dropdown Functions
            function initializeCustomDropdowns() {
                // Initialize all custom dropdowns
                const dropdowns = document.querySelectorAll('.custom-dropdown');
                
                dropdowns.forEach(dropdown => {
                    const button = dropdown.querySelector('.dropdown-button');
                    const menu = dropdown.querySelector('.dropdown-menu');
                    const options = dropdown.querySelectorAll('.dropdown-option');
                    
                    // Toggle dropdown on button click
                    button.addEventListener('click', function(e) {
                        e.stopPropagation();
                        
                        // Close all other dropdowns
                        document.querySelectorAll('.dropdown-menu.open').forEach(otherMenu => {
                            if (otherMenu !== menu) {
                                otherMenu.classList.remove('open');
                                otherMenu.parentElement.querySelector('.dropdown-button').classList.remove('open');
                            }
                        });
                        
                        // Toggle this dropdown
                        menu.classList.toggle('open');
                        button.classList.toggle('open');
                    });
                    
                    // Handle option selection
                    options.forEach(option => {
                        option.addEventListener('click', function(e) {
                            e.stopPropagation();
                            
                            // Update selected state
                            options.forEach(opt => opt.classList.remove('selected'));
                            option.classList.add('selected');
                            
                            // Update button text
                            const textElement = button.querySelector('span:first-child');
                            textElement.textContent = option.textContent;
                            
                            // Close dropdown
                            menu.classList.remove('open');
                            button.classList.remove('open');
                            
                            // Trigger change event
                            const changeEvent = new CustomEvent('dropdownChange', {
                                detail: {
                                    value: option.getAttribute('data-value'),
                                    text: option.textContent,
                                    dropdown: dropdown
                                }
                            });
                            dropdown.dispatchEvent(changeEvent);
                        });
                    });
                });
                
                // Close dropdowns when clicking outside
                document.addEventListener('click', function() {
                    document.querySelectorAll('.dropdown-menu.open').forEach(menu => {
                        menu.classList.remove('open');
                        menu.parentElement.querySelector('.dropdown-button').classList.remove('open');
                    });
                });
            }
            
            function setDropdownValue(dropdownId, value, text) {
                const dropdown = document.getElementById(dropdownId);
                if (!dropdown) return;
                
                const button = dropdown.querySelector('.dropdown-button');
                const textElement = button.querySelector('span:first-child');
                const options = dropdown.querySelectorAll('.dropdown-option');
                
                // Update selected state
                options.forEach(option => {
                    option.classList.remove('selected');
                    if (option.getAttribute('data-value') === value) {
                        option.classList.add('selected');
                    }
                });
                
                // Update button text
                textElement.textContent = text;
            }
            
            function addDropdownOption(dropdownMenuId, value, text, selected = false) {
                const menu = document.getElementById(dropdownMenuId);
                if (!menu) return;
                
                const option = document.createElement('div');
                option.className = 'dropdown-option';
                if (selected) option.classList.add('selected');
                option.setAttribute('data-value', value);
                option.textContent = text;
                
                // Add click handler
                option.addEventListener('click', function(e) {
                    e.stopPropagation();
                    
                    // Update selected state
                    menu.querySelectorAll('.dropdown-option').forEach(opt => opt.classList.remove('selected'));
                    option.classList.add('selected');
                    
                    // Update button text
                    const dropdown = menu.parentElement;
                    const button = dropdown.querySelector('.dropdown-button');
                    const textElement = button.querySelector('span:first-child');
                    textElement.textContent = option.textContent;
                    
                    // Close dropdown
                    menu.classList.remove('open');
                    button.classList.remove('open');
                    
                    // Trigger change event
                    const changeEvent = new CustomEvent('dropdownChange', {
                        detail: {
                            value: option.getAttribute('data-value'),
                            text: option.textContent,
                            dropdown: dropdown
                        }
                    });
                    dropdown.dispatchEvent(changeEvent);
                });
                
                menu.appendChild(option);
            }

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

                // Collection filter (custom dropdown)
                document.getElementById('collection-dropdown').addEventListener('dropdownChange', function(e) {
                    currentFilters.collection = e.detail.value;
                    resetAndReload();
                });

                // Sort field change (custom dropdown)
                document.getElementById('sort-dropdown').addEventListener('dropdownChange', function(e) {
                    currentFilters.sortField = e.detail.value;
                    updateSortDirectionText();
                    resetAndReload();
                });

                // Sort direction toggle
                document.getElementById('sort-direction').addEventListener('click', function() {
                    currentFilters.sortDirection = currentFilters.sortDirection === 'desc' ? 'asc' : 'desc';
                    updateSortDirectionText();
                    resetAndReload();
                });

                // Bulk select toggle
                document.getElementById('toggle-bulk-select').addEventListener('click', function() {
                    toggleBulkSelectMode();
                });

                // Clear filters
                document.getElementById('clear-filters').addEventListener('click', function() {
                    document.getElementById('search-input').value = '';
                    
                    // Reset regular select dropdowns (if any remain)
                    const checkpointFilter = document.getElementById('checkpoint-filter');
                    const loraFilter = document.getElementById('lora-filter');
                    const nodeTypeFilter = document.getElementById('node-type-filter');
                    
                    if (checkpointFilter) checkpointFilter.value = '';
                    if (loraFilter) loraFilter.value = '';
                    if (nodeTypeFilter) nodeTypeFilter.value = '';
                    
                    // Reset custom dropdowns
                    setDropdownValue('collection-dropdown', '', 'All Collections');
                    setDropdownValue('sort-dropdown', 'ingest_date', 'Ingest Date');
                    
                    currentFilters = {
                        search: '',
                        checkpoint: '',
                        lora: '',
                        nodeType: '',
                        collection: '',
                        sortField: 'ingest_date',
                        sortDirection: 'desc',
                        offset: 0,
                        limit: 50
                    };
                    
                    updateSortDirectionText();
                    resetAndReload();
                });

                // Load more button
                document.getElementById('load-more').addEventListener('click', function() {
                    currentFilters.offset += currentFilters.limit;
                    loadWorkflows(true);
                });
            }

            function updateSortDirectionText() {
                const sortField = currentFilters.sortField;
                const sortDirection = currentFilters.sortDirection;
                const textElement = document.getElementById('sort-direction-text');
                const iconElement = document.getElementById('sort-direction-icon');
                
                let text = '';
                let icon = '';
                
                if (sortDirection === 'desc') {
                    icon = '↓';
                    switch (sortField) {
                        case 'ingest_date':
                            text = 'Newest Ingested';
                            break;
                        case 'file_date':
                            text = 'Newest Files';
                            break;
                        case 'name':
                            text = 'Z→A';
                            break;
                        case 'file_size':
                            text = 'Largest';
                            break;
                        default:
                            text = 'Newest First';
                    }
                } else {
                    icon = '↑';
                    switch (sortField) {
                        case 'ingest_date':
                            text = 'Oldest Ingested';
                            break;
                        case 'file_date':
                            text = 'Oldest Files';
                            break;
                        case 'name':
                            text = 'A→Z';
                            break;
                        case 'file_size':
                            text = 'Smallest';
                            break;
                        default:
                            text = 'Oldest First';
                    }
                }
                
                textElement.textContent = text;
                iconElement.textContent = icon;
            }

            function copyToClipboard(text) {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(() => {
                        // Show brief success indication
                        const toast = document.createElement('div');
                        toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-blue);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                        toast.textContent = 'Path copied to clipboard';
                        document.body.appendChild(toast);
                        setTimeout(() => document.body.removeChild(toast), 2000);
                    }).catch(() => {
                        fallbackCopyPath(text);
                    });
                } else {
                    fallbackCopyPath(text);
                }
            }

            function fallbackCopyPath(text) {
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                
                const toast = document.createElement('div');
                toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-blue);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                toast.textContent = 'Path copied to clipboard';
                document.body.appendChild(toast);
                setTimeout(() => document.body.removeChild(toast), 2000);
            }

            function openFileLocation(filePath) {
                if (!filePath) {
                    const toast = document.createElement('div');
                    toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-orange);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                    toast.textContent = 'No file path available';
                    document.body.appendChild(toast);
                    setTimeout(() => document.body.removeChild(toast), 2000);
                    return;
                }

                // Try different methods based on platform/browser
                if (navigator.platform.indexOf('Mac') !== -1) {
                    // macOS - try to open in Finder
                    fetch('/api/open-file-location', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ file_path: filePath })
                    }).then(response => {
                        if (response.ok) {
                            const toast = document.createElement('div');
                            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-blue);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                            toast.textContent = 'Opening file location...';
                            document.body.appendChild(toast);
                            setTimeout(() => document.body.removeChild(toast), 2000);
                        } else {
                            throw new Error('Failed to open file location');
                        }
                    }).catch(error => {
                        // Fallback: copy path to clipboard
                        copyToClipboard(filePath);
                        const toast = document.createElement('div');
                        toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-orange);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                        toast.textContent = 'Could not open location, path copied instead';
                        document.body.appendChild(toast);
                        setTimeout(() => document.body.removeChild(toast), 3000);
                    });
                } else {
                    // For other platforms, just copy to clipboard for now
                    copyToClipboard(filePath);
                    const toast = document.createElement('div');
                    toast.style.cssText = 'position:fixed;top:20px;right:20px;background:var(--nasa-blue);color:white;padding:8px 16px;border-radius:4px;z-index:1000;font-size:12px;';
                    toast.textContent = 'File path copied to clipboard';
                    document.body.appendChild(toast);
                    setTimeout(() => document.body.removeChild(toast), 2000);
                }
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
                    checkpointSelect.innerHTML = '<option value="">ALL CHECKPOINTS</option>';
                    allCheckpoints.forEach(checkpoint => {
                        const option = document.createElement('option');
                        option.value = checkpoint;
                        option.textContent = checkpoint.toUpperCase();
                        checkpointSelect.appendChild(option);
                    });

                    // Populate LoRAs
                    allLoras = Array.from(loraSet).sort();
                    const loraSelect = document.getElementById('lora-filter');
                    loraSelect.innerHTML = '<option value="">ALL LORAS</option>';
                    allLoras.forEach(lora => {
                        const option = document.createElement('option');
                        option.value = lora;
                        option.textContent = lora.toUpperCase();
                        loraSelect.appendChild(option);
                    });

                    // Populate node types
                    allNodeTypes = Array.from(nodeTypeSet).sort();
                    const nodeTypeSelect = document.getElementById('node-type-filter');
                    nodeTypeSelect.innerHTML = '<option value="">ALL NODE TYPES</option>';
                    allNodeTypes.forEach(nodeType => {
                        const option = document.createElement('option');
                        option.value = nodeType;
                        option.textContent = nodeType.toUpperCase();
                        nodeTypeSelect.appendChild(option);
                    });

                    // Load collections separately
                    await loadCollections();

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
                    if (currentFilters.collection) params.append('collection', currentFilters.collection);
                    params.append('sort_field', currentFilters.sortField);
                    params.append('sort_direction', currentFilters.sortDirection);
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
                    // Note: Collection filtering is done server-side, but keep for consistency
                    if (currentFilters.collection && !params.has('collection')) {
                        workflows = workflows.filter(w => 
                            w.collections && w.collections.includes(currentFilters.collection)
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
                div.className = 'neo-brutalist-card workflow-card';
                div.setAttribute('data-workflow-id', workflow.id);
                
                const createdAt = workflow.created_at ? new Date(workflow.created_at).toLocaleDateString() : 'UNKNOWN';
                
                // Separate tags by type
                const checkpointTags = workflow.tags.filter(tag => tag.startsWith('checkpoint:')).map(tag => tag.substring(11));
                const loraTags = workflow.tags.filter(tag => tag.startsWith('lora:')).map(tag => tag.substring(5));
                const otherTags = workflow.tags.filter(tag => !tag.startsWith('checkpoint:') && !tag.startsWith('lora:'));
                
                const checkpointTagsHtml = checkpointTags.map(tag => `<span class="tag-checkpoint">CHECKPOINT: ${tag.toUpperCase()}</span>`).join('');
                const loraTagsHtml = loraTags.map(tag => `<span class="tag-lora">LORA: ${tag.toUpperCase()}</span>`).join('');
                const otherTagsHtml = otherTags.map(tag => 
                    `<span class="tag-item-wrapper-catalog relative inline-block">
                        <span class="tag-custom group" style="display: inline-flex; align-items: center; gap: 4px;">
                            <span class="tag-text">${tag.toUpperCase()}</span>
                            <button onclick="showDeleteConfirmCatalog(this, '${tag}', '${workflow.id}')" class="btn-danger opacity-0 group-hover:opacity-100 transition-opacity text-xs px-1 py-0" title="Delete tag">×</button>
                        </span>
                        <div class="delete-confirm confirmation-dialog hidden absolute top-full left-0 mt-2 p-3 z-50 whitespace-nowrap">
                            <div class="text-xs font-bold mb-2 uppercase">DELETE "${tag.toUpperCase()}"?</div>
                            <div class="flex gap-2">
                                <button onclick="confirmDeleteCatalog(this, '${tag}', '${workflow.id}')" class="btn-danger text-xs px-2 py-1">DELETE</button>
                                <button onclick="cancelDeleteCatalog(this)" class="btn-secondary text-xs px-2 py-1">CANCEL</button>
                            </div>
                        </div>
                    </span>`
                ).join(' ');
                
                div.innerHTML = `
                    <!-- Bulk Selection Checkbox -->
                    <div class="workflow-checkbox">
                        <input type="checkbox" id="checkbox-${workflow.id}" onchange="toggleWorkflowSelection('${workflow.id}')">
                    </div>
                    
                    ${workflow.has_image ? 
                        `<div class="thumbnail-container">
                            <img src="${API_BASE}/workflows/${workflow.id}/thumbnail" alt="${workflow.name}" class="thumbnail" 
                                 onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                                 oncontextmenu="openFileLocation('${workflow.file_path ? workflow.file_path.replace(/'/g, "\\'") : ''}'); return false;"
                                 title="Right-click to open file location">
                            <div class="no-thumbnail" style="display: none;">�</div>
                         </div>`
                        : '<div class="no-thumbnail">�</div>'
                    }
                        
                    <div class="p-6">
                        <h3 class="font-bold text-lg uppercase tracking-wider mb-1" style="color: var(--nasa-dark);">${(workflow.name || workflow.filename || 'UNTITLED WORKFLOW').toUpperCase()}</h3>
                        
                        ${workflow.file_path ? 
                            `<div class="file-path-container mb-2">
                                <div class="file-path-buttons">
                                    <button onclick="copyToClipboard('${workflow.file_path.replace(/'/g, "\\'")}')" class="btn-path text-xs px-2 py-1" title="Copy file path">CPY</button>
                                    <button onclick="openFileLocation('${workflow.file_path.replace(/'/g, "\\'")}')" class="btn-path text-xs px-2 py-1" title="Open file location">GTO</button>
                                </div>
                                <div class="file-path-text">
                                    <div class="file-path text-xs">${workflow.file_path}</div>
                                </div>
                            </div>` 
                            : ''
                        }
                        
                        ${workflow.description ? 
                            `<p class="text-sm mb-4 mt-3 font-mono" style="color: var(--nasa-dark);">${workflow.description.toUpperCase()}</p>` 
                            : '<div class="mb-2"></div>'
                        }
                        
                        <div class="mission-stats flex items-center justify-between text-xs mb-4">
                            <span>📊 ${workflow.node_count || 0} NODES</span>
                            <span>📅 ${createdAt.toUpperCase()}</span>
                        </div>
                        
                        ${checkpointTagsHtml ? `<div class="mb-3 flex flex-wrap gap-1">${checkpointTagsHtml}</div>` : ''}
                        ${loraTagsHtml ? `<div class="mb-3 flex flex-wrap gap-1">${loraTagsHtml}</div>` : ''}
                        
                        <div class="mb-4 flex-grow">
                            <div class="flex items-center justify-between mb-2">
                                <span class="font-bold text-xs tracking-wide" style="color: var(--nasa-dark);">Tags:</span>
                                <button onclick="showAddTagForm('${workflow.id}')" class="btn-primary text-xs px-2 py-1" title="Add tag">+ ADD</button>
                            </div>
                            <div id="tags-container-${workflow.id}" class="flex flex-wrap gap-1 mb-2">
                                ${otherTagsHtml || '<span class="text-xs font-mono" style="color: var(--nasa-gray);">NO TAGS ASSIGNED</span>'}
                            </div>
                            <div id="add-tag-form-${workflow.id}" class="hidden">
                                <input type="text" id="new-tag-input-${workflow.id}" placeholder="ENTER TAG..." class="input-field w-full mb-2 text-xs">
                                <div class="flex gap-2">
                                    <button onclick="saveNewTagCatalog('${workflow.id}')" class="btn-primary text-xs px-3 py-1">SAVE</button>
                                    <button onclick="cancelAddTagCatalog('${workflow.id}')" class="btn-secondary text-xs px-3 py-1">CANCEL</button>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Compact buttons and ID section at bottom -->
                    <div class="card-buttons px-6 pb-3 pt-2">
                        <!-- Main action buttons - compact and less tall -->
                        <div class="flex gap-2 mb-2">
                            <button onclick="viewWorkflow('${workflow.id}')" 
                                    class="btn-primary flex-1 text-s py-1" 
                                    style="padding-top: 4px; padding-bottom: 4px;">
                                WORKFLOW DETAILS
                            </button>
                            <button onclick="downloadWorkflow('${workflow.id}', '${workflow.name || workflow.filename}')" 
                                    class="btn-secondary text-s px-2 py-1" 
                                    style="padding-top: 4px; padding-bottom: 4px;min-width: 50px;">
                                DWN WFL
                            </button>
                        </div>
                        
                        <!-- Delete button and ID on same row -->
                        <div class="flex justify-between items-center">
                            <div class="text-xs font-mono opacity-50" style="color: var(--nasa-dark-gray); font-size: 10px;">
                                ${workflow.id}
                            </div>
                            <div class="workflow-delete-wrapper relative">
                                <button onclick="showWorkflowDeleteConfirm(this, '${workflow.id}', '${(workflow.name || workflow.filename).replace(/'/g, "\\'")}')" 
                                        class="btn-danger text-xs px-3 py-1" 
                                        style="background: #cc0000; border: 1px solid #990000; color: white; font-size: 10px; font-weight: bold;">
                                    DEL
                                </button>
                                <div class="workflow-delete-confirm confirmation-dialog hidden absolute top-full right-0 mt-2 p-3 z-50 whitespace-nowrap" 
                                     style="background: var(--nasa-white); border: 2px solid var(--nasa-red); color: var(--nasa-dark);">
                                    <div class="text-xs font-bold mb-2 uppercase">REMOVE "${(workflow.name || workflow.filename).toUpperCase()}"?</div>
                                    <div class="text-xs mb-3" style="color: var(--nasa-gray);">Database entry only - files preserved</div>
                                    <div class="flex gap-2">
                                        <button onclick="confirmWorkflowDelete(this, '${workflow.id}', '${(workflow.name || workflow.filename).replace(/'/g, "\\'")}')" 
                                                class="btn-danger text-xs px-2 py-1" 
                                                style="background: #cc0000; border: 1px solid #990000; color: white; font-weight: bold;">REMOVE</button>
                                        <button onclick="cancelWorkflowDelete(this)" 
                                                class="btn-secondary text-xs px-2 py-1">CANCEL</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
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

            // Workflow deletion confirmation functions
            function showWorkflowDeleteConfirm(button, workflowId, filename) {
                // Hide any other open confirmations
                document.querySelectorAll('.workflow-delete-confirm').forEach(confirm => {
                    confirm.classList.add('hidden');
                });
                
                const deleteWrapper = button.closest('.workflow-delete-wrapper');
                const confirmDiv = deleteWrapper.querySelector('.workflow-delete-confirm');
                confirmDiv.classList.remove('hidden');
            }

            function cancelWorkflowDelete(button) {
                const confirmDiv = button.closest('.workflow-delete-confirm');
                confirmDiv.classList.add('hidden');
            }

            async function confirmWorkflowDelete(button, workflowId, filename) {
                // Hide the confirmation
                const confirmDiv = button.closest('.workflow-delete-confirm');
                confirmDiv.classList.add('hidden');
                
                // Perform the actual deletion
                await removeSingleWorkflow(workflowId, filename);
            }

            async function removeSingleWorkflow(workflowId, filename) {
                try {
                    const response = await fetch(`${API_BASE}/workflows/${workflowId}`, {
                        method: 'DELETE'
                    });
                    
                    if (response.ok) {
                        const result = await response.json();
                        showToast(result.message, 'success');
                        
                        // Remove the card from the UI with animation
                        const card = document.querySelector(`[data-workflow-id="${workflowId}"]`);
                        if (card) {
                            card.style.opacity = '0.5';
                            card.style.transform = 'scale(0.95)';
                            card.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                            
                            setTimeout(() => {
                                card.remove();
                                
                                // Update workflow count
                                currentWorkflows = currentWorkflows.filter(w => w.id !== workflowId);
                                updateWorkflowCount(currentWorkflows.length);
                                
                                // Show empty state if no workflows left
                                if (currentWorkflows.length === 0) {
                                    showEmpty();
                                }
                            }, 300);
                        }
                        
                    } else {
                        const error = await response.json();
                        showToast('Failed to remove workflow: ' + (error.detail || 'Unknown error'), 'error');
                    }
                } catch (error) {
                    console.error('Error removing workflow:', error);
                    showToast('Failed to remove workflow: Network error', 'error');
                }
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
                const noTagsSpan = container.querySelector('span[style*="nasa-gray"]');
                if (noTagsSpan && noTagsSpan.textContent.includes('NO TAGS ASSIGNED')) {
                    noTagsSpan.remove();
                }
                
                const tagHtml = `
                    <span class="tag-item-wrapper-catalog relative inline-block">
                        <span class="tag-custom group" style="display: inline-flex; align-items: center; gap: 4px;">
                            <span class="tag-text">${tagValue.toUpperCase()}</span>
                            <button onclick="showDeleteConfirmCatalog(this, '${tagValue.replace(/'/g, "\\'")}', '${workflowId}')" class="btn-danger opacity-0 group-hover:opacity-100 transition-opacity text-xs px-1 py-0" title="Delete tag">×</button>
                        </span>
                        <div class="delete-confirm confirmation-dialog hidden absolute top-full left-0 mt-2 p-3 z-50 whitespace-nowrap">
                            <div class="text-xs font-bold mb-2 uppercase">DELETE "${tagValue.toUpperCase()}"?</div>
                            <div class="flex gap-2">
                                <button onclick="confirmDeleteCatalog(this, '${tagValue.replace(/'/g, "\\'")}', '${workflowId}')" class="btn-danger text-xs px-2 py-1">DELETE</button>
                                <button onclick="cancelDeleteCatalog(this)" class="btn-secondary text-xs px-2 py-1">CANCEL</button>
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

            // Bulk Selection State
            let bulkSelectMode = false;
            let selectedWorkflows = new Set();

            // Bulk Selection Functions
            function toggleBulkSelectMode() {
                bulkSelectMode = !bulkSelectMode;
                const button = document.getElementById('toggle-bulk-select');
                const grid = document.getElementById('workflow-grid');
                const bulkBar = document.getElementById('bulk-actions-bar');
                
                if (bulkSelectMode) {
                    button.textContent = 'CANCEL SELECTION';
                    button.classList.remove('btn-secondary');
                    button.classList.add('btn-danger');
                    grid.classList.add('bulk-select-mode');
                } else {
                    button.textContent = 'SELECT WORKFLOWS';
                    button.classList.remove('btn-danger');
                    button.classList.add('btn-secondary');
                    grid.classList.remove('bulk-select-mode');
                    clearSelection();
                    bulkBar.classList.add('hidden');
                }
            }

            function toggleWorkflowSelection(workflowId) {
                if (!bulkSelectMode) return;
                
                const checkbox = document.getElementById(`checkbox-${workflowId}`);
                const card = document.querySelector(`[data-workflow-id="${workflowId}"]`);
                
                if (checkbox.checked) {
                    selectedWorkflows.add(workflowId);
                    card.classList.add('selected');
                } else {
                    selectedWorkflows.delete(workflowId);
                    card.classList.remove('selected');
                }
                
                updateBulkActionsBar();
            }

            function clearSelection() {
                selectedWorkflows.clear();
                document.querySelectorAll('.workflow-checkbox input[type="checkbox"]').forEach(cb => {
                    cb.checked = false;
                });
                document.querySelectorAll('.workflow-card.selected').forEach(card => {
                    card.classList.remove('selected');
                });
                updateBulkActionsBar();
            }

            function updateBulkActionsBar() {
                const bulkBar = document.getElementById('bulk-actions-bar');
                const countElement = document.getElementById('selected-count');
                
                if (selectedWorkflows.size > 0) {
                    bulkBar.classList.remove('hidden');
                    countElement.textContent = `${selectedWorkflows.size} workflow${selectedWorkflows.size === 1 ? '' : 's'} selected`;
                } else {
                    bulkBar.classList.add('hidden');
                }
            }

            function bulkAddToCollection() {
                if (selectedWorkflows.size === 0) return;
                openCollectionPicker(Array.from(selectedWorkflows));
            }

            async function bulkRemoveWorkflows() {
                if (selectedWorkflows.size === 0) return;
                
                const count = selectedWorkflows.size;
                const plural = count === 1 ? 'workflow' : 'workflows';
                
                if (!confirm(`Remove ${count} ${plural} from the database?\\n\\nThis will delete the catalog entries but preserve all original files.`)) {
                    return;
                }
                
                const workflowIds = Array.from(selectedWorkflows);
                let successCount = 0;
                let failedCount = 0;
                
                for (const workflowId of workflowIds) {
                    try {
                        const response = await fetch(`${API_BASE}/workflows/${workflowId}`, {
                            method: 'DELETE'
                        });
                        
                        if (response.ok) {
                            successCount++;
                            // Remove the card from the UI
                            const card = document.querySelector(`[data-workflow-id="${workflowId}"]`);
                            if (card) {
                                card.remove();
                            }
                        } else {
                            failedCount++;
                        }
                    } catch (error) {
                        failedCount++;
                    }
                }
                
                // Update current workflows and clear selection
                currentWorkflows = currentWorkflows.filter(w => !workflowIds.includes(w.id));
                clearSelection();
                toggleBulkSelectMode(); // Exit bulk mode
                updateWorkflowCount(currentWorkflows.length);
                
                // Show results
                if (failedCount === 0) {
                    showToast(`Successfully removed ${successCount} ${plural}`, 'success');
                } else {
                    showToast(`Removed ${successCount}, failed ${failedCount}`, 'error');
                }
            }

            // Collection Management Functions
            let collectionPickerWorkflows = [];

            function openCollectionPicker(workflowIds) {
                collectionPickerWorkflows = workflowIds;
                document.getElementById('collection-picker-modal').classList.remove('hidden');
                loadCollectionPickerList();
            }

            function closeCollectionPicker() {
                document.getElementById('collection-picker-modal').classList.add('hidden');
                document.getElementById('quick-collection-name').value = '';
                collectionPickerWorkflows = [];
            }

            async function loadCollectionPickerList() {
                try {
                    const response = await fetch(`${API_BASE}/collections`);
                    if (!response.ok) return;
                    
                    const data = await response.json();
                    const collections = data.collections || [];
                    
                    const container = document.getElementById('collection-picker-list');
                    container.innerHTML = '';
                    
                    if (collections.length === 0) {
                        container.innerHTML = '<p class="filter-label text-center py-4">No collections yet. Create one above.</p>';
                        return;
                    }
                    
                    collections.forEach(collection => {
                        const item = document.createElement('div');
                        item.className = 'collection-picker-item';
                        item.setAttribute('data-collection-id', collection.id);
                        
                        item.innerHTML = `
                            <div class="collection-color-dot" style="background-color: ${collection.color || '#105bd8'}"></div>
                            <div class="flex-1">
                                <div class="filter-label">${collection.name}</div>
                                ${collection.description ? `<div class="text-xs" style="color: var(--nasa-gray);">${collection.description}</div>` : ''}
                            </div>
                            <div class="text-xs" style="color: var(--nasa-gray);">${collection.file_count || 0} workflows</div>
                        `;
                        
                        item.addEventListener('click', function() {
                            item.classList.toggle('selected');
                        });
                        
                        container.appendChild(item);
                    });
                    
                } catch (error) {
                    console.error('Error loading collections:', error);
                }
            }

            async function createQuickCollection() {
                const name = document.getElementById('quick-collection-name').value.trim();
                if (!name) return;
                
                try {
                    const response = await fetch(`${API_BASE}/collections`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            name: name,
                            description: '',
                            color: '#105bd8'
                        })
                    });
                    
                    if (!response.ok) {
                        const error = await response.json();
                        alert(error.detail || 'Failed to create collection');
                        return;
                    }
                    
                    document.getElementById('quick-collection-name').value = '';
                    await loadCollectionPickerList();
                    
                } catch (error) {
                    console.error('Error creating collection:', error);
                    alert('Failed to create collection');
                }
            }

            async function saveCollectionAssignments() {
                const selectedCollectionIds = Array.from(
                    document.querySelectorAll('.collection-picker-item.selected')
                ).map(item => item.getAttribute('data-collection-id'));
                
                if (collectionPickerWorkflows.length === 0) {
                    closeCollectionPicker();
                    return;
                }
                
                try {
                    // Assign collections to each workflow
                    for (const workflowId of collectionPickerWorkflows) {
                        const response = await fetch(`${API_BASE}/workflows/${workflowId}/collections`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ collection_ids: selectedCollectionIds })
                        });
                        
                        if (!response.ok) {
                            console.error(`Failed to update workflow ${workflowId}`);
                        }
                    }
                    
                    closeCollectionPicker();
                    clearSelection();
                    toggleBulkSelectMode(); // Exit bulk mode
                    
                    // Reload workflows to show updated collections
                    resetAndReload();
                    
                    alert('Collections updated successfully!');
                    
                } catch (error) {
                    console.error('Error saving collection assignments:', error);
                    alert('Failed to update collections');
                }
            }

            // Collections Management Functions
            async function loadCollections() {
                try {
                    const response = await fetch(`${API_BASE}/collections`);
                    if (!response.ok) return;
                    
                    const data = await response.json();
                    allCollections = data.collections || [];
                    
                    // Populate custom collection filter dropdown
                    const collectionMenu = document.getElementById('collection-filter-menu');
                    if (collectionMenu) {
                        // Clear existing options (except "All Collections")
                        const allOption = collectionMenu.querySelector('[data-value=""]');
                        collectionMenu.innerHTML = '';
                        if (allOption) {
                            collectionMenu.appendChild(allOption);
                        } else {
                            addDropdownOption('collection-filter-menu', '', 'All Collections', true);
                        }
                        
                        // Add collection options
                        allCollections.forEach(collection => {
                            addDropdownOption('collection-filter-menu', collection.name, collection.name.toUpperCase());
                        });
                    }
                    
                } catch (error) {
                    console.error('Error loading collections:', error);
                }
            }

            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }

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
    <title>Comfy Light Table</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        :root {
            --nasa-red: #fc3d21;
            --nasa-blue: #105bd8;
            --nasa-gray: #aeb0b5;
            --nasa-dark-gray: #6b6b6b;
            --nasa-white: #ffffff;
            --nasa-dark: #212121;
            --nasa-orange: #ff9d1e;
        }
        
        * {
            font-family: '3270 Nerd Font Mono', 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Source Code Pro', 'Menlo', 'Consolas', monospace !important;
        }
        
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
        
        /* Directory Selector Styles */
        .upload-section {
            background: var(--nasa-white);
            border: 1px solid var(--nasa-dark);
            color: var(--nasa-dark);
            padding: 2rem;
            margin-bottom: 2rem;
            border-radius: 2px;
        }
        
        .upload-icon {
            font-size: 4rem;
            font-weight: 400;
            color: var(--nasa-dark);
            margin-bottom: 1rem;
        }
        
        .upload-section h2 {
            font-size: 1.5rem;
            font-weight: 400;
            color: var(--nasa-dark);
            margin-bottom: 1rem;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        
        .upload-description {
            color: var(--nasa-gray);
            margin-bottom: 2rem;
            font-size: 0.9rem;
            line-height: 1.4;
        }
        
        .directory-selector-container {
            display: flex;
            justify-content: center;
            margin: 2rem 0;
        }
        
        .directory-select-btn {
            background: transparent !important;
            color: var(--nasa-dark) !important;
            border: 1px solid var(--nasa-dark) !important;
            font-weight: 400 !important;
            padding: 1rem 2rem !important;
            font-size: 16px !important;
            border-radius: 2px !important;
            cursor: pointer !important;
            transition: all 0.1s ease !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
            font-family: '3270 Nerd Font Mono', monospace !important;
        }
        
        .directory-select-btn:hover {
            background: var(--nasa-dark) !important;
            color: var(--nasa-white) !important;
        }
        
        .directory-input-container {
            text-align: left;
            margin: 1rem 0;
        }
        
        .directory-path-input {
            width: 100% !important;
            background: var(--nasa-white) !important;
            color: var(--nasa-dark) !important;
            border: 1px solid var(--nasa-dark) !important;
            font-weight: 400 !important;
            padding: 0.75rem !important;
            font-size: 14px !important;
            border-radius: 2px !important;
            font-family: '3270 Nerd Font Mono', monospace !important;
            transition: all 0.1s ease !important;
        }
        
        .directory-path-input:focus {
            outline: none !important;
            border-color: var(--nasa-blue) !important;
            box-shadow: 0 0 0 2px rgba(0, 114, 188, 0.2) !important;
        }
        
        .input-help-text {
            font-size: 0.7rem;
            color: var(--nasa-dark);
            margin-top: 0.5rem;
            opacity: 0.7;
        }
        
        .directory-preview {
            background: var(--nasa-white);
            border: 1px solid var(--nasa-dark);
            padding: 1.5rem;
            margin: 1rem 0;
            border-radius: 2px;
        }
        
        .directory-info {
            text-align: left;
        }
        
        .directory-label {
            font-size: 0.75rem;
            font-weight: 400;
            color: var(--nasa-dark);
            margin-bottom: 0.5rem;
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        
        .directory-path {
            font-size: 0.9rem;
            color: var(--nasa-dark);
            word-break: break-all;
            margin-bottom: 0.5rem;
            font-weight: 400;
            background: var(--nasa-white);
            border: 1px solid var(--nasa-dark);
            padding: 0.5rem;
            border-radius: 2px;
        }
        
        .file-count {
            font-size: 0.8rem;
            color: var(--nasa-dark);
            margin-bottom: 1rem;
        }
        
        .change-directory-btn {
            background: transparent !important;
            color: var(--nasa-dark) !important;
            border: 1px solid var(--nasa-dark) !important;
            font-weight: 400 !important;
            padding: 0.5rem 1rem !important;
            font-size: 12px !important;
            border-radius: 2px !important;
            cursor: pointer !important;
            transition: all 0.1s ease !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
            font-family: '3270 Nerd Font Mono', monospace !important;
        }
        
        .change-directory-btn:hover {
            background: var(--nasa-dark) !important;
            color: var(--nasa-white) !important;
        }
        
        .scan-controls {
            display: flex;
            justify-content: center;
            margin: 2rem 0;
        }
        
        .scan-btn {
            background: transparent !important;
            color: var(--nasa-blue) !important;
            border: 1px solid var(--nasa-blue) !important;
            font-weight: 400 !important;
            padding: 1rem 2rem !important;
            font-size: 16px !important;
            border-radius: 2px !important;
            cursor: pointer !important;
            transition: all 0.1s ease !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
            font-family: '3270 Nerd Font Mono', monospace !important;
        }
        
        .scan-btn:hover {
            background: var(--nasa-blue) !important;
            color: var(--nasa-white) !important;
        }
        
        .scan-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            background: transparent;
            color: var(--nasa-gray);
            border-color: var(--nasa-gray);
        }
        
        /* Navigation Buttons */
        .nav-buttons {
            display: flex;
            justify-content: center;
            gap: 1rem;
            margin: 2rem 0;
        }
        
        .nav-btn {
            background: transparent !important;
            color: var(--nasa-dark) !important;
            border: 1px solid var(--nasa-dark) !important;
            font-weight: 400 !important;
            padding: 0.75rem 1.5rem !important;
            font-size: 14px !important;
            border-radius: 2px !important;
            cursor: pointer !important;
            transition: all 0.1s ease !important;
            text-decoration: none !important;
            text-transform: uppercase !important;
            letter-spacing: 1px !important;
            display: inline-block !important;
            font-family: '3270 Nerd Font Mono', monospace !important;
        }
        
        .nav-btn:hover {
            background: var(--nasa-dark) !important;
            color: var(--nasa-white) !important;
            text-decoration: none !important;
        }
        
        .nav-btn-primary:hover {
            background: var(--nasa-blue);
            color: var(--nasa-white);
            border-color: var(--nasa-blue);
        }
        
        .nav-btn-secondary:hover {
            background: var(--nasa-orange);
            color: var(--nasa-white);
            border-color: var(--nasa-orange);
        }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <header class="text-center mb-8">
            <h1 class="text-5xl font-bold text-gray-900 mb-4">
                COMFY LIGHT TABLE
            </h1>
            <p class="text-xl text-gray-600 max-w-2xl mx-auto mb-6">
                Index workflow files from your existing directories. Files remain in their original locations - this creates a searchable catalog database.
            </p>
            
            <!-- Navigation -->
            <div class="nav-buttons">
                <a href="/catalog" class="nav-btn nav-btn-primary">
                    BROWSE CATALOG
                </a>
                <a href="#" onclick="scrollToScanner()" class="nav-btn nav-btn-secondary">
                    SCAN DIRECTORY
                </a>
            </div>
        </header>

        <!-- Directory Scanning -->
        <div class="upload-section">
            <div class="space-y-6">
                <div class="text-center">
                    <div class="upload-icon">DIR</div>
                    <h2>SCAN DIRECTORY FOR WORKFLOWS</h2>
                    <p class="upload-description">
                        Index workflow files from an existing directory. Files remain in their original location.
                    </p>
                </div>
                
                <div class="max-w-2xl mx-auto">
                    <div class="space-y-4">
                        <!-- Directory Path Input -->
                        <div class="directory-input-container">
                            <label for="directoryPathInput" class="directory-label">DIRECTORY PATH:</label>
                            <input type="text" 
                                   id="directoryPathInput" 
                                   class="directory-path-input"
                                   placeholder="/Users/username/path/to/workflows"
                                   spellcheck="false">
                            <div class="input-help-text">
                                Copy and paste the full path to your workflow directory
                            </div>
                        </div>
                        
                        <!-- Scan Button -->
                        <div class="scan-controls">
                            <button id="scanDirectoryBtn" class="scan-btn">
                                START SCAN
                            </button>
                        </div>
                    </div>
                    
                    <div class="mt-4 space-y-2">
                        <div class="flex items-center space-x-2">
                            <input type="checkbox" id="recursiveCheckbox" class="rounded">
                            <label for="recursiveCheckbox" class="text-sm text-gray-700">Scan subdirectories recursively</label>
                        </div>
                        <div class="flex items-center space-x-2">
                            <input type="checkbox" id="watchCheckbox" class="rounded">
                            <label for="watchCheckbox" class="text-sm text-gray-700">Watch for new files (future feature)</label>
                        </div>
                    </div>
                </div>
                
                <div class="flex justify-center space-x-4 text-sm text-gray-400">
                    <span class="bg-gray-100 px-3 py-1 rounded-full">Scans PNG</span>
                    <span class="bg-gray-100 px-3 py-1 rounded-full">Scans WebP</span>
                    <span class="bg-gray-100 px-3 py-1 rounded-full">Scans JPEG</span>
                    <span class="bg-gray-100 px-3 py-1 rounded-full">Scans JSON</span>
                </div>
                
                <div class="text-xs text-gray-500 text-center max-w-lg mx-auto">
                    <p>Files will be indexed in place - no copying or moving. This creates a catalog of your existing workflows.</p>
                </div>
            </div>
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
            <span class="font-medium">COMFY LIGHT TABLE</span>
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
            showStatus('Connected to server', 'success');
        };
        
        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        };
        
        ws.onclose = function(event) {
            console.log('WebSocket disconnected');
            showStatus('Disconnected from server', 'error');
        };

        // Directory scanning elements
        const directoryPathInput = document.getElementById('directoryPathInput');
        const scanDirectoryBtn = document.getElementById('scanDirectoryBtn');
        const recursiveCheckbox = document.getElementById('recursiveCheckbox');
        
        // Default to recursive scanning
        recursiveCheckbox.checked = true;
        
        // Directory scanning event handler
        scanDirectoryBtn.addEventListener('click', handleDirectoryScan);
        
        // Navigation helpers
        function scrollToScanner() {
            document.querySelector('.upload-section').scrollIntoView({ 
                behavior: 'smooth' 
            });
        }
        

        
        async function handleDirectoryScan() {
            console.log('🔍 Directory scan button clicked');
            
            // Get directory path from input
            const directoryPath = directoryPathInput.value.trim();
            console.log('📁 Directory path:', directoryPath);
            
            if (!directoryPath) {
                showStatus('Please enter a directory path', 'error');
                directoryPathInput.focus();
                return;
            }
            
            // Get recursive setting
            const recursive = recursiveCheckbox.checked;
            console.log('🔄 Recursive:', recursive);
            
            const confirmed = confirm(`This will scan "${directoryPath}" ${recursive ? 'recursively' : 'non-recursively'} for workflow files and add them to your catalog. Continue?`);
            
            if (!confirmed) {
                console.log('❌ User cancelled scan');
                return;
            }
            
            try {
                console.log('📤 Sending scan request...');
                scanDirectoryBtn.disabled = true;
                scanDirectoryBtn.textContent = 'SCANNING...';
                
                showStatus(`Scanning directory: ${directoryPath}`, 'processing');
                
                // Send request to scan directory endpoint
                const response = await fetch('/scan-directory', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        directory: directoryPath,
                        recursive: recursive
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showStatus(`Directory scan started! Task ID: ${result.task_id}`, 'success');
                    // The WebSocket will provide real-time updates
                } else {
                    showStatus(`Error: ${result.detail || 'Failed to start directory scan'}`, 'error');
                }
                
            } catch (error) {
                console.error('Error starting directory scan:', error);
                showStatus(`Scan error: ${error.message}`, 'error');
            } finally {
                scanDirectoryBtn.disabled = false;
                scanDirectoryBtn.textContent = 'START SCAN';
            }
        }

        





        
        function handleWebSocketMessage(data) {
            console.log('WebSocket message:', data);
            
            switch(data.type) {
                case 'task_started':
                    addTaskCard(data.task_id, data.filename);
                    showStatus(`Started processing: ${data.filename}`, 'processing');
                    break;
                    
                case 'task_update':
                    updateTaskCard(data.task_id, data.status, data.message);
                    break;
                    
                case 'task_completed':
                    completeTaskCard(data.task_id, data.analysis);
                    if (data.workflow_id) {
                        showStatus(`Workflow saved to database! Redirecting to catalog...`, 'success');
                        // Redirect to catalog after a brief delay
                        setTimeout(() => {
                            window.location.href = '/catalog';
                        }, 2000);
                    } else {
                        showStatus(`✅ Completed: ${data.filename}`, 'success');
                    }
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
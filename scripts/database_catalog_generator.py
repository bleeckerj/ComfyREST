#!/usr/bin/env python3
"""
Database-Powered ComfyUI Workflow Catalog Generator

This module provides functions to generate interactive HTML catalogs that use
database queries for filtering instead of static client-side filtering.

The generated catalogs connect to the local database API for real-time filtering
by checkpoints, LoRAs, node types, and search terms.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import quote

# Add parent directory to path to import database package
sys.path.insert(0, str(Path(__file__).parent.parent))
from database import get_database_manager
from database.models import WorkflowFile


def generate_database_powered_catalog_html(output_path: Path, database_url: Optional[str] = None, 
                                         title: str = "ComfyUI Workflow Catalog") -> str:
    """Generate a single HTML file that connects to the database API for filtering.
    
    Args:
        output_path: Where to save the HTML catalog
        database_url: Optional database URL (uses default if None)
        title: Title for the catalog page
        
    Returns:
        The generated HTML content
    """
    
    # Get database stats for the header
    db_manager = get_database_manager()
    with db_manager.get_session() as session:
        total_workflows = session.query(WorkflowFile).count()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Generate the HTML with embedded API client
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .workflow-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1.5rem;
            padding: 0;
        }}
        .workflow-card {{
            transition: all 0.3s ease;
            width: 100%;
        }}
        .workflow-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
        }}
        .tag {{
            display: inline-block;
            padding: 0.25rem 0.5rem;
            margin: 0.125rem;
            background: #e5e7eb;
            border-radius: 0.375rem;
            font-size: 0.75rem;
            font-weight: 500;
            color: #374151;
        }}
        .checkpoint-tag {{ background: #dbeafe; color: #1e40af; }}
        .lora-tag {{ background: #fef3c7; color: #92400e; }}
        .node-tag {{ background: #f3e8ff; color: #7c3aed; }}
        .thumbnail {{
            width: 100%;
            height: 200px;
            object-fit: cover;
            border-radius: 0.5rem;
        }}
        .no-thumbnail {{
            width: 100%;
            height: 200px;
            background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
            border-radius: 0.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 3rem;
            color: #9ca3af;
        }}
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <!-- Header -->
    <header class="bg-white shadow-sm border-b">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between items-center py-4">
                <div class="flex items-center space-x-4">
                    <h1 class="text-3xl font-bold text-gray-900">💡 {title}</h1>
                    <span id="workflow-count" class="bg-blue-100 text-blue-800 text-sm font-medium px-2.5 py-0.5 rounded">
                        {total_workflows} workflows
                    </span>
                </div>
                <div class="flex items-center space-x-4 text-sm text-gray-500">
                    <span>📅 Generated: {timestamp}</span>
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
            <p class="text-gray-600 mb-4">Try adjusting your filters or check your database.</p>
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
        // Configuration - assumes local API server
        const API_BASE = 'http://localhost:8080/api';
        
        // State management
        let currentWorkflows = [];
        let allCheckpoints = [];
        let allLoras = [];
        let allNodeTypes = [];
        let currentFilters = {{
            search: '',
            checkpoint: '',
            lora: '',
            nodeType: '',
            offset: 0,
            limit: 50
        }};
        let hasMore = true;

        // Initialize page
        document.addEventListener('DOMContentLoaded', function() {{
            loadFilters();
            loadWorkflows();
            setupEventListeners();
        }});

        function setupEventListeners() {{
            // Search input with debounce
            let searchTimeout;
            document.getElementById('search-input').addEventListener('input', function(e) {{
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {{
                    currentFilters.search = e.target.value;
                    resetAndReload();
                }}, 300);
            }});

            // Filter dropdowns
            document.getElementById('checkpoint-filter').addEventListener('change', function(e) {{
                currentFilters.checkpoint = e.target.value;
                resetAndReload();
            }});

            document.getElementById('lora-filter').addEventListener('change', function(e) {{
                currentFilters.lora = e.target.value;
                resetAndReload();
            }});

            document.getElementById('node-type-filter').addEventListener('change', function(e) {{
                currentFilters.nodeType = e.target.value;
                resetAndReload();
            }});

            // Clear filters
            document.getElementById('clear-filters').addEventListener('click', function() {{
                document.getElementById('search-input').value = '';
                document.getElementById('checkpoint-filter').value = '';
                document.getElementById('lora-filter').value = '';
                document.getElementById('node-type-filter').value = '';
                currentFilters = {{
                    search: '',
                    checkpoint: '',
                    lora: '',
                    nodeType: '',
                    offset: 0,
                    limit: 50
                }};
                resetAndReload();
            }});

            // Load more button
            document.getElementById('load-more').addEventListener('click', function() {{
                currentFilters.offset += currentFilters.limit;
                loadWorkflows(true);
            }});
        }}

        async function loadFilters() {{
            try {{
                // Load filter options from API
                const response = await fetch(`${{API_BASE}}/workflows?limit=1000`);
                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                }}
                
                const data = await response.json();
                
                // Extract unique values from workflows
                const checkpoints = new Set();
                const loras = new Set();
                const nodeTypes = new Set();
                
                data.workflows.forEach(workflow => {{
                    // Extract checkpoints directly from checkpoints field
                    if (workflow.checkpoints) {{
                        workflow.checkpoints.forEach(checkpoint => {{
                            checkpoints.add(checkpoint);
                        }});
                    }}
                    
                    // Extract LoRAs directly from loras field  
                    if (workflow.loras) {{
                        workflow.loras.forEach(lora => {{
                            loras.add(lora);
                        }});
                    }}
                    
                    // Also check tags for legacy compatibility
                    if (workflow.tags) {{
                        workflow.tags.forEach(tag => {{
                            if (tag.startsWith('checkpoint:')) {{
                                checkpoints.add(tag.substring(11));
                            }} else if (tag.startsWith('lora:')) {{
                                loras.add(tag.substring(5));
                            }}
                        }});
                    }}
                    
                    // Extract node types from node_types field
                    if (workflow.node_types) {{
                        workflow.node_types.forEach(nodeType => {{
                            nodeTypes.add(nodeType);
                        }});
                    }}
                }});
                
                allCheckpoints = Array.from(checkpoints).sort();
                allLoras = Array.from(loras).sort();
                allNodeTypes = Array.from(nodeTypes).sort();
                
                // Populate filter dropdowns
                populateFilterDropdown('checkpoint-filter', allCheckpoints);
                populateFilterDropdown('lora-filter', allLoras);
                populateFilterDropdown('node-type-filter', allNodeTypes);

            }} catch (error) {{
                console.error('Error loading filters:', error);
            }}
        }}

        function populateFilterDropdown(selectId, options) {{
            const select = document.getElementById(selectId);
            const defaultOption = select.children[0]; // Keep "All X" option
            
            // Clear existing options except the first
            while (select.children.length > 1) {{
                select.removeChild(select.lastChild);
            }}
            
            // Add new options
            options.forEach(option => {{
                const optElement = document.createElement('option');
                optElement.value = option;
                optElement.textContent = option;
                select.appendChild(optElement);
            }});
        }}

        async function loadWorkflows(append = false) {{
            try {{
                showLoading(!append);
                
                // Build query parameters
                const params = new URLSearchParams();
                
                // Handle search - look in both filename and tags
                if (currentFilters.search) {{
                    params.append('search', currentFilters.search);
                }}
                
                // Handle checkpoint filter via tags
                if (currentFilters.checkpoint) {{
                    params.append('tag', `checkpoint:${{currentFilters.checkpoint}}`);
                }}
                
                // Handle LoRA filter via tags  
                if (currentFilters.lora) {{
                    params.append('tag', `lora:${{currentFilters.lora}}`);
                }}
                
                // Handle node type filter
                if (currentFilters.nodeType) {{
                    params.append('node_type', currentFilters.nodeType);
                }}
                
                params.append('limit', currentFilters.limit);
                params.append('offset', currentFilters.offset);

                const response = await fetch(`${{API_BASE}}/workflows?${{params}}`);
                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                }}
                
                const data = await response.json();
                
                if (append) {{
                    currentWorkflows = currentWorkflows.concat(data.workflows);
                }} else {{
                    currentWorkflows = data.workflows;
                }}
                
                hasMore = data.has_more;
                
                renderWorkflows(append);
                updateWorkflowCount(data.total);
                
                hideLoading();
                
            }} catch (error) {{
                console.error('Error loading workflows:', error);
                showError(error.message);
            }}
        }}

        function resetAndReload() {{
            currentFilters.offset = 0;
            hasMore = true;
            loadWorkflows(false);
        }}

        function renderWorkflows(append = false) {{
            const grid = document.getElementById('workflow-grid');
            
            if (!append) {{
                grid.innerHTML = '';
            }}
            
            if (currentWorkflows.length === 0) {{
                showEmpty();
                return;
            }}
            
            const workflowsToRender = append ? 
                currentWorkflows.slice(currentFilters.offset) : 
                currentWorkflows;
            
            workflowsToRender.forEach(workflow => {{
                const workflowCard = createWorkflowCard(workflow);
                grid.appendChild(workflowCard);
            }});
            
            // Show/hide load more button
            const loadMoreContainer = document.getElementById('load-more-container');
            if (hasMore) {{
                loadMoreContainer.classList.remove('hidden');
            }} else {{
                loadMoreContainer.classList.add('hidden');
            }}
            
            grid.classList.remove('hidden');
        }}

        function createWorkflowCard(workflow) {{
            const div = document.createElement('div');
            div.className = 'workflow-card bg-white rounded-lg shadow-md overflow-hidden';
            
            const createdAt = workflow.created_at ? new Date(workflow.created_at).toLocaleDateString() : 'Unknown';
            
            // Separate tags by type
            const checkpointTags = workflow.tags.filter(tag => tag.startsWith('checkpoint:')).map(tag => tag.substring(11));
            const loraTags = workflow.tags.filter(tag => tag.startsWith('lora:')).map(tag => tag.substring(5));
            const otherTags = workflow.tags.filter(tag => !tag.startsWith('checkpoint:') && !tag.startsWith('lora:'));
            
            const checkpointTagsHtml = checkpointTags.map(tag => `<span class="tag checkpoint-tag">📁 ${{tag}}</span>`).join('');
            const loraTagsHtml = loraTags.map(tag => `<span class="tag lora-tag">🎯 ${{tag}}</span>`).join('');
            const otherTagsHtml = otherTags.map(tag => `<span class="tag">🏷️ ${{tag}}</span>`).join('');
            
            div.innerHTML = `
                ${{workflow.has_image ? 
                    `<div class="thumbnail-container">
                        <img src="${{API_BASE}}/workflows/${{workflow.id}}/thumbnail" alt="${{workflow.name}}" class="thumbnail" 
                             onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                        <div class="no-thumbnail" style="display: none;">🖼️</div>
                     </div>`
                    : '<div class="no-thumbnail">📄</div>'
                }}
                        
                <div class="p-4">
                    <h3 class="font-semibold text-lg text-gray-900 mb-2">${{workflow.name || workflow.filename || 'Untitled'}}</h3>
                    
                    ${{workflow.description ? 
                        `<p class="text-gray-600 text-sm mb-3">${{workflow.description}}</p>` 
                        : ''
                    }}
                    
                    <div class="flex items-center justify-between text-xs text-gray-500 mb-3">
                        <span>📊 ${{workflow.node_count || 0}} nodes</span>
                        <span>📅 ${{createdAt}}</span>
                    </div>
                    
                    ${{checkpointTagsHtml ? `<div class="mb-2">${{checkpointTagsHtml}}</div>` : ''}}
                    ${{loraTagsHtml ? `<div class="mb-2">${{loraTagsHtml}}</div>` : ''}}
                    ${{otherTagsHtml ? `<div class="mb-3">${{otherTagsHtml}}</div>` : ''}}
                    
                    <div class="flex space-x-2">
                        <button onclick="viewWorkflow('${{workflow.id}}')" 
                                class="flex-1 bg-blue-500 text-white px-3 py-2 rounded text-sm hover:bg-blue-600 transition-colors">
                            👁️ View Details
                        </button>
                        <button onclick="downloadWorkflow('${{workflow.id}}', '${{workflow.name || workflow.filename}}')" 
                                class="flex-1 bg-gray-500 text-white px-3 py-2 rounded text-sm hover:bg-gray-600 transition-colors">
                            📥 Download
                        </button>
                    </div>
                </div>
            `;
            
            return div;
        }}

        function updateWorkflowCount(total) {{
            document.getElementById('workflow-count').textContent = `${{total}} workflows`;
        }}

        function showLoading(show = true) {{
            document.getElementById('loading').classList.toggle('hidden', !show);
        }}

        function hideLoading() {{
            document.getElementById('loading').classList.add('hidden');
        }}

        function showError(message) {{
            hideLoading();
            document.getElementById('error-message').textContent = message;
            document.getElementById('error').classList.remove('hidden');
            document.getElementById('workflow-grid').classList.add('hidden');
        }}

        function showEmpty() {{
            document.getElementById('empty').classList.remove('hidden');
            document.getElementById('workflow-grid').classList.add('hidden');
        }}

        function viewWorkflow(workflowId) {{
            // Open detailed HTML page in new tab - much richer than modal
            window.open(`${{API_BASE.replace('/api', '')}}/workflows/${{workflowId}}`, '_blank');
        }}


        function downloadWorkflow(workflowId, filename) {{
            // Download workflow JSON
            const link = document.createElement('a');
            link.href = `${{API_BASE}}/workflows/${{workflowId}}/download`;
            link.download = `${{filename}}_workflow.json`;
            link.click();
        }}
    </script>
</body>
</html>'''

    return html_content


def generate_database_catalog_from_cli_args(args) -> int:
    """Generate database-powered catalog from command line arguments.
    
    This replaces the static HTML generation in workflow_catalog.py
    """
    
    # Set up output directory
    output_dir = Path(args.output_dir) if args.output_dir else Path("./catalogs")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate catalog HTML
    master_catalog_name = getattr(args, 'master_catalog', None) or "index.html"
    catalog_path = output_dir / master_catalog_name
    
    print(f"🚀 Generating database-powered catalog...")
    print(f"📁 Output: {catalog_path}")
    
    # Determine database URL
    database_url = None
    if hasattr(args, 'database') and args.database and args.database != True:
        database_url = args.database
    
    # Generate HTML content
    html_content = generate_database_powered_catalog_html(
        output_path=catalog_path,
        database_url=database_url,
        title="ComfyUI Workflow Light Table"
    )
    
    # Write to file
    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Database-powered catalog generated: {catalog_path}")
    print(f"💡 Start web server with: python web_interface.py")
    print(f"🌐 Then open: {catalog_path}")
    
    return 0


if __name__ == '__main__':
    # Test the catalog generator
    output_path = Path('./test_database_catalog.html')
    html = generate_database_powered_catalog_html(output_path)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
        
    print(f"Test catalog generated: {output_path}")
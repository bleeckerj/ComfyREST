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
                    "tags": [],  # Temporarily disabled - would require separate query
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
    """Serve the database-powered workflow catalog page."""
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
        <title>📚 Comfy Light Table - Workflow Catalog</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .workflow-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 1.5rem;
                padding: 0;
            }
            .workflow-card {
                break-inside: avoid;
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
                cursor: pointer;
                transition: all 0.2s ease;
            }
            .tag:hover {
                background: #d1d5db;
            }
            .tag.active {
                background: #3b82f6;
                color: white;
            }
            .loading-skeleton {
                animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
            }
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
                        <h1 class="text-2xl font-bold text-gray-900">📚 Workflow Catalog</h1>
                        <span id="workflow-count" class="bg-blue-100 text-blue-800 text-sm font-medium px-2.5 py-0.5 rounded">
                            Loading...
                        </span>
                    </div>
                    <div class="flex space-x-4">
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
                        
                        <!-- Tag Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">Tags:</label>
                            <select id="tag-filter" class="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                                <option value="">All Tags</option>
                            </select>
                        </div>
                        
                        <!-- Collection Filter -->
                        <div class="flex items-center space-x-2">
                            <label class="text-sm font-medium text-gray-700">Collections:</label>
                            <select id="collection-filter" class="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                                <option value="">All Collections</option>
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
            let currentWorkflows = [];
            let allTags = [];
            let allCollections = [];
            let currentFilters = {
                search: '',
                tag: '',
                collection: '',
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
                document.getElementById('tag-filter').addEventListener('change', function(e) {
                    currentFilters.tag = e.target.value;
                    resetAndReload();
                });

                document.getElementById('collection-filter').addEventListener('change', function(e) {
                    currentFilters.collection = e.target.value;
                    resetAndReload();
                });

                // Clear filters
                document.getElementById('clear-filters').addEventListener('click', function() {
                    document.getElementById('search-input').value = '';
                    document.getElementById('tag-filter').value = '';
                    document.getElementById('collection-filter').value = '';
                    currentFilters = {
                        search: '',
                        tag: '',
                        collection: '',
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
                    // Load tags
                    const tagsResponse = await fetch('/api/tags');
                    const tagsData = await tagsResponse.json();
                    allTags = tagsData.tags;
                    
                    const tagSelect = document.getElementById('tag-filter');
                    tagSelect.innerHTML = '<option value="">All Tags</option>';
                    allTags.forEach(tag => {
                        const option = document.createElement('option');
                        option.value = tag.name;
                        option.textContent = `${tag.name} (${tag.workflow_count})`;
                        tagSelect.appendChild(option);
                    });

                    // Load collections
                    const collectionsResponse = await fetch('/api/collections');
                    const collectionsData = await collectionsResponse.json();
                    allCollections = collectionsData.collections;
                    
                    const collectionSelect = document.getElementById('collection-filter');
                    collectionSelect.innerHTML = '<option value="">All Collections</option>';
                    allCollections.forEach(collection => {
                        const option = document.createElement('option');
                        option.value = collection.name;
                        option.textContent = `${collection.name} (${collection.workflow_count})`;
                        collectionSelect.appendChild(option);
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
                    if (currentFilters.tag) params.append('tag', currentFilters.tag);
                    if (currentFilters.collection) params.append('collection', currentFilters.collection);
                    params.append('limit', currentFilters.limit);
                    params.append('offset', currentFilters.offset);

                    console.log('Loading workflows with params:', params.toString());
                    
                    const response = await fetch(`/api/workflows?${params}`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }
                    
                    const data = await response.json();
                    console.log('Received workflows data:', data);
                    
                    if (append) {
                        currentWorkflows = currentWorkflows.concat(data.workflows);
                    } else {
                        currentWorkflows = data.workflows;
                    }
                    
                    hasMore = data.has_more;
                    
                    renderWorkflows(append);
                    updateWorkflowCount(data.total);
                    
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
                const tags = workflow.tags.map(tag => `<span class="tag">${tag}</span>`).join('');
                const collections = workflow.collections.map(collection => `<span class="tag">${collection}</span>`).join('');
                
                div.innerHTML = `
                    ${workflow.has_image ? 
                        `<div class="thumbnail-container">
                            <img src="${workflow.thumbnail_path}" alt="${workflow.name}" class="thumbnail" 
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
                        
                        ${tags ? `<div class="mb-3">${tags}</div>` : ''}
                        ${collections ? `<div class="mb-3">${collections}</div>` : ''}
                        
                        <div class="flex space-x-2">
                            <button onclick="viewWorkflow('${workflow.id}')" 
                                    class="flex-1 bg-blue-500 text-white px-3 py-2 rounded text-sm hover:bg-blue-600 transition-colors">
                                👁️ View
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

            async function viewWorkflow(workflowId) {
                try {
                    const response = await fetch(`/api/workflows/${workflowId}`);
                    const workflow = await response.json();
                    
                    // Create a modal or new window to show workflow details
                    const modal = document.createElement('div');
                    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4';
                    modal.onclick = (e) => {
                        if (e.target === modal) modal.remove();
                    };
                    
                    modal.innerHTML = `
                        <div class="bg-white rounded-lg max-w-4xl max-h-[90vh] overflow-auto">
                            <div class="p-6">
                                <div class="flex justify-between items-start mb-4">
                                    <h2 class="text-2xl font-bold text-gray-900">${workflow.name}</h2>
                                    <button onclick="this.closest('.fixed').remove()" class="text-gray-500 hover:text-gray-700 text-2xl">×</button>
                                </div>
                                
                                ${workflow.description ? `<p class="text-gray-600 mb-4">${workflow.description}</p>` : ''}
                                
                                <div class="grid grid-cols-2 gap-4 mb-4 text-sm">
                                    <div><strong>Filename:</strong> ${workflow.filename}</div>
                                    <div><strong>Nodes:</strong> ${workflow.node_count || 0}</div>
                                    <div><strong>Created:</strong> ${workflow.created_at ? new Date(workflow.created_at).toLocaleString() : 'Unknown'}</div>
                                    <div><strong>File Size:</strong> ${workflow.file_size ? Math.round(workflow.file_size / 1024) + ' KB' : 'Unknown'}</div>
                                </div>
                                
                                ${workflow.tags.length > 0 ? `
                                    <div class="mb-4">
                                        <strong class="block mb-2">Tags:</strong>
                                        ${workflow.tags.map(tag => `<span class="tag">${tag}</span>`).join('')}
                                    </div>
                                ` : ''}
                                
                                ${workflow.collections.length > 0 ? `
                                    <div class="mb-4">
                                        <strong class="block mb-2">Collections:</strong>
                                        ${workflow.collections.map(collection => `<span class="tag">${collection}</span>`).join('')}
                                    </div>
                                ` : ''}
                                
                                <div class="flex space-x-2">
                                    <button onclick="downloadWorkflow(${workflow.id}, '${workflow.name}')" 
                                            class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                                        📥 Download JSON
                                    </button>
                                    ${workflow.has_image ? `
                                        <button onclick="window.open('/api/workflows/${workflow.id}/thumbnail', '_blank')" 
                                                class="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600">
                                            🖼️ View Image
                                        </button>
                                    ` : ''}
                                </div>
                            </div>
                        </div>
                    `;
                    
                    document.body.appendChild(modal);
                    
                } catch (error) {
                    console.error('Error viewing workflow:', error);
                    alert('Error loading workflow details');
                }
            }

            async function downloadWorkflow(workflowId, workflowName) {
                try {
                    const response = await fetch(`/api/workflows/${workflowId}`);
                    const data = await response.json();
                    
                    if (data.workflow) {
                        const blob = new Blob([JSON.stringify(data.workflow, null, 2)], {
                            type: 'application/json'
                        });
                        
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `${workflowName.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.json`;
                        a.click();
                        URL.revokeObjectURL(url);
                    } else {
                        alert('Workflow JSON not available');
                    }
                    
                } catch (error) {
                    console.error('Error downloading workflow:', error);
                    alert('Error downloading workflow');
                }
            }

            function updateWorkflowCount(total) {
                document.getElementById('workflow-count').textContent = `${total} workflows`;
            }

            function showLoading(show = true) {
                const loading = document.getElementById('loading');
                const error = document.getElementById('error');
                const empty = document.getElementById('empty');
                const grid = document.getElementById('workflow-grid');
                
                if (show) {
                    loading.classList.remove('hidden');
                    error.classList.add('hidden');
                    empty.classList.add('hidden');
                    grid.classList.add('hidden');
                }
            }

            function hideLoading() {
                document.getElementById('loading').classList.add('hidden');
            }

            function showError(message) {
                hideLoading();
                document.getElementById('error-message').textContent = message;
                document.getElementById('error').classList.remove('hidden');
                document.getElementById('empty').classList.add('hidden');
                document.getElementById('workflow-grid').classList.add('hidden');
            }

            function showEmpty() {
                hideLoading();
                document.getElementById('empty').classList.remove('hidden');
                document.getElementById('error').classList.add('hidden');
                document.getElementById('workflow-grid').classList.add('hidden');
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
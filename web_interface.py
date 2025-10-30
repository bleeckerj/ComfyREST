#!/usr/bin/env python3
"""
ComfyREST Web Interface

A web-based drag-and-drop interface for processing ComfyUI workflows from images and JSON files.
Features real-time processing, interactive visualization, and batch operations.
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
from fastapi.responses import HTMLResponse, JSONResponse
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

app = FastAPI(
    title="ComfyREST Web Interface",
    description="Drag-and-drop workflow processing for ComfyUI",
    version="1.0.0"
)

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
    <title>ComfyREST Web Interface</title>
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
        <header class="text-center mb-12">
            <h1 class="text-5xl font-bold text-gray-900 mb-4">
                🚀 ComfyREST Web Interface
            </h1>
            <p class="text-xl text-gray-600 max-w-2xl mx-auto">
                Drag and drop your ComfyUI images or workflow JSON files to extract, analyze, and visualize workflows instantly
            </p>
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
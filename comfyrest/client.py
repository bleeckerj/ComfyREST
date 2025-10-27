"""ComfyClient: helpers to discover and call ComfyUI REST endpoints."""
from __future__ import annotations

import requests
from typing import Dict, Any, Optional
import time
import json
import uuid


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def probe_root(self) -> Dict[str, Any]:
        """Try GET / and return parsed JSON or text.

        If the request fails (ConnectionError, timeout, etc.) return a dict
        containing an `error` key so callers can continue.
        """
        url = f"{self.base_url}/"
        try:
            resp = requests.get(url, timeout=self.timeout)
            try:
                return resp.json()
            except Exception:
                return {"status_code": resp.status_code, "text": resp.text}
        except requests.RequestException as e:
            return {"error": str(e)}

    def list_routes(self) -> Dict[str, Any]:
        """Try to discover routes via common endpoints.

        ComfyUI may expose /openapi.json or /swagger.json or /routes. This
        function checks common places and returns a dict of endpoint -> data.
        """
        candidates = ["/openapi.json", "/swagger.json", "/api/docs/openapi.json", "/routes", "/v1/openapi.json"]
        found = {}
        for path in candidates:
            url = f"{self.base_url}{path}"
            try:
                r = requests.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    try:
                        found[path] = r.json()
                    except Exception:
                        found[path] = {"status_code": r.status_code, "text": r.text}
            except requests.RequestException as e:
                # record that the candidate failed to be reached; don't raise
                found[path] = {"error": str(e)}
        return found

    def get(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        return requests.get(url, timeout=self.timeout, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        return requests.post(url, timeout=self.timeout, **kwargs)

    # Comfy-specific helpers
    def post_prompt(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """POST a workflow to /prompt and return parsed JSON result or error dict.
        
        The workflow should be in API format (node IDs as keys with class_type and inputs).
        This method wraps it in the required {"prompt": workflow} payload format.
        """
        try:
            payload = {"prompt": workflow}
            r = self.post("/prompt", json=payload)
            try:
                return r.json()
            except Exception:
                return {"status_code": r.status_code, "text": r.text}
        except requests.RequestException as e:
            return {"error": str(e)}

    def get_history(self, prompt_id: Optional[str] = None) -> Dict[str, Any]:
        """GET /history or /history/{prompt_id} to fetch run state info."""
        path = "/history"
        if prompt_id:
            path = f"/history/{prompt_id}"
        try:
            r = self.get(path)
            try:
                return r.json()
            except Exception:
                return {"status_code": r.status_code, "text": r.text}
        except requests.RequestException as e:
            return {"error": str(e)}

    def wait_for_prompt(self, prompt_id: str, timeout: int = 60, poll_interval: float = 1.0) -> Dict[str, Any]:
        """Poll history for the prompt_id until it finishes or timeout (seconds).

        Returns the final history entry or an error dict if timed out.
        """
        start = time.time()
        last_status = None
        
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                return {"error": "timeout", "prompt_id": prompt_id, "elapsed": elapsed}
                
            h = self.get_history(prompt_id)
            
            if isinstance(h, dict) and "error" in h:
                return h
                
            # Check if we got history data
            if h and isinstance(h, dict) and prompt_id in h:
                prompt_data = h[prompt_id]
                
                # Check for completion or error status
                status = prompt_data.get("status", {})
                
                if status != last_status:
                    print(f"🔄 Status update: {status}")
                    last_status = status
                
                # If we have status info, check for completion
                if isinstance(status, dict):
                    if status.get("completed") or "outputs" in prompt_data:
                        print("✅ Workflow completed")
                        return {"status": "completed", **prompt_data}
                    elif "error" in status:
                        print(f"❌ Workflow failed: {status['error']}")
                        return {"status": "error", **prompt_data}
                        
            elif h:
                # Fallback: if we got any history data, assume completion
                print(f"📊 Got history data (assuming completion): {type(h)}")
                return {"status": "unknown", "data": h}
                
            time.sleep(poll_interval)

    def get_object_info(self) -> Dict[str, Any]:
        """Fetch /object_info which returns metadata for available node classes."""
        try:
            r = self.get("/object_info")
            try:
                return r.json()
            except Exception:
                return {"status_code": r.status_code, "text": r.text}
        except requests.RequestException as e:
            return {"error": str(e)}

    def wait_for_prompt_with_ws(self, prompt_id: str, timeout: int = 300) -> Dict[str, Any]:
        """Wait for prompt completion with WebSocket real-time updates."""
        try:
            import websocket
        except ImportError:
            print("⚠ websocket-client not installed, falling back to polling")
            return self.wait_for_prompt(prompt_id, timeout)
        
        # Generate client_id for WebSocket connection
        client_id = str(uuid.uuid4())
        ws_url = f"ws://{self.base_url.split('://', 1)[1]}/ws?clientId={client_id}"
        
        result = {"status": "unknown", "outputs": {}}
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                
                # Debug: show important message types (filter out frequent monitor messages)
                if msg_type not in ['crystools.monitor']:
                    print(f"🔍 WebSocket message: {msg_type} - {data}")
                
                if msg_type == "progress":
                    progress_data = data.get("data", {})
                    node = progress_data.get("node")
                    value = progress_data.get("value", 0)
                    max_val = progress_data.get("max", 100)
                    print(f"⏳ Node {node}: {value}/{max_val}")
                    
                elif msg_type == "executing":
                    exec_data = data.get("data", {})
                    node = exec_data.get("node")
                    prompt_id_from_msg = exec_data.get("prompt_id")
                    
                    # Only process messages for our specific prompt
                    if prompt_id_from_msg == prompt_id:
                        if node:
                            print(f"🔄 Executing node {node}")
                        else:
                            # This is the definitive completion signal from ComfyUI
                            print("✅ Execution finished (node=null)")
                            # Set status first to break the waiting loop
                            result["status"] = "completed"
                            # Get final results
                            history = self.get_history(prompt_id)
                            if history:
                                result.update(history)
                            ws.close()
                            
                elif msg_type == "status":
                    status_data = data.get("data", {})
                    exec_info = status_data.get("status", {}).get("exec_info", {})
                    queue_remaining = exec_info.get("queue_remaining", 1)
                    
                    print(f"📊 Status: queue_remaining={queue_remaining}")
                    
                    # Fallback completion detection for cached workflows
                    if queue_remaining == 0 and result["status"] == "unknown":
                        print("📊 Queue empty - assuming workflow completed")
                        result["status"] = "completed"
                        try:
                            history = self.get_history(prompt_id)
                            if history:
                                result.update(history)
                        except:
                            pass
                        print("✅ Workflow completed (detected via empty queue)")
                        ws.close()
                        
                # We don't use execution_success or status messages for completion detection
                # Only the executing message with node=None is reliable
                    
                elif msg_type == "execution_error":
                    error_data = data.get("data", {})
                    print(f"❌ Execution error: {error_data}")
                    # Set status first to break the waiting loop
                    result["status"] = "error"
                    result["error"] = error_data
                    ws.close()
                    
                elif msg_type == "progress_state":
                    # Show progress but don't use it to determine completion
                    progress_data = data.get("data", {})
                    nodes = progress_data.get("nodes", {})
                    for node_id, node_info in nodes.items():
                        state = node_info.get("state")
                        if state == "failed":
                            print(f"❌ Node {node_id} failed: {node_info}")
                            # Set status first to break the waiting loop
                            result["status"] = "error" 
                            result["error"] = f"Node {node_id} failed: {node_info}"
                            ws.close()
                            return
                        elif state == "finished":
                            print(f"✅ Node {node_id} completed")
                        elif state == "executing":
                            print(f"🔄 Node {node_id} executing...")
                    
                    # DON'T close based on progress_state - wait for definitive completion messages
                    
            except Exception as e:
                print(f"WebSocket message error: {e}")
        
        def on_error(ws, error):
            print(f"WebSocket error: {error}")
            result["status"] = "error"
            result["error"] = str(error)
        
        def on_close(ws, close_status_code, close_msg):
            if result["status"] == "unknown":
                print("WebSocket closed before completion")
                result["status"] = "timeout"
        
        try:
            ws = websocket.WebSocketApp(ws_url,
                                      on_message=on_message,
                                      on_error=on_error,
                                      on_close=on_close)
            
            # Start WebSocket in a thread and wait for completion
            import threading
            ws_thread = threading.Thread(target=ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
            
            # Wait for completion or timeout
            start_time = time.time()
            while result["status"] == "unknown" and (time.time() - start_time) < timeout:
                time.sleep(0.1)
            
            if result["status"] == "unknown":
                result["status"] = "timeout"
                ws.close()
            
            return result
            
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            return self.wait_for_prompt(prompt_id, timeout)


def update_workflow_node(workflow: Dict[str, Any], node_id: Optional[str] = None, node_type: Optional[str] = None, updates: Dict[str, Any] = None) -> Dict[str, Any]:
    """Return a new workflow dict with updates applied to matching node(s).

    - If node_id is provided, it targets the node with that id.
    - Otherwise node_type (class name) can be used to match nodes by type.
    - updates is a dict of keys to set inside the node's parameters (shape depends on workflow format).

    This function attempts to be conservative and only updates keys present in the node's data.
    """
    if updates is None:
        updates = {}
    wf = workflow.copy()
    # workflows typically have a top-level 'nodes' dict or list depending on export format.
    nodes = None
    if isinstance(wf, dict) and "nodes" in wf:
        nodes = wf["nodes"]
    elif isinstance(wf, dict) and "graph" in wf and "nodes" in wf["graph"]:
        nodes = wf["graph"]["nodes"]

    if nodes is None:
        return wf

    # nodes may be a dict keyed by id, or a list of node objects
    if isinstance(nodes, dict):
        for nid, node in nodes.items():
            if node_id and nid != node_id:
                continue
            if node_type and node.get("type") != node_type and node.get("class") != node_type:
                continue
            # apply updates to node['params'] if present, else merge at top-level
            if "params" in node and isinstance(node["params"], dict):
                node["params"].update(updates)
            else:
                node.update(updates)
            nodes[nid] = node
    elif isinstance(nodes, list):
        for i, node in enumerate(nodes):
            if node_id and str(node.get("id")) != str(node_id):
                continue
            if node_type and node.get("type") != node_type and node.get("class") != node_type:
                continue
            if "params" in node and isinstance(node["params"], dict):
                node["params"].update(updates)
            else:
                node.update(updates)
            nodes[i] = node

    # write back
    if "nodes" in wf:
        wf["nodes"] = nodes
    elif "graph" in wf and "nodes" in wf["graph"]:
        wf["graph"]["nodes"] = nodes

    return wf


def discover_all(base_url: str = "http://127.0.0.1:8188") -> Dict[str, Any]:
    c = ComfyClient(base_url)
    results = {"root": c.probe_root(), "candidates": c.list_routes()}
    return results

    def discover_comfy(self) -> Dict[str, Any]:
        """Probe the standard ComfyUI endpoints and return a dict of results.

        This method checks the endpoints used by Comfy as discovered in the
        main ComfyUI server implementation (server.py) and returns their
        responses or error messages.
        """
        endpoints = {
            "/ws": "websocket",
            "/": "root",
            "/embeddings": "list",
            "/models": "list",
            "/models/{folder}": "list_files",
            "/extensions": "list",
            "/upload/image": "upload",
            "/upload/mask": "upload",
            "/view": "view",
            "/view_metadata/{folder_name}": "view_meta",
            "/system_stats": "stats",
            "/features": "features",
            "/prompt": "prompt",
            "/queue": "queue",
            "/interrupt": "interrupt",
            "/free": "free",
            "/history": "history",
            "/object_info": "object_info",
        }

        out = {}
        for path, kind in endpoints.items():
            # for templated paths, probe a sensible example where possible
            url_path = path
            if "{folder}" in path:
                url_path = path.replace("{folder}", "checkpoints")
            if "{folder_name}" in path:
                url_path = path.replace("{folder_name}", "checkpoints")

            try:
                if kind == "websocket":
                    out[url_path] = {"note": "websocket endpoint"}
                elif kind in ("upload",):
                    out[url_path] = {"note": "POST multipart/form-data expected"}
                else:
                    r = self.get(url_path)
                    try:
                        out[url_path] = r.json()
                    except Exception:
                        out[url_path] = {"status_code": r.status_code, "text": r.text}
            except requests.RequestException as e:
                out[url_path] = {"error": str(e)}

        return out

    def upload_image(self, image_path: str, subfolder: str = "", overwrite: bool = False) -> Dict[str, Any]:
        """Upload an image file to ComfyUI's input directory.
        
        Args:
            image_path: Path to local image file
            subfolder: Optional subfolder in input directory  
            overwrite: Whether to overwrite existing files
            
        Returns:
            Response from upload endpoint containing filename
        """
        import os
        from pathlib import Path
        
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
            
        url = f"{self.base_url}/upload/image"
        
        # Prepare multipart form data
        with open(image_path, 'rb') as f:
            files = {
                'image': (Path(image_path).name, f, 'image/png')
            }
            data = {
                'subfolder': subfolder,
                'overwrite': str(overwrite).lower()
            }
            
            response = requests.post(url, files=files, data=data, timeout=30)
            response.raise_for_status()
            return response.json()


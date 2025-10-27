"""ComfyClient: helpers to discover and call ComfyUI REST endpoints."""
from __future__ import annotations

import requests
from typing import Dict, Any, Optional


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def probe_root(self) -> Dict[str, Any]:
        """Try GET / and return parsed JSON or text."""
        url = f"{self.base_url}/"
        resp = requests.get(url, timeout=self.timeout)
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}

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
            except requests.RequestException:
                continue
        return found

    def get(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        return requests.get(url, timeout=self.timeout, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        return requests.post(url, timeout=self.timeout, **kwargs)


def discover_all(base_url: str = "http://127.0.0.1:8188") -> Dict[str, Any]:
    c = ComfyClient(base_url)
    results = {"root": c.probe_root(), "candidates": c.list_routes()}
    return results

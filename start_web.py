#!/usr/bin/env python3
"""
ComfyREST Web Interface Launcher

Checks dependencies and starts the web interface server.
"""

import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed."""
    required_packages = [
        'fastapi',
        'uvicorn',
        'websockets',
        'multipart'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print("❌ Missing required dependencies:")
        for pkg in missing:
            print(f"   - {pkg}")
        print("\n📦 Install with:")
        print("   pip install -r web_requirements.txt")
        print("   # OR")
        print("   pip install fastapi uvicorn[standard] websockets python-multipart")
        return False
    
    return True

def main():
    print("🚀 ComfyREST Web Interface Launcher")
    print("=" * 40)
    
    # Check if we're in the right directory
    if not Path("scripts/workflow_catalog.py").exists():
        print("❌ Please run from the ComfyREST root directory")
        sys.exit(1)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    print("✅ All dependencies found")
    print("🌐 Starting web server...")
    print("   URL: http://localhost:8080")
    print("   Press Ctrl+C to stop")
    print("")
    
    # Start the web interface
    try:
        import uvicorn
        uvicorn.run(
            "web_interface:app",
            host="0.0.0.0",
            port=8080,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
    except Exception as e:
        print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
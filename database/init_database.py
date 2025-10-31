#!/usr/bin/env python3
"""
ComfyREST Light Table Database Initialization
=============================================

Initialize the database for the ComfyREST Light Table with proper schema and default data.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# Add the project root to the path so we can import our modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from .database import initialize_database, get_database_manager, WorkflowFileManager
from .models import Base
import subprocess


def run_alembic_upgrade():
    """Run Alembic migrations to upgrade database to latest schema."""
    try:
        print("🔄 Running Alembic migrations...")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Database schema updated successfully")
            if result.stdout:
                print(f"   Alembic output: {result.stdout.strip()}")
        else:
            print(f"❌ Alembic migration failed: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("❌ Alembic not found. Please install with: pip install alembic")
        return False
    except Exception as e:
        print(f"❌ Error running migrations: {e}")
        return False
    
    return True


def check_database_exists(database_url: str) -> bool:
    """Check if the database file exists (for SQLite)."""
    if database_url.startswith('sqlite:///'):
        db_path = database_url.replace('sqlite:///', '')
        return Path(db_path).exists()
    return True  # For other databases, assume they exist


def initialize_fresh_database(database_url: Optional[str] = None, force: bool = False):
    """Initialize a fresh database with schema and default data."""
    
    # Check if database already exists
    database_dir = Path(__file__).parent
    final_db_url = database_url or f"sqlite:///{database_dir}/comfy_light_table.db"
    
    if not force and check_database_exists(final_db_url):
        print(f"⚠️ Database already exists: {final_db_url}")
        print("   Use --force to recreate or --upgrade to run migrations")
        return False
    
    if force:
        print("🗑️ Force mode: Recreating database...")
        # Remove existing SQLite database
        if final_db_url.startswith('sqlite:///'):
            db_path = Path(final_db_url.replace('sqlite:///', ''))
            if db_path.exists():
                db_path.unlink()
                print(f"   Removed existing database: {db_path}")
    
    print(f"🚀 Initializing ComfyREST Light Table database: {final_db_url}")
    
    # Initialize database manager
    try:
        db_manager = initialize_database(final_db_url, create_tables=True)
        print("✅ Database initialized successfully!")
        
        # Test basic operations
        workflow_manager = WorkflowFileManager(db_manager)
        stats = workflow_manager.get_workflow_stats()
        print(f"📊 Database ready - {stats['total_workflows']} workflows, {stats['total_tags']} tags, {stats['total_collections']} collections")
        
        return True
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return False


def upgrade_existing_database(database_url: Optional[str] = None):
    """Upgrade existing database using Alembic migrations."""
    database_dir = Path(__file__).parent
    final_db_url = database_url or f"sqlite:///{database_dir}/comfy_light_table.db"
    
    print(f"🔄 Upgrading database: {final_db_url}")
    
    if not check_database_exists(final_db_url):
        print("❌ Database does not exist. Use --init to create a new database.")
        return False
    
    # Run Alembic upgrade
    if not run_alembic_upgrade():
        return False
    
    # Test connection and get stats
    try:
        db_manager = initialize_database(final_db_url, create_tables=False)
        workflow_manager = WorkflowFileManager(db_manager)
        stats = workflow_manager.get_workflow_stats()
        print(f"✅ Database upgraded successfully!")
        print(f"📊 Current state - {stats['total_workflows']} workflows, {stats['total_tags']} tags, {stats['total_collections']} collections")
        
        db_manager.close()
        return True
        
    except Exception as e:
        print(f"❌ Database connection test failed: {e}")
        return False


def check_database_status(database_url: Optional[str] = None):
    """Check the current status of the database."""
    database_dir = Path(__file__).parent
    final_db_url = database_url or f"sqlite:///{database_dir}/comfy_light_table.db"
    
    print(f"🔍 Checking database status: {final_db_url}")
    
    if not check_database_exists(final_db_url):
        print("❌ Database does not exist")
        print("   Use --init to create a new database")
        return False
    
    try:
        db_manager = initialize_database(final_db_url, create_tables=False)
        workflow_manager = WorkflowFileManager(db_manager)
        stats = workflow_manager.get_workflow_stats()
        
        print("✅ Database is accessible")
        print(f"📊 Statistics:")
        print(f"   Workflows: {stats['total_workflows']}")
        print(f"   Tags: {stats['total_tags']}")
        print(f"   Collections: {stats['total_collections']}")
        print(f"   Total Nodes: {stats['total_nodes']}")
        print(f"   Total Connections: {stats['total_connections']}")
        
        if stats['common_node_types']:
            print(f"   Common Node Types:")
            for node_type, count in list(stats['common_node_types'].items())[:5]:
                print(f"     {node_type}: {count}")
        
        db_manager.close()
        return True
        
    except Exception as e:
        print(f"❌ Database access failed: {e}")
        print("   The database may be corrupted or incompatible")
        return False


def main():
    """Main CLI interface for database initialization."""
    parser = argparse.ArgumentParser(
        description="Initialize ComfyREST Light Table database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize new database (SQLite)
  python -m database.init_database --init
  
  # Initialize with custom database URL
  python -m database.init_database --init --database "postgresql://user:pass@localhost/comfyrest"
  
  # Force recreate existing database
  python -m database.init_database --init --force
  
  # Upgrade existing database with migrations
  python -m database.init_database --upgrade
  
  # Check database status
  python -m database.init_database --status
        """
    )
    
    parser.add_argument('--init', action='store_true', 
                       help='Initialize a new database')
    parser.add_argument('--upgrade', action='store_true',
                       help='Upgrade existing database using migrations')
    parser.add_argument('--status', action='store_true',
                       help='Check database status and statistics')
    parser.add_argument('--database', '--db',
                       help='Database URL (default: sqlite:///database/comfy_light_table.db)')
    parser.add_argument('--force', action='store_true',
                       help='Force recreate database if it exists')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not any([args.init, args.upgrade, args.status]):
        parser.error("Must specify one of: --init, --upgrade, or --status")
    
    if sum([args.init, args.upgrade, args.status]) > 1:
        parser.error("Can only specify one operation at a time")
    
    # Execute requested operation
    success = False
    
    if args.init:
        success = initialize_fresh_database(args.database, args.force)
    elif args.upgrade:
        success = upgrade_existing_database(args.database)
    elif args.status:
        success = check_database_status(args.database)
    
    if success:
        print("\n🎉 Operation completed successfully!")
        return 0
    else:
        print("\n💥 Operation failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
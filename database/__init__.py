"""
ComfyREST Database Package
=========================

Database models, management, and utilities for the ComfyREST Light Table.

This package provides:
- SQLAlchemy models for workflow metadata
- Database connection and session management
- Incremental ingestion system for workflow directories
- Database initialization and migration utilities
"""

from .models import Base, WorkflowFile, Tag, Collection, WorkflowExecution, SearchIndex, AppSettings
from .database import (
    DatabaseManager, WorkflowFileManager, 
    initialize_database, get_database_manager
)

__all__ = [
    # Models
    'Base', 'WorkflowFile', 'Tag', 'Collection', 'WorkflowExecution', 'SearchIndex', 'AppSettings',
    
    # Database Management
    'DatabaseManager', 'WorkflowFileManager', 
    'initialize_database', 'get_database_manager'
]
"""
ComfyREST Light Table Database Schema
====================================

SQLAlchemy models for metadata management, tagging, and workflow organization.
"""

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON, Boolean, 
    ForeignKey, Table, Index, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

# Many-to-many association tables
file_tags = Table(
    'file_tags',
    Base.metadata,
    Column('file_id', String, ForeignKey('workflow_files.id')),
    Column('tag_id', String, ForeignKey('tags.id'))
)

file_collections = Table(
    'file_collections', 
    Base.metadata,
    Column('file_id', String, ForeignKey('workflow_files.id')),
    Column('collection_id', String, ForeignKey('collections.id'))
)

file_clients = Table(
    'file_clients',
    Base.metadata,
    Column('file_id', String, ForeignKey('workflow_files.id')),
    Column('client_id', String, ForeignKey('clients.id'))
)

file_projects = Table(
    'file_projects',
    Base.metadata,
    Column('file_id', String, ForeignKey('workflow_files.id')),
    Column('project_id', String, ForeignKey('projects.id'))
)


class WorkflowFile(Base):
    """Main file record with extracted workflow and metadata."""
    __tablename__ = "workflow_files"
    
    # Primary data
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    file_path = Column(String, unique=True, index=True)
    filename = Column(String, index=True)
    file_hash = Column(String, index=True)  # For duplicate detection
    file_size = Column(Integer)
    file_modified_at = Column(DateTime, index=True)  # Actual file modification time
    
    # Workflow data
    workflow_data = Column(JSON)  # Complete extracted workflow
    node_count = Column(Integer, index=True)
    connection_count = Column(Integer)
    node_types = Column(JSON)  # Array of unique node types used
    
    # Image metadata
    image_width = Column(Integer)
    image_height = Column(Integer)
    image_format = Column(String)
    
    # User-added metadata
    notes = Column(Text)
    rating = Column(Integer)  # 1-5 stars
    is_favorite = Column(Boolean, default=False, index=True)
    is_archived = Column(Boolean, default=False, index=True)
    
    # Workflow metadata
    deliverable_type = Column(String)  # "concept", "final", "revision", "presentation", etc.
    version = Column(String)  # Version number or identifier
    status = Column(String, index=True)  # "draft", "review", "approved", "delivered", etc.
    
    # Visual analysis results (populated by AI)
    visual_description = Column(Text)  # AI-generated description
    detected_objects = Column(JSON)    # ["person", "landscape", "building"]
    color_palette = Column(JSON)       # Dominant colors
    style_tags = Column(JSON)          # ["photorealistic", "anime", "abstract"]
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_accessed = Column(DateTime)
    
    # Relationships
    tags = relationship("Tag", secondary=file_tags, back_populates="files")
    collections = relationship("Collection", secondary=file_collections, back_populates="files")
    clients = relationship("Client", secondary=file_clients, back_populates="files")
    projects = relationship("Project", secondary=file_projects, back_populates="files")
    executions = relationship("WorkflowExecution", back_populates="source_file")


class Tag(Base):
    """User-defined tags for organizing files."""
    __tablename__ = "tags"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, index=True)
    color = Column(String)  # Hex color for UI
    description = Column(Text)
    
    # Auto vs manual tagging
    is_auto_generated = Column(Boolean, default=False)
    confidence_score = Column(Float)  # For AI-generated tags
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    files = relationship("WorkflowFile", secondary=file_tags, back_populates="tags")


class Collection(Base):
    """User-defined collections/projects."""
    __tablename__ = "collections"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    description = Column(Text)
    color = Column(String)
    
    # Collection metadata
    is_system = Column(Boolean, default=False)  # Built-in collections like "Favorites"
    sort_order = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    files = relationship("WorkflowFile", secondary=file_collections, back_populates="collections")


class Client(Base):
    """Client organizations for workflow management."""
    __tablename__ = "clients"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, index=True)  # Client/Organization name
    description = Column(Text)
    contact_email = Column(String)
    contact_phone = Column(String)
    address = Column(Text)
    
    # Client metadata
    client_code = Column(String, unique=True, index=True)  # Short code like "ACME", "NIKE"
    industry = Column(String)  # "Fashion", "Tech", "Healthcare", etc.
    is_active = Column(Boolean, default=True, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    files = relationship("WorkflowFile", secondary=file_clients, back_populates="clients")
    projects = relationship("Project", back_populates="client")


class Project(Base):
    """Projects for organizing workflows."""
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)  # Project name
    description = Column(Text)
    project_code = Column(String, unique=True, index=True)  # Unique project identifier
    
    # Project details
    client_id = Column(String, ForeignKey('clients.id'), index=True)  # Primary client
    start_date = Column(DateTime)
    deadline = Column(DateTime)
    budget = Column(Float)
    status = Column(String, index=True)  # "planning", "active", "review", "completed", "cancelled"
    priority = Column(String)  # "low", "medium", "high", "urgent"
    
    # Project metadata
    project_type = Column(String)  # "campaign", "product", "event", "brand", etc.
    deliverable_format = Column(String)  # "digital", "print", "video", "mixed"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    client = relationship("Client", back_populates="projects")
    files = relationship("WorkflowFile", secondary=file_projects, back_populates="projects")


class WorkflowExecution(Base):
    """Record of workflow executions from Light Table."""
    __tablename__ = "workflow_executions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_file_id = Column(String, ForeignKey('workflow_files.id'))
    
    # Execution details
    comfy_server_url = Column(String)
    prompt_id = Column(String)  # ComfyUI prompt ID
    status = Column(String, index=True)  # pending, running, completed, failed
    
    # Parameter overrides used
    parameter_overrides = Column(JSON)
    
    # Results
    output_files = Column(JSON)  # Generated image paths
    execution_time = Column(Float)  # Seconds
    error_message = Column(Text)
    
    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)
    
    # Relationships
    source_file = relationship("WorkflowFile", back_populates="executions")


class SearchIndex(Base):
    """Full-text search index for fast searching."""
    __tablename__ = "search_index"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(String, ForeignKey('workflow_files.id'), index=True)
    
    # Searchable content
    searchable_text = Column(Text)  # Combined: filename, notes, tags, node types
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSettings(Base):
    """Application configuration and user preferences."""
    __tablename__ = "app_settings"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String, unique=True, index=True)
    value = Column(JSON)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Indices for performance
Index('idx_files_created_rating', WorkflowFile.created_at, WorkflowFile.rating)
Index('idx_files_node_count', WorkflowFile.node_count)
Index('idx_executions_status_started', WorkflowExecution.status, WorkflowExecution.started_at)
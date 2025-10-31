"""
ComfyREST Database Setup and Management
======================================

Database initialization, session management, and utility functions for the Light Table.
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.pool import StaticPool

from .models import Base, WorkflowFile, Tag, Collection, WorkflowExecution, SearchIndex, AppSettings


class DatabaseManager:
    """Manages database connection, sessions, and operations."""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize database manager.
        
        Args:
            database_url: SQLAlchemy database URL. If None, uses SQLite in project directory.
        """
        if database_url is None:
            # Default to SQLite database in project directory
            project_root = Path(__file__).parent.parent  # Go up one level to project root
            db_path = project_root / "comfy_light_table.db"
            database_url = f"sqlite:///{db_path}"
        
        self.database_url = database_url
        
        # Configure engine based on database type
        if database_url.startswith('sqlite'):
            # SQLite-specific configuration
            self.engine = create_engine(
                database_url,
                echo=False,  # Set to True for SQL debugging
                connect_args={
                    "check_same_thread": False,  # Allow multiple threads
                    "timeout": 30  # 30 second timeout
                },
                poolclass=StaticPool,  # Use static pool for SQLite
            )
            
            # Enable WAL mode for better concurrency
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA cache_size=10000")
                cursor.execute("PRAGMA temp_store=MEMORY")
                cursor.close()
        else:
            # PostgreSQL/MySQL configuration
            self.engine = create_engine(
                database_url,
                echo=False,
                pool_size=10,
                max_overflow=20,
                pool_recycle=3600,  # Recycle connections after 1 hour
            )
        
        # Create session factory
        self.SessionLocal = scoped_session(sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        ))
    
    def create_tables(self):
        """Create all database tables."""
        print("🗄️ Creating database tables...")
        Base.metadata.create_all(bind=self.engine)
        
        # Create default collections
        with self.get_session() as session:
            self._create_default_collections(session)
            session.commit()
        
        print("✅ Database tables created successfully")
    
    def _create_default_collections(self, session: Session):
        """Create default system collections."""
        default_collections = [
            {"name": "Favorites", "description": "Your favorite workflows", "color": "#ef4444", "is_system": True, "sort_order": 1},
            {"name": "Archived", "description": "Archived workflows", "color": "#6b7280", "is_system": True, "sort_order": 2},
            {"name": "Recent", "description": "Recently added workflows", "color": "#3b82f6", "is_system": True, "sort_order": 3},
        ]
        
        for collection_data in default_collections:
            existing = session.query(Collection).filter_by(name=collection_data["name"], is_system=True).first()
            if not existing:
                collection = Collection(**collection_data)
                session.add(collection)
        
        # Create default app settings
        default_settings = {
            "version": "1.0.0",
            "auto_tag_enabled": True,
            "image_analysis_enabled": True,
            "thumbnail_size": 256,
            "cards_per_page": 50,
            "default_sort": "created_at",
            "default_order": "desc"
        }
        
        for key, value in default_settings.items():
            existing = session.query(AppSettings).filter_by(key=key).first()
            if not existing:
                setting = AppSettings(key=key, value=value)
                session.add(setting)
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get a database session with automatic cleanup."""
        session = self.SessionLocal()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def close(self):
        """Close database connections."""
        self.SessionLocal.remove()
        self.engine.dispose()


class WorkflowFileManager:
    """Manages workflow file operations with database integration."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def add_workflow_file(self, file_path: Path, workflow_data: Dict, 
                         image_metadata: Dict = None, notes: str = None, 
                         tags: List[str] = None, collections: List[str] = None,
                         auto_analyze: bool = True) -> WorkflowFile:
        """Add a new workflow file to the database.
        
        Args:
            file_path: Path to the workflow file
            workflow_data: Extracted ComfyUI workflow data
            image_metadata: Image metadata (dimensions, format, etc.)
            notes: User notes
            tags: List of tag names to associate
            collections: List of collection names to associate
            auto_analyze: Whether to perform automatic analysis
        
        Returns:
            Created WorkflowFile instance
        """
        with self.db.get_session() as session:
            # Check if file already exists
            existing = session.query(WorkflowFile).filter_by(file_path=str(file_path)).first()
            if existing:
                print(f"⚠️ File already exists in database: {file_path.name}")
                return existing
            
            # Calculate file hash for duplicate detection
            file_hash = self._calculate_file_hash(file_path)
            
            # Check for duplicate by hash
            duplicate = session.query(WorkflowFile).filter_by(file_hash=file_hash).first()
            if duplicate:
                print(f"⚠️ Duplicate file detected (hash match): {file_path.name} matches {duplicate.filename}")
                # Could create a relationship or skip - for now we'll add it anyway but note the duplicate
            
            # Extract workflow analysis
            workflow_analysis = self._analyze_workflow(workflow_data)
            
            # Create WorkflowFile instance (always use absolute paths)
            workflow_file = WorkflowFile(
                file_path=str(file_path.resolve()),
                filename=file_path.name,
                file_hash=file_hash,
                file_size=file_path.stat().st_size if file_path.exists() else 0,
                workflow_data=workflow_data,
                node_count=workflow_analysis.get('node_count', 0),
                connection_count=workflow_analysis.get('connection_count', 0),
                node_types=workflow_analysis.get('node_types', []),
                notes=notes
            )
            
            # Add image metadata if provided
            if image_metadata:
                workflow_file.image_width = image_metadata.get('width')
                workflow_file.image_height = image_metadata.get('height')
                workflow_file.image_format = image_metadata.get('format')
            
            # Perform automatic analysis if enabled
            if auto_analyze:
                self._auto_analyze_workflow(workflow_file, workflow_data)
            
            session.add(workflow_file)
            session.flush()  # Get the ID
            
            # Add tags
            if tags:
                self._add_tags_to_file(session, workflow_file, tags)
            
            # Add to collections
            if collections:
                self._add_file_to_collections(session, workflow_file, collections)
            
            # Update search index
            self._update_search_index(session, workflow_file)
            
            session.commit()
            print(f"✅ Added workflow file: {workflow_file.filename}")
            return workflow_file
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of file for duplicate detection."""
        if not file_path.exists():
            return ""
        
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"⚠️ Could not hash file {file_path}: {e}")
            return ""
    
    def _analyze_workflow(self, workflow_data: Dict) -> Dict:
        """Analyze workflow data to extract metrics."""
        if not workflow_data:
            return {'node_count': 0, 'connection_count': 0, 'node_types': []}
        
        node_count = len(workflow_data)
        connection_count = 0
        node_types = set()
        
        for node_id, node_data in workflow_data.items():
            if isinstance(node_data, dict):
                class_type = node_data.get('class_type', 'Unknown')
                node_types.add(class_type)
                
                # Count connections
                inputs = node_data.get('inputs', {})
                for param_value in inputs.values():
                    if isinstance(param_value, list) and len(param_value) == 2:
                        connection_count += 1
        
        return {
            'node_count': node_count,
            'connection_count': connection_count,
            'node_types': list(node_types)
        }
    
    def _auto_analyze_workflow(self, workflow_file: WorkflowFile, workflow_data: Dict):
        """Perform automatic analysis of workflow to extract insights."""
        # Extract model references
        models = self._extract_models_from_workflow(workflow_data)
        
        # Auto-generate tags based on node types and models
        auto_tags = []
        
        # Add node type-based tags
        node_types = workflow_file.node_types or []
        for node_type in node_types:
            if 'LoRA' in node_type:
                auto_tags.append('lora')
            elif 'ControlNet' in node_type:
                auto_tags.append('controlnet')
            elif 'Upscale' in node_type:
                auto_tags.append('upscaling')
            elif 'Checkpoint' in node_type:
                auto_tags.append('checkpoint')
            elif 'Text' in node_type:
                auto_tags.append('text-to-image')
            elif 'Image' in node_type:
                auto_tags.append('image-to-image')
        
        # Add complexity tags
        if workflow_file.node_count > 20:
            auto_tags.append('complex')
        elif workflow_file.node_count < 5:
            auto_tags.append('simple')
        else:
            auto_tags.append('moderate')
        
        # Store auto-generated tags in a field or as actual tags
        if auto_tags:
            workflow_file.style_tags = auto_tags
    
    def _extract_models_from_workflow(self, workflow_data: Dict) -> Dict[str, List[str]]:
        """Extract model references from workflow (similar to workflow_catalog.py)."""
        models = {
            'checkpoints': [],
            'loras': [],
            'vaes': [],
            'controlnets': []
        }
        
        # This is a simplified version - could import from workflow_catalog.py
        for node_data in workflow_data.values():
            if isinstance(node_data, dict):
                class_type = node_data.get('class_type', '')
                inputs = node_data.get('inputs', {})
                
                # Look for model file references
                for key, value in inputs.items():
                    if isinstance(value, str) and any(ext in value.lower() for ext in ['.safetensors', '.ckpt', '.pt']):
                        if 'checkpoint' in class_type.lower():
                            models['checkpoints'].append(value.split('/')[-1])
                        elif 'lora' in class_type.lower():
                            models['loras'].append(value.split('/')[-1])
                        elif 'vae' in class_type.lower():
                            models['vaes'].append(value.split('/')[-1])
                        elif 'controlnet' in class_type.lower():
                            models['controlnets'].append(value.split('/')[-1])
        
        return models
    
    def _add_tags_to_file(self, session: Session, workflow_file: WorkflowFile, tag_names: List[str]):
        """Associate tags with a workflow file."""
        for tag_name in tag_names:
            tag = session.query(Tag).filter_by(name=tag_name).first()
            if not tag:
                # Create new tag
                tag = Tag(name=tag_name)
                session.add(tag)
                session.flush()
            
            if tag not in workflow_file.tags:
                workflow_file.tags.append(tag)
    
    def _add_file_to_collections(self, session: Session, workflow_file: WorkflowFile, collection_names: List[str]):
        """Add workflow file to collections."""
        for collection_name in collection_names:
            collection = session.query(Collection).filter_by(name=collection_name).first()
            if not collection:
                # Create new collection
                collection = Collection(name=collection_name)
                session.add(collection)
                session.flush()
            
            if collection not in workflow_file.collections:
                workflow_file.collections.append(collection)
    
    def _update_search_index(self, session: Session, workflow_file: WorkflowFile):
        """Update full-text search index for workflow file."""
        # Create searchable text from various fields
        searchable_parts = [
            workflow_file.filename,
            workflow_file.notes or "",
            " ".join(workflow_file.node_types or []),
            " ".join(tag.name for tag in workflow_file.tags),
            " ".join(workflow_file.style_tags or [])
        ]
        
        searchable_text = " ".join(filter(None, searchable_parts)).lower()
        
        # Update or create search index entry
        search_entry = session.query(SearchIndex).filter_by(file_id=workflow_file.id).first()
        if search_entry:
            search_entry.searchable_text = searchable_text
            search_entry.updated_at = datetime.utcnow()
        else:
            search_entry = SearchIndex(
                file_id=workflow_file.id,
                searchable_text=searchable_text
            )
            session.add(search_entry)
    
    def search_workflows(self, query: str = None, tags: List[str] = None, 
                        collections: List[str] = None, node_types: List[str] = None,
                        limit: int = 50, offset: int = 0) -> List[WorkflowFile]:
        """Search workflow files with various filters."""
        with self.db.get_session() as session:
            query_builder = session.query(WorkflowFile)
            
            # Text search
            if query:
                # Join with search index for full-text search
                query_builder = query_builder.join(SearchIndex, WorkflowFile.id == SearchIndex.file_id)
                query_builder = query_builder.filter(SearchIndex.searchable_text.contains(query.lower()))
            
            # Tag filtering
            if tags:
                query_builder = query_builder.join(WorkflowFile.tags).filter(Tag.name.in_(tags))
            
            # Collection filtering
            if collections:
                query_builder = query_builder.join(WorkflowFile.collections).filter(Collection.name.in_(collections))
            
            # Node type filtering
            if node_types:
                for node_type in node_types:
                    query_builder = query_builder.filter(WorkflowFile.node_types.contains([node_type]))
            
            # Apply pagination and ordering
            query_builder = query_builder.order_by(WorkflowFile.created_at.desc())
            query_builder = query_builder.offset(offset).limit(limit)
            
            return query_builder.all()
    
    def get_workflow_stats(self) -> Dict[str, Any]:
        """Get database statistics for dashboard."""
        with self.db.get_session() as session:
            total_workflows = session.query(WorkflowFile).count()
            total_tags = session.query(Tag).count()
            total_collections = session.query(Collection).filter_by(is_system=False).count()
            
            # Most common node types
            common_node_types = {}
            all_files = session.query(WorkflowFile).all()
            for file in all_files:
                for node_type in file.node_types or []:
                    common_node_types[node_type] = common_node_types.get(node_type, 0) + 1
            
            # Sort by frequency
            common_node_types = dict(sorted(common_node_types.items(), key=lambda x: x[1], reverse=True)[:10])
            
            return {
                'total_workflows': total_workflows,
                'total_tags': total_tags,
                'total_collections': total_collections,
                'common_node_types': common_node_types,
                'total_nodes': sum(f.node_count or 0 for f in all_files),
                'total_connections': sum(f.connection_count or 0 for f in all_files)
            }


# Global database manager instance
db_manager: Optional[DatabaseManager] = None

def get_database_manager() -> DatabaseManager:
    """Get or create the global database manager instance."""
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager()
    return db_manager

def initialize_database(database_url: Optional[str] = None, create_tables: bool = True):
    """Initialize the database with optional custom URL."""
    global db_manager
    db_manager = DatabaseManager(database_url)
    
    if create_tables:
        db_manager.create_tables()
    
    print(f"✅ Database initialized: {db_manager.database_url}")
    return db_manager

def close_database():
    """Close database connections."""
    global db_manager
    if db_manager:
        db_manager.close()
        db_manager = None
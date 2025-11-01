#!/usr/bin/env python3
"""
ComfyREST Light Table - Incremental Ingestion Manager
====================================================

Handles intelligent ingestion of workflow directories with:
- Persistent memory of processed files
- Detection of new/modified/deleted files
- Incremental updates without reprocessing
- Cleanup of orphaned database records
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

# Import our database and catalog functionality
from .database import get_database_manager, WorkflowFileManager, initialize_database
from .models import WorkflowFile
from scripts.workflow_catalog import (
    scan_directory_for_images, extract_workflow_from_image, 
    extract_image_metadata, analyze_workflow
)


@dataclass
class FileChangeSet:
    """Represents changes detected during directory scan."""
    new_files: List[Path]
    modified_files: List[Path]  # Files that exist but changed (size/mtime)
    unchanged_files: List[Path]  # Files already in database and unchanged
    deleted_files: List[Path]   # Files in database but no longer exist
    
    @property
    def total_changes(self) -> int:
        return len(self.new_files) + len(self.modified_files) + len(self.deleted_files)
    
    def print_summary(self):
        """Print a summary of detected changes."""
        print(f"📊 Change Detection Summary:")
        print(f"   🆕 New files: {len(self.new_files)}")
        print(f"   📝 Modified files: {len(self.modified_files)}")
        print(f"   ♻️ Unchanged files: {len(self.unchanged_files)}")
        print(f"   🗑️ Deleted files: {len(self.deleted_files)}")
        print(f"   📈 Total changes: {self.total_changes}")


class IncrementalIngestionManager:
    """Manages incremental ingestion with change detection."""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.workflow_manager = WorkflowFileManager(db_manager)
    
    def scan_for_changes(self, directory: Path, extensions: List[str] = None) -> FileChangeSet:
        """Scan directory and detect changes compared to database."""
        print(f"🔍 Scanning for changes in: {directory}")
        
        if extensions is None:
            extensions = ['.png', '.webp', '.jpg', '.jpeg']
        
        # Get current files in directory
        current_files = scan_directory_for_images(directory, extensions)
        # Always use absolute paths for consistency and portability
        current_file_map = {str(f.resolve()): f for f in current_files}
        
        # Get files already in database
        with self.db.get_session() as session:
            db_files = session.query(WorkflowFile).all()
            db_file_map = {f.file_path: f for f in db_files}
        
        new_files = []
        modified_files = []
        unchanged_files = []
        deleted_files = []
        
        # Check each current file
        for file_path_str, file_path in current_file_map.items():
            if file_path_str not in db_file_map:
                # New file
                new_files.append(file_path)
            else:
                # File exists in database - check if modified
                db_file = db_file_map[file_path_str]
                if self._is_file_modified(file_path, db_file):
                    modified_files.append(file_path)
                else:
                    unchanged_files.append(file_path)
        
        # Check for deleted files (in database but not in current directory)
        for db_file_path, db_file in db_file_map.items():
            db_path = Path(db_file_path)
            # Normalize database path to absolute for comparison
            db_path_resolved = str(db_path.resolve()) if db_path.exists() else db_file_path
            if not db_path.exists() or db_path_resolved not in current_file_map:
                deleted_files.append(db_path)
        
        changeset = FileChangeSet(
            new_files=new_files,
            modified_files=modified_files,
            unchanged_files=unchanged_files,
            deleted_files=deleted_files
        )
        
        changeset.print_summary()
        return changeset
    
    def _is_file_modified(self, file_path: Path, db_file: WorkflowFile) -> bool:
        """Check if file has been modified since last ingestion."""
        try:
            stat = file_path.stat()
            
            # Check file size first (most reliable indicator)
            if stat.st_size != db_file.file_size:
                return True
            
            # Check file hash if available (most reliable)
            if hasattr(db_file, 'file_hash') and db_file.file_hash:
                current_hash = self._calculate_file_hash(file_path)
                if current_hash != db_file.file_hash:
                    return True
                else:
                    # Hash matches - file is definitely unchanged
                    return False
            
            # Fallback: check modification time
            # Only consider file modified if it was changed AFTER we last processed it
            file_mtime = datetime.fromtimestamp(stat.st_mtime)
            db_processed_time = db_file.updated_at or db_file.created_at
            
            # File is modified if its mtime is newer than when we last processed it
            # (with 1 second tolerance for filesystem precision)
            if file_mtime > db_processed_time and (file_mtime - db_processed_time).total_seconds() > 1:
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️ Error checking modification for {file_path}: {e}")
            return True  # Assume modified if we can't check
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of file."""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return ""
    
    def process_changes(self, changeset: FileChangeSet, 
                       tags: List[str] = None, 
                       collections: List[str] = None,
                       notes: str = None,
                       dry_run: bool = False) -> Dict[str, int]:
        """Process detected changes (add/update/delete records)."""
        
        stats = {
            'added': 0,
            'updated': 0,
            'deleted': 0,
            'errors': 0
        }
        
        if dry_run:
            print("🧪 DRY RUN MODE - No changes will be made")
        
        # Process new files
        if changeset.new_files:
            print(f"\n🆕 Processing {len(changeset.new_files)} new files...")
            for file_path in changeset.new_files:
                try:
                    if self._add_new_file(file_path, tags, collections, notes, dry_run):
                        stats['added'] += 1
                        print(f"  ✅ Added: {file_path.name}")
                    else:
                        print(f"  ⏭️ Skipped: {file_path.name} (no workflow)")
                except Exception as e:
                    stats['errors'] += 1
                    print(f"  ❌ Error adding {file_path.name}: {e}")
        
        # Process modified files
        if changeset.modified_files:
            print(f"\n📝 Processing {len(changeset.modified_files)} modified files...")
            for file_path in changeset.modified_files:
                try:
                    if self._update_existing_file(file_path, dry_run):
                        stats['updated'] += 1
                        print(f"  ✅ Updated: {file_path.name}")
                    else:
                        print(f"  ⏭️ Skipped: {file_path.name} (no changes needed)")
                except Exception as e:
                    stats['errors'] += 1
                    print(f"  ❌ Error updating {file_path.name}: {e}")
        
        # Process deleted files
        if changeset.deleted_files:
            print(f"\n🗑️ Processing {len(changeset.deleted_files)} deleted files...")
            for file_path in changeset.deleted_files:
                try:
                    if self._remove_deleted_file(file_path, dry_run):
                        stats['deleted'] += 1
                        print(f"  ✅ Removed: {file_path.name}")
                except Exception as e:
                    stats['errors'] += 1
                    print(f"  ❌ Error removing {file_path.name}: {e}")
        
        return stats
    
    def _add_new_file(self, file_path: Path, tags: List[str], collections: List[str], 
                      notes: str, dry_run: bool) -> bool:
        """Add a new file to the database."""
        if dry_run:
            # Check if file has workflow without actually adding
            workflow = extract_workflow_from_image(file_path)
            return workflow is not None
        
        # Extract workflow
        workflow = extract_workflow_from_image(file_path)
        if not workflow:
            return False
        
        # Extract metadata
        metadata = extract_image_metadata(file_path)
        
        # Add to database
        self.workflow_manager.add_workflow_file(
            file_path=file_path,
            workflow_data=workflow,
            image_metadata=metadata,
            notes=notes,
            tags=tags,
            collections=collections,
            auto_analyze=True
        )
        
        return True
    
    def _update_existing_file(self, file_path: Path, dry_run: bool) -> bool:
        """Update an existing file in the database."""
        if dry_run:
            return True  # Assume update would be successful
        
        with self.db.get_session() as session:
            # Find existing record
            existing = session.query(WorkflowFile).filter_by(file_path=str(file_path)).first()
            if not existing:
                return False
            
            # Re-extract workflow and metadata
            workflow = extract_workflow_from_image(file_path)
            if not workflow:
                # File no longer has workflow - mark for potential deletion
                print(f"    ⚠️ File no longer contains workflow: {file_path.name}")
                return False
            
            metadata = extract_image_metadata(file_path)
            workflow_analysis = self._analyze_workflow(workflow)
            
            # Update fields
            existing.workflow_data = workflow
            existing.node_count = workflow_analysis.get('node_count', 0)
            existing.connection_count = workflow_analysis.get('connection_count', 0)
            existing.node_types = workflow_analysis.get('node_types', [])
            existing.updated_at = datetime.utcnow()
            
            # Update file metadata
            if metadata:
                existing.image_width = metadata.get('width')
                existing.image_height = metadata.get('height')
                existing.image_format = metadata.get('format')
            
            # Update file size and hash
            stat = file_path.stat()
            existing.file_size = stat.st_size
            existing.file_modified_at = datetime.fromtimestamp(stat.st_mtime)
            existing.file_hash = self._calculate_file_hash(file_path)
            
            # Update search index
            self.workflow_manager._update_search_index(session, existing)
            
            session.commit()
            return True
    
    def _remove_deleted_file(self, file_path: Path, dry_run: bool) -> bool:
        """Remove a deleted file from the database."""
        if dry_run:
            return True  # Assume deletion would be successful
        
        with self.db.get_session() as session:
            # Find and delete record
            existing = session.query(WorkflowFile).filter_by(file_path=str(file_path)).first()
            if existing:
                session.delete(existing)
                session.commit()
                return True
            return False
    
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


def main():
    """CLI interface for incremental ingestion."""
    parser = argparse.ArgumentParser(
        description="ComfyREST Light Table - Incremental Ingestion Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan for changes (dry run)
  python -m database.incremental_ingestion --directory ./outputs --dry-run
  
  # Process all changes
  python -m database.incremental_ingestion --directory ./outputs --process
  
  # Process with metadata
  python -m database.incremental_ingestion --directory ./outputs --process --tags "project-new,batch-2" --notes "November batch"
  
  # Only scan and report (no processing)
  python -m database.incremental_ingestion --directory ./outputs --scan-only
        """
    )
    
    parser.add_argument('--directory', '-d', required=True,
                       help='Directory to scan for workflow images')
    parser.add_argument('--extensions', nargs='+', 
                       default=['.png', '.webp', '.jpg', '.jpeg'],
                       help='Image extensions to process')
    
    # Operation modes
    parser.add_argument('--scan-only', action='store_true',
                       help='Only scan and report changes (no processing)')
    parser.add_argument('--process', action='store_true',
                       help='Process detected changes')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    
    # Metadata for new files
    parser.add_argument('--tags', help='Comma-separated tags for new files')
    parser.add_argument('--collections', help='Comma-separated collections for new files')
    parser.add_argument('--notes', help='Notes to add to new files')
    
    # Options
    parser.add_argument('--force-update', action='store_true',
                       help='Force update all files even if unchanged')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not any([args.scan_only, args.process, args.dry_run]):
        parser.error("Must specify one of: --scan-only, --process, or --dry-run")
    
    directory = Path(args.directory)
    if not directory.exists() or not directory.is_dir():
        print(f"❌ Directory not found: {directory}")
        return 1
    
    # Initialize database
    try:
        db_manager = get_database_manager()
        ingestion_manager = IncrementalIngestionManager(db_manager)
        print("✅ Database connection established")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        print("   Run: python -m database.init_database --init")
        return 1
    
    # Parse metadata
    tags = [tag.strip() for tag in args.tags.split(',')] if args.tags else None
    collections = [col.strip() for col in args.collections.split(',')] if args.collections else None
    
    print(f"🚀 Incremental ingestion manager")
    print(f"📂 Target directory: {directory}")
    
    # Scan for changes
    changeset = ingestion_manager.scan_for_changes(directory, args.extensions)
    
    if args.scan_only:
        print("\n📋 Scan complete - no processing requested")
        return 0
    
    if changeset.total_changes == 0:
        print("\n✅ No changes detected - database is up to date")
        return 0
    
    # Process changes
    print(f"\n🔄 Processing {changeset.total_changes} changes...")
    
    stats = ingestion_manager.process_changes(
        changeset=changeset,
        tags=tags,
        collections=collections,
        notes=args.notes,
        dry_run=args.dry_run
    )
    
    # Print final summary
    print(f"\n📊 Processing Summary:")
    print(f"   ✅ Added: {stats['added']}")
    print(f"   📝 Updated: {stats['updated']}")
    print(f"   🗑️ Deleted: {stats['deleted']}")
    print(f"   ❌ Errors: {stats['errors']}")
    
    if args.dry_run:
        print("\n🧪 This was a dry run - no actual changes were made")
        print("   Use --process to apply these changes")
    else:
        print("\n🎉 Incremental ingestion complete!")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
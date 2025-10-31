#!/usr/bin/env python3
"""
Database Path Migration Utility
===============================

Converts relative paths in existing database records to absolute paths
for better portability and consistency.
"""

import sys
from pathlib import Path
from .database import get_database_manager
from .models import WorkflowFile

def migrate_paths_to_absolute():
    """Convert all relative paths in database to absolute paths."""
    
    print("🔄 Migrating database paths from relative to absolute...")
    
    try:
        db_manager = get_database_manager()
        
        with db_manager.get_session() as session:
            # Get all workflow files
            files = session.query(WorkflowFile).all()
            print(f"📊 Found {len(files)} files to check")
            
            updated_count = 0
            error_count = 0
            
            for workflow_file in files:
                try:
                    original_path = workflow_file.file_path
                    path_obj = Path(original_path)
                    
                    # Check if it's already absolute
                    if path_obj.is_absolute():
                        continue
                    
                    # Convert to absolute path
                    if path_obj.exists():
                        absolute_path = str(path_obj.resolve())
                        workflow_file.file_path = absolute_path
                        updated_count += 1
                        print(f"  ✅ Updated: {original_path} -> {absolute_path}")
                    else:
                        print(f"  ⚠️ File not found: {original_path}")
                        error_count += 1
                        
                except Exception as e:
                    print(f"  ❌ Error processing {workflow_file.filename}: {e}")
                    error_count += 1
            
            if updated_count > 0:
                session.commit()
                print(f"\n✅ Migration complete:")
                print(f"   📝 Updated: {updated_count} files")
                print(f"   ❌ Errors: {error_count}")
            else:
                print(f"\n✅ No updates needed - all paths are already absolute")
                
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False
    
    return True

if __name__ == '__main__':
    if migrate_paths_to_absolute():
        print("🎉 Path migration successful!")
        sys.exit(0)
    else:
        print("💥 Path migration failed!")
        sys.exit(1)
import os
import json
import subprocess
import shutil
from datetime import datetime
from typing import List, Dict, Optional

# Constants
BACKUP_ROOT_NAME = ".metadata_history"
EXIFTOOL_PATH = 'exiftool'

def get_backup_root(project_root: str = None) -> str:
    """
    Returns the absolute path to the backup root directory.
    If project_root is not provided, tries to find it typical ways or defaults to CWD.
    """
    if not project_root:
        # Assumption: This runs from within the app, so CWD usually is project root 
        # or we can go up from this file path. 
        # Let's rely on os.getcwd() for now as app/run.py sets it.
        project_root = os.getcwd()
    
    return os.path.join(project_root, BACKUP_ROOT_NAME)

def get_timestamped_backup_dir(project_root: str = None) -> str:
    """
    Creates/Returns a path like: <Root>/.metadata_history/2026/01/19
    """
    root = get_backup_root(project_root)
    now = datetime.now()
    # Structure: YYYY/MM/DD to keep folders manageable
    daily_path = os.path.join(root, now.strftime('%Y'), now.strftime('%m'), now.strftime('%d'))
    
    if not os.path.exists(daily_path):
        os.makedirs(daily_path, exist_ok=True)
        
    return daily_path

def create_backups(file_paths: List[str]) -> Dict[str, str]:
    """
    Batched Backup Creation.
    1. Runs ExifTool once for all provided files.
    2. Writes individual JSON dumps to the history folder.
    
    Returns: Dict mapping {original_path: backup_path}
    """
    if not file_paths:
        return {}
        
    # Check if exiftool exists
    if shutil.which(EXIFTOOL_PATH) is None:
        print("Error: ExifTool not found in PATH")
        return {}

    # 1. Run ExifTool in Batch
    # -j = JSON output
    # -a = Allow duplicates (get all tags)
    # -G1 = Group names (specific location)
    # -struct = Preserve structure of XMP (important for Regions)
    cmd = [EXIFTOOL_PATH, '-j', '-a', '-G1', '-struct'] + file_paths
    
    try:
        # Increase buffer size limit if needed, though subprocess handles streams well.
        # Run command
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        
        if result.returncode != 0:
            print(f"ExifTool Batch Backup Error: {result.stderr}")
            # If batch fails (e.g. one file missing), we might get partial output or error.
            # ExifTool usually continues for valid files.
            
    except Exception as e:
        print(f"ExifTool Execution Failed: {e}")
        return {}

    try:
        metadata_list = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Failed to decode ExifTool JSON output")
        return {}

    # 2. Map Results to Files and Write Backups
    backup_map = {}
    backup_dir = get_timestamped_backup_dir()
    
    # ExifTool JSON is a list of dicts. Each dict has 'SourceFile'.
    # Note: SourceFile uses forward slashes usually.
    
    for entry in metadata_list:
        source_file = entry.get('SourceFile')
        if not source_file:
            continue
            
        # Normalize path to match input list style (OS dependent)
        # ExifTool returns absolute path if input was absolute, or relative if relative.
        # Ideally we match loosely or by cleaning paths.
        
        # Construct backup filename: "original_basename.timestamp.json" 
        # Or better: "original_basename.v<timestamp>.json"
        
        # We need to map this back to the absolute path used in DB usually.
        # Let's verify file existence locally to handle the write.
        
        # Handle path normalization for matching
        # (This is tricky if ExifTool mangles path chars, but usually fine)
        
        base_name = os.path.basename(source_file)
        # Append microsecond timestamp to ensure uniqueness if multiple backups happen same run/second
        timestamp_suffix = datetime.now().strftime('%H%M%S_%f')
        backup_filename = f"{base_name}.v{timestamp_suffix}.json"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(entry, f, indent=2, ensure_ascii=False)
            
            # Record success
            # We want to key this by the input path provided, or the absolute path.
            # Let's try to rectify source_file to absolute path
            abs_source = os.path.abspath(source_file)
            backup_map[abs_source] = backup_path
            
        except OSError as e:
            print(f"Failed to write backup file for {base_name}: {e}")

    return backup_map

def list_backups(file_path: str, project_root: str = None) -> List[str]:
    """
    Finds all backups for a specific file.
    Note: This is expensive as it crawls the history tree. 
    Optimization: In Phase 2, we might index backups in SQLite.
    For now, we just scan.
    """
    root = get_backup_root(project_root)
    if not os.path.exists(root):
        return []
        
    found_backups = []
    target_base = os.path.basename(file_path)
    
    # Walk the tree
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            # Check if fname starts with target_base and looks like a backup
            # Backup format: "filename.ext.vTIMESTAMP.json"
            if fname.startswith(target_base) and fname.endswith(".json"):
                 full_path = os.path.join(dirpath, fname)
                 found_backups.append(full_path)
                 
    return sorted(found_backups)

def get_backup_info(file_path: str, project_root: str = None) -> List[Dict]:
    """
    Returns a list of backup info dicts:
    [{
        'timestamp': datetime object, 
        'pretty_time': str,
        'path': absolute path,
        'filename': filename
    }]
    """
    backups = list_backups(file_path, project_root)
    result = []
    
    for b_path in backups:
        # Parse timestamp from filename: file.ext.vHHMMSS_ffffff.json
        # Parent directory is DD, parent of that is MM, parent of that is YYYY
        try:
            fname = os.path.basename(b_path)
            # We can try to extract time from filename, or rely on file mtime?
            # Filename is safer if we move things.
            # Format: .v<HHMMSS_ffffff>.json
            
            parts = fname.split('.v')
            if len(parts) < 2: 
                continue
                
            time_part = parts[-1].replace('.json', '')
            # time_part like 203205_025579 (HHMMSS_microseconds)
            
            # Get date from path components
            # path: .../YYYY/MM/DD/filename...
            path_parts = os.path.normpath(b_path).split(os.sep)
            # Assuming standard structure: ... date_root / YYYY / MM / DD / file
            # Day = -2, Month = -3, Year = -4 (since file is -1)
            day = path_parts[-2]
            month = path_parts[-3]
            year = path_parts[-4]
            
            # Construct datetime
            dt_str = f"{year}-{month}-{day} {time_part}"
            # time_part might need formatting
            # 203205_025579 -> %H%M%S_%f
            
            full_dt = datetime.strptime(dt_str, "%Y-%m-%d %H%M%S_%f")
            
            result.append({
                'timestamp': full_dt,
                'pretty_time': full_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'path': b_path,
                'filename': fname
            })
        except Exception as e:
            # Fallback for old/weird files
            print(f"Error parsing backup {b_path}: {e}")
            continue
            
    # Sort by timestamp descending (newest first)
    result.sort(key=lambda x: x['timestamp'], reverse=True)
    return result

def read_backup(backup_path: str) -> Optional[Dict]:
    """Reads the JSON content of a backup file."""
    if not os.path.exists(backup_path):
        return None
        
    try:
        with open(backup_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading backup {backup_path}: {e}")
        return None

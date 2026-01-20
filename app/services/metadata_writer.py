
import os
import shutil
import subprocess
import json
from typing import Dict, List, Optional, Union
from app.services import metadata_backup

# Constants
EXIFTOOL_PATH = 'exiftool'

# Extensions safely supported for embedding (Standard Containers)
SAFE_EMBED_EXTENSIONS = {
    '.jpg', '.jpeg', '.dng', '.tiff', '.tif', '.png', '.webp'
}

# Extensions that strictly force sidecar usage (Proprietary RAW)
# Note: Practically, anything NOT in safe list should fallback to sidecar.
FORCE_SIDECAR_EXTENSIONS = {
    '.cr2', '.nef', '.arw', '.orf', '.rw2', '.raf', '.pef', '.srw', '.cr3'
}

def get_target_file(file_path: str) -> str:
    """
    Determines the actual file to write to.
    - If safe extension: returns original path.
    - Else: returns path + '.xmp'
    """
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    
    if ext in SAFE_EMBED_EXTENSIONS:
        return file_path
    
    # Fallback for RAWs or unknown: use Sidecar
    return file_path + ".xmp"

def format_exiftool_args(metadata: Dict) -> List[str]:
    """
    Maps simple generic keys to ExifTool tag arguments.
    Supported keys: 'rating', 'description', 'title', 'keywords', 'orientation'
    
    TODO: Add complex Face Region support.
    """
    args = []
    
    # 1. Rating (XMP)
    if 'rating' in metadata:
        val = metadata['rating']
        # Ensure 0-5
        args.append(f"-xmp:Rating={val}")
        
    # 2. Description / Caption (XMP & IPTC for max compatibility)
    if 'description' in metadata:
        val = metadata['description']
        args.append(f"-xmp-dc:Description={val}")
        args.append(f"-iptc:Caption-Abstract={val}")
        args.append(f"-ImageDescription={val}")
        
    # 3. Title (XMP & IPTC)
    if 'title' in metadata:
        val = metadata['title']
        args.append(f"-xmp-dc:Title={val}")
        args.append(f"-iptc:ObjectName={val}")
        
    # 4. Keywords (List)
    if 'keywords' in metadata:
        tags = metadata['keywords']
        if isinstance(tags, str):
            tags = [tags]
            
        # Clear existing to overwrite list properly? Or add?
        # Strategy: Overwrite list provided by UI as source of truth.
        # ExifTool -sep allows writing lists.
        # But separate args is safer for adding.
        # To replace list: "-Subject=Tag1" "-Subject=Tag2"
        # We need to know if we are Adding or Replacing.
        # For now, let's assume we are REPLACING the tag set.
        
        args.append("-xmp-dc:Subject=") # Clear existing
        args.append("-iptc:Keywords=")  # Clear existing
        for tag in tags:
            args.append(f"-xmp-dc:Subject={tag}")
            args.append(f"-iptc:Keywords={tag}")
            
    return args

def write_metadata(file_path: str, metadata: Dict) -> bool:
    """
    Writes metadata to the file (or its sidecar) safely.
    
    Steps:
    1. Safety Backup (Time Machine)
    2. Determine Target (Embed vs Sidecar)
    3. Execute ExifTool
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found {file_path}")
        return False
        
    # 1. Safety Backup
    # We abort if backup fails to ensure we never write without safety net.
    # Note: create_backups returns a map. If empty, it might mean failure or no file.
    backups = metadata_backup.create_backups([file_path])
    if not backups:
        print(f"Aborting write: Backup failed for {file_path}")
        return False
        
    # 2. Determine Target
    target_file = get_target_file(file_path)
    is_sidecar = target_file != file_path
    
    # 3. Construct Command
    cmd = [EXIFTOOL_PATH]
    
    # Flags
    # -overwrite_original_in_place is best for embedded to preserve system creation attributes
    # For sidecars, -overwrite_original is fine or default.
    if not is_sidecar:
        cmd.append("-overwrite_original_in_place")
    else:
        # If writing sidecar, we might be creating it new.
        cmd.append("-overwrite_original")

    # Add Tags
    tag_args = format_exiftool_args(metadata)
    if not tag_args:
        print("No valid metadata keys provided.")
        return False
        
    cmd.extend(tag_args)
    cmd.append(target_file)
    
    # 4. Execute
    try:
        # Use simple run. 
        # Note: subprocess arguments with special chars need care, but list arg is safe from shell injection usually.
        # However, ExifTool parsing might need quote handling if not via shell.
        # subprocess in list mode passes args directly to exec.
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        
        if result.returncode != 0:
            print(f"ExifTool Write Error: {result.stderr}")
            return False
            
        return True
        
    except Exception as e:
        print(f"Metadata Write Exception: {e}")
        return False

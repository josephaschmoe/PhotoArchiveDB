import subprocess
import json
import shutil
from datetime import datetime

EXIFTOOL_PATH = 'exiftool' # Assumes it's in PATH

def is_exiftool_available():
    return shutil.which(EXIFTOOL_PATH) is not None

def get_metadata(file_path):
    """
    Runs exiftool on the file and returns a dictionary of metadata.
    """
    if not is_exiftool_available():
        return {}

    try:
        # -j for JSON output
        # -G for group names? No, keeps it flat for now but let's ensure we get duplicates if any.
        # Actually, user specifically asked for "Caption-Abstract" and "Description".
        # Sometimes these are in XMP or IPTC. ExifTool gets them by default but maybe -a (duplicates) helps if hidden.
        # -u for unknown tags? -s for short names?
        # Let's try adding -a to be safe.
        cmd = [EXIFTOOL_PATH, '-j', '-a', '-G', file_path] # Adding -G might make keys "Group:Tag", which complicates parsing?
        # Let's stick to flat keys but use -a. 
        # Wait, if we use -G, the keys become "IPTC:Caption-Abstract". If we don't, it's "Caption-Abstract".
        # The user said they are MISSING. 
        # Let's try to just use default first but maybe the user's files have them in a way standard scan missed?
        # Or maybe I need to specifically ask for them? No, exiftool usually dumps all.
        # I'll update command to include -struct to get structural XMP if needed, and -a.
        cmd = [EXIFTOOL_PATH, '-j', '-a', file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if result.returncode != 0:
            print(f"ExifTool Error: {result.stderr}")
            return {}

        data = json.loads(result.stdout)
        if data:
            return data[0] # Exiftool returns a list of objects
        return {}

    except Exception as e:
        print(f"Metadata Extraction Failed: {e}")
        return {}

def parse_date(date_str):
    """
    Attempts to parse ExifTool date strings like '2023:01:01 12:00:00'
    """
    if not date_str:
        return None
    
    formats = [
        '%Y:%m:%d %H:%M:%S',
        '%Y:%m:%d %H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S'
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def write_metadata(file_path, tags):
    """
    Writes metadata tags to the file using ExifTool.
    tags: dict of {Tag: Value}
    """
    if not is_exiftool_available() or not tags:
        return False

    cmd = [EXIFTOOL_PATH, '-overwrite_original']
    for tag, value in tags.items():
        # Sanitize? ExifTool handles most, but we should be careful with quotes if shelling out. 
        # subprocess.run handles args safely.
        cmd.append(f"-{tag}={value}")
    
    cmd.append(file_path)

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"ExifTool Write Error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"ExifTool Write Failed: {e}")
        return False

def extract_ai_info(metadata):
    """
    Parses the 'AIGenerationInfo' from the metadata dictionary.
    Looks specifically in 'UserComment'.
    """
    if not metadata:
        return None

    user_comment = metadata.get('UserComment') or metadata.get('User Comment')
    
    # Sometimes it might be in XMP:UserComment specifically if strictly keyed
    if not user_comment:
        # Check keys that end with UserComment just in case
        for key, value in metadata.items():
            if key.endswith('UserComment'):
                user_comment = value
                break
    
    if not user_comment:
        return None

    # Clean the comment string (remove charset prefix if present)
    # ExifTool JSON output usually gives the string "charset=..." or just the content
    raw = str(user_comment).strip()
    if raw.startswith("charset="):
        # usually "charset=Ascii " or "charset=Unknown "
        try:
            _, content = raw.split(" ", 1)
            raw = content
        except ValueError:
            pass # Failed to split, try using as is or it's malformed
            
    try:
        # It's stored as a JSON string inside the comment
        data = json.loads(raw)
        return data.get("AIGenerationInfo")
    except json.JSONDecodeError:
        return None

def extract_camera_info(metadata):
    """
    Extracts standard photography metadata.
    """
    if not metadata:
        return None
    
    # helper to get first available key
    def get(keys, default=None):
        for k in keys:
            if k in metadata:
                return metadata[k]
        return default

    info = {
        'Make': get(['Make']),
        'Model': get(['Model']),
        'Lens': get(['LensModel', 'LensID', 'Lens']),
        'ISO': get(['ISO']),
        'Aperture': get(['FNumber', 'ApertureValue']),
        'ShutterSpeed': get(['ExposureTime', 'ShutterSpeedValue', 'ShutterSpeed']),
        'FocalLength': get(['FocalLength']),
        'Flash': get(['Flash']),
        'Software': get(['Software'])
    }
    
    # Filter out empty values
    return {k: v for k, v in info.items() if v}

def extract_gps_info(metadata):
    """
    Extracts GPS coordinates and returns decimal latitude and longitude.
    Returns dictionary {'lat': float, 'lng': float} or None.
    """
    if not metadata:
        return None

    # ExifTool often returns "deg min sec" string or sometimes decimal if -n is used.
    # We used default call, so it's likely strings like "40 deg 42' 46.00\" N"
    # Or sometimes separate Reference fields.
    
    lat = metadata.get('GPSLatitude')
    lng = metadata.get('GPSLongitude')
    
    if not lat or not lng:
        return None
        
    # Helper to parse DMS string to decimal
    def parse_dms(dms_str):
        # Check if already float/int
        if isinstance(dms_str, (int, float)):
            return float(dms_str)
            
        # Regex or simple string manipulation
        # Format often: "40 deg 42' 46.00\" N"
        try:
            dms_str = str(dms_str).strip()
            parts = dms_str.replace("deg", "").replace("'", "").replace('"', "").split()
            
            # parts should be [deg, min, sec, Ref] or [deg, min, sec]
            # But ExifTool output varies wildly based on OS/Version/Options.
            # However, if we look at ExifTool docs, it says it parses standard EXIF.
            # A more robust way with ExifTool relies on the fact that if we used -n (numerical), 
            # we would get decimals. But we didn't use -n in get_metadata.
            # 
            # WAIT: If we change get_metadata to use -c "%.6f" (coord format), we get decimals!
            # BUT that changes global behavior. 
            # Let's see if we can just parse the string "40.1234 N" vs "40 deg..."
            
            # Simple heuristic: look for N/S/E/W at end
            ref_mult = 1
            if dms_str.upper().endswith("S") or dms_str.upper().endswith("W"):
                ref_mult = -1
            
            dms_str = dms_str.upper().rstrip("NSEW").strip()
            
            if "DEG" in dms_str:
                 # Parse DMS
                 # This is complex to robustly parse all variants.
                 pass
            else:
                 # Maybe it's "40.7128" (if already decimal in string)
                 return float(dms_str) * ref_mult
                 
        except:
            pass
            
        return None

    # Since parsing DMS is annoying and fragile without a library,
    # let's assume ExifTool *usually* gives a nice Composite string 
    # OR lets convert safely.
    # Actually, the easier path: The caller (routes.py) could re-query with -n if needed?
    # NO, that's slow.
    
    # Better approach: string parsing "40 deg 42' 46.00\" N"
    # Let's try to extract numbers.
    try:
        def dms_to_dd(dms_str):
            import re
            # Match: 40 deg 42' 46.00" N
            # regex to find float-like numbers
            parts = re.findall(r"[\d\.]+", dms_str)
            if len(parts) >= 3:
                d = float(parts[0])
                m = float(parts[1])
                s = float(parts[2])
                dd = d + m/60 + s/3600
                if 'S' in dms_str.upper() or 'W' in dms_str.upper():
                    dd = -dd
                return dd
            elif len(parts) == 1:
                # Just a number?
                return float(parts[0])
            return None

        lat_dd = dms_to_dd(str(lat))
        lng_dd = dms_to_dd(str(lng))
        
        if lat_dd is not None and lng_dd is not None:
             return {'lat': lat_dd, 'lng': lng_dd}
             
    except Exception as e:
        print(f"GPS Parse Error: {e}")
        
    return None

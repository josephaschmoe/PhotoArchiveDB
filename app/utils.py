import os
from PIL import Image
from flask import current_app

def get_thumbnail_path(asset_id):
    """Returns the absolute path to the thumbnail for the given asset ID."""
    thumb_dir = os.path.join(current_app.instance_path, 'thumbnails')
    if not os.path.exists(thumb_dir):
        os.makedirs(thumb_dir)
    return os.path.join(thumb_dir, f"{asset_id}.jpg")

def generate_thumbnail(original_path, asset_id):
    """
    Generates a thumbnail for the image at original_path.
    Returns the path to the generated thumbnail.
    """
    thumb_path = get_thumbnail_path(asset_id)
    
    # If thumbnail exists, return it (simple cache check)
    if os.path.exists(thumb_path):
        return thumb_path

    try:
        with Image.open(original_path) as img:
            # Convert to RGB if necessary (e.g. for PNGs with transparency if saving as JPG)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Resize
            img.thumbnail((300, 300))
            
            # Save
            img.save(thumb_path, "JPEG", quality=85)
            
        return thumb_path
    except Exception as e:
        print(f"Error generating thumbnail for {original_path}: {e}")
        return None

import os
import hashlib
from app import db
from app.models import Asset
from app.services.metadata import get_metadata, parse_date
from datetime import datetime

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.pdf', '.txt', '.mp4', '.mov'}

def get_file_hash(filepath):
    """Calculates SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def is_allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def scan_directory(library_path):
    """
    Walks the library_path, finds new files, initializes Assets.
    Returns tuple: (added_count, skipped_count, error_count)
    """
    added = 0
    skipped = 0
    errors = 0

    print(f"Scanning {library_path}...")

    if not os.path.exists(library_path):
        print(f"Error: Path {library_path} does not exist.")
        return 0, 0, 1

    for root, dirs, files in os.walk(library_path):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for file in files:
            if file.startswith('.'):
                continue
                
            if not is_allowed_file(file):
                continue

            full_path = os.path.join(root, file)
            
            # Check if exists by path
            # Use no_autoflush to prevent SQLAlchemy from trying to flush pending inserts 
            # (from previous loop iterations) just to run this SELECT.
            with db.session.no_autoflush:
                existing_asset = Asset.query.filter_by(file_path=full_path).first()
            
            if existing_asset:
                skipped += 1
                continue

            if existing_asset:
                skipped += 1
                continue

            # Calculate Hash to check for MOVED files (Self-Healing)
            try:
                f_hash = get_file_hash(full_path)
                
                # Check if this hash exists under a different path
                with db.session.no_autoflush:
                    moved_asset = Asset.query.filter_by(file_hash=f_hash).first()

                if moved_asset:
                    # SELF-HEALING: Update the path of the existing record
                    print(f"Move Detected: {moved_asset.file_path} -> {full_path}")
                    moved_asset.file_path = full_path
                    # Optionally update metadata?
                    # Let's assume the file on disk is the source of truth for metadata, 
                    # but the DB is source of truth for People/Faces.
                    # We keep the old ID, so People/Faces are preserved!
                    # We might want to re-read metadata in case it changed during move?
                    # Let's do a light metadata refresh.
                    meta = get_metadata(full_path) 
                    if meta:
                        moved_asset.meta_json = meta
                        
                    skipped += 1 # Count as skipped (or maybe a new 'updated' category?)
                    # Let's count as skipped for now to avoid confusion, or print it.
                    continue

                # If we get here, it's truly a NEW file
                
                # Metadata Extraction
                meta = get_metadata(full_path)
                
                # Try to find date
                captured_date = None
                if meta:
                    date_str = meta.get('DateTimeOriginal') or meta.get('CreateDate') or meta.get('MediaCreateDate')
                    captured_date = parse_date(date_str)

                new_asset = Asset(
                    file_path=full_path,
                    file_hash=f_hash,
                    media_type=os.path.splitext(file)[1].lower()[1:], # 'jpg', 'png'
                    title=meta.get('Title') or file, # Use Title tag if available
                    added_at=datetime.utcnow(),
                    captured_at=captured_date,
                    meta_json=meta
                )
                db.session.add(new_asset)
                added += 1
                
                # Commit every 100 items to avoid huge transactions
                if added % 100 == 0:
                    try:
                        db.session.commit()
                        print(f"Committed {added} assets...")
                    except Exception as e:
                        db.session.rollback()
                        print(f"Commit error: {e}")
                        errors += 1

            except Exception as e:
                print(f"Error processing {full_path}: {e}")
                # Don't increment errors for just processing errors if we want to continue?
                # But here we do.
                errors += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Final commit error: {e}")

    print(f"Scan complete. Added: {added}, Skipped: {skipped}, Errors: {errors}")
    return added, skipped, errors

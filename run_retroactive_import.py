
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from app import create_app, db
from app.models import Asset
from app.services import face_import_utils

app = create_app()

print(">>> Starting Retroactive Face Metadata Import...")
print("    This will scan all assets and merge XMP-mwg-rs face tags.")

with app.app_context():
    assets = Asset.query.all()
    total = len(assets)
    print(f"    Found {total} assets to check.")
    
    updated_count = 0
    errors = 0
    
    for i, asset in enumerate(assets):
        try:
            # Simple progress
            if i % 10 == 0:
                print(f"    Processing {i}/{total}...", end='\r')
                
            # Run Import
            changes = face_import_utils.import_faces_from_metadata(asset)
            if changes > 0:
                print(f"    [UPDATE] {os.path.basename(asset.file_path)}: {changes} faces updated/added.")
                updated_count += 1
                
        except Exception as e:
            # print(f"    [ERR] {asset.id}: {e}")
            errors += 1
            continue

    print(f"\n\nDone! Processed {total} assets.")
    print(f"Assets Updated: {updated_count}")
    print(f"Errors (Skipped): {errors}")


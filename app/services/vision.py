try:
    import face_recognition
    FACE_REC_AVAILABLE = True
except ImportError:
    FACE_REC_AVAILABLE = False
    print("Warning: 'face_recognition' library not found. Face detection disabled.")

import pickle
import numpy as np
from app import db
from app.models import Asset, Face, Person

def process_all_faces():
    """
    Iterates through all assets without face data and processes them.
    Returns: processed_count
    """
    # Find assets that haven't been processed? 
    # For MVP, simplify: Find assets that don't have faces? 
    # Or add a 'processed' flag to Asset?
    # Let's iterate all images and check if they have associated faces. 
    # If 0 faces, might mean 0 faces found OR not processed.
    # Ideally, we need a flag 'scanned_for_faces'.
    # We'll just run on all images for this prototype demo command.
    
    if not FACE_REC_AVAILABLE:
        print("Skipping face detection: Library not installed.")
        return 0

    assets = Asset.query.filter(Asset.media_type.in_(['jpg', 'jpeg', 'png'])).all()
    count = 0
    
    # Pre-fetch known faces for clustering
    known_faces_query = Face.query.filter(Face.person_id.isnot(None), Face.encoding.isnot(None)).all()
    known_encodings = []
    known_person_ids = []
    
    for kf in known_faces_query:
        try:
            arr = pickle.loads(kf.encoding)
            known_encodings.append(arr)
            known_person_ids.append(kf.person_id)
        except:
            pass

    for asset in assets:
        # Skip if already has faces? (Simple optimization)
        if asset.faces.count() > 0:
            continue
            
        try:
            print(f"Processing faces for {asset.file_path}...")
            image = face_recognition.load_image_file(asset.file_path)
            
            # Detect
            locations = face_recognition.face_locations(image)
            if not locations:
                # Mark as processed? 
                continue
                
            encodings = face_recognition.face_encodings(image, locations)
            
            for location, encoding in zip(locations, encodings):
                # suggested_person_id = None
                
                # Clustering / Matching Logic
                suggested_person_id = None
                matches = []
                if known_encodings:
                    # distance is euclidean distance
                    distances = face_recognition.face_distance(known_encodings, encoding)
                    # Find min distance
                    min_dist_idx = np.argmin(distances)
                    if distances[min_dist_idx] < 0.6: # Threshold
                        suggested_person_id = known_person_ids[min_dist_idx]

                # Store
                new_face = Face(
                    asset_id=asset.id,
                    person_id=suggested_person_id,
                    location=location, # [top, right, bottom, left]
                    encoding=pickle.dumps(encoding),
                    confidence=1.0, # dlib doesn't give confidence in this call easily, assume 1
                    is_confirmed=False
                )
                db.session.add(new_face)
            
            db.session.commit()
            count += 1
            
        except Exception as e:
            print(f"Face processing error on {asset.id}: {e}")

    return count

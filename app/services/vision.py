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
            
            # Step 2: Merge with Metadata (XMP-mwg-rs) logic
            # This ensures we pick up any existing names from the file tags
            try:
                from app.services import face_import_utils
                face_import_utils.import_faces_from_metadata(asset)
            except Exception as e:
                print(f"Metadata import warning for {asset.id}: {e}")

            count += 1
            
        except Exception as e:
            print(f"Face processing error on {asset.id}: {e}")

    return count

def scan_unknowns_for_match(person_id, tolerance=0.6, include_rejected=False):
    """
    Scans all unknown faces and checks if they match the given person.
    Returns number of new suggestions found.
    """
    if not FACE_REC_AVAILABLE:
        return 0
        
    person = Person.query.get(person_id)
    if not person:
        return 0
        
    # Get all confirmed encodings for this person
    confirmed_faces = Face.query.filter_by(person_id=person_id, is_confirmed=True).all()
    if not confirmed_faces:
        return 0
        
    known_encodings = []
    for f in confirmed_faces:
        try:
            arr = pickle.loads(f.encoding)
            known_encodings.append(arr)
        except:
            pass
            
    if not known_encodings:
        return 0
        
    # Get all unconfirmed faces (Unknown OR Suggested for others)
    # Optimization: Filter out faces already in person.rejected_matches
    
    rejected_ids = [f.id for f in person.rejected_faces]
     
    # query faces that are NOT confirmed (is_confirmed is False)
    # This allows stealing matches that were incorrectly suggested for someone else
    query = Face.query.filter(Face.is_confirmed == False)
    
    if rejected_ids and not include_rejected:
        # Only exclude rejected faces if we are NOT including them
        query = query.filter(Face.id.notin_(rejected_ids))
        
    unknown_faces = query.all()
    
    match_count = 0
    
    for face in unknown_faces:
        try:
            encoding = pickle.loads(face.encoding)
            
            # Compare
            distances = face_recognition.face_distance(known_encodings, encoding)
            # Check if ANY match fits the threshold? Or Average?
            # Typically min distance is best
            min_dist = np.min(distances)
            
            if min_dist < tolerance: # Use dynamic tolerance
                face.person_id = person_id
                face.is_confirmed = False # Suggested, not confirmed
                # face.confidence = ... update confidence based on dist? (1 - dist)
                face.confidence = 1.0 - min_dist
                match_count += 1
        except Exception as e:
            print(f"Error matching face {face.id}: {e}")
            continue
            
    if match_count > 0:
        db.session.commit()
        
    return match_count

def encode_face_region(file_path, top, right, bottom, left):
    """
    Attempts to compute a face encoding for a specific manually defined region.
    Returns the pickled encoding (bytes) or None if no face data could be computed.
    """
    if not FACE_REC_AVAILABLE:
        return None
        
    try:
        # Load with PIL to handle EXIF orientation
        from PIL import Image, ImageOps
        import numpy as np
        
        with Image.open(file_path) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert('RGB')
            image = np.array(img)
            
        locations = [(top, right, bottom, left)]
        
        # 'num_jitters' can be increased for better accuracy on re-sampling
        encodings = face_recognition.face_encodings(image, locations, num_jitters=1)
        
        if encodings:
            return pickle.dumps(encodings[0])
            
    except Exception as e:
        print(f"Error encoding manual region for {file_path}: {e}")
        
    return None

def find_best_matches_for_face(face_id):
    """
    Returns a list of (Person, min_distance) tuples, sorted by distance (ASC).
    Used to populate the 'Assign Face' dropdown with likely candidates.
    """
    target_face = Face.query.get(face_id)
    if not target_face or not target_face.encoding:
        return []
        
    try:
        target_encoding = pickle.loads(target_face.encoding)
    except:
        return []
        
    # Get all confirmed faces that have a person assigned
    # Optimization: This could be cached or pre-calculated in a real production app.
    known_faces = Face.query.filter(Face.is_confirmed == True, Face.person_id.isnot(None)).all()
    
    if not known_faces:
        return []
        
    # Prepare arrays
    known_encodings = []
    known_person_ids = []
    
    for kf in known_faces:
        try:
            arr = pickle.loads(kf.encoding)
            known_encodings.append(arr)
            known_person_ids.append(kf.person_id)
        except:
            continue
            
    if not known_encodings:
        return []
        
    # Calculate Distances
    # face_recognition.face_distance returns euclidean distance for each face
    # Lower is better.
    if FACE_REC_AVAILABLE:
        distances = face_recognition.face_distance(known_encodings, target_encoding)
    else:
        # Fallback if library missing (shouldn't happen if we have encodings)
        return []
        
    # Group by Person and find min distance
    person_scores = {} # person_id -> min_distance
    
    for pid, dist in zip(known_person_ids, distances):
        if pid not in person_scores:
            person_scores[pid] = dist
        else:
            if dist < person_scores[pid]:
                person_scores[pid] = dist
                
    # Create sorted list
    results = []
    all_people = Person.query.all()
    people_map = {p.id: p for p in all_people}
    
    # Add scored people
    for pid, score in person_scores.items():
        if pid in people_map:
            results.append((people_map[pid], score))
            
    # Add unscored people (infinite distance)
    for p in all_people:
        if p.id not in person_scores:
            results.append((p, 999.0))
            
    # Sort: Score ASC, then Name ASC
    results.sort(key=lambda x: (x[1], x[0].name))
    
    return results

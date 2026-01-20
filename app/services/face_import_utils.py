
import os
import pickle
import numpy as np
from app import db
from app.models import Asset, Face, Person
from app.services import metadata as metadata_service

def calculate_iou(box1, box2):
    """
    Calculates Intersection over Union (IoU) between two boxes.
    Box Format: [top, right, bottom, left] (dlib/face_recognition style)
    """
    # Determine intersection rectangle
    x_left = max(box1[3], box2[3])
    y_top = max(box1[0], box2[0])
    x_right = min(box1[1], box2[1])
    y_bottom = min(box1[2], box2[2])

    if x_right < x_left or y_bottom < y_top:
        return 0.0

    intersection_area = (x_right - x_left) * (y_bottom - y_top)

    # Determine union area
    box1_area = (box1[1] - box1[3]) * (box1[2] - box1[0])
    box2_area = (box2[1] - box2[3]) * (box2[2] - box2[0])
    
    union_area = box1_area + box2_area - intersection_area

    if union_area == 0:
        return 0.0

    return intersection_area / union_area

def mwg_to_css(area, width, height):
    """
    Converts MWG Area (Center X, Center Y, W, H normalized) to CSS Box [top, right, bottom, left] (pixels).
    MWG: x,y are center. w,h are dimensions. 0-1 normalized.
    CSS: top, right, bottom, left (pixels).
    """
    cx = float(area.get('X', 0.5))
    cy = float(area.get('Y', 0.5))
    w = float(area.get('W', 0))
    h = float(area.get('H', 0))
    
    # Calculate Top-Left and Bottom-Right in Normalized
    half_w = w / 2
    half_h = h / 2
    
    n_left = cx - half_w
    n_right = cx + half_w
    n_top = cy - half_h
    n_bottom = cy + half_h
    
    # Convert to Pixels
    top = int(n_top * height)
    bottom = int(n_bottom * height)
    left = int(n_left * width)
    right = int(n_right * width)
    
    # Clamp
    top = max(0, top)
    left = max(0, left)
    bottom = min(height, bottom)
    right = min(width, right)
    
    return [top, right, bottom, left]

def import_faces_from_metadata(asset):
    """
    Imports faces from asset metadata and merges with existing DB faces.
    """
    # 1. Get Metadata Regions
    # We need -struct output. get_metadata currently has -a. 
    # Let's assume get_metadata returns the struct if ExifTool gave it.
    # If not, we might need a specialized call. 
    # Using existing service for now.
    
    meta = metadata_service.get_metadata(asset.file_path)
    regions = metadata_service.extract_face_regions(meta)
    
    if not regions:
        return 0
        
    # Get image dimensions (from DB or meta)
    # meta usually has Composite:ImageSize = "1500x1125"
    if 'Composite:ImageSize' in meta:
        w_str, h_str = meta['Composite:ImageSize'].split('x')
        width = int(w_str)
        height = int(h_str)
    elif 'File:ImageWidth' in meta and 'File:ImageHeight' in meta:
        width = int(meta['File:ImageWidth'])
        height = int(meta['File:ImageHeight'])
    elif 'ImageWidth' in meta:
        width = int(meta['ImageWidth'])
        height = int(meta['ImageHeight'])
    else:
        # Fallback to load image? Expensive.
        print(f"Skipping import for {asset.id}: No dimensions found.")
        return 0
        
    existing_faces = Face.query.filter_by(asset_id=asset.id).all()
    
    imported_count = 0
    
    for r in regions:
        name = r['name']
        area = r['area']
        
        # Convert MWG to CSS Box
        mwg_box = mwg_to_css(area, width, height) # [top, right, bottom, left]
        
        # Check against existing
        matched_face = None
        best_iou = 0
        
        for face in existing_faces:
            # Face location is stored as JSON List [top, right, bottom, left]
            try:
                # Direct access if valid JSON column
                db_box = face.location
                if not db_box: continue
                
                iou = calculate_iou(mwg_box, db_box)
                
                if iou > 0.4 and iou > best_iou: # 0.4 overlap threshold
                    best_iou = iou
                    matched_face = face
            except:
                continue
                
        if matched_face:
            # UPDATE existing face
            
            # Prioritize Source Metadata Name? YES per user.
            # Even if face has a name, overwrite it if metadata has one?
            # User said: "If there are any cases where I had labeled a face... trust the source file"
            
            person = Person.query.filter_by(name=name).first()
            if not person:
                person = Person(name=name)
                db.session.add(person)
                db.session.commit() 
                
            matched_face.person_id = person.id
            matched_face.is_confirmed = True
            print(f"Updated Face {matched_face.id} with name '{name}' (IoU: {best_iou:.2f})")
            imported_count += 1
            
        else:
            # CREATE new face
            print(f"Creating NEW Face for '{name}' from metadata")
            
            person = Person.query.filter_by(name=name).first()
            if not person:
                person = Person(name=name)
                db.session.add(person)
                db.session.commit()
                
            new_face = Face(
                asset_id=asset.id,
                person_id=person.id,
                location=mwg_box, # Store as List, not pickle
                encoding=None, 
                confidence=1.0,
                is_confirmed=True
            )
            db.session.add(new_face)
            imported_count += 1

    db.session.commit()
    return imported_count

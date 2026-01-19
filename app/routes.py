from flask import Blueprint, render_template, current_app, flash, redirect, url_for, send_file
from flask import Blueprint, render_template, current_app, flash, redirect, url_for, send_file, request
import subprocess
import os
from app.models import Asset, Person, Face
from app import db
from datetime import datetime
from app.services.scanner import scan_directory
from app.models import Asset, Person, Face, LibraryPath
from app.services.vision import process_all_faces, scan_unknowns_for_match
from app.services.metadata import write_metadata, extract_ai_info, extract_camera_info, extract_gps_info, get_metadata
from app.utils import generate_thumbnail

main = Blueprint('main', __name__)

@main.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort', 'date_desc')
    path_filter = request.args.get('path_filter')

    query = Asset.query
    
    if path_filter:
        # Filter for files starting with the path. 
        # Ensure path ends with separator to avoid partial matches (e.g. /foo/bar matching /foo/bar_baz)
        # But we also want /foo/bar to match /foo/bar/image.jpg
        pf = path_filter
        if not pf.endswith(os.path.sep):
            pf += os.path.sep
        query = query.filter(Asset.file_path.startswith(pf))

    if sort_by == 'date_asc':
        query = query.order_by(Asset.captured_at.asc())
    elif sort_by == 'added_desc':
        query = query.order_by(Asset.added_at.desc())
    elif sort_by == 'added_asc':
        query = query.order_by(Asset.added_at.asc())
    else: # date_desc default
        query = query.order_by(Asset.captured_at.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    assets = pagination.items

    return render_template('index.html', 
                         assets=assets, 
                         pagination=pagination, 
                         sort_by=sort_by, 
                         search_query=None,
                         path_filter=path_filter)

@main.route('/browse_folder')
def browse_folder():
    """Opens a native OS dialog to select a folder (Server-side, works because app is local)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        root = tk.Tk()
        root.withdraw() # Hide the main window
        root.attributes('-topmost', True) # Bring to front
        
        folder_path = filedialog.askdirectory(title="Select Library Folder")
        root.destroy()
        
        return {"path": folder_path}
    except Exception as e:
        return {"error": str(e)}, 500

@main.route('/folders')
def browse_folders():
    # Security: Ensure req_path is within one of the LibraryPaths
    req_path = request.args.get('path', '')
    
    library_paths = LibraryPath.query.all()
    roots = [lp.path for lp in library_paths]
    
    if not req_path:
        # Show roots
        return render_template('folders.html', current_path='', folders=roots, assets=[], is_root=True)
    
    # Check if req_path is valid
    is_valid = False
    for root in roots:
        # Normalize paths for comparison
        if os.path.abspath(req_path).startswith(os.path.abspath(root)):
            is_valid = True
            break
            
    if not is_valid:
        flash("Access denied or invalid path.", "error")
        return redirect(url_for('main.browse_folders'))

    # List contents
    try:
        subfolders = []
        files = []
        
        with os.scandir(req_path) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    subfolders.append(entry.name)
                elif entry.is_file():
                    files.append(entry.name)
        
        subfolders.sort()
        files.sort()
        
        # Get DB assets for these files to show thumbnails/metadata
        # We need to reconstruct full paths. 
        # Note: os.scandir returns relative names in entry.name
        
        full_file_paths = [os.path.join(req_path, f) for f in files]
        assets = Asset.query.filter(Asset.file_path.in_(full_file_paths)).all()
        
        # Sort assets based on file list order or keep DB order? 
        # DB query result order is undefined unless ordered.
        # Let's map filename -> asset to easier display
        asset_map = {a.file_path: a for a in assets}
        
        display_files = []
        for f in files:
            full_path = os.path.join(req_path, f)
            display_files.append({
                'name': f,
                'path': full_path,
                'asset': asset_map.get(full_path)
            })
            
        parent_path = os.path.dirname(req_path)
        
        return render_template('folders.html', 
                               current_path=req_path, 
                               parent_path=parent_path, 
                               folders=subfolders, 
                               files=display_files,
                               is_root=False)

    except Exception as e:
        flash(f"Error accessing path: {e}", "error")
        return redirect(url_for('main.browse_folders'))

@main.route('/scan/delete/<int:id>', methods=['POST'])
def delete_library(id):
    lp = LibraryPath.query.get_or_404(id)
    path_name = lp.path
    
    # Automatic Cleanup: Remove assets associated with this path
    search_path = path_name
    if not search_path.endswith(os.path.sep):
        search_path += os.path.sep
        
    assets_to_delete = Asset.query.filter(Asset.file_path.startswith(search_path)).all()
    count = len(assets_to_delete)
    
    for asset in assets_to_delete:
        db.session.delete(asset)

    db.session.delete(lp)
    db.session.commit()
    flash(f"Stopped tracking folder: {path_name} and removed {count} associated records.", 'success')
    return redirect(url_for('main.scan'))

@main.route('/scan/cleanup', methods=['POST'])
def cleanup_orphans():
    assets = Asset.query.all()
    library_paths = LibraryPath.query.all()
    tracked_roots = [lp.path for lp in library_paths]
    
    deleted_count = 0
    untracked_count = 0
    missing_count = 0
    
    for asset in assets:
        # Check 1: File must exist on disk
        if not os.path.exists(asset.file_path):
            db.session.delete(asset)
            missing_count += 1
            deleted_count += 1
            continue
            
        # Check 2: File must be within a tracked library folder
        # We need to normalize paths for comparison to be safe
        is_tracked = False
        asset_path = os.path.normpath(asset.file_path)
        for root in tracked_roots:
            root_path = os.path.normpath(root)
            # Check if asset_path is inside root_path
            # commonpath returns the longest common sub-path
            try:
                if os.path.commonpath([asset_path, root_path]) == root_path:
                    is_tracked = True
                    break
            except ValueError:
                # Can happen on Windows if paths are on different drives
                continue
                
        if not is_tracked:
            db.session.delete(asset)
            untracked_count += 1
            deleted_count += 1
            
    if deleted_count > 0:
        db.session.commit()
        flash(f"Cleanup complete. Removed {deleted_count} items ({missing_count} missing from disk, {untracked_count} from untracked folders).", 'success')
    else:
        flash("No orphaned files found.", 'info')
        
    return redirect(url_for('main.scan'))

@main.route('/scan/all', methods=['POST'])
def scan_all_libraries():
    paths = LibraryPath.query.all()
    total_added = 0
    total_errors = 0
    scanned_count = 0
    
    for lp in paths:
        if os.path.exists(lp.path):
            a, s, e = scan_directory(lp.path)
            lp.last_scanned = datetime.utcnow()
            total_added += a
            total_errors += e
            scanned_count += 1
            
    db.session.commit()
    flash(f"Scanned {scanned_count} libraries. Added {total_added} new items. Errors: {total_errors}", 'success')
    return redirect(url_for('main.scan'))

@main.route('/scan', methods=['GET', 'POST'])
def scan():
    if request.method == 'POST':
        # Check if adding a new path
        new_path = request.form.get('new_path')
        if new_path:
            if os.path.exists(new_path):
                # Add to DB
                exists = LibraryPath.query.filter_by(path=new_path).first()
                if not exists:
                    lp = LibraryPath(path=new_path)
                    db.session.add(lp)
                    db.session.commit()
                    flash(f"Added library path: {new_path}", 'success')
                else:
                    flash("Path already exists.", 'warning')
            else:
                 flash("Path does not exist on disk.", 'error')
            return redirect(url_for('main.scan'))

        # Check if scanning a specific path ID
        scan_id = request.form.get('scan_id')
        if scan_id:
            lp = LibraryPath.query.get(scan_id)
            if lp and os.path.exists(lp.path):
                added, skipped, errors = scan_directory(lp.path)
                lp.last_scanned = datetime.utcnow() # Need datetime import
                db.session.commit()
                # For now, just render results or flash? 
                # Flash is better for persistent UI
                flash(f"Scan complete for {lp.path}. Added: {added}, Skipped: {skipped}, Errors: {errors}", 'info')
                return redirect(url_for('main.scan'))
            else:
                flash("Library path not found or invalid.", 'error')
    
    # GET: Show list
    libraries = LibraryPath.query.all()
    
    # Optional: Ad-hoc scan (legacy support or just one-off)
    return render_template('scan.html', libraries=libraries)

@main.route('/asset/<int:asset_id>/image')
def serve_image(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    return send_file(asset.file_path)

@main.route('/asset/<int:asset_id>/thumb')
def serve_thumbnail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    face_id = request.args.get('face_id')
    
    # Simple file serving if it's not an image (video etc)
    if asset.media_type not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
         return send_file(asset.file_path)

    # If face_id provided, crop on the fly!
    if face_id:
        face = Face.query.get(face_id)
        if face and face.location:
            try:
                from PIL import Image
                import io
                
                # Verify calling PIL for every request might be slow, 
                # but for local app it's often acceptable. Caching is better.
                # For now, on-the-fly.
                
                # location is [top, right, bottom, left]
                top, right, bottom, left = face.location
                
                # Add some padding?
                h = bottom - top
                w = right - left
                pad_h = int(h * 0.2)
                pad_w = int(w * 0.2)
                
                with Image.open(asset.file_path) as img:
                    width, height = img.size
                    
                    # Safe crop coords
                    crop_top = max(0, top - pad_h)
                    crop_bottom = min(height, bottom + pad_h)
                    crop_left = max(0, left - pad_w)
                    crop_right = min(width, right + pad_w)
                    
                    face_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
                    
                    # Resize for thumbnail consistency? 
                    # Let's keep it close to actual max-size or fixed thumb size
                    face_img.thumbnail((200, 200))
                    
                    img_io = io.BytesIO()
                    # Convert to RGB if needed (swallow errors for RGBA -> JPEG)
                    if face_img.mode in ('RGBA', 'P'):
                        face_img = face_img.convert('RGB')
                        
                    face_img.save(img_io, 'JPEG', quality=85)
                    img_io.seek(0)
                    return send_file(img_io, mimetype='image/jpeg')
            except Exception as e:
                print(f"Error cropping face: {e}")
                # Fallback to full thumb
                pass

    thumb_path = generate_thumbnail(asset.file_path, asset_id)
    
    if thumb_path and os.path.exists(thumb_path):
        return send_file(thumb_path)
    else:
        # Fallback
        return send_file(asset.file_path)

@main.route('/asset/<int:asset_id>')
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    
    # Navigation Logic (Previous/Next)
    sort_by = request.args.get('sort', 'date_desc')
    path_filter = request.args.get('path_filter')
    
    # Context for "Back to ..." button
    view_mode = request.args.get('view_mode', 'library') # 'library' or 'folder'
    folder_path = request.args.get('folder_path')
    
    back_url = url_for('main.index', sort=sort_by, path_filter=path_filter)
    back_label = "Back to Library"
    
    if view_mode == 'folder' and folder_path:
        back_url = url_for('main.browse_folders', path=folder_path)
        back_label = "Back to Folder"
        # For next/prev in folder mode, we might want to respect the folder sort order (usually name)
        # But for now, let's keep the standard sort unless we implement folder-specific sorting.
        # If user came from folder, path_filter should effectively be the folder_path to valid next/prev?
        # Actually asset_detail doesn't know the file list from browse_folders logic. 
        # But if we treat 'path_filter' as the folder path, our existing next/prev logic works!
        if not path_filter:
            path_filter = folder_path

    query = Asset.query
    if path_filter:
        pf = path_filter
        if not pf.endswith(os.path.sep):
            pf += os.path.sep
        query = query.filter(Asset.file_path.startswith(pf))

    if sort_by == 'date_asc':
        query = query.order_by(Asset.captured_at.asc())
    elif sort_by == 'added_desc':
        query = query.order_by(Asset.added_at.desc())
    elif sort_by == 'added_asc':
        query = query.order_by(Asset.added_at.asc())
    else: # date_desc default
        query = query.order_by(Asset.captured_at.desc())
        
    # Get all IDs in order. 
    # Performance note: fetching all IDs might be slow for massive DBs. 
    # For < 50k items, it's roughly okay. For larger, we'd need a subquery or window function.
    # Assuming local app scale for now.
    all_assets = query.with_entities(Asset.id).all()
    # all_assets is list of tuples (id,)
    asset_ids = [a[0] for a in all_assets]
    
    prev_id = None
    next_id = None
    
    try:
        curr_idx = asset_ids.index(asset_id)
        if curr_idx > 0:
            prev_id = asset_ids[curr_idx - 1]
        if curr_idx < len(asset_ids) - 1:
            next_id = asset_ids[curr_idx + 1]
    except ValueError:
        # Asset might not be in the current filter
        pass
    
    # Prepare face data for the frontend overlay
    faces_data = []
    for face in asset.faces:
        loc = face.location if face.location else [0, 0, 0, 0]
        faces_data.append({
            'id': face.id,
            'top': loc[0],
            'right': loc[1],
            'bottom': loc[2],
            'left': loc[3],
            'name': face.person.name if face.person else 'Unknown',
            'is_confirmed': face.is_confirmed
        })

    ai_info = extract_ai_info(asset.meta_json)
    camera_info = extract_camera_info(asset.meta_json)
    gps_info = extract_gps_info(asset.meta_json)
    
    # Fetch people for assignment dropdown
    people = Person.query.order_by(Person.name).all()
    
    return render_template('asset_detail.html', 
                         asset=asset, 
                         ai_info=ai_info, 
                         camera_info=camera_info, 
                         gps_info=gps_info,
                         faces_data=faces_data,
                         people=people,
                         prev_id=prev_id,
                         next_id=next_id,
                         current_sort=sort_by,
                         current_filter=path_filter,
                         back_url=back_url,
                         back_label=back_label,
                         view_mode=view_mode,
                         folder_path=folder_path)

@main.route('/face/<int:face_id>/delete', methods=['POST'])
def delete_face(face_id):
    face = Face.query.get_or_404(face_id)
    asset_id = face.asset_id
    db.session.delete(face)
    db.session.commit()
    flash("Face deleted.", "info")
    return redirect(url_for('main.asset_detail', asset_id=asset_id))

@main.route('/asset/<int:asset_id>/add_face', methods=['POST'])
def add_manual_face(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    
    try:
        top = int(float(request.form.get('top')))
        right = int(float(request.form.get('right')))
        bottom = int(float(request.form.get('bottom')))
        left = int(float(request.form.get('left')))
        
        # Validation
        if top < 0 or left < 0:
            raise ValueError("Negative coordinates")
            
        from app.services.vision import encode_face_region
        
        # Try to compute encoding for future matching
        encoding_blob = encode_face_region(asset.file_path, top, right, bottom, left)

        face = Face(
            asset_id=asset.id,
            location=[top, right, bottom, left],
            person_id=None, # Unknown
            is_confirmed=False,
            encoding=encoding_blob, # Store if found
            confidence=1.0 # Manual = 100% confidence it's a face
        )
        db.session.add(face)
        db.session.commit()
        
        if encoding_blob:
            flash("New face added manually (and analyzed for matching).", "success")
        else:
            flash("New face added manually (but could not be analyzed for matching - image data too vague).", "warning")
        
    except Exception as e:
        flash(f"Error adding face: {e}", "error")
        
    return redirect(url_for('main.asset_detail', asset_id=asset_id))

@main.route('/asset/<int:asset_id>/refresh_metadata')
def refresh_metadata(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    
    # Re-read metadata from disk
    new_meta = get_metadata(asset.file_path)
    
    if new_meta:
        asset.meta_json = new_meta
        # Optionally update timestamps if they are missing or changed?
        # For now, let's trust the scan time, or we could update captured_at if it was None.
        # Let's keep it simple: just update the JSON blob which contains GPS.
        db.session.commit()
        flash("Metadata successfully refreshed from disk.", "success")
    else:
        flash("Failed to read metadata from file.", "error")
        
    return redirect(url_for('main.asset_detail', asset_id=asset_id))

@main.route('/asset/<int:asset_id>/open_folder', methods=['POST'])
def open_folder(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    try:
        # Windows specific: explorer /select,"path" (highlights the file)
        # Verify path exists first
        if not os.path.exists(asset.file_path):
             flash(f"File not found on disk: {asset.file_path}", 'error')
        else:
            # We use subprocess.Popen to avoid blocking the server script
            # Windows Explorer requires backslashes and strict formatting for /select
            norm_path = os.path.normpath(asset.file_path)
            subprocess.Popen(f'explorer /select,"{norm_path}"')
            flash("Opened folder on server.", "success")
    except Exception as e:
        flash(f"Error opening folder: {e}", 'error')
        
    return redirect(url_for('main.asset_detail', asset_id=asset_id))

@main.route('/process_faces', methods=['POST'])
def trigger_face_processing():
    try:
        count = process_all_faces()
        flash(f"Processed {count} images for faces.", 'success')
    except Exception as e:
        flash(f"Error processing faces: {str(e)}", 'error')
    return redirect(url_for('main.scan'))

@main.route('/people', methods=['GET', 'POST'])
def people():
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            person = Person(name=name)
            db.session.add(person)
            db.session.commit()
    
    people = Person.query.all()
    # diverse list of unknown faces (distinct asset?)
    unknown_faces = Face.query.filter_by(person_id=None).limit(50).all()
    return render_template('people.html', people=people, unknown_faces=unknown_faces)

@main.route('/person/<int:person_id>/rename', methods=['POST'])
def rename_person(person_id):
    person = Person.query.get_or_404(person_id)
    new_name = request.form.get('new_name')
    
    if new_name:
        # Check uniqueness
        existing = Person.query.filter_by(name=new_name).first()
        if existing and existing.id != person.id:
            flash(f"Name '{new_name}' already exists. Please choose another.", "error")
        else:
            person.name = new_name
            db.session.commit()
            flash(f"Renamed to {new_name}.", "success")
            
    return redirect(url_for('main.person_detail', person_id=person.id))

@main.route('/face/<int:face_id>/assign/<int:person_id>')
def assign_face(face_id, person_id):
    face = Face.query.get_or_404(face_id)
    face.person_id = person_id
    face.is_confirmed = True
    db.session.commit()
    return redirect(url_for('main.people'))

@main.route('/person/<int:person_id>')
def person_detail(person_id):
    person = Person.query.get_or_404(person_id)
    confirmed_faces = Face.query.filter_by(person_id=person.id, is_confirmed=True).all()
    suggested_faces = Face.query.filter_by(person_id=person.id, is_confirmed=False).all()
    
    # Fetch all people for the reassignment modal
    people = Person.query.order_by(Person.name).all()
    
    # We need asset data for thumbnails
    return render_template('person_detail.html', 
                         person=person, 
                         confirmed=confirmed_faces, 
                         suggested=suggested_faces,
                         people=people)

@main.route('/face/<int:face_id>/confirm/<int:person_id>')
def confirm_face(face_id, person_id):
    face = Face.query.get_or_404(face_id)
    face.person_id = person_id
    face.is_confirmed = True
    db.session.commit()
    flash("Face confirmed.", "success")
    return redirect(url_for('main.person_detail', person_id=person_id))

@main.route('/face/<int:face_id>/remove')
def remove_face(face_id):
    face = Face.query.get_or_404(face_id)
    old_person_id = face.person_id
    
    # Store rejection memory if it was assigned/suggested to a person
    if old_person_id:
        person = Person.query.get(old_person_id)
        if person:
            # Check if likely already rejected? (Set lookup handles dups usually, but append is safe)
            # using the relationship
            if face not in person.rejected_faces:
                person.rejected_faces.append(face)
    
    face.person_id = None
    face.is_confirmed = False
    db.session.commit()
    flash("Face removed/rejected.", "info")
    if old_person_id:
        return redirect(url_for('main.person_detail', person_id=old_person_id))
    return redirect(url_for('main.people'))

@main.route('/person/<int:person_id>/find_matches', methods=['POST'])
def find_matches(person_id):
    try:
        count = scan_unknowns_for_match(person_id)
        if count > 0:
            flash(f"Found {count} new potential matches!", "success")
        else:
            flash("No new matches found in unknown faces.", "info")
    except Exception as e:
        flash(f"Error scanning for matches: {e}", "error")
        
    return redirect(url_for('main.person_detail', person_id=person_id))

@main.route('/person/<int:person_id>/confirm_all', methods=['POST'])
def confirm_all_matches(person_id):
    person = Person.query.get_or_404(person_id)
    # Find all unconfirmed faces for this person
    count = Face.query.filter_by(person_id=person.id, is_confirmed=False).update({
        'is_confirmed': True
    })
    db.session.commit()
    
    if count > 0:
        flash(f"Confirmed {count} faces for {person.name}.", "success")
    else:
        flash("No suggested matches found to confirm.", "info")
        
    return redirect(url_for('main.person_detail', person_id=person_id))

@main.route('/person/<int:person_id>/reject_all', methods=['POST'])
def reject_all_matches(person_id):
    person = Person.query.get_or_404(person_id)
    # Find all unconfirmed faces for this person
    faces_to_reject = Face.query.filter_by(person_id=person.id, is_confirmed=False).all()
    
    count = 0
    for face in faces_to_reject:
        if face not in person.rejected_faces:
            person.rejected_faces.append(face)
        face.person_id = None
        face.is_confirmed = False
        count += 1
        
    db.session.commit()
    
    if count > 0:
        flash(f"Rejected {count} faces for {person.name}.", "info")
    else:
        flash("No suggested matches found to reject.", "info")
        
    return redirect(url_for('main.person_detail', person_id=person_id))

@main.route('/assign_face_form', methods=['POST'])
def assign_face_form():
    face_id = request.form.get('face_id')
    action = request.form.get('action') # 'save' or 'remove'
    
    face = Face.query.get_or_404(face_id)
    
    if action == 'remove':
        old_name = face.person.name if face.person else 'Unknown'
        face.person_id = None
        face.is_confirmed = False
        db.session.commit()
        flash(f"Unassigned face (was {old_name}).", "info")
        return redirect(url_for('main.asset_detail', asset_id=face.asset_id))
        
    person_id = request.form.get('person_id') # From dropdown
    new_person_name = request.form.get('new_person_name') # Explicit new name
    
    target_person = None
    
    if new_person_name and new_person_name.strip():
        # Create new person
        name = new_person_name.strip()
        target_person = Person.query.filter_by(name=name).first()
        if not target_person:
            target_person = Person(name=name)
            db.session.add(target_person)
            db.session.flush() # get ID
            flash(f"Created new person: {target_person.name}", "success")
    elif person_id:
        target_person = Person.query.get(person_id)
        
    if target_person:
        face.person = target_person
        face.is_confirmed = True
        db.session.commit()
        flash(f"Face assigned to {target_person.name}.", "success")
    else:
        flash("No person selected or created.", "warning")
        
    return redirect(url_for('main.asset_detail', asset_id=face.asset_id))


@main.route('/sync')
def sync_all():
    # Example sync: Sync confirmed people names to keywords? or Title?
    # For MVP, let's just sync the Title from DB to File if changed.
    # Or Sync People names to 'Subject' or 'PersonInImage' (XMP) logic?
    # Let's simple sync: Title -> Title.
    
    assets = Asset.query.all()
    count = 0
    for asset in assets:
        tags = {}
        if asset.title:
            tags['Title'] = asset.title
        
        # Sync People
        confirmed_faces = asset.faces.filter_by(is_confirmed=True).all()
        people_names = [f.person.name for f in confirmed_faces if f.person]
        if people_names:
            tags['Subject'] = people_names # ExifTool handles list for Subject/Keywords usually, or repeated args.
            # subprocess list logic might need care, usually -Subject=Name1 -Subject=Name2
            # Our simple wrapper does -key=value. 
            # We might need to update wrapper for list support or join with specific delimiter.
            # ExifTool often accepts comma separated for some tags?
            # Let's stick to Title for MVP safety.
        
        if tags:
            if write_metadata(asset.file_path, tags):
                count += 1
                
    return f"Synced metadata for {count} assets. <a href='/'>Home</a>"

@main.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        return render_template('index.html', assets=[], search_query=None)
    
    # Simple SQL LIKE search
    # Searching Title or Meta JSON string
    # Note: Accessing meta_json as text might vary by DB driver, but in SQLite it's stored as text/JSON.
    # We can cast to text or just search the column if SQLAlchemy allows.
    # For SQLite, JSON columns are often just text.
    
    search_term = f"%{query}%"
    base_query = Asset.query.filter(
        (Asset.title.like(search_term)) | 
        (Asset.meta_json.cast(db.String).like(search_term))
    )
    # Re-use path filtering logic if provided
    path_filter = request.args.get('path_filter')
    if path_filter:
        pf = path_filter
        if not pf.endswith(os.path.sep):
            pf += os.path.sep
        base_query = base_query.filter(Asset.file_path.startswith(pf))

    # Re-use sort logic
    sort_by = request.args.get('sort', 'date_desc')
    if sort_by == 'date_asc':
        base_query = base_query.order_by(Asset.captured_at.asc())
    elif sort_by == 'added_desc':
        base_query = base_query.order_by(Asset.added_at.desc())
    elif sort_by == 'added_asc':
        base_query = base_query.order_by(Asset.added_at.asc())
    else:
        base_query = base_query.order_by(Asset.captured_at.desc())

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    results = pagination.items
    
    return render_template('index.html', assets=results, pagination=pagination, sort_by=sort_by, search_query=query, path_filter=path_filter)

from flask import Blueprint, render_template, current_app, flash, redirect, url_for, send_file
from flask import Blueprint, render_template, current_app, flash, redirect, url_for, send_file, request
import subprocess
import os
from app.models import Asset, Person, Face
from app import db
from datetime import datetime
from app.services.scanner import scan_directory
from app.models import Asset, Person, Face, LibraryPath
from app.services.vision import process_all_faces
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
    db.session.delete(lp)
    db.session.commit()
    flash(f"Stopped tracking folder: {path_name}", 'success')
    flash(f"Stopped tracking folder: {path_name}", 'success')
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
    
    # Only generate thumbs for images
    if asset.media_type not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
         # For non-images, we might want a placeholder or just 404? 
         # But the UI handles this by checking media_type.
         # If called anyway, serve full file or a placeholder?
         # Let's serve full file as fallback/placeholder logic is in UI.
         return send_file(asset.file_path)

    thumb_path = generate_thumbnail(asset.file_path, asset_id)
    
    if thumb_path and os.path.exists(thumb_path):
        return send_file(thumb_path)
    else:
        # Fallback
        return send_file(asset.file_path)

@main.route('/asset/<int:asset_id>')
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    ai_info = extract_ai_info(asset.meta_json)
    camera_info = extract_camera_info(asset.meta_json)
    gps_info = extract_gps_info(asset.meta_json)
    gps_info = extract_gps_info(asset.meta_json)
    return render_template('asset_detail.html', asset=asset, ai_info=ai_info, camera_info=camera_info, gps_info=gps_info)

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

@main.route('/process_faces')
def trigger_face_processing():
    count = process_all_faces()
    return f"Processed {count} images for faces. <a href='/'>Back to Home</a>"

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

@main.route('/face/<int:face_id>/assign/<int:person_id>')
def assign_face(face_id, person_id):
    face = Face.query.get_or_404(face_id)
    face.person_id = person_id
    face.is_confirmed = True
    db.session.commit()
    return redirect(url_for('main.people'))

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

# PhotoArchiveDB: Master System Specification

**Version:** 4.0 (Unified Master)
**Date:** 2026-01-20
**Status:** Active/Implemented

---

## 1. System Philosophy & Architecture

### 1.1 Core Directives
**PhotoArchiveDB** is built on a "Local-First, File-Centric" philosophy. It differs from traditional DAMs (like Lightroom or Google Photos) by treating the user's file system as the **only permanent source of truth**.

1.  **The File is King**: The database is a transient index. If the SQLite file is deleted, it can be fully rebuilt by re-scanning the images.
2.  **Metadata Permeability**: All organizational work (ratings, titles, face tags) must be writable to the files themselves using standard XMP/IPTC tags. This ensures data survives if the user migrates to different software.
3.  **Self-Healing**: The system must handle files being moved, renamed, or reorganized outside of the app without losing data.
4.  **Privacy**: No external cloud dependencies. AI runs on the CPU.

### 1.2 Technology Stack
*   **Backend**: Python 3.10+ running Flask (WSGI).
    *   *Rationale*: Python offers the strongest ecosystem for both local IO scriptability (`os`, `shutil`) and AI/Vision libraries (`dlib`, `numpy`).
*   **Database**: SQLite 3.35+
    *   *Configuration*: `PRAGMA journal_mode=WAL` (Write-Ahead Logging).
    *   *Rationale*: WAL allows concurrent readers and writers. This is critical for a local app where a background scan (Writer) might run while the user browses (Reader). Standard rollback mode would lock the interface.
*   **Vision Engine**: `dlib` (C++ bindings) + `face_recognition`.
    *   *Model*: HOG (Histogram of Oriented Gradients) for detection, ResNet-34 for encoding.
    *   *Rationale*: HOG is CPU-efficient and sufficient for "Family Photo" resolution. CID (Convolutional) detectors are more accurate but require CUDA/GPUs which average users may not have.
*   **Metadata Engine**: `ExifTool` by Phil Harvey.
    *   *Rationale*: The industry standard for robust, safe metadata IO. We use it via `subprocess` rather than native Python libraries (`piexif`) because ExifTool handles thousands of edge-case Vendor MakerNotes that other libraries corrupt.

---

## 2. Data Layer Specification

### 2.1 Database Schema
The schema is normalized to separate Physical Content (`assets`) from Identity (`people`) and Biometrics (`faces`).

#### Table: `assets`
*   **`id`** (Integer, PK): Internal reference.
*   **`file_path`** (String, Unique): Absolute path on disk.
*   **`file_hash`** (String, Index): **SHA-256** of the first 64KB + File Size.
    *   *Rationale*: Full hashing is IO-prohibitive for Terabyte archives. A 64KB head-hash combined with exact file size is statistically unique enough for collision avoidance in personal libraries.
*   **`captured_at`** (DateTime): The "True" creation date derived from Exif.
*   **`meta_json`** (JSON): A cached dump of the full ExifTool output.

#### Table: `faces`
*   **`id`** (Integer, PK): Internal reference.
*   **`encoding`** (Blob): 128-float vector (Pickled NumPy array). This is the "Faceprint".
*   **`location`** (JSON): `[top, right, bottom, left]` pixel coordinates.
*   **`confidence`** (Float): `1.0` for Manual/Legacy faces. `<1.0` for AI detections.
*   **`is_confirmed`** (Bool): `True` = Human Verified / `False` = AI Suggestion.

#### Table: `rejected_matches`
*   **`face_id`** / **`person_id`** (Composite PK): Records that a specific face is definitively *NOT* a specific person.
*   *Rationale*: Prevent the AI from repeatedly suggesting the same wrong match (The "Nagging" problem).

---

## 3. Core Module: The Scanner (Ingestion)

### 3.1 Functional Goal
To maintain a synchronized state between the File System and the Database without requiring the user to manually "import" files.

### 3.2 The "Self-Healing" Algorithm
Executed in `services/scanner.py`.

1.  **Walk**: Iterate through `LibraryPaths`.
2.  **Filter**: Ignore `.` dotfiles. Check if extension is in `ALLOWED_EXTENSIONS`.
3.  **Hash**: Calculate the 64KB Head-Hash.
4.  **Drift Detection (The Logic)**:
    *   Query DB: `SELECT * FROM assets WHERE file_hash = ?`.
    *   **Case A (No Match)**: It's a new photo. -> **INSERT**.
    *   **Case B (Match Found, Path Same)**: No change. -> **SKIP**.
    *   **Case C (Match Found, Path Different)**: The user moved the file. -> **UPDATE file_path**.
        *   *Result*: The Asset ID remains the same. The Face tags, Ratings, and Person links follow the file to its new location.

---

## 4. Core Module: Face Recognition (Forensics)

### 4.1 The Pipeline
The system uses a multi-stage pipeline to handle the messiness of real-world photography.

#### Phase 1: Rotation-Aware Detection
*   **Problem**: `face_recognition` loads images as raw pixel arrays. If a photo is taken in Portrait mode, the raw pixels are sideways. The AI looks for upright faces and fails.
*   **Solution**: We apply `ImageOps.exif_transpose` (from Pillow) *before* passing the array to the detector. This aligns the pixel grid with the visual orientation.

#### Phase 2: Smart Sort (Identification)
*   **Problem**: Sorting "Unknown" faces alphabetically (by potential match name?) is useless.
*   **Solution**: Euclidean Distance Ranking.
    *   For every Unknown Face ($U$), we calculate the distance to the centroid of every Known Person ($P$).
    *   Matches are returned sorted by Similarity Score (`(1.0 - distance) * 100`).
    *   *UI Implementation*: In the "Assign Face" dropdown, likely matches appear at the top with a Green Star.

#### Phase 3: Manual "Force-Read"
*   **Scenario**: The AI fails to detect a face (obscured, profile, blurry).
*   **Mechanism**:
    1.  User draws a box on the UI.
    2.  Coordinates sent to backend.
    3.  Backend **Force-Crops** that region.
    4.  The crop is fed directly to the ResNet Encoder (bypassing the Detector).
    5.  Result: A valid biometric encoding is generated for a "non-detected" face, allowing it to be matched in the future.

#### Phase 4: Legacy Import (Interop)
*   **Scenario**: User has existing face tags from Picasa/Lightroom.
*   **Mechanism**:
    1.  Scanner checks `XMP-mwg-rs:Regions`.
    2.  Parses the normalized (0..1) coordinates.
    3.  Runs the "Force-Read" logic on those regions to generate encodings.
    4.  Auto-creates Persons based on the XMP Name.

---

## 5. Core Module: Metadata Engine

### 5.1 The Safety Layer ("Atomic Writes")
We treat file modification as a critical operation. No write occurs without a recovery path.

**The Protocol (`services/metadata_writer.py`)**:
1.  **Resolve Backup Path**: `.metadata_history/YYYY/MM/DD/`.
2.  **Snapshot**: Execute `exiftool -j -struct source.jpg > backup.json`.
3.  **Verify**: Check that the backup file exists and is valid JSON.
4.  **Write**: Execute the write command.
5.  **Rollback**: (Manual via UI) The "Restore" feature reads the JSON backup and re-applies the tags.

### 5.2 Hybrid Write Strategy
*   **Standard Formats** (JPG, PNG, TIFF): **Embedded**.
    *   Argument: `-overwrite_original_in_place`. (Preserves system file creation dates).
*   **Proprietary RAW** (CR2, NEF, ARW): **Sidecar**.
    *   Argument: `-overwrite_original` on a `.xmp` file.
    *   *Rationale*: Never risk byte-level corruption of a RAW sensor dump.

---

## 6. User Interface Specification (UI/UX)

This section details the functional surfaces of the application.

### 6.1 View: Asset Detail (`/asset/<id>`)
A deep-inspection view for single items.

**A. Image Interaction**
*   **Navigation**: Left/Right absolute floating arrows. *Keys: ArrowLeft/ArrowRight*.
    *   *Context Logic*: If you filtered by "Folder: Vacation", clicking Next goes to the next photo *in that folder*, not the next ID in the DB.
*   **Face Overlay**:
    *   **Confirmed Faces**: Green Border. Hover shows name.
    *   **Suggestions**: Yellow Border.
    *   **Interaction**: Click any box to open the **Assign Modal**.
*   **Manual Add**:
    *   Click "Add Missing Face" button.
    *   Cursor changes to Crosshair.
    *   Draw box -> Auto-opens Confirmation Modal.

**B. Data Panel**
*   **Tabs**: "Current" (Live Data) vs "History" (Backups).
*   **Star Rating**: Interactive 1-5 stars. Clicking triggers an AJAX Atomic Write.
*   **Modals**:
    *   **AI Info**: Shows Stable Diffusion prompt/seed if present.
    *   **Camera Info**: ISO/Shutter/Aperture grid.
    *   **View on Google Maps**: If GPS coordinates exist, opens the location in a new tab.
    *   **Edit Metadata**: Form for Title/Description/Rating.

### 6.2 View: Person Detail (`/person/<id>`)
The Workbench for identity management.

**A. The "Find Matches" Toolbar**
Designed for high-throughput tagging.
*   **Tolerance Slider**: 0.4 (Strict) - 0.8 (Loose). Adjusts the radius of the search.
*   **"Include Rejected"**: A checkbox that bypasses the `rejected_matches` table. Critical for recovering false-negatives (e.g., you accidentally rejected a valid match).
*   **Bulk Actions**: "Confirm All" / "Reject All" buttons.

**B. The Grid System**
*   **Suggested Queue**: Thumbnails sorted by Confidence.
    *   *Actions*: Confirm (Check), Reject (X), Re-assign (Pencil), View Full (Eye).
*   **Confirmed Gallery**: All verified faces.
    *   *Correction*: "Incorrect?" link un-links the face but preserves the biometric region (demotes to Unknown).

---

## 7. API & Routing Reference

### 7.1 Key Endpoints
*   **`GET /scan`**: Triggers main library scan. Returns stream of `Scan complete` events.
*   **`POST /person/<id>/find_matches`**:
    *   Payload: `tolerance`, `include_rejected`.
    *   Logic: Runs `services.vision.scan_unknowns_for_match`.
*   **`POST /asset/<id>/update_metadata`**:
    *   Payload: `title`, `description`, `rating`.
    *   Logic: Triggers `metadata_writer.write_metadata` (Backup -> Write).

### 7.2 Context Preservation
*   **Mechanism**: Use of Query Parameters (`path_filter`, `sort`, `page`).
*   **Implementation**: Every internal link (Next Photo, Back to Grid) appends `request.args`. This ensures that if a user drills down into a specific search result, they don't lose their place when navigating up/down the hierarchy.


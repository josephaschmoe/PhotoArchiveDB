# Project Specification: ArchiveDB

**Goal:** A standalone personal Digital Asset Management (DAM) system for cataloging, searching, and tagging scanned historical assets.
**Philosophy:** "Better than nothing." robust simplicity over complex microservices.
**Stack:** Python (Flask), SQLite, HTML/Bootstrap.

---

## 1. Database Schema (Hybrid SQL + JSON)

We will use SQLite. The core philosophy is to keep shared structural data in rigid columns and flexible asset-specific data in a JSON column.

### Table: `assets`
*Primary storage for all files (photos, documents, letters).*

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | Auto-incrementing. |
| `file_path` | TEXT NOT NULL | Absolute path to the file on disk. Unique index. |
| `file_hash` | TEXT | SHA-256 hash for duplicate detection. Indexed. |
| `added_at` | DATETIME | When the record was created in the DB. |
| `captured_at` | DATETIME | Extracted "Date Taken" or "Creation Date". Nullable. Indexed. |
| `media_type` | TEXT | 'image', 'video', 'pdf', 'text', etc. |
| `title` | TEXT | Short display title. Defaults to filename if empty. |
| `meta_json` | JSON | **The Flexible Core.** Stores type-specific data. |

**`meta_json` Structure Examples:**
*Photo:*
```json
{
  "width": 4000,
  "height": 3000,
  "camera": "Canon EOS 5D",
  "aperture": 1.8,
  "iso": 400,
  "tags": ["vacation", "grandma"]
}
```
*Letter:*
```json
{
  "page_count": 2,
  "recipient": "John Doe",
  "sender": "Jane Doe",
  "ocr_text": "Dearest John..."
}
```

### Table: `people`
*Identity registry.*

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | |
| `name` | TEXT NOT NULL | The person's name. Unique. |
| `created_at` | DATETIME | |

### Table: `faces`
*Stores detected face encodings and links them to assets and people.*

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | |
| `asset_id` | INTEGER | FK to `assets.id`. |
| `person_id` | INTEGER | FK to `people.id`. Nullable (if unidentified). |
| `encoding` | BLOB | The 128-d vector from `face_recognition`. |
| `location` | JSON | Bounding box `[top, right, bottom, left]`. |
| `confidence` | FLOAT | Detection confidence score (if available). |
| `is_confirmed` | BOOLEAN | `0` = Machine match (suggestion), `1` = User confirmed. |

---

## 2. Project Structure (Flask)

We will use a simplified Flask factory pattern to allow for easy growth without over-engineering.

```text
/ArchiveDB
├── app/
│   ├── __init__.py          # create_app(), db init
│   ├── models.py            # SQLAlchemy models (Asset, Person, Face)
│   ├── routes.py            # Main view functions
│   ├── services/
│   │   ├── scanner.py       # File system walker, new file detection
│   │   ├── metadata.py      # ExifTool wrapper (Read/Write)
│   │   └── vision.py        # Face recognition logic
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   └── templates/
│       ├── base.html
│       ├── index.html       # Grid view
│       ├── asset_detail.html
│       └── people.html      # Face clustering UI
├── instance/
│   └── archivedb.sqlite
├── config.py                # Configuration classes
├── run.py                   # Entry point
├── requirements.txt
└── SPEC.md
```

---

## 3. Feature Logic

### Face Recognition Workflow

1.  **Ingest (Background/Triggered Task)**
    *   Iterate through the library folder.
    *   If a file is new, read metadata (ExifTool) and insert into `assets`.
    *   If it's an image, pass to `services.vision.process_asset(asset_id)`.

2.  **Detect & Store**
    *   `face_recognition.load_image_file()` loads the image.
    *   `face_recognition.face_locations()` finds bounding boxes.
    *   `face_recognition.face_encodings()` generates 128-d vectors.
    *   Insert into `faces` table with `person_id = NULL` and `is_confirmed = 0`.

3.  **Clustering & Matching (The "Suggestion" Phase)**
    *   When a new face is found, compare its encoding against known `Faces` that include a `person_id`.
    *   Calculate Euclidean distance (`face_recognition.face_distance`).
    *   If distance < threshold (e.g., 0.6), tentatively assign `person_id` and keep `is_confirmed = 0`.

4.  **User Tagging (The Feedback Loop)**
    *   **UI - Unknowns:** "Here are faces we see often but don't know." User names them -> Create/Link `Person`.
    *   **UI - Suggestions:** "Is this Uncle Bob?" User clicks "Yes" -> Set `is_confirmed = 1`.
    *   **Retraining:** Not strictly "retraining" a model, but adding more "confirmed" vectors to the reference set for Uncle Bob improves future matching accuracy (by comparing against all confirmed instances or a mean vector).

### Metadata Strategy (Sync)

*   **Read:** Occurs during Ingest. `ExifTool` stdout -> JSON -> DB `meta_json`.
*   **Write (Sync):**
    *   User edits Title, Date, or Tags in the Web UI.
    *   Changes save to the **Database** immediately.
    *   User clicks "Sync to Files" (Global or Per-Asset).
    *   System constructs ExifTool command: `exiftool -Title="New Title" -Subject="Tag1" ... file.jpg`
    *   Executes command to update physical file.

---

## 4. Implementation Plan (Phase 1 MVP)

- [ ] **Step 1: Boilerplate**: Set up Flask, SQLite connection, and base HTML templates.
- [ ] **Step 2: Basic Ingest**: Build `scanner.py` to walk a directory, hash files, and populate `assets` table (Path + Filename only).
- [ ] **Step 3: Metadata extraction**: Integrate `exiftool` to populate `captured_at` and `meta_json`.
- [ ] **Step 4: Grid View**: Create a simple Bootstrap grid to display assets (thumbnails generated on the fly or lazy-loaded).
- [ ] **Step 5: Face Detection**: Implement `vision.py` to run on a single image and save results to `faces` table.
- [ ] **Step 6: People UI**: Build a page to view faces and assign names (create `People` records).
- [ ] **Step 7: Sync Logic**: Implement the database-to-file tag writing using ExifTool.

```

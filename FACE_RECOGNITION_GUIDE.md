# Face Recognition System: Technical Guide

## Overview
PhotoArchiveDB implements a **local-first, privacy-focused face recognition system**. Unlike cloud services, all processing happens on your device. The system is designed not just to detect faces, but to provide a robust workflow for **managing** them—handling corrections, misses, and false positives with the same fidelity as a human archivist.

---

## 1. System Architecture

### Detection Engine
*   **Library**: Powered by `dlib` (HOG/CNN models) and `face_recognition`.
*   **Process**:
    1.  **Scan**: Iterates through images, converting them to RGB.
    2.  **Detect**: Locates face bounding boxes (Top, Right, Bottom, Left).
    3.  **Encode**: Generates a 128-dimensional vector ("encoding") representing the unique biometric features of the face.
    4.  **Store**: Saves the location JSON and the encoding blob (pickle) to the SQLite database.

### Storage Model
*   **Assets**: The source images.
*   **Faces**: Individual detection instances. Each `Face` is linked to an `Asset`.
*   **People**: The identity entities. `Faces` are assigned to `People`.
*   **Rejected Matches**: A dedicated memory table that tracks when a user says "Face X is NOT Person Y". This prevents the AI from making the same mistake twice.

---

## 2. Key Features & Logic

### A. Manual Face Addition (The "Force-Read" Protocol)
Most face scanners fail on side profiles, partially obscured faces, or artistic/blurry shots. We implemented a hybrid approach:
1.  **User Interaction**: The user draws a bounding box manually on the UI.
2.  **Region Encoding**: Instead of just saving a dumb box, the backend **isolates that specific region** and forces the encoding engine to analyze just those pixels.
3.  **Result**:
    *   **Success**: If the crop contains enough detail, we generate a valid encoding. This manual face becomes **matchable**—the AI can now find this person in other photos.
    *   **Fallback**: If the crop is too vague, we save the box for tagging purposes but flag it as "Unmatchable" to prevent pollution of the clustering algorithm.

### B. False Positive Management
AI models occasionally identify shadow patterns or clothing folds as faces.
*   **Action**: "Not a Face" button.
*   **Effect**: Hard deletion of the `Face` record.
*   **Design Choice**: We chose immediate deletion over a "Hidden/Ignored" flag to keep the database lean. Re-scanning will re-detect it, but for a personal archive, this trade-off is acceptable for simplicity.

### C. Persistent Learning (Rejection Memory)
If the AI mistakenly clusters "Uncle Bob" as "Aunt Mary":
1.  User clicks "Reject" or "Unassign".
2.  We insert a record into `rejected_matches (face_id, person_id)`.
3.  **Future Impact**: The `find_matches` algorithm joins against this table. Even if the biometric similarity is high (e.g., siblings), the system respects the user's explicit "No" forever.

### D. Dynamic Match Sensitivity
Biometrics aren't black and white. Lighting, age, and blur affect similarity scores.
*   We expose the **Euclidean Distance Threshold** (0.4 to 0.8) to the user via a slider.
*   **Strict (0.4)**: Only identical inputs match. Best for distinguishing siblings.
*   **Loose (0.6-0.8)**: Catches faces across decades of aging or poor lighting.

---

## 3. Performance & Concurrency
Long-running background scans used to lock the database, freezing the UI.
*   **Solution**: **Write-Ahead Logging (WAL)**.
*   **Implementation**: `PRAGMA journal_mode=WAL` is enabled on database connection.
*   **Benefit**: This allows the "Scanner" (Writer) and the "User Browser" (Reader) to operate simultaneously without locking errors.

## 4. Navigation Context
Navigation (Next/Prev) is context-aware. If you are filtering by "Folder: Summer 2024" or "Person: John", the arrow keys traverse **only suitable candidates**, preserving your mental model of the collection.

---

## 5. Standards & Interoperability (Planned)

To ensure your work isn't locked into this application, we aim to adhere to industry standards for metadata. **(Implementation Pending)**

### The Standard: XMP-mwg-rs
We plan to utilize the **Metadata Working Group (MWG)** region schema for storing face tags. This is the **exact same standard** used by:
*   **Adobe Lightroom Classic**
*   **DigiKam**
*   **Picasa (Legacy)**
*   **Excire Foto** (via XMP sidecar export)

### Metadata Structure
When exporting or syncing metadata, we will write to the XMP block (embedded or `.xmp` sidecar):
*   **Namespace**: `http://www.metadataworkinggroup.com/schemas/regions/`
*   **Prefix**: `mwg-rs`
*   **Fields**:
    *   `Type`: "Face"
    *   `Name`: Person's Name (e.g., "John Doe")
    *   `Area`: Normalized coordinates (0.0 - 1.0) for `x`, `y`, `w`, `h`.

---

## 6. Import Workflow (Smart Ingestion) [Planned]

Future versions of PhotoArchiveDB will check for existing XMP metadata (from Lightroom, Excire, etc.) to **process pre-tagged images intelligently**.

### The Logic: "Trust but Verify"
If an image has existing `XMP-mwg-rs` face regions:

1.  **Skip Detection**: We will NOT need to run the slow face-detection algorithm to find *where* the faces are. We simply read the existing boxes from the XMP.
2.  **Forced Encoding**:
    *   We **MUST** still run the `encoding` pass on those specific crops.
    *   *Why?* XMP stores the *name* and *box*, but not the biometric vector. To allow this face to be found in *future, untagged* photos, we need to generate its biometric signature.
3.  **Auto-Assignment**:
    *   Ideally, we read the `Description` or `Name` field from the XMP region.
    *   We verify if "Person: John Doe" exists in our DB. If not, we create it.
    *   We assign the newly encoded face to that Person ID automatically.

### Summary of Benefit
*   **Speed**: Faster scanning (skipped detection step).
*   **Continuity**: Your years of tagging in Lightroom/Excire are preserved.
*   **Training**: Every imported face immediately becomes "training data" for our AI, making it smarter at recognizing those people in new, untagged photos.

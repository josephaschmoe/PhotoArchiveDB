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

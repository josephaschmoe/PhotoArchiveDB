# PhotoArchiveDB: Strategic Enhancement Roadmap

**Target Version:** 5.0
**Status:** Proposed
**Reference Spec:** Master System Specification v4.0

---

## 1. Executive Summary
This document outlines the prioritized enhancements for PhotoArchiveDB. The goal is to evolve the system from a "Passive Archive" (storage and retrieval) into an "Active Workspace" (restoration, rediscovery, and semantic organization).

All proposed changes strictly adhere to the core philosophy: **Local-First, File-Centric, and Privacy-Focused**.

---

## 2. High Priority: Integrated Restoration Workspace ("ReDevelop")

Currently, the system manages assets but does not modify their visual content. This module introduces in-app restoration tools.

### 2.1 Functional Goal
To allow users to repair, upscale, and colorize images using local AI models without leaving the application or breaking the "File is King" rule.

### 2.2 Technical Implementation
* **Engine**: Integration of **CodeFormer** or **GFPGAN** (Python-based face restoration) and **ESRGAN** (General upscaling).
* **Architecture Update**:
    * **Non-Destructive Workflow**: The original `file_path` in the `assets` table remains the immutable "Master".
    * **Versioning**: Restored images are saved as "Stacked Versions" (e.g., `filename_v1_restored.jpg`).
    * **UI**: Implementation of the "Swipe View" (Before/After) logic currently planned for the web presentation layer.

### 2.3 Database Schema Impact
New table `asset_versions` to track derived works:
* `id` (PK)
* `parent_asset_id` (FK to `assets.id`)
* `file_path` (Path to the restored file)
* `generation_method` (String: e.g., "GFPGAN-v1.4")
* `parameters` (JSON: Seed, strength, upscaling factor)

---

## 3. High Priority: Semantic Search ("The Discovery Layer")

Current search relies on explicit metadata (Tags, Folders, Dates). This module enables natural language queries (e.g., "Dad fixing the car").

### 3.1 Technology Stack
* **Model**: **OpenAI CLIP** (Vision Transformer). Runs locally on CPU/GPU.
* **Process**:
    1.  **Ingestion**: During the standard `Scanner` walk, pass the image through CLIP.
    2.  **Vectorization**: Generate a 512-dimensional embedding vector.
    3.  **Storage**: Store the vector in a dedicated index.

### 3.2 Database Schema Impact
New table `semantic_index`:
* `asset_id` (FK)
* `embedding` (BLOB): The serialized vector.
* *Performance Note*: For archives < 100k images, a brute-force cosine similarity search in NumPy is sufficiently fast (sub-second).

---

## 4. Medium Priority: Virtual Organization ("Smart Albums")

Currently, organization is tied to `LibraryPaths` (physical folders). This module decouples logical grouping from physical storage.

### 4.1 Functional Goal
Create collections based on criteria, not file location.

### 4.2 Types
1.  **Static Albums**: A fixed list of Asset IDs (e.g., "Slideshow 2024").
2.  **Dynamic Albums**: A saved SQL query (e.g., "Rating > 4 AND Person = 'Daughter'").

### 4.3 Database Schema Impact
* Table `albums`: `id`, `name`, `query_logic` (Text, Nullable).
* Table `album_assets`: `album_id`, `asset_id` (For static albums).

---

## 5. Medium Priority: "Memory Lane" (Temporal Clustering)

Leverages the `captured_at` data to surface memories.

### 5.1 Features
* **"On This Day"**: Query `assets` where `month` and `day` match current date, distinct by `year`.
* **Event Clustering**: Algorithmically group photos based on `captured_at` proximity (e.g., > 20 photos within 4 hours = "Event").

---

## 6. Technical Debt: Biometric Engine Upgrade

### 6.1 Issue
The current `dlib` HOG model struggles with side profiles and requires "Force-Read" manual cropping for difficult angles.

### 6.2 Solution
* **Upgrade**: Implement **InsightFace (ArcFace)** via ONNX Runtime.
* **Migration Strategy**:
    * Add `model_version` column to the `faces` table.
    * Keep existing `dlib` encodings (Legacy).
    * New scans use InsightFace.
    * *Result*: Drastically reduces the need for the "Force-Read" protocol by correctly identifying profiles automatically.

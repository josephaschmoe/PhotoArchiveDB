# ArchiveDB: Your History, De-Siloed.

**ArchiveDB** is a robust, self-hosted Digital Asset Management (DAM) system designed for the serious archivist who rejects subscription clouds and proprietary lock-in. Built with a "Files First" philosophy, it turns your chaotic folder of scans into a searchable, portable, and intelligent library.

## The Philosophy: "Better Than Nothing" became "Better Than Everything"
Most photo managers lock your data into a hidden database. ArchiveDB does the opposite. It treats your **physical files** as the source of truth but gives you the power of a modern database to query them.

## Key Features

### 🔍 Deep Metadata Extraction
We don't just read the date. ArchiveDB uses **ExifTool** to extract every scrap of hidden data—from `Caption-Abstract` to `XMP-Description`—ensuring no context from your historical scans is lost.

### 🧠 On-Device Face Intelligence (AI)
ArchiveDB inspects your library, detects faces, and clusters them.
*   **Teach it once:** Tell it "This is Grandma."
*   **Know it forever:** It finds Grandma in 5,000 other photos automatically.
*   *Privacy First:* Runs 100% locally. No photos are ever sent to the cloud.

### 🔄 Two-Way "Forever" Sync
This is our killer feature. When you tag a photo or name a face in ArchiveDB, you can **Write Back** that data to the file itself.
*   Tag "Summer 1985" in the app -> Becomes embedded IPTC metadata in the `.jpg`.
*   Open that file 20 years from now in any software, and the tag is still there.

### ⚡ Hybrid SQL/JSON Search
Stop digging through folders.
*   **Structure:** Filter by Date, Camera, or File Type.
*   **Flexibility:** Search the full text of letters, descriptions, and obscure metadata tags instantly using our JSON-powered search engine.

## Tech Stack
*   **Core:** Python & Flask (Robust, extensible).
*   **Data:** SQLite (Single file, easy backup).
*   **Engine:** ExifTool (The industry standard for metadata).
*   **Interface:** Clean, responsive Web UI.

---
*ArchiveDB: Because your history belongs to you, not a subscription service.*

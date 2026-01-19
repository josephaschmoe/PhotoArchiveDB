# Setting up Face Recognition on Windows

The `face_recognition` library depends on `dlib`, which is a powerful C++ toolkit. Installing it on Windows requires compiling it from source, which means you need a couple of build tools installed first.

## Step 1: Install CMake
1.  Download **CMake** from [cmake.org/download](https://cmake.org/download/).
    *   Look for the **Windows x64 Installer** (e.g., `cmake-3.x.x-windows-x86_64.msi`).
2.  Run the installer.
3.  **IMPORTANT:** During installation, select **"Add CMake to the system PATH for all users"** (or current user). If you miss this, it won't work.

## Step 2: Install Visual Studio Build Tools
1.  Download the **Visual Studio Build Tools** from [visualstudio.microsoft.com/visual-cpp-build-tools/](https://visualstudio.microsoft.com/visual-cpp-build-tools/).
2.  Run the installer.
3.  Select the **"Desktop development with C++"** workload.
    *   Ensure "MSVC ... C++ x64/x86 build tools" is checked on the right side.
    *   Ensure "Windows 10 (or 11) SDK" is checked.
4.  Click **Install** (this is a large download, ~2-6GB).

## Step 3: Install the Python Libraries
Once the above tools are installed **and you have restarted your terminal**:

1.  Open your terminal in the project folder.
2.  Run:
    ```powershell
    pip install cmake
    pip install dlib
    pip install face_recognition
    ```

## Step 4: Re-enable in ArchiveDB
1.  Open `requirements.txt` and uncomment `face_recognition`.
2.  Restart the `python run.py` server.
3.  The "Warning: face_recognition not found" message should be gone.

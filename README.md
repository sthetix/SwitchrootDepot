# Switchroot Depot

<p align="center">
  <img src="/images/preview.png" alt="Switchroot Depot Preview" width="75%">
</p>

Switchroot Depot is a Python-based desktop application that simplifies downloading all necessary files for Switchroot (Linux and Android) on the Nintendo Switch.

It scans official build sources for Linux distros, LineageOS, and compatible MindTheGapps packages. It then presents them in a unified list and downloads your selection using a multi-threaded, segmented download manager to maximize speed.

The tool automatically organizes all downloaded files (including bootloader files, boot images, and other dependencies) into the correct folder structure required by Hekate.

## Features

* **Unified Downloader:** Fetches all available builds for LineageOS (Tablet and TV) and Switchroot Linux (Ubuntu, L4T) into one simple list.
* **Automatic GApps Matching:** Automatically finds and bundles the correct MindTheGapps release for each LineageOS build.
* **Multi-Connection Downloading:** Uses parallel connections to download large files (like OS images) much faster, similar to a dedicated download manager.
* **Automatic File Organization:** Creates a clean, ready-to-use folder structure for your SD card (e.g., `Android-TV/`, `bootloader/ini/`, `switchroot/install/`) and places all files in their correct locations.
* **Dependency Handling:** Automatically downloads all required dependencies for Android, such as bootloader files, boot images, and `.ini` configurations.
* **Build Caching:** Caches the list of builds locally for 24 hours to provide a near-instant startup.
* **Customizable Settings:** Allows configuration of download connections, chunk size, and an optional GitHub PAT to prevent API rate-limiting.

## How to Use

There are two ways to run Switchroot Depot.

### Option 1: The Launcher (Recommended for Windows)

The easiest way to get started on Windows is by using the provided launcher.

1.  Go to the **Releases** section on GitHub.
2.  Download `SwitchrootDepot.exe`.
3.  Run the executable. It will automatically install all necessary dependencies and launch the application.

### Option 2: Running from Source (Manual)

If you prefer to run the script directly, you can do so using Python. This method is required for Linux or macOS.

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/your-username/switchroot-depot.git](https://github.com/your-username/switchroot-depot.git)
    cd switchroot-depot
    ```

2.  **Create and activate a virtual environment (venv):**
    ```bash
    # On Windows
    python -m venv venv
    .\venv\Scripts\activate
    
    # On macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install ttkbootstrap requests
    ```

4.  **Run the application:**
    ```bash
    python SwitchrootDepot.py
    ```

## Configuration

The application relies on several JSON files located in its root directory:

* `components.json`: This is the main configuration file. It defines the API URLs to scan, the Linux distros to look for, and the list of required files for Android.
* `settings.json`: This file stores your personal settings, such as your GitHub PAT (to avoid rate limits) and download preferences.
* `last_scan.json`: This is a cache file used to store the results of the last server scan. Deleting it will force a full refresh on the next launch.

## Building the Executable (Optional)

If you want to build the `SwitchrootDepot.exe` file yourself, you can use PyInstaller.

1.  Install PyInstaller in your venv:
    ```bash
    pip install pyinstaller
    ```

2.  Run the PyInstaller build command. You must include the `components.json` file.
    ```bash
    # --onefile: Create a single .exe
    # --windowed: Hide the console window
    # --add-data: Bundle the essential components.json
    
    pyinstaller --onefile --windowed --add-data="components.json;." SwitchrootDepot.py
    ```

## License

This project is licensed under the MIT License.

## Acknowledgements

* This tool is built on the great work of the **Switchroot team**.
* The user interface is made possible by **ttkbootstrap**.
* Android builds are provided by the **LineageOS team**.
* GApps packages are provided by the **MindTheGapps team**.


### Support My Work

If you find this project useful, please consider supporting me by buying me a coffee!

<a href="https://www.buymeacoffee.com/sthetixofficial" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" >
</a>
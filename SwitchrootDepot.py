import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import filedialog, messagebox, scrolledtext
import requests
import os
import shutil
import sys
import platform
import ctypes
import struct
import threading
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse # Import for URL logic

# --- Resource & DPI Scaling (from NX_Wifi_Region_Changer) ---

# Set DPI awareness for high-resolution scaling on Windows
if platform.system() == "Windows":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except AttributeError:
        pass

# Determine the script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def resource_path(relative_path):
    """Get the absolute path to a resource, handling PyInstaller's temp folder."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = SCRIPT_DIR
    return os.path.join(base_path, relative_path)

# Icon check removed - icons are optional

# --- Settings Management ---

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")
LAST_SCAN_FILE = os.path.join(SCRIPT_DIR, "last_scan.json")
COMPONENTS_FILE = os.path.join(SCRIPT_DIR, "components.json")

def load_settings():
    """Load settings from JSON file"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
    return {}

def save_settings(settings):
    """Save settings to JSON file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

def load_last_scan():
    """Load last scan cache from JSON file"""
    if os.path.exists(LAST_SCAN_FILE):
        try:
            with open(LAST_SCAN_FILE, 'r') as f:
                data = json.load(f)
                # Check if cache is valid (less than 24 hours old)
                scan_time = data.get('scan_timestamp', 0)
                age = time.time() - scan_time
                if age < 86400:  # 24 hours
                    return data
                else:
                    print(f"Cache is {age/3600:.1f} hours old, will refresh.")
        except Exception as e:
            print(f"Error loading last scan cache: {e}")
    return None

def save_last_scan(builds, timestamp):
    """Save scan results to cache file"""
    try:
        data = {
            'scan_timestamp': timestamp,
            'builds': builds
        }
        with open(LAST_SCAN_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving last scan cache: {e}")

def load_components():
    """Load component definitions from JSON file"""
    if not os.path.exists(COMPONENTS_FILE):
        raise FileNotFoundError(
            f"components.json not found at {COMPONENTS_FILE}\n"
            f"This file is required for the application to run."
        )

    try:
        with open(COMPONENTS_FILE, 'r', encoding='utf-8') as f:
            components = json.load(f)

        # Validate required keys
        required_keys = [
            'linux_distros', 'android_devices', 'android_required_files',
            'android_ini_template', 'api_urls', 'version_map', 'file_patterns'
        ]

        missing_keys = [key for key in required_keys if key not in components]
        if missing_keys:
            raise ValueError(f"Missing required keys in components.json: {', '.join(missing_keys)}")

        return components
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in components.json: {e}")
    except Exception as e:
        raise Exception(f"Error loading components.json: {e}")

# --- Main Application Class ---

class SwitchrootDownloader:
    VERSION = "1.0.0"

    def __init__(self, master):
        self.master = master
        self.master.title(f"Switchroot Depot v{self.VERSION}")
        self.master.geometry("1000x1000")

        # --- Load Components from JSON ---
        try:
            components = load_components()
            self.LINUX_DISTROS = components['linux_distros']
            self.ANDROID_DEVICES = components['android_devices']
            self.ANDROID_REQUIRED_FILES = components['android_required_files']
            self.ANDROID_INI_TEMPLATE = components['android_ini_template']
            self.ANDROID_API_URL = components['api_urls']['android_api']
            self.GAPPS_ORG_URL = components['api_urls']['gapps_org']
            self.DOWNLOAD_FILE_PATTERN = re.compile(components['file_patterns']['download_file_pattern'])
            self.VERSION_MAP = components['version_map']
        except Exception as e:
            messagebox.showerror(
                "Configuration Error",
                f"Failed to load components.json:\n\n{e}\n\nThe application will now exit."
            )
            master.destroy()
            return

        # --- State Variables ---
        self.settings = load_settings()
        self.github_token = self.settings.get('github_token', '')
        self.download_chunk_size = self.settings.get('download_chunk_size', 8388608)  # Default 8MB (increased from 2MB)
        self.download_connections = self.settings.get('download_connections', 8)  # Number of parallel connections per file
        self.download_dir = os.path.expanduser("~/Downloads")
        self.cancel_download = False
        self.last_update_time = 0
        self.fetched_gapps = set() # To prevent duplicate GApps entries
        self.gapps_repo_list = []  # Cache for the list of GApps repos
        self.completed_downloads = 0  # Track completed downloads
        self.download_lock = threading.Lock()  # Thread-safe counter
        self.session = requests.Session()  # Reusable session for connection pooling

        self.create_widgets()
        self.log_message("Welcome to the Switchroot Depot!")
        self.log_message(f"Default download directory: {self.download_dir}")
        if self.github_token:
            self.log_message("GitHub PAT loaded from settings.")

        # Load cached scan data on startup
        self.load_cached_scan()

    def create_widgets(self):
        # --- Menu Bar ---
        menubar = ttk.Menu(self.master)
        self.master.config(menu=menubar)

        # File menu
        file_menu = ttk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Select Download Folder", command=self.select_download_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Settings", command=self.open_settings)
        file_menu.add_command(label="Download Settings", command=self.open_download_settings)

        # --- Top Control Frame ---
        control_frame = ttk.Frame(self.master, padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)

        self.scan_button = ttk.Button(control_frame, text="Refresh Data",
                                      command=lambda: self.start_scan_thread(force=True), bootstyle="primary", width=15)
        self.scan_button.pack(side="left", padx=5)

        ttk.Label(control_frame, text="(Cached data loads automatically)",
                  font=("Segoe UI", 8), bootstyle="secondary").pack(side="left", padx=5)

        self.download_button = ttk.Button(control_frame, text="Download Selected",
                                          command=self.start_download_thread, bootstyle="success", state="disabled", width=20)
        self.download_button.pack(side="left", padx=5)

        # --- Treeview for Builds ---
        tree_frame = ttk.Frame(self.master, padding=10)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("type", "distro", "file", "size")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        
        self.tree.heading("type", text="Type", command=lambda: self.sort_tree("type", False))
        self.tree.column("type", width=100, anchor="w")
        self.tree.heading("distro", text="Distribution", command=lambda: self.sort_tree("distro", False))
        self.tree.column("distro", width=200, anchor="w") # Made wider for date
        self.tree.heading("file", text="File Name", command=lambda: self.sort_tree("file", False))
        self.tree.column("file", width=500, anchor="w")  # Widened to prevent text cutoff
        self.tree.heading("size", text="Size", command=lambda: self.sort_tree("size", True))
        self.tree.column("size", width=100, anchor="e")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)

        # --- Progress Frame (from LineageOSDownloader) ---
        progress_frame = ttk.Frame(self.master, padding=10)
        progress_frame.pack(fill="x", padx=10, pady=5)
        
        self.progress_label = ttk.Label(progress_frame, text="Ready", font=("Segoe UI", 9), bootstyle="secondary")
        self.progress_label.pack(fill="x")
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", bootstyle="success-striped")
        self.progress_bar.pack(fill="x", pady=5)

        self.total_progress_label = ttk.Label(progress_frame, text="", font=("Segoe UI", 9), bootstyle="light")
        self.total_progress_label.pack(fill="x")

        # --- Log Frame (from NX_Wifi_Region_Changer) ---
        log_frame = ttk.LabelFrame(self.master, text="Log Output", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.log_widget = scrolledtext.ScrolledText(log_frame, wrap="word", height=10, state="disabled",
                                                    font=("Consolas", 9))
        self.log_widget.pack(fill="both", expand=True)
        
        log_button_frame = ttk.Frame(log_frame)
        log_button_frame.pack(fill="x", pady=(5, 0))
        ttk.Frame(log_button_frame).pack(side="left", fill="x", expand=True) # Spacer
        clear_log_button = ttk.Button(log_button_frame, text="Clear Log", command=self.clear_log, 
                                 bootstyle="secondary", width=12)
        clear_log_button.pack(side="right")


    # --- GUI & Logging Functions (from NX_Wifi_Region_Changer) ---
    
    def log_message(self, message):
        """Add a message to the log widget"""
        def _log():
            self.log_widget.config(state="normal")
            self.log_widget.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_widget.see("end")
            self.log_widget.config(state="disabled")
        self.master.after(0, _log)

    def clear_log(self):
        """Clear the log widget"""
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")
        
    def select_download_dir(self):
        new_dir = filedialog.askdirectory(initialdir=self.download_dir)
        if new_dir:
            self.download_dir = new_dir
            self.log_message(f"Download directory set to: {self.download_dir}")

    def center_window(self, window):
        """Center a popup window on the main window"""
        # This function is now a wrapper to call the actual centering logic
        # after a small delay, preventing the "flicker" effect.
        window.after(10, lambda: self._do_center(window))

    def _do_center(self, window):
        """Internal method to center a window relative to the parent"""
        # Update both parent and child window to get accurate current positions
        self.master.update_idletasks()
        window.update_idletasks()

        parent_x = self.master.winfo_x()
        parent_y = self.master.winfo_y()
        parent_w = self.master.winfo_width()
        parent_h = self.master.winfo_height()

        window_w = window.winfo_width()
        window_h = window.winfo_height()

        x = parent_x + (parent_w // 2) - (window_w // 2)
        y = parent_y + (parent_h // 2) - (window_h // 2)

        window.geometry(f"+{x}+{y}")

    def open_settings(self):
        """Open settings dialog"""
        settings_window = ttk.Toplevel(self.master)
        settings_window.title("Settings")
        settings_window.geometry("500x300")
        settings_window.resizable(False, False)
        settings_window.transient(self.master)
        settings_window.grab_set()

        # GitHub PAT Frame
        pat_frame = ttk.LabelFrame(settings_window, text="GitHub Personal Access Token (PAT)", padding=20)
        pat_frame.pack(fill="both", expand=True, padx=20, pady=20)

        info_label = ttk.Label(pat_frame, text="Enter your GitHub PAT to avoid API rate limits.\n"
                                               "This is optional but recommended for MindTheGapps downloads.",
                              justify="left", bootstyle="info")
        info_label.pack(anchor="w", pady=(0, 10))

        token_frame = ttk.Frame(pat_frame)
        token_frame.pack(fill="x", pady=5)

        ttk.Label(token_frame, text="Token:", width=10).pack(side="left")
        token_entry = ttk.Entry(token_frame, width=50, show="*")
        token_entry.pack(side="left", padx=5, fill="x", expand=True)
        token_entry.insert(0, self.github_token)

        # Buttons
        button_frame = ttk.Frame(pat_frame)
        button_frame.pack(fill="x", pady=(10, 0))

        def save_token():
            new_token = token_entry.get().strip()
            self.github_token = new_token
            self.settings['github_token'] = new_token
            save_settings(self.settings)
            self.log_message("GitHub PAT saved to settings.")
            settings_window.destroy()

        def clear_token():
            token_entry.delete(0, 'end')

        ttk.Button(button_frame, text="Save", command=save_token, bootstyle="success", width=10).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Clear", command=clear_token, bootstyle="secondary", width=10).pack(side="right")
        ttk.Button(button_frame, text="Cancel", command=settings_window.destroy, bootstyle="danger", width=10).pack(side="right", padx=5)

        # Center the window
        self.center_window(settings_window)

    def open_download_settings(self):
        """Open download settings dialog"""
        download_dialog = ttk.Toplevel(self.master)
        download_dialog.title("Download Settings")
        download_dialog.geometry("550x700")
        download_dialog.transient(self.master)
        download_dialog.grab_set()

        info_frame = ttk.Frame(download_dialog, padding=20)
        info_frame.pack(fill="both", expand=True)

        ttk.Label(info_frame, text="Download Settings",
                  font=('Segoe UI', 11, 'bold')).pack(pady=(0, 10))

        ttk.Label(info_frame, text="Configure download settings for faster downloads.",
                  wraplength=500).pack(pady=(0, 20))

        # Parallel connections setting
        connections_frame = ttk.LabelFrame(info_frame, text="Parallel Connections Per File", padding=15)
        connections_frame.pack(fill="x", pady=(0, 15))

        ttk.Label(connections_frame, text="More connections = faster downloads (like Internet Download Manager).\n"
                                   "Files are split into segments and downloaded simultaneously.",
                  wraplength=480, font=('Segoe UI', 8)).pack(pady=(0, 10))

        # Connection options
        connections_var = ttk.IntVar(value=self.download_connections)

        conn_options_frame = ttk.Frame(connections_frame)
        conn_options_frame.pack(fill="x")

        ttk.Radiobutton(conn_options_frame, text="4 connections (Balanced)",
                        variable=connections_var, value=4,
                        bootstyle="primary").pack(anchor="w", pady=2)

        ttk.Radiobutton(conn_options_frame, text="8 connections (Recommended)",
                        variable=connections_var, value=8,
                        bootstyle="primary").pack(anchor="w", pady=2)

        ttk.Radiobutton(conn_options_frame, text="16 connections (Maximum speed)",
                        variable=connections_var, value=16,
                        bootstyle="primary").pack(anchor="w", pady=2)

        current_conn_label = ttk.Label(info_frame, text=f"Current: {self.download_connections} connections",
                                  font=('Segoe UI', 9, 'bold'), bootstyle="info")
        current_conn_label.pack(pady=(5, 20))

        # Chunk size setting
        chunk_frame = ttk.LabelFrame(info_frame, text="Download Chunk Size", padding=15)
        chunk_frame.pack(fill="x", pady=(0, 15))

        ttk.Label(chunk_frame, text="Larger chunks = faster downloads but less frequent progress updates.\n"
                                   "Smaller chunks = more frequent updates but slightly slower.",
                  wraplength=480, font=('Segoe UI', 8)).pack(pady=(0, 10))

        # Chunk size options
        chunk_size_var = ttk.IntVar(value=self.download_chunk_size)

        options_frame = ttk.Frame(chunk_frame)
        options_frame.pack(fill="x")

        ttk.Radiobutton(options_frame, text="2 MB (More updates)",
                        variable=chunk_size_var, value=2097152,
                        bootstyle="primary").pack(anchor="w", pady=2)

        ttk.Radiobutton(options_frame, text="4 MB (Balanced)",
                        variable=chunk_size_var, value=4194304,
                        bootstyle="primary").pack(anchor="w", pady=2)

        ttk.Radiobutton(options_frame, text="8 MB (Recommended)",
                        variable=chunk_size_var, value=8388608,
                        bootstyle="primary").pack(anchor="w", pady=2)

        ttk.Radiobutton(options_frame, text="16 MB (Faster, fewer updates)",
                        variable=chunk_size_var, value=16777216,
                        bootstyle="primary").pack(anchor="w", pady=2)

        # Current size display
        current_mb = self.download_chunk_size / (1024 * 1024)
        current_label = ttk.Label(info_frame, text=f"Current: {current_mb:.1f} MB",
                                  font=('Segoe UI', 9, 'bold'), bootstyle="info")
        current_label.pack(pady=(5, 20))

        # Buttons
        button_frame = ttk.Frame(info_frame)
        button_frame.pack(pady=(15, 0))

        def save_download_settings():
            new_chunk_size = chunk_size_var.get()
            new_connections = connections_var.get()
            self.download_chunk_size = new_chunk_size
            self.download_connections = new_connections
            self.settings['download_chunk_size'] = new_chunk_size
            self.settings['download_connections'] = new_connections
            save_settings(self.settings)

            new_mb = new_chunk_size / (1024 * 1024)
            messagebox.showinfo("Saved",
                              f"Settings saved:\n"
                              f"- Parallel connections: {new_connections}\n"
                              f"- Chunk size: {new_mb:.1f} MB\n\n"
                              f"This will take effect on the next download.",
                              parent=download_dialog)
            download_dialog.destroy()

        ttk.Button(button_frame, text="Save", command=save_download_settings,
                   bootstyle="primary").pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=download_dialog.destroy,
                   bootstyle="secondary").pack(side="left", padx=5)

        self.center_window(download_dialog)

    def set_ui_state(self, state):
        """Helper to enable/disable buttons"""
        self.scan_button.config(state=state)
        self.download_button.config(state=state)

    def sort_tree(self, col, as_bytes):
        """Sorts the treeview column"""
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        
        if as_bytes:
            # Custom sort for file sizes (e.g., "1.2 GB", "500 MB")
            def sort_key(item):
                size_str = item[0]
                if "GB" in size_str:
                    return float(size_str.replace(" GB", "")) * 1024 * 1024 * 1024
                elif "MB" in size_str:
                    return float(size_str.replace(" MB", "")) * 1024 * 1024
                elif "KB" in size_str:
                    return float(size_str.replace(" KB", "")) * 1024
                else:
                    return 0
            items.sort(key=sort_key)
        else:
            # Standard string sort
            items.sort()

        # Re-insert items in sorted order
        for index, (val, k) in enumerate(items):
            self.tree.move(k, "", index)

    # --- Scanning Functions (Threaded) ---

    def start_scan_thread(self, force=False):
        """Starts the server scan in a separate thread"""
        self.set_ui_state("disabled")
        if force:
            self.log_message("Force refreshing server data...")
        else:
            self.log_message("Starting server scan...")
        self.progress_label.config(text="Scanning servers...")
        self.download_button.config(state="disabled")

        # Clear existing items and caches
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.fetched_gapps.clear()
        self.gapps_repo_list.clear()

        threading.Thread(target=self.scan_servers, daemon=True).start()

    def scan_servers(self):
        """Main scanning logic"""
        try:
            self.fetch_gapps_repo_list() # *** NEW: Fetch GApps repos first ***
            self.scan_linux_builds()
            self.scan_android_builds()

            # Save scan results to cache
            self.save_scan_cache()

            self.log_message("Server scan complete.")
            self.master.after(0, self.download_button.config, {"state": "normal"})
        except Exception as e:
            self.log_message(f"ERROR: Server scan failed: {e}")
            messagebox.showerror("Error", f"Server scan failed:\n{e}")
        finally:
            self.master.after(0, self.set_ui_state, "normal")
            self.master.after(0, self.progress_label.config, {"text": "Ready"})

    def get_github_headers(self):
        """Returns GitHub API headers with PAT if available"""
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if self.github_token:
            headers['Authorization'] = f'token {self.github_token}'
        return headers

    # *** NEW ***
    def fetch_gapps_repo_list(self):
        """Fetches the list of all MindTheGapps repositories once per scan."""
        self.log_message("Fetching MindTheGapps repository list...")
        try:
            session = requests.Session()
            headers = self.get_github_headers()
            response = session.get(self.GAPPS_ORG_URL, timeout=10, headers=headers)
            response.raise_for_status()
            repos = response.json()
            self.gapps_repo_list = [repo['name'] for repo in repos]
            self.log_message(f"Found {len(self.gapps_repo_list)} GApps repositories.")
        except Exception as e:
            self.log_message(f"Warning: Could not fetch GApps repository list. GApps will not be available. Error: {e}")
            self.gapps_repo_list = [] # Ensure it's a list

    # *** NEW ***
    def find_matching_gapps_repo(self, android_version, gapps_suffix):
        """Finds a repo name from the fetched list that matches the version and suffix.

        MindTheGapps repo naming pattern: {version}.0.0-{arch} or {version}.0.0-{arch}-{variant}
        Examples: 14.0.0-arm64, 14.0.0-arm64-ATV, 16.0.0-arm64-ATV
        """
        # Try exact match first: {version}.0.0-{suffix}
        exact_pattern = f"{android_version}.0.0-{gapps_suffix}"
        for name in self.gapps_repo_list:
            if name == exact_pattern:
                self.log_message(f"Found exact GApps repo match: {name}")
                return name

        # Try pattern match: starts with {version}. and ends with -{suffix}
        for name in self.gapps_repo_list:
            if name.startswith(f"{android_version}.") and name.endswith(f"-{gapps_suffix}"):
                self.log_message(f"Found pattern GApps repo match: {name}")
                return name

        # Log available repos for debugging
        matching_version = [n for n in self.gapps_repo_list if n.startswith(f"{android_version}.")]
        matching_suffix = [n for n in self.gapps_repo_list if n.endswith(f"-{gapps_suffix}")]

        if matching_version:
            self.log_message(f"Available GApps for Android {android_version}: {', '.join(matching_version)}")
        if matching_suffix:
            self.log_message(f"Available GApps for {gapps_suffix}: {', '.join(matching_suffix)}")

        return None

    def scan_linux_builds(self):
        """Scans Linux builds from various sources"""
        self.log_message("Scanning for Linux builds...")
        session = requests.Session()
        
        for distro in self.LINUX_DISTROS:
            name = distro["name"]
            url = distro["url"]
            
            # Get the domain root (e.g., "https://download.switchroot.org")
            parsed_url = urlparse(url)
            domain_root = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            try:
                self.log_message(f"Checking {name} at {url} ...")
                response = session.get(url, timeout=10)
                response.raise_for_status()
                
                files = self.DOWNLOAD_FILE_PATTERN.findall(response.text)
                
                if not files:
                    self.log_message(f"No files found for {name} (pattern: .7z, .zip, .tar)")
                    continue

                for file in files:
                    file_name = file.split('/')[-1]
                    file_url = "" 
                    
                    # --- URL FIX LOGIC ---
                    if file.startswith('http'):
                        file_url = file
                    elif file.startswith('/'):
                        file_url = f"{domain_root}{file}"
                    else:
                        file_url = f"{url}{file}"
                    # --- END OF FIX ---
                    
                    # Send HEAD request to get file size
                    try:
                        head_resp = session.head(file_url, timeout=5, allow_redirects=True)
                        size_bytes = int(head_resp.headers.get('Content-Length', 0))
                        size_str = self.format_size(size_bytes)
                    except Exception as e:
                        self.log_message(f"Warning: Could not get size for {file_name}. URL: {file_url}. Error: {e}")
                        size_bytes = 0
                        size_str = "0 B" 
                    
                    item_data = ("Linux", name, file_name, size_str, file_url, size_bytes)
                    self.master.after(0, self.add_tree_item, item_data)
                    
            except Exception as e:
                self.log_message(f"Warning: Failed to scan {name}: {e}")

    def scan_android_builds(self):
        """Scans ALL Android builds and compatible GApps, combining them into unified entries"""
        self.log_message("Scanning LineageOS API for Android...")
        session = requests.Session()

        # Use version map from components.json
        version_map = self.VERSION_MAP

        for device_id, device_name in self.ANDROID_DEVICES.items():
            try:
                url = self.ANDROID_API_URL.format(device_id)
                self.log_message(f"Checking {device_name} API: {url}")
                response = session.get(url, timeout=10)
                response.raise_for_status()
                builds = response.json()

                if not builds:
                    self.log_message(f"No builds found for {device_name}.")
                    continue

                self.log_message(f"Found {len(builds)} builds for {device_name}.")

                # Track which GApps we've fetched to avoid redundant API calls
                fetched_gapps_versions = {}

                for build in builds:
                    los_version = build['version']
                    build_date = build['date']

                    # --- 1. Get LineageOS files ---
                    build_files = {}
                    lineage_zip_name = None
                    lineage_zip_url = None
                    lineage_zip_size = 0

                    for file_info in build['files']:
                        file_name = file_info['filename']
                        file_url = file_info['url']
                        size_bytes = int(file_info['size'])

                        # Store all files in the dictionary
                        build_files[file_name] = {'url': file_url, 'size': size_bytes}

                        # Get the main LineageOS zip file
                        if file_name.startswith('lineage-') and file_name.endswith('.zip'):
                            lineage_zip_name = file_name
                            lineage_zip_url = file_url
                            lineage_zip_size = size_bytes

                    if not lineage_zip_name:
                        continue

                    # --- 2. Find compatible MindTheGapps ---
                    android_version = version_map.get(los_version, los_version.split('.')[0])
                    gapps_suffix = "arm64" if device_id == "nx_tab" else "arm64-ATV"
                    gapps_key = (android_version, gapps_suffix)

                    gapps_name = None
                    gapps_url = None
                    gapps_size = 0

                    # Check cache first to avoid redundant API calls
                    if gapps_key in fetched_gapps_versions:
                        # Use cached GApps info
                        cached = fetched_gapps_versions[gapps_key]
                        gapps_name = cached.get('name')
                        gapps_url = cached.get('url')
                        gapps_size = cached.get('size', 0)
                        if gapps_name:
                            self.log_message(f"Using cached GApps: {gapps_name}")
                    else:
                        # Fetch GApps from API
                        try:
                            self.log_message(f"Searching for GApps: Android {android_version} ({gapps_suffix}) for LineageOS {los_version}")

                            repo_name = self.find_matching_gapps_repo(android_version, gapps_suffix)

                            if repo_name:
                                gapps_api_url = f"https://api.github.com/repos/MindTheGapps/{repo_name}/releases/latest"
                                self.log_message(f"Found matching GApps repo: {repo_name}")

                                gapps_response = session.get(gapps_api_url, timeout=10, headers=self.get_github_headers())
                                gapps_response.raise_for_status()

                                gapps_data = gapps_response.json()
                                for asset in gapps_data.get('assets', []):
                                    if asset['name'].endswith('.zip'):
                                        gapps_name = asset['name']
                                        gapps_url = asset['browser_download_url']
                                        gapps_size = int(asset['size'])
                                        self.log_message(f"Found compatible GApps: {gapps_name}")
                                        break

                                # Cache the result
                                fetched_gapps_versions[gapps_key] = {
                                    'name': gapps_name,
                                    'url': gapps_url,
                                    'size': gapps_size
                                }
                        except Exception as e:
                            self.log_message(f"Warning: Could not find GApps for Android {android_version} ({gapps_suffix}). Reason: {e}")
                            # Cache the failure
                            fetched_gapps_versions[gapps_key] = {
                                'name': None,
                                'url': None,
                                'size': 0
                            }

                    # --- 3. Create unified entry ---
                    # Clean device name: "Android (TV)" -> "TV", "Android (Tablet)" -> "Tablet"
                    device_type_clean = device_name.split('(')[1].replace(')', '') if '(' in device_name else device_name

                    # Distribution: "Android TV" or "Android Tablet"
                    distro_display = f"Android {device_type_clean}"

                    # Format date: "2024-01-15" -> "20240115"
                    date_formatted = build_date.replace('-', '')

                    # File name: "LineageOS 21.0 (20240115) + MindTheGapps" or "LineageOS 21.0 (20240115)" (if no GApps found)
                    if gapps_name:
                        file_display = f"LineageOS {los_version} ({date_formatted}) + MindTheGapps"
                        combined_size = lineage_zip_size + gapps_size
                    else:
                        file_display = f"LineageOS {los_version} ({date_formatted}) (GApps not available)"
                        combined_size = lineage_zip_size

                    size_str = self.format_size(combined_size)

                    # Store all necessary info in tags for download
                    # Format: (lineage_url, lineage_size, gapps_url, gapps_size, device_type, build_files_json)
                    build_files_json = json.dumps(build_files)
                    device_type = device_type_clean

                    item_data = (
                        "Android",
                        distro_display,
                        file_display,
                        size_str,
                        lineage_zip_url,
                        lineage_zip_size,
                        build_files,
                        gapps_url,
                        gapps_size,
                        device_type
                    )

                    self.master.after(0, self.add_tree_item, item_data)
                    self.log_message(f"Added unified entry: {file_display} for {distro_display} ({build_date})")

            except Exception as e:
                self.log_message(f"Warning: Failed to scan {device_name}: {e}")

    def add_tree_item(self, item_data):
        """Thread-safe method to add an item to the treeview"""
        # Handle different formats:
        # From cache: (type, distro, filename, size_str, tag1, tag2, ...) - variable length
        # Linux format: (type, distro, filename, size_str, url, size_bytes)
        # Unified Android format: (type, distro, filename, size_str, lineage_url, lineage_size, build_files, gapps_url, gapps_size, device_type)

        # Check if this is cached data (values + tags already separated in cache format)
        if len(item_data) >= 4:
            # First 4 items are always the tree values
            dist_type, dist_name, file_name, size_str = item_data[:4]

            # Remaining items are tags
            if len(item_data) > 4:
                tags = item_data[4:]
            else:
                tags = ()

            # If this is fresh data (not from cache), we need to process it
            # Fresh Android data has 10 items: (type, distro, filename, size_str, lineage_url, lineage_size, build_files, gapps_url, gapps_size, device_type)
            if len(item_data) == 10 and isinstance(item_data[6], dict):
                # New unified Android format (fresh from scan)
                lineage_url, lineage_size, build_files, gapps_url, gapps_size, device_type = item_data[4:]
                build_files_json = json.dumps(build_files) if build_files else ""
                tags = (lineage_url, gapps_url, lineage_size, gapps_size, device_type, build_files_json)

            # Fresh Linux data has 6 items: (type, distro, filename, size_str, url, size_bytes)
            elif len(item_data) == 6 and len(tags) == 2:
                # Linux format (fresh from scan)
                file_url, size_bytes = tags
                tags = (file_url, size_bytes, "", "")

            # Otherwise, tags are already in the correct format (from cache)

        else:
            # Fallback - shouldn't happen
            tags = ()

        self.tree.insert("", "end", values=(dist_type, dist_name, file_name, size_str), tags=tags)

    def load_cached_scan(self):
        """Load cached scan data on startup"""
        cache_data = load_last_scan()
        if cache_data:
            builds = cache_data.get('builds', [])
            scan_time = cache_data.get('scan_timestamp', 0)

            # Convert timestamp to readable format
            from datetime import datetime
            scan_date = datetime.fromtimestamp(scan_time).strftime('%Y-%m-%d %H:%M:%S')

            if builds:
                self.log_message(f"Loading {len(builds)} cached builds from {scan_date}")

                for build in builds:
                    # Cache format: [values (4 items), tags (variable items)]
                    # Split the build data back into values and tags
                    if len(build) >= 4:
                        values = build[:4]  # First 4 items are the tree values
                        tags = build[4:]    # Remaining items are tags

                        # Reconstruct the item_data based on the number of tags
                        if len(tags) >= 6:
                            # New unified Android format: (type, distro, filename, size_str, lineage_url, gapps_url, lineage_size, gapps_size, device_type, build_files_json)
                            item_data = tuple(values) + tuple(tags)
                        else:
                            # Old format or Linux format
                            item_data = tuple(values) + tuple(tags)

                        self.add_tree_item(item_data)

                self.download_button.config(state="normal")
                self.log_message("Cached data loaded. Click 'Refresh Data' to fetch latest.")
            else:
                self.log_message("No cached builds found. Click 'Refresh Data' to scan servers.")
        else:
            self.log_message("No cached data found. Click 'Refresh Data' to scan servers.")

    def save_scan_cache(self):
        """Save current tree items to cache"""
        builds = []
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            tags = self.tree.item(item_id, "tags")

            # Combine values and tags into a single list
            build_data = list(values) + list(tags)
            builds.append(build_data)

        timestamp = time.time()
        save_last_scan(builds, timestamp)

        from datetime import datetime
        scan_date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        self.log_message(f"Saved {len(builds)} builds to cache ({scan_date})")

    # --- Download Functions (Threaded, from LineageOSDownloader) ---

    def start_download_thread(self):
        """Validates selection and starts the download thread pool"""
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select one or more files to download.")
            return

        if not self.download_dir or not os.path.exists(self.download_dir):
            messagebox.showerror("Invalid Directory", f"Download directory is invalid:\n{self.download_dir}")
            return

        self.log_message(f"Preparing to download {len(selected_items)} file(s)...")
        self.set_ui_state("disabled")

        # Create a list of download tasks
        tasks = []
        android_device_types = set()  # Track which Android device types are being downloaded
        android_build_files = {}  # Track build files for each device type
        task_num = 0

        for item_id in selected_items:
            values = self.tree.item(item_id, "values")
            tags = self.tree.item(item_id, "tags")

            dist_type = values[0]
            file_name = values[2]

            # Handle unified Android format (6 tags) vs old formats (2-4 tags)
            if dist_type == "Android" and len(tags) >= 6:
                # New unified format: (lineage_url, gapps_url, lineage_size, gapps_size, device_type, build_files_json)
                lineage_url = tags[0]
                gapps_url = tags[1]
                lineage_size = int(tags[2]) if isinstance(tags[2], str) else tags[2]
                gapps_size = int(tags[3]) if isinstance(tags[3], str) else tags[3]
                device_type = tags[4]
                build_files_json = tags[5]

                # Check for 0-byte files
                if lineage_size == 0:
                    self.log_message(f"Skipping {file_name}: LineageOS file size is reported as 0 B (invalid URL).")
                    continue

                android_device_types.add(device_type)

                # Parse build files
                if build_files_json:
                    try:
                        build_files = json.loads(build_files_json)
                        android_build_files[device_type] = build_files
                    except json.JSONDecodeError:
                        pass

                # Add LineageOS download task
                task_num += 1
                lineage_filename = [k for k in (build_files if build_files_json else {}) if k.startswith('lineage-') and k.endswith('.zip')]
                lineage_filename = lineage_filename[0] if lineage_filename else "lineage.zip"
                tasks.append((lineage_url, lineage_filename, task_num, 0, "Android", device_type))
                self.log_message(f"Adding LineageOS download: {lineage_filename}")

                # Add GApps download task if available
                if gapps_url and gapps_size > 0:
                    task_num += 1
                    # Extract GApps filename from URL
                    gapps_filename = gapps_url.split('/')[-1]
                    tasks.append((gapps_url, gapps_filename, task_num, 0, "GApps", device_type))
                    self.log_message(f"Adding GApps download: {gapps_filename}")

            else:
                # Old format or Linux format
                file_url = tags[0]
                size_bytes = tags[1] if len(tags) > 1 else 0
                device_type = tags[2] if len(tags) > 2 else ""
                build_files_json = tags[3] if len(tags) > 3 else ""

                # Check for 0-byte files
                if size_bytes == 0:
                    self.log_message(f"Skipping {file_name}: File size is reported as 0 B (invalid URL).")
                    continue

                # Track Android device types for additional file downloads
                if dist_type in ["Android", "GApps"] and device_type:
                    android_device_types.add(device_type)

                    # If this is a LineageOS build with associated files, store them
                    if dist_type == "Android" and build_files_json:
                        try:
                            build_files = json.loads(build_files_json)
                            android_build_files[device_type] = build_files
                        except json.JSONDecodeError:
                            pass

                task_num += 1
                tasks.append((file_url, file_name, task_num, 0, dist_type, device_type))

        # Add required Android files for each device type
        for device_type in android_device_types:
            # Add the hidden build files (boot.img, recovery.img, etc.)
            if device_type in android_build_files:
                build_files = android_build_files[device_type]
                for file_name, file_info in build_files.items():
                    # Skip the main LineageOS zip (already in tasks) and super_empty.img
                    if file_name.startswith('lineage-') or 'super_empty.img' in file_name:
                        continue

                    task_num += 1
                    tasks.append((
                        file_info['url'],
                        file_name,
                        task_num,
                        0,
                        "Android-Build",
                        device_type
                    ))
                    self.log_message(f"Adding build file for Android {device_type}: {file_name}")

            # Add the static required files (bootloader files, icons, etc.)
            for req_file in self.ANDROID_REQUIRED_FILES:
                task_num += 1
                tasks.append((
                    req_file['url'],
                    req_file['name'],
                    task_num,
                    0,
                    "Android-Extras",
                    device_type,
                    req_file['path']  # Add path info
                ))
                self.log_message(f"Adding required file for Android {device_type}: {req_file['name']}")

        if not tasks:
            self.log_message("No valid files to download.")
            self.reset_ui_after_download()
            return

        # Update all tasks with correct total count
        total_tasks = len(tasks)
        tasks = [(url, name, num, total_tasks) + tuple(rest) for url, name, num, _, *rest in tasks]

        # Start the download pool
        threading.Thread(target=self.download_files_pool, args=(tasks,), daemon=True).start()

    def download_files_pool(self, tasks):
        """Manages the ThreadPoolExecutor for downloads"""
        # Reset completed downloads counter
        self.completed_downloads = 0

        # Track which Android device types we're downloading
        android_device_types = set()
        for task in tasks:
            if len(task) >= 6:  # Has device_type
                dist_type = task[4]
                device_type = task[5]
                if dist_type in ["Android", "Android-Build", "Android-Extras"] and device_type:
                    android_device_types.add(device_type)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(self.download_file_worker, *task) for task in tasks]

            for future in futures:
                try:
                    future.result() # Wait for each download to finish
                except Exception as e:
                    self.log_message(f"Error during download: {e}")

        # Create android.ini files for each Android device type
        for device_type in android_device_types:
            self.create_android_ini(device_type)

        self.log_message("All download tasks complete.")
        self.master.after(0, self.reset_ui_after_download)

    def download_segment(self, url, start, end, segment_num, temp_file, progress_dict, filename):
        """Download a single segment of a file"""
        headers = {'Range': f'bytes={start}-{end}'}
        try:
            response = self.session.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True)
            response.raise_for_status()

            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=self.download_chunk_size):
                    if chunk:
                        f.write(chunk)
                        progress_dict[segment_num] += len(chunk)
        except Exception as e:
            self.log_message(f"Error downloading segment {segment_num} of {filename}: {e}")
            raise

    def download_file_worker(self, url, filename, file_num, total_files, dist_type="", device_type="", file_path=None):
        """The actual file downloader with multi-connection support"""
        # Get current completed count + 1 for "Starting" message
        with self.download_lock:
            current_starting = self.completed_downloads + 1

        self.log_message(f"({current_starting}/{total_files}) Starting download: {filename}")

        # Determine download path based on type
        if dist_type in ["Android", "GApps"] and device_type:
            # Create subfolder for Android files (main zip goes to root of Android-X folder)
            folder_name = f"Android-{device_type}"
            download_path = os.path.join(self.download_dir, folder_name)
            os.makedirs(download_path, exist_ok=True)
            filepath = os.path.join(download_path, filename)
            self.log_message(f"Organizing into folder: {folder_name}")
        elif dist_type == "Android-Build" and device_type:
            # Build files go to specific locations based on their type
            folder_name = f"Android-{device_type}"

            # Determine subfolder based on file type
            if filename in ['boot.img', 'recovery.img', 'nx-plat.dtimg']:
                # Installation files go to switchroot/install/
                target_path = os.path.join(self.download_dir, folder_name, "switchroot", "install")
            else:
                # Runtime files (bl31.bin, bl33.bin, boot.scr) go to switchroot/android/
                target_path = os.path.join(self.download_dir, folder_name, "switchroot", "android")

            os.makedirs(target_path, exist_ok=True)
            filepath = os.path.join(target_path, filename)
            self.log_message(f"Placing in: {os.path.relpath(target_path, self.download_dir)}/")
        elif dist_type == "Android-Extras" and device_type:
            # Extra files use the path from ANDROID_REQUIRED_FILES
            folder_name = f"Android-{device_type}"
            if file_path:
                # Use the specified path (e.g., "switchroot/android/bootlogo_android.bmp")
                target_path = os.path.join(self.download_dir, folder_name, os.path.dirname(file_path))
                os.makedirs(target_path, exist_ok=True)
                filepath = os.path.join(self.download_dir, folder_name, file_path)
            else:
                # Fallback to switchroot/android
                android_extras_path = os.path.join(self.download_dir, folder_name, "switchroot", "android")
                os.makedirs(android_extras_path, exist_ok=True)
                filepath = os.path.join(android_extras_path, filename)
            self.log_message(f"Placing in: {os.path.relpath(os.path.dirname(filepath), self.download_dir)}/")
        else:
            # Default location
            filepath = os.path.join(self.download_dir, filename)

        try:
            # First, get the file size and check if server supports range requests
            head_response = self.session.head(url, timeout=10, allow_redirects=True)
            head_response.raise_for_status()

            total_size = int(head_response.headers.get('Content-Length', 0))
            accept_ranges = head_response.headers.get('Accept-Ranges', 'none')

            # Use multi-connection download only if:
            # 1. Server supports range requests
            # 2. File is larger than 5MB (otherwise overhead isn't worth it)
            # 3. We have more than 1 connection configured
            use_multiconnection = (
                accept_ranges != 'none' and
                total_size > 5 * 1024 * 1024 and
                self.download_connections > 1
            )

            if use_multiconnection:
                self.log_message(f"Using {self.download_connections} parallel connections for {filename}")

                # Calculate segment size
                segment_size = total_size // self.download_connections
                segments = []
                temp_files = []

                # Create segment ranges
                for i in range(self.download_connections):
                    start = i * segment_size
                    # Last segment gets any remaining bytes
                    end = start + segment_size - 1 if i < self.download_connections - 1 else total_size - 1
                    temp_file = f"{filepath}.part{i}"
                    segments.append((start, end, i, temp_file))
                    temp_files.append(temp_file)

                # Progress tracking for all segments
                progress_dict = {i: 0 for i in range(self.download_connections)}

                # Download all segments in parallel
                with ThreadPoolExecutor(max_workers=self.download_connections) as executor:
                    futures = []
                    for start, end, segment_num, temp_file in segments:
                        future = executor.submit(
                            self.download_segment,
                            url, start, end, segment_num, temp_file,
                            progress_dict, filename
                        )
                        futures.append(future)

                    # Monitor progress while downloading
                    while any(not f.done() for f in futures):
                        time.sleep(0.1)
                        downloaded_size = sum(progress_dict.values())

                        # Rate-limit GUI updates
                        current_time = time.time()
                        if current_time - self.last_update_time > 0.1:
                            self.last_update_time = current_time
                            with self.download_lock:
                                completed = self.completed_downloads
                            self.master.after(0, self.update_progress, filename,
                                              completed, total_files, downloaded_size, total_size)

                    # Check for any errors
                    for future in futures:
                        future.result()  # This will raise any exceptions that occurred

                # Combine all segments into final file
                self.log_message(f"Combining {self.download_connections} segments for {filename}...")
                with open(filepath, 'wb') as outfile:
                    for temp_file in temp_files:
                        with open(temp_file, 'rb') as infile:
                            shutil.copyfileobj(infile, outfile)
                        os.remove(temp_file)  # Clean up temp file

            else:
                # Fall back to single-connection download
                if not use_multiconnection and total_size > 5 * 1024 * 1024:
                    self.log_message(f"Server doesn't support range requests, using single connection for {filename}")

                response = self.session.get(url, stream=True, timeout=30, allow_redirects=True)
                response.raise_for_status()

                if total_size == 0:
                    total_size = int(response.headers.get('Content-Length', 0))

                downloaded_size = 0

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=self.download_chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)

                            # Rate-limit GUI updates
                            current_time = time.time()
                            if current_time - self.last_update_time > 0.1:
                                self.last_update_time = current_time
                                with self.download_lock:
                                    completed = self.completed_downloads
                                self.master.after(0, self.update_progress, filename,
                                                  completed, total_files, downloaded_size, total_size)

            # Increment completed counter after successful download
            with self.download_lock:
                self.completed_downloads += 1
                completed = self.completed_downloads

            self.log_message(f"({completed}/{total_files}) Finished download: {filename}")

        except requests.RequestException as e:
            self.log_message(f"ERROR downloading {filename}: {e}")
            try:
                os.remove(filepath) # Clean up partial file
            except OSError:
                pass # File might not exist
            # Clean up any temp segment files
            for i in range(self.download_connections):
                try:
                    os.remove(f"{filepath}.part{i}")
                except OSError:
                    pass
        except Exception as e:
            self.log_message(f"FATAL ERROR on {filename}: {e}")
            # Clean up any temp segment files
            for i in range(self.download_connections):
                try:
                    os.remove(f"{filepath}.part{i}")
                except OSError:
                    pass

    def update_progress(self, filename, completed_count, total_files, downloaded_size, total_size):
        """Thread-safe method to update all progress indicators"""
        try:
            if total_size > 0:
                percent = (downloaded_size / total_size) * 100
                self.progress_bar["value"] = percent
                self.progress_label.config(
                    text=f"Downloading {filename} ({self.format_size(downloaded_size)} / {self.format_size(total_size)})"
                )
            else:
                self.progress_bar["value"] = 0
                self.progress_label.config(
                    text=f"Downloading {filename} ({self.format_size(downloaded_size)})"
                )

            # Show completed count (files currently downloading are not yet completed)
            self.total_progress_label.config(text=f"Overall: Completed {completed_count} of {total_files} files")
        except Exception as e:
            print(f"Progress update error: {e}") # Non-critical, print to console

    def create_android_ini(self, device_type):
        """Creates the android.ini file for Hekate bootloader"""
        try:
            folder_name = f"Android-{device_type}"
            ini_dir = os.path.join(self.download_dir, folder_name, "bootloader", "ini")
            os.makedirs(ini_dir, exist_ok=True)

            ini_path = os.path.join(ini_dir, "android.ini")

            with open(ini_path, 'w', encoding='utf-8') as f:
                f.write(self.ANDROID_INI_TEMPLATE)

            self.log_message(f"Created android.ini for {device_type} at: bootloader/ini/android.ini")

        except Exception as e:
            self.log_message(f"Error creating android.ini for {device_type}: {e}")

    def reset_ui_after_download(self):
        """Resets the UI to 'Ready' state"""
        self.set_ui_state("normal")
        self.progress_label.config(text="Ready")
        self.total_progress_label.config(text="")
        self.progress_bar["value"] = 0
        
    def format_size(self, size_bytes):
        """Converts bytes to human-readable format"""
        if size_bytes == 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


if __name__ == "__main__":
    # Use the 'darkly' theme from ttkbootstrap
    root = ttk.Window(themename="darkly")
    
    # --- Icon Handling (optional) ---
    # Icons are optional, silently skip if not found

    # Set Windows Taskbar App ID
    if platform.system() == "Windows":
        try:
            myappid = 'mycompany.switchroot.downloader.1'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            print(f"Error setting taskbar icon: {e}")
            
    app = SwitchrootDownloader(root)
    root.mainloop()
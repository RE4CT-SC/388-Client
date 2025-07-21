"""
388-Client
~~~~~~~~~~

Desktop companion app for the “Team-Lead Whisper” Discord workflow.

• First launch → setup wizard:
    1. Press the key / mouse-button / joystick-button you want **twice**.
       (NOTE - left & right mouse clicks are **ignored**).
    2. Paste the bot-issued auth-token.
    3. Config is saved under  %USERPROFILE%\\Documents\\388 Client\\config.json

• Subsequent launches →
    - Press your key once to **/activate** (grants Team-Lead role).
    - Press again any time to **/trigger** (enter/leave leader channel).

Windows users get a chime (“Speech On / Speech Off”) when entering/leaving
the merged channel. Non-Windows → silent stubs (cross-platform friendly).
"""
from __future__ import annotations

import base64, io, json, os, platform, sys, threading, time
from pathlib import Path
from typing import Callable, Optional

import requests
import tkinter as tk
from tkinter import ttk

# --- try to import the real logo ---
try:
    from logo_base64 import LOGO_BASE64 as _LOGO_B64  # user-supplied image
    LOGO_BASE64 = _LOGO_B64
except Exception:
    # 1×1 transparent PNG fallback – prevents crashes if missing
    LOGO_BASE64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+WIuwAAAAASUVORK5CYII="
    )

# --- Optional / soft dependencies ---
try:
    from PIL import Image, ImageTk  # Pillow for logo
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

try:
    import psutil  # raise priority
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import pygame  # joystick support
    PYGAME_OK = True
except ImportError:
    PYGAME_OK = False
    print("pygame not found → joystick buttons disabled")

from pynput import keyboard, mouse

# --- Built-in Windows chimes ---
if platform.system() == "Windows":
    import winsound
    import ctypes
    from ctypes import wintypes

    _SND_ENTER = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Media/Speech On.wav"
    _SND_EXIT = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Media/Speech Off.wav"

    def _play_enter(): winsound.PlaySound(str(_SND_ENTER), winsound.SND_FILENAME | winsound.SND_ASYNC)
    def _play_exit(): winsound.PlaySound(str(_SND_EXIT), winsound.SND_FILENAME | winsound.SND_ASYNC)
else:
    _play_enter = _play_exit = lambda: None  # NOP on macOS/Linux

# --- Paths / constants ---
LOCAL_SERVER_URL = "http://192.168.1.10:28808"
EXTERNAL_SERVER_URL = "https://whisper.ggkserver.com"

CFG_DIR = Path.home() / "Documents/388 Client"
CFG_FILE = CFG_DIR / "config.json"

# --- UI Style Constants ---
STYLE = {
    "bg": "#181818",
    "fg": "#DCDDDE",
    "bg_light": "#2B2B2B",
    "accent": "#5865F2",
    "accent_fg": "#FFFFFF",
    "success": "#43B581",
    "danger": "#F04747",
    "font_normal": ("Segoe UI", 10),
    "font_bold": ("Segoe UI", 11, "bold"),
    "font_header": ("Segoe UI", 14, "bold"),
}

# mouse buttons to ignore during first-run capture
IGNORED_MOUSE = {"left", "right"}  # names as given by pynput Button.name

# --- Helpers - config JSON I/O ---
def load_cfg() -> Optional[dict]:
    if CFG_FILE.exists():
        try:
            with CFG_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Config read failed →", e)
    return None

def save_cfg(cfg: dict) -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    with CFG_FILE.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


# --- Keybind / button listener ---
class KeybindListener:
    """
    Listens for keyboard keys, mouse buttons, and (optionally) joystick buttons.
    Keyboard combinations are now evaluated on key release.
    """
    def __init__(self, on_press: Callable[[str], None]):
        self.on_press = on_press
        self._stop_evt = threading.Event()
        self._debounce = 0.0
        self.pressed_keys = set() # For keyboard combinations

        self.k_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self.m_listener = mouse.Listener(on_click=self._on_mouse_click)

        if PYGAME_OK:
            try:
                pygame.joystick.init()
                self.j_thread = threading.Thread(target=self._joy_loop, daemon=True)
            except pygame.error:
                self.j_thread = None
                print("Pygame joystick init failed → joystick buttons disabled")
        else:
            self.j_thread = None

    def _get_hotkey_str(self) -> str:
        """Creates a canonical string representation from the set of pressed keys."""
        parts = []
        # Sort keys to handle different press orders (e.g., Ctrl+Shift vs Shift+Ctrl)
        # We convert to string for sorting because pynput key types are not comparable
        sorted_keys = sorted(list(self.pressed_keys), key=lambda k: str(k))
        for key in sorted_keys:
            if isinstance(key, keyboard.KeyCode) and key.char:
                parts.append(f"'{key.char}'")
            elif isinstance(key, keyboard.Key):
                parts.append(str(key))
        return "+".join(parts)

    def _trigger(self, code: str):
        """Debounces and calls the main callback."""
        if time.time() - self._debounce > 0.35:
            self._debounce = time.time()
            if self.on_press:
                # Run in a new thread to avoid blocking the listener
                threading.Thread(target=self.on_press, args=(code,), daemon=True).start()

    def _on_key_press(self, key):
        """Press handler: adds the CANONICAL version of the key to the tracking set."""
        try:
            # Use canonical to normalize keys (e.g., get 'c' from Ctrl+C, get '9' from '(')
            canonical_key = self.k_listener.canonical(key)
            self.pressed_keys.add(canonical_key)
        except Exception:
            # Fallback for special keys that might not have a canonical form
            self.pressed_keys.add(key)
    
    def _on_key_release(self, key):
        """Release handler: evaluates the key combination that was held down."""
        hotkey_str = self._get_hotkey_str()
        self.pressed_keys.clear() 

        if not hotkey_str: return
        self._trigger(hotkey_str)

    def _on_mouse_click(self, x, y, button, pressed):
        if not pressed: return
        if button.name in IGNORED_MOUSE: return
        btn_code = f"<Button.{button.name}>"
        self._trigger(btn_code)

    def _joy_loop(self):
        joysticks: dict[int, pygame.joystick.Joystick] = {}
        while not self._stop_evt.is_set():
            for e in pygame.event.get():
                if e.type == pygame.JOYDEVICEADDED:
                    j = pygame.joystick.Joystick(e.device_index)
                    joysticks[j.get_instance_id()] = j
                elif e.type == pygame.JOYDEVICEREMOVED:
                    joysticks.pop(e.instance_id, None)
                elif e.type == pygame.JOYBUTTONDOWN:
                    btn_code = f"joybtn_{e.button}"
                    self._trigger(btn_code)
            time.sleep(0.01)

    def start(self):
        self.k_listener.start()
        self.m_listener.start()
        if self.j_thread: self.j_thread.start()

    def stop(self):
        self._stop_evt.set()
        self.k_listener.stop()
        self.m_listener.stop()


# --- Custom UI Dialogs ---
class CustomDialog(tk.Toplevel):
    """Base class for custom styled dialogs."""
    def __init__(self, parent, title=""):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self.configure(bg=STYLE["bg"])
        s = ttk.Style()
        s.configure("TFrame", background=STYLE["bg"])
        s.configure("TLabel", background=STYLE["bg"], foreground=STYLE["fg"], font=STYLE["font_normal"])
        s.configure("TButton", font=STYLE["font_normal"])

        self.main_frame = ttk.Frame(self, padding="12 12 12 12")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def wait(self):
        self.wait_window()
        return self.result

class MessageDialog(CustomDialog):
    """A custom messagebox."""
    def __init__(self, parent, title, message, alert_type="info"):
        super().__init__(parent, title)
        
        color = {"info": STYLE["fg"], "warning": "#FAA61A", "error": STYLE["danger"]}.get(alert_type, STYLE["fg"])
        
        ttk.Label(self.main_frame, text=message, wraplength=300, foreground=color).grid(row=0, column=0, columnspan=2, pady=(0, 10))
        ok_button = ttk.Button(self.main_frame, text="OK", command=self.destroy)
        ok_button.grid(row=1, column=0, columnspan=2, pady=5)
        ok_button.focus_set()
        self.bind("<Return>", lambda e: self.destroy())


class AskStringDialog(CustomDialog):
    """A custom simpledialog for asking for a string."""
    def __init__(self, parent, title, prompt):
        super().__init__(parent, title)
        ttk.Label(self.main_frame, text=prompt).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        
        self.entry = ttk.Entry(self.main_frame, width=50, font=STYLE["font_normal"])
        self.entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.entry.focus_set()

        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.grid(row=2, column=0, columnspan=2)

        ttk.Button(btn_frame, text="OK", command=self.on_ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=5)
        
        self.bind("<Return>", self.on_ok)
        self.bind("<Escape>", self.on_cancel)

    def on_ok(self, event=None):
        self.result = self.entry.get()
        self.destroy()

    def on_cancel(self, event=None):
        self.destroy()


# --- Main Application UI ---
class App(tk.Tk):
    def __init__(self, cfg: dict | None):
        super().__init__()
        self.cfg = cfg
        self.current_handler = None
        self.first_press: str | None = None
        self._status_poll_thread: threading.Thread | None = None
        self._logo_img = None
        self.is_active_session = False

        self._configure_styles()
        self.title("388-Client")
        self.geometry("500x300")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- Set Title Bar Color (Windows 10/11 only) ---
        if platform.system() == "Windows":
            self.update() 
            try:
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                DWMWA_CAPTION_COLOR = 35 
                COLOR_HEX = 0x00181818
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(ctypes.c_int(COLOR_HEX)), ctypes.sizeof(ctypes.c_int))
            except Exception as e:
                print(f"Failed to set title bar color: {e}")
        
        self.main_frame = ttk.Frame(self, padding="10")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self._load_logo()
        
        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 20))
        self.main_frame.grid_columnconfigure(1, weight=1)
        
        # Create a single, persistent listener
        self.listener = KeybindListener(on_press=self._dispatch_action)
        self.listener.start()

        if self.cfg:
            self.current_handler = self._handle_activation
            self._build_main_ui()
        else:
            self.current_handler = self._handle_capture
            self._build_setup_ui()

    def _load_logo(self):
        """Loads and places the logo in the UI."""
        if PILLOW_OK and LOGO_BASE64:
            try:
                img_data = base64.b64decode(LOGO_BASE64)
                img = Image.open(io.BytesIO(img_data))
                img = img.resize((200, 200), Image.Resampling.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(img)

                logo_label = ttk.Label(self.main_frame, image=self._logo_img, background=STYLE["bg"])
                logo_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

            except Exception as e:
                print(f"Failed to load logo: {e}")
                self._logo_img = None

    def _configure_styles(self):
        self.configure(bg=STYLE["bg"])
        s = ttk.Style()
        s.theme_use('clam')

        s.configure("TFrame", background=STYLE["bg"])
        s.configure("TLabel", background=STYLE["bg"], foreground=STYLE["fg"], font=STYLE["font_normal"])
        s.configure("Header.TLabel", font=STYLE["font_header"], foreground=STYLE["accent_fg"])
        s.configure("Status.TLabel", font=STYLE["font_bold"])
        s.configure("TButton", background=STYLE["accent"], foreground=STYLE["accent_fg"], font=STYLE["font_bold"], borderwidth=0)
        s.map("TButton", background=[('active', STYLE["accent"])])
        s.configure("TEntry", fieldbackground=STYLE["bg_light"], foreground=STYLE["fg"], bordercolor=STYLE["bg_light"], insertcolor=STYLE["fg"])
        
    def _clear_content_frame(self):
        """Clears only the content frame, leaving the logo intact."""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _format_keybind_for_display(self, keybind: str) -> str:
        """Makes the keybind string more human-readable."""
        if keybind.startswith("<Button") or keybind.startswith("joybtn"):
            return keybind.replace("_", " ").replace("<", "").replace(">", "")
        
        parts = keybind.split('+')
        formatted_parts = []
        for part in parts:
            part = part.replace("Key.", "")
            part = part.replace("_r", "").replace("_l", "")
            part = part.replace("'", "")
            formatted_parts.append(part.capitalize())
        return ' + '.join(formatted_parts)

    # --- UI Builders ---
    def _build_setup_ui(self):
        self._clear_content_frame()
        
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(4, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)
        
        ttk.Label(self.content_frame, text="First-Time Setup", style="Header.TLabel", anchor="center").grid(row=1, column=0, pady=(0, 20), sticky="ew")

        self.status_label = ttk.Label(self.content_frame, text="Press your desired key or button twice to confirm.", style="Status.TLabel", wraplength=220, justify="center")
        self.status_label.grid(row=2, column=0, pady=5, sticky="ew")
        
        self.token_frame = ttk.Frame(self.content_frame)
        ttk.Label(self.token_frame, text="Auth Token:").pack(side="top", anchor="w")
        self.token_entry = ttk.Entry(self.token_frame, width=35, state="disabled")
        self.token_entry.pack(side="top", fill="x", expand=True)

        self.save_button = ttk.Button(self.content_frame, text="Save and Continue", state="disabled", command=self._save_new_config)
        
    def _build_main_ui(self):
        self._clear_content_frame()
        
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(5, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ttk.Label(self.content_frame, text="Status: Inactive", style="Status.TLabel", anchor="center")
        self.status_label.grid(row=1, column=0, pady=10, sticky="ew")

        raw_keybind = self.cfg.get('keybind', 'Not Set')
        display_keybind = self._format_keybind_for_display(raw_keybind)
        ttk.Label(self.content_frame, text=f"Your keybind is:", anchor="center").grid(row=2, column=0, sticky="ew")
        ttk.Label(self.content_frame, text=display_keybind, font=STYLE["font_bold"], foreground=STYLE["accent"], anchor="center").grid(row=3, column=0, pady=(0, 10), sticky="ew")

        ttk.Label(self.content_frame, text="Press your keybind to activate as Team-Lead.", name="info_activate", anchor="center", wraplength=220, justify="center").grid(row=4, column=0, sticky="ew")
        
        self.update_status_display("inactive")

    # --- UI Updaters ---
    def update_status_display(self, status: str, message: str | None = None):
        try:
            activate_info = self.content_frame.nametowidget("info_activate")
        except KeyError:
            return

        if status == "inactive":
            activate_info.config(text="Press your keybind to activate as Team-Lead.")
            self.status_label.config(text="Status: Inactive", foreground=STYLE["danger"])
            self.is_active_session = False
        elif status == "activated":
            activate_info.config(text="Press again to start/end a whisper session.")
            self.status_label.config(text="Status: Activated", foreground=STYLE["success"])
            self.is_active_session = True
        elif status == "in_session":
            activate_info.config(text="Press again to end the session or leave early.")
            self.status_label.config(text="Status: In Session", foreground=STYLE["accent"])
        elif status == "error":
             self.status_label.config(text=f"Error: {message}", foreground=STYLE["danger"])

    # --- Action Handlers ---
    def _dispatch_action(self, hotkey_str: str):
        """The single entry point for all keybind presses."""
        if self.current_handler:
            self.current_handler(hotkey_str)

    def _handle_capture(self, code: str):
        """Handles input during the first-time setup phase."""
        self.after(0, self._update_capture_ui, code)

    def _update_capture_ui(self, code: str):
        display_code = self._format_keybind_for_display(code)
        if self.first_press is None:
            self.first_press = code
            self.status_label.config(text=f"First press: {display_code}. Press again.")
        elif code == self.first_press:
            self.current_handler = None # Disable listener during token input
            self.status_label.config(text=f"Keybind Confirmed: {display_code}", foreground=STYLE["success"])
            
            self.token_frame.grid(row=3, column=0, pady=(20, 10), sticky="ew")
            self.save_button.grid(row=4, column=0, pady=10)

            self.token_entry.config(state="normal")
            self.save_button.config(state="normal")
            self.token_entry.focus_set()
        else:
            self.first_press = None
            self.status_label.config(text="Mismatch! Press your desired key again.", foreground=STYLE["danger"])

    def _save_new_config(self):
        token = self.token_entry.get()
        if not token:
            MessageDialog(self, "Setup Incomplete", "Token is required to proceed.", "warning").wait()
            return
        
        self.cfg = { "keybind": self.first_press, "auth_token": token.strip(), "local_instance": "false" }
        save_cfg(self.cfg)
        
        self.token_frame.grid_forget()
        self.save_button.grid_forget()
        
        self._build_main_ui()
        self.current_handler = self._handle_activation

    def _handle_activation(self, code: str):
        if self.cfg and code == self.cfg.get("keybind"):
            self.current_handler = None # Prevent multiple activation requests
            success, message = _http_activate(self.cfg)
            self.after(0, self._on_activation_result, success, message)
        
    def _on_activation_result(self, success: bool, message: str):
        if success:
            self.update_status_display("activated")
            self.current_handler = self._handle_trigger
            self._status_poll_thread = threading.Thread(target=self._status_poll_loop, daemon=True)
            self._status_poll_thread.start()
        else:
            MessageDialog(self, "Activation Failed", message, "error").wait()
            self.current_handler = self._handle_activation

    def _handle_trigger(self, code: str):
        if self.cfg and code == self.cfg.get("keybind"):
            resp = _http_trigger(self.cfg)
            print(f"Trigger response: {resp}")

            if "started" in resp:
                _play_enter()
                self.after(0, self.update_status_display, "in_session")
            elif "ended" in resp or "left" in resp:
                _play_exit()
                self.after(0, self.update_status_display, "activated")

    def _status_poll_loop(self):
        while True:
            time.sleep(15)
            if not self.cfg or not self.is_active_session: 
                break 
            
            is_lead = _http_am_i_lead(self.cfg)
            if not is_lead:
                _play_exit()
                self.after(0, self._on_deactivated_by_server)
                break
    
    def _on_deactivated_by_server(self):
        MessageDialog(self, "Deactivated", "Server revoked your Team-Lead role.", "info").wait()
        self.update_status_display("inactive")
        self.current_handler = self._handle_activation

    def _on_close(self):
        self.listener.stop()
        if self.cfg and self.is_active_session:
            print("Sending deactivation request on close...")
            _http_deactivate(self.cfg)
        
        self.destroy()
        os._exit(0)

# --- HTTP helpers ---
def _base_url(cfg: dict) -> str:
    return LOCAL_SERVER_URL if cfg.get("local_instance") == "true" else EXTERNAL_SERVER_URL

def _http_activate(cfg: dict) -> tuple[bool, str]:
    hdr = {"Authorization": cfg["auth_token"], "Content-Type": "application/json"}
    try:
        r = requests.post(f"{_base_url(cfg)}/activate", headers=hdr, timeout=10)
        return (True, r.text) if r.ok else (False, r.text or r.reason)
    except Exception as e:
        return False, str(e)

def _http_deactivate(cfg: dict) -> None:
    """Notifies the server that the client is closing."""
    hdr = {"Authorization": cfg["auth_token"], "Content-Type": "application/json"}
    try:
        requests.post(f"{_base_url(cfg)}/deactivate", headers=hdr, timeout=3)
    except Exception as e:
        print(f"Could not send deactivation signal: {e}")

def _http_trigger(cfg: dict) -> str:
    hdr = {"Authorization": cfg["auth_token"], "Content-Type": "application/json"}
    try:
        r = requests.post(f"{_base_url(cfg)}/trigger", headers=hdr, timeout=10)
        return r.text.lower()
    except Exception as e:
        return f"error: {e}"

def _http_am_i_lead(cfg: dict) -> bool:
    hdr = {"Authorization": cfg["auth_token"], "Content-Type": "application/json"}
    try:
        r = requests.get(f"{_base_url(cfg)}/status", headers=hdr, timeout=10)
        return r.json().get("is_lead", False)
    except Exception:
        return False

# --- MAIN ---
def main():
    if PYGAME_OK:
        pygame.init() # Initialize pygame once globally

    if PSUTIL_OK and platform.system() == "Windows":
        try:
            psutil.Process(os.getpid()).nice(psutil.HIGH_PRIORITY_CLASS)
        except Exception:
            pass

    config = load_cfg()
    app = App(config)
    app.mainloop()

if __name__ == "__main__":
    main()
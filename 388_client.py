"""
388_client.py – personal notes for 2025‑07‑21 update

•   Fixed that annoying "main thread not in main loop" error – all Tkinter stuff now runs on the main thread.
•   Added pop-ups to explain why activation failed (like if user is not in a voice channel or token's bad).
•   Made it work with pygame 2.6.x (just the joystick API).
"""

# essential imports
import os, sys, time, json, threading, base64, io, requests, tkinter as tk
from tkinter import messagebox
from pynput import keyboard, mouse
from logo_base64 import LOGO_BASE64 # logo data

# Checking if Pillow is available for image handling
try:
    from PIL import Image, ImageTk
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# Checking if psutil is around for process priority
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Checking for pygame for joystick support
try:
    import pygame                      # SDL2 wrapper
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not found – joystick support disabled") # Just a heads-up for myself

# server URLs and config paths
LOCAL_SERVER_URL    = "http://192.168.1.10:28808"
EXTERNAL_SERVER_URL = "https://whisper.ggkserver.com"

# Figuring out where to put config file
try:
    DOCS = os.path.join(os.path.expanduser('~'), 'Documents')
    CONFIG_DIR  = os.path.join(DOCS, '388 Client')
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
except Exception:
    APP = os.path.dirname(os.path.realpath(sys.argv[0]))
    CONFIG_DIR, CONFIG_FILE = APP, os.path.join(APP, 'config.json')

# UI colors
BG_COLOR = "#2E2E2E"; FG_COLOR = "#EAEAEA"; ACCENT = "#E34B4B"
ENTRY_BG = "#3C3C3C"; BTN_BG  = "#4A4A4A"

# keybind detection logic
class KeybindListener:
    """This class detects keyboard, mouse, joystick, and vJoy inputs and triggers activation."""

    def __init__(self, cfg: dict, on_activate):
        self.cfg         = cfg
        self.on_activate = on_activate
        self.stop_evt    = threading.Event()
        self.last_fire   = 0.0
        self.debounce    = 0.35 # Debounce time to prevent multiple triggers
        self.keys_held   = set() # Keeping track of held keys for combos

        # Parsing joystick token (GUID or old format)
        self.t_guid = self.t_btn = None
        self.l_id   = self.l_btn = None
        tok = cfg.get("keybind", "")
        if tok.startswith("joyguid_"):
            _, g, b = tok.split("_", 2)
            self.t_guid, self.t_btn = g.lower(), int(b)
        elif tok.startswith("joy_"):
            _, i, b = tok.split("_", 2)
            self.l_id, self.l_btn = int(i), int(b)

    # --------------- public control methods ---------------
    def start(self):
        # Starting keyboard and mouse listeners
        self.kb_listener = keyboard.Listener(on_press=self._kp, on_release=self._kr)
        self.kb_listener.start()
        self.ms_listener = mouse.Listener(on_click=self._mc); self.ms_listener.start()

        # Starting joystick thread if pygame is available
        if PYGAME_AVAILABLE:
            self.j_thread = threading.Thread(target=self._joy_loop, daemon=True)
            self.j_thread.start()

    def stop(self):
        # Stopping all listeners
        self.stop_evt.set()
        if hasattr(self, "kb_listener"): self.kb_listener.stop()
        if hasattr(self, "ms_listener"): self.ms_listener.stop()

    # --------------- keyboard helpers ------------
    @staticmethod
    def _kstr(k):
        # Converting key objects to strings for comparison
        from pynput.keyboard import Key, KeyCode
        if isinstance(k, Key):     return k.name
        if isinstance(k, KeyCode): return k.char.upper() if k.char else str(k.vk)
        return str(k)

    def _kp(self, key):
        # Handling key presses
        self.keys_held.add(self._kstr(key))
        if set(self.cfg.get("keybind","").split("+")) == self.keys_held:
            self._fire() # Trigger if keybind matches
    def _kr(self, key): self.keys_held.discard(self._kstr(key)) # Removing released keys

    # --------------- mouse handling -----------------------
    def _mc(self, x, y, button, pressed):
        # Handling mouse clicks
        if pressed and f"mouse_{button.name}" == self.cfg.get("keybind"):
            self._fire() # Trigger if mouse button matches

    # --------------- joystick loop ---------------
    def _attach(self, idx, js, id2g):
        # Attaching a joystick
        try:
            j = pygame.joystick.Joystick(idx)
            js[j.get_instance_id()] = j
            id2g[j.get_instance_id()] = j.get_guid().lower()
            print(f"[JOY] attached idx={idx} inst={j.get_instance_id()} guid={id2g[j.get_instance_id()]}") # For own debugging
        except Exception as e:
            print(f"[WARN] could not open joystick {idx}: {e}") # For own debugging

    def _joy_loop(self):
        # main joystick polling loop
        pygame.init(); pygame.joystick.init()
        joysticks, id2g = {}, {}

        # Initial joystick scan
        for i in range(pygame.joystick.get_count()):
            self._attach(i, joysticks, id2g)

        # Only listening for specific pygame events to keep it light
        pygame.event.set_allowed([
            pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED, pygame.JOYBUTTONDOWN
        ])

        # Loop until I tell it to stop
        while not self.stop_evt.is_set():
            for e in pygame.event.get():
                if e.type == pygame.JOYDEVICEADDED:
                    self._attach(e.device_index, joysticks, id2g)
                elif e.type == pygame.JOYDEVICEADDED: # This looks like a duplicate, I should double check this later.
                    self._attach(e.device_index, joysticks, id2g)
                elif e.type == pygame.JOYDEVICEREMOVED:
                    joysticks.pop(e.instance_id, None); id2g.pop(e.instance_id, None)
                elif e.type == pygame.JOYBUTTONDOWN:
                    inst, btn = e.instance_id, e.button
                    guid = id2g.get(inst)
                    if guid is None: # If GUID not found, try to get it
                        try:
                            j = pygame.joystick.Joystick(inst)
                            guid = j.get_guid().lower(); id2g[inst] = guid
                        except Exception:
                            guid = ""
                    # Check if the joystick button matches configured keybind
                    if ((self.t_guid and guid == self.t_guid and btn == self.t_btn) or
                        (self.l_id is not None and inst == self.l_id and btn == self.l_btn)):
                        self._fire()
            time.sleep(0.005) # Small delay to not hog CPU

        # Cleaning up pygame resources
        for j in joysticks.values(): j.quit()
        pygame.joystick.quit(); pygame.quit()

    # --------------- internal trigger logic --------------------
    def _fire(self):
        # Debounce check
        if time.time() - self.last_fire < self.debounce: return
        self.last_fire = time.time()
        # Triggering the activation in a new thread
        threading.Thread(target=self.on_activate, daemon=True).start()

# initial setup window
class SetupWindow:
    """This window captures keybind and authentication token, and stores the joystick GUID."""

    def __init__(self, master, on_complete):
        self.master, self.on_complete = master, on_complete
        self.stage = 1 # setup stage (1: press, 2: confirm, 3: save)
        self.captured = None # What I captured
        self.held = set() # Keys user is holding down
        self.lock = threading.RLock() # For thread safety
        self.stop_evt = threading.Event() # To signal listeners to stop

        # Setting up window
        master.title("388 Client Setup"); master.geometry("400x290")
        master.configure(bg=BG_COLOR); master.resizable(False, False)
        frm = tk.Frame(master, padx=20, pady=20, bg=BG_COLOR); frm.pack(fill="both", expand=True)
        self.info = tk.Label(frm, text="Press desired key / button …",
                             fg=FG_COLOR, bg=BG_COLOR); self.info.pack()
        self.stat = tk.Label(frm, text="", fg=ACCENT, bg=BG_COLOR); self.stat.pack(pady=6)
        self.tk_token = tk.Entry(frm, width=38, bg=ENTRY_BG,
                                fg=FG_COLOR, insertbackground=FG_COLOR)

        self._start_listeners() # Starting input listeners

    # ---------- input listeners ----------
    def _start_listeners(self):
        self.kb = keyboard.Listener(on_press=self._kp,on_release=self._kr); self.kb.start()
        self.ms = mouse.Listener(on_click=self._mc); self.ms.start()
        self.jt = threading.Thread(target=self._joy_loop, daemon=True); self.jt.start()

    def _kp(self,k): self.held.add(KeybindListener._kstr(k)) # Add pressed key
    def _kr(self,k):
        c='+'.join(sorted(self.held)); self._proc(c); self.held.clear() # Process combination on release
    def _mc(self,x,y,b,p):
        if p: self._proc(f"mouse_{b.name}") # Process mouse click

    def _joy_loop(self):
        # joystick setup loop for capturing a keybind
        if not PYGAME_AVAILABLE: return
        pygame.init(); pygame.joystick.init()
        id2g={} # Mapping instance IDs to GUIDs
        for i in range(pygame.joystick.get_count()):
            j=pygame.joystick.Joystick(i); id2g[j.get_instance_id()] = j.get_guid().lower()
        while self.stage<3 and not self.stop_evt.is_set():
            for e in pygame.event.get():
                if e.type==pygame.JOYBUTTONDOWN:
                    if e.instance_id not in id2g: # If new joystick, get its GUID
                        j=pygame.joystick.Joystick(e.instance_id)
                        id2g[e.instance_id]=j.get_guid().lower()
                    self._proc(f"joyguid_{id2g[e.instance_id]}_{e.button}") # Process joystick button
            time.sleep(0.01)
        pygame.quit() # Clean up pygame

    # ---------- state machine for keybind capture ----------
    def _proc(self, tok):
        if not tok: return
        with self.lock: # Ensuring thread safety for state changes
            if self.stage==1: # First press
                self.captured=tok; self.stat.config(text=f"Captured: {tok}"); self.stage=2
            elif self.stage==2: # Second press (confirmation)
                if tok==self.captured:
                    self.stat.config(text="Confirmed – paste token & save.")
                    self.tk_token.pack(pady=8) # Show token entry
                    tk.Button(self.master,text="Save",bg=BTN_BG,fg=FG_COLOR,
                              command=self._save).pack() # Show save button
                    self.stage=3
                else:
                    self.stat.config(text="Mismatch – try again."); self.stage=1 # Mismatch, restart

    def _save(self):
        # Saving configuration
        t=self.tk_token.get().strip()
        if not t: messagebox.showerror("Err","Token required"); return # Token can't be empty
        self.on_complete({"keybind":self.captured,"auth_token":t}) # Call the completion callback
        self.stop_evt.set(); self.master.destroy() # Close the window

# general utility functions
def save_cfg(c): os.makedirs(CONFIG_DIR,exist_ok=True); json.dump(c,open(CONFIG_FILE,"w"),indent=4) # Saving config
def load_cfg():  return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else None # Loading config
def check_status(c,cb):
    # Periodically checking server status to see if user is still the lead
    h={"Authorization":c["auth_token"],"Content-Type":"application/json"}
    base=LOCAL_SERVER_URL if c.get("local_instance")=="true" else EXTERNAL_SERVER_URL
    while True:
        time.sleep(15) # Check every 15 seconds
        try:
            # If user is not the lead anymore, deactivate
            if not requests.get(f"{base}/status",headers=h,timeout=10).json().get("is_lead"):
                cb(); break
        except: cb(); break # If error, assume user is deactivated
def on_deactivated():
    # What to do when user is deactivated by the server
    tk.Tk().withdraw(); messagebox.showinfo("Deactivated","Server cleared lead status."); os._exit(0)
def send_trigger(c):
    # Sending a trigger request to the server
    h={"Authorization":c["auth_token"],"Content-Type":"application/json"}
    base=LOCAL_SERVER_URL if c.get("local_instance")=="true" else EXTERNAL_SERVER_URL
    try: print(requests.post(f"{base}/trigger",headers=h,timeout=10).text) # Print response for own info
    except Exception as e: print("Trigger failed:",e) # Log errors for myself

# activation window
class ActivationWindow:
    def __init__(self,m,c):
        self.master=m; self.c=c
        m.title("Activate"); m.geometry("300x120"); m.configure(bg=BG_COLOR)
        tk.Label(m,text="Press keybind to activate",bg=BG_COLOR,fg=FG_COLOR).pack(pady=20)
        self.listener=KeybindListener(c,on_activate=self._act); self.listener.start() # Start listening for keybind

    # background thread for activation
    def _act(self):
        h={"Authorization":self.c["auth_token"],"Content-Type":"application/json"}
        base=LOCAL_SERVER_URL if self.c.get("local_instance")=="true" else EXTERNAL_SERVER_URL
        try:
            r = requests.post(f"{base}/activate", headers=h, timeout=10)
            r.raise_for_status() # Check for HTTP errors
            # Schedule success on the UI thread
            self.master.after(0, self._success)
        except requests.exceptions.HTTPError as e:
            # custom error messages for common HTTP issues
            msg = ("You must be in a team voice channel."     if e.response.status_code == 403 else
                   "Invalid or expired token."                if e.response.status_code == 401 else
                   f"Server error: {e.response.status_code}")
            self.master.after(0, self._fail, msg) # Schedule failure with message
        except Exception as e:
            self.master.after(0, self._fail, str(e)) # Schedule generic error

    # -------- UI‑thread helpers --------
    def _success(self):
        self.listener.stop() # Stop listening
        self.master.destroy() # Close the window

    def _fail(self, msg):
        self.listener.stop() # Stop listening
        messagebox.showerror("Activation failed", msg) # Show error message
        self.master.destroy() # Close the window

# main program entry point
def main():
    # Trying to set process priority for better performance
    if PSUTIL_AVAILABLE:
        try: psutil.Process(os.getpid()).nice(psutil.HIGH_PRIORITY_CLASS)
        except: pass
    cfg=load_cfg() # Load configuration
    if not cfg:
        # If no config, run the setup window
        root=tk.Tk(); SetupWindow(root,save_cfg); root.mainloop(); cfg=load_cfg()
        if not cfg: return # If still no config after setup, just exit
    act=tk.Tk(); ActivationWindow(act,cfg); act.mainloop() # Show activation window
    # Start the main keybind listener for sending triggers
    listener=KeybindListener(cfg,on_activate=lambda:send_trigger(cfg)); listener.start()
    # Start a background thread to check server status
    threading.Thread(target=check_status,args=(cfg,on_deactivated),daemon=True).start()
    try:
        # Keep the main thread alive
        while True: time.sleep(1)
    except KeyboardInterrupt: listener.stop() # Stop listener on Ctrl+C

if __name__=="__main__":
    main() # Run main function

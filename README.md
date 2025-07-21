# 388 Client

<p align="center">
  <img src="388Logo.png" alt="388 Logo" width="200">
</p>

A small, self‑contained Windows app that lets you **trigger your 388 server with a custom hot‑key**.
It opens a friendly GUI the first time you run it, captures your preferred key‑combo (or mouse / joystick button) and stores your authentication token. From then on, it quietly runs in the background and fires whenever you press the hot‑key.

---

## ✨ Features

* One‑time setup wizard for key‑bind & token
* Works with **keyboard, mouse, Xbox/Direct‑Input joysticks, and vJoy**
* Auto‑retries the server until you become lead, then exits when lead is lost
* Color‑themed Tkinter pop‑ups that explain exactly **why** activation failed
* Optional goodies:

  * **High‑priority process** if `psutil` is installed
  * PNG/ICO logo if Pillow is installed
  * Joystick support if Pygame is installed

The tiny settings file lives in your **Documents → 388 Client → config.json** so you can wipe or move the folder at any time without editing code.

---

## 🖥️ What you’ll need

| Requirement                 | Why you need it               | Download                                                                               |
| --------------------------- | ----------------------------- | -------------------------------------------------------------------------------------- |
| **Python 3.11 or newer**    | Runs the program              | [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/) |
| **Pip** (comes with Python) | Installs the helper libraries | –                                                                                      |
| **A 388 auth token**        | Paste this during first‑run   | Provided by your team                                                                  |

> **Tip:** When you install Python, tick the box that says **“Add python.exe to PATH.”**

---

## 🚀 Quick Start (Non‑technical version)

1. **Download the project**
   *Click the big green **Code** button at the top of the GitHub page → “Download ZIP”.
   Un‑zip it to any folder on your PC (e.g. `C:\388_client`).*

2. **Install the helper libraries**
   *Right‑click the folder while holding **Shift** → **Open PowerShell window here**
   Then copy‑paste:*

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. **Run the app**

   ```powershell
   python 388_client.py
   ```

   *A window pops up asking you to press your desired hot‑key, press it **twice** to confirm, then paste your auth token and click **Save**.
   Another window appears; stay in your team voice‑channel and click the hot‑key once to activate.*

That’s it! The script now lives in your system tray (or task‑bar) and will notify the server whenever you hit the hot‑key.

---

## 🔧 Troubleshooting

| Symptom                                    | Fix                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------- |
| **“Token required”** pop‑up                | Paste a valid token in the box and click **Save**                   |
| **“You must be in a team voice channel.”** | Join a voice channel before triggering                              |
| **Joystick button not recognised**         | Make sure Pygame is installed: `pip install pygame`                 |
| **No icon / blurry icon**                  | Install Pillow: `pip install pillow`                                |
| **Windows Defender alert**                 | Click **More info → Run anyway** (the script isn’t code‑signed yet) |

---

## 📝 Advanced Notes

* Configuration file: `%USERPROFILE%\Documents\388 Client\config.json`
  Delete it to run the setup wizard again.
* Server URL defaults can be changed at the top of **388\_client.py** (`LOCAL_SERVER_URL` & `EXTERNAL_SERVER_URL`).
* Need a desktop shortcut? Right‑click **388\_client.py** → **Send to → Desktop (create shortcut)**.

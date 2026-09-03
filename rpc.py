#!/usr/bin/env python3

"""
Setup
-----
1. Install dependencies:            pip install -r requirements.txt
2. Create a Discord application at  https://discord.com/developers/applications
   and copy its "Application ID" into CLIENT_ID below.
3. To show images, paste there image link/address at LARGE_IMAGE / SMALL_IMAGE below. This is only optional though.
4. Keep Discord running, then run:   python rpc.py
   It updates in real time as you type. Press Ctrl+C to stop.
"""

import argparse
import ctypes
import os
import re
import sys
import time

CLIENT_ID = ""
LARGE_IMAGE = ("https://upload.wikimedia.org/wikipedia/commons/c/c9/"
               "Windows_Notepad_icon.png?utm_source=commons.wikimedia.org"
               "&utm_campaign=index&utm_content=original")
LARGE_TEXT = ""
SMALL_IMAGE = ""
SMALL_TEXT = ""
POLL_INTERVAL = 1.0
MAX_FILE_READ = 20 * 1024 * 1024
IDLE_AFTER_SECONDS = 300

WM_USER = 0x0400
SB_GETPARTS = WM_USER + 6
SB_GETTEXTLENGTH = WM_USER + 12
SB_GETTEXT = WM_USER + 13

SCI_GETCURRENTPOS = 2008
SCI_GETLENGTH = 2010
SCI_GETLINECOUNT = 2154
SCI_LINEFROMPOSITION = 2166
SCI_GETCOLUMN = 2129

CLASSIC_LN_COL_RE = re.compile(
    r"Ln\s*([\d,]+).{0,40}?Col\s*([\d,]+)", re.IGNORECASE)
UIA_LN_COL_RE = re.compile(
    r"Line\s*([\d,]+)\s*(?:,|\s+)\s*Column\s*([\d,]+)", re.IGNORECASE)
UIA_CHARS_RE = re.compile(r"(\d[\d,]*)\s*characters?\b", re.IGNORECASE)

_uia_cache = {"chars": None, "lines": None, "at": 0.0}

user32 = ctypes.windll.user32
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_ssize_t, ctypes.c_ssize_t]

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:
    sys.exit("Missing pywin32. Install it with:  pip install pywin32")

try:
    import psutil
except ImportError:
    psutil = None

try:
    import uiautomation as _uia
except ImportError:
    _uia = None

START_TS = int(time.time())


def get_exe_name(pid):
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
            False, pid)
        try:
            return (win32process.GetModuleFileNameEx(handle, 0) or "").lower()
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def foreground_info():
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        title = win32gui.GetWindowText(hwnd) or ""
        cls = win32gui.GetClassName(hwnd) or ""
    except Exception:
        return None
    return hwnd, pid, title, cls, get_exe_name(pid)


def classify(app):
    if app is None:
        return None
    _hwnd, _pid, title, cls, exe = app
    exe = os.path.basename(exe).lower()
    if exe == "notepad++.exe" or cls == "Notepad++":
        return "notepad++"
    if exe == "notepad.exe" or title.lower().endswith(" - notepad"):
        return "notepad"
    return None


def extract_filename(title, kind):
    marker = "notepad++" if kind == "notepad++" else "notepad"
    idx = title.lower().rfind(" - " + marker)
    if idx == -1:
        idx = title.lower().rfind(" - ")
    name = title[:idx].strip() if idx != -1 else title.strip()
    return name or None


def send_msg(hwnd, msg, wparam=0, lparam=0):
    return user32.SendMessageW(hwnd, msg, wparam, lparam)


def find_children(parent, class_name):
    results = []

    def _cb(h, _):
        if win32gui.GetClassName(h) == class_name:
            results.append(h)
        return True

    win32gui.EnumChildWindows(parent, _cb, None)
    return results


def notepad_plus_info(hwnd):
    scintilla = find_children(hwnd, "Scintilla")
    if not scintilla:
        return None
    h = scintilla[0]
    pos = send_msg(h, SCI_GETCURRENTPOS)
    info = {
        "line": send_msg(h, SCI_LINEFROMPOSITION, pos) + 1,
        "col": send_msg(h, SCI_GETCOLUMN, pos) + 1,
    }
    length = send_msg(h, SCI_GETLENGTH)
    if length > 0:
        info["chars"] = length
        info["lines"] = send_msg(h, SCI_GETLINECOUNT)
    return info


def notepad_status_info(hwnd):
    for child in find_children(hwnd, "msctls_statusbar32"):
        parts = max(send_msg(child, SB_GETPARTS, 0, 0), 1)
        for i in range(parts):
            ln = send_msg(child, SB_GETTEXTLENGTH, i, 0) & 0xFFFF
            if ln <= 0:
                continue
            buf = ctypes.create_unicode_buffer(ln + 1)
            send_msg(child, SB_GETTEXT, i,
                     ctypes.cast(buf, ctypes.c_void_p).value)
            m = CLASSIC_LN_COL_RE.search(buf.value)
            if m:
                return {"line": int(m.group(1).replace(",", "")),
                        "col": int(m.group(2).replace(",", ""))}
    return None


def notepad_uia_info(hwnd):
    if _uia is None:
        return None
    caret = None
    chars = None
    editor_el = None
    try:
        root = _uia.ControlFromHandle(hwnd)
        stack = [root]
        visited = 0
        while stack and visited < 4000:
            el = stack.pop()
            visited += 1
            try:
                name = el.Name or ""
            except Exception:
                continue
            if caret is None:
                m = UIA_LN_COL_RE.search(" ".join(name.split()))
                if m:
                    caret = (int(m.group(1).replace(",", "")),
                             int(m.group(2).replace(",", "")))
            if chars is None:
                m = UIA_CHARS_RE.search(name)
                if m:
                    chars = int(m.group(1).replace(",", ""))
            if editor_el is None:
                try:
                    ctype = (el.ControlTypeName or "")
                except Exception:
                    ctype = ""
                if ctype == "DocumentControl":
                    editor_el = el
            if caret and chars is not None and editor_el:
                break
            try:
                stack.extend(el.GetChildren())
            except Exception:
                pass
    except Exception:
        return None

    info = {}
    if caret:
        info["line"], info["col"] = caret
    if chars is not None:
        info["chars"] = chars
    if chars is not None and chars <= MAX_FILE_READ and editor_el is not None:
        now = time.monotonic()
        if (_uia_cache["chars"] == chars
                and now - _uia_cache["at"] < 2.5
                and _uia_cache["lines"] is not None):
            info["lines"] = _uia_cache["lines"]
        else:
            try:
                text = editor_el.GetValuePattern().Value or ""
            except Exception:
                text = ""
            if text:
                norm = text.replace("\r\n", "\n").replace("\r", "\n")
                lines = norm.count("\n") + (
                    1 if not norm.endswith("\n") else 0)
                info["lines"] = lines
                _uia_cache.update(chars=chars, lines=lines, at=now)
    return info or None


def notepad_info(hwnd):
    return notepad_status_info(hwnd) or notepad_uia_info(hwnd)


def process_file_path(pid):
    if psutil is None:
        return None
    try:
        args = psutil.Process(pid).cmdline()
    except Exception:
        return None
    for arg in args[1:]:
        arg = arg.strip().strip('"')
        if arg and os.path.isfile(arg):
            return arg
    return None


def file_stats(path):
    try:
        if os.path.getsize(path) > MAX_FILE_READ:
            return None
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        return {"chars": len(text), "lines": lines}
    except Exception:
        return None


def pipe_indices():
    indices = []
    for i in range(16):
        if os.path.exists(rf"\\.\pipe\discord-ipc-{i}"):
            indices.append(i)
    return indices


def sync_clients(clients, indices):
    for i in list(clients):
        if i not in indices:
            try:
                clients[i].close()
            except Exception:
                pass
            del clients[i]
    for i in indices:
        if i not in clients:
            try:
                from pypresence import Presence
                c = Presence(CLIENT_ID, pipe=i)
                c.connect()
                clients[i] = c
                print(f"  connected to Discord pipe {i}", flush=True)
            except Exception:
                pass
    return clients


def send_to_all(clients, activity):
    sent = False
    for i, c in list(clients.items()):
        try:
            c.update(name="Notepad",
                     details=activity.get("details"),
                     state=activity.get("state"),
                     start=activity.get("start"),
                     large_image=activity.get("large_image") or None,
                     large_text=activity.get("large_text") or None,
                     small_image=activity.get("small_image") or None,
                     small_text=activity.get("small_text") or None)
            sent = True
        except Exception:
            try:
                c.close()
            except Exception:
                pass
            clients.pop(i, None)
    return sent


def build_activity(app, filename, editor):
    extra_parts = []
    if editor:
        if editor.get("chars") is not None:
            extra_parts.append(f"{(editor['chars']):,} chars")
        if editor.get("lines") is not None:
            extra_parts.append(f"{(editor['lines']):,} lines")
    label = "Notepad++" if app == "notepad++" else "Notepad"
    line_col = None
    if editor and editor.get("line"):
        line_col = f"Line {editor['line']}, Col {editor['col']}"
    return {
        "details": filename or "Untitled",
        "state": line_col or "Idle",
"start": START_TS,
        "large_image": LARGE_IMAGE or None,
        "large_text": LARGE_TEXT or label,
        "small_image": SMALL_IMAGE or None,
        "small_text": SMALL_TEXT or (" - ".join(extra_parts) if extra_parts else None),
        "editor": label,
    }


def idle_activity():
    return {
        "details": "Idle",
        "state": None,
        "start": START_TS,
        "large_image": LARGE_IMAGE or None,
        "large_text": LARGE_TEXT or "Notepad",
        "small_image": SMALL_IMAGE or None,
        "small_text": None,
        "editor": "Notepad",
    }


def activity_key(activity):
    if activity is None:
        return None
    return (activity["details"], activity.get("state"),
            activity.get("small_text"), activity["editor"])


def capture(app):
    kind = classify(app) if app else None
    if kind is None:
        return None
    hwnd, pid, title, _cls, _exe = app
    filename = extract_filename(title, kind)
    if filename and ("\\" in filename or "/" in filename):
        filename = os.path.basename(filename.rstrip("\\/"))
    editor = (notepad_plus_info(hwnd) if kind == "notepad++"
              else notepad_info(hwnd)) or {}
    path = process_file_path(pid)
    if path:
        stats = file_stats(path)
        if stats:
            for key in ("chars", "lines"):
                if editor.get(key) is None:
                    editor[key] = stats[key]
    return build_activity(kind, filename, editor or None)


def main():
    global CLIENT_ID
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", default=CLIENT_ID,
                        help="Discord application ID (overrides CONFIG)")
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL,
                        help="poll interval in seconds")
    parser.add_argument("--debug", action="store_true",
                        help="print every detection cycle")
    args = parser.parse_args()

    client_id = (args.client_id or os.environ.get("DISCORD_CLIENT_ID", "")).strip()
    if not client_id:
        sys.exit("No client ID set. Create a Discord application at "
                 "https://discord.com/developers/applications, put its ID "
                 "into CLIENT_ID at the top of the script, then run it again.")

    CLIENT_ID = client_id
    print(f"Playing Notepad (updates every {args.interval}s). "
          "Press Ctrl+C to stop.", flush=True)
    info = foreground_info()
    if info:
        _hwnd, _pid, _t, _c, _e = info
        print(f"Foreground right now: class={_c!r} title={_t[:50]!r} "
              f"app={os.path.basename(_e)}", flush=True)

    rpc_clients = {}
    last_signature = frozenset()
    last_key = object()
    last_editor = None
    last_editor_at = -1e18

    try:
        while True:
            app = foreground_info()
            snap = capture(app)
            now = time.monotonic()
            if snap is not None:
                last_editor = snap
                last_editor_at = now
            if snap is not None:
                activity = snap
            elif last_editor is not None and now - last_editor_at < IDLE_AFTER_SECONDS:
                activity = last_editor
            else:
                activity = idle_activity()
            if args.debug:
                _hwnd, _pid, _t, _c, _e = app if app else (None, None, "", "", "")
                print("[debug]", repr(_t[:40]), "class=", _c, "->",
                      activity["details"], flush=True)

            signature = frozenset(pipe_indices())
            dirty = signature != last_signature
            if dirty:
                last_signature = signature
                sync_clients(rpc_clients, signature)
            if rpc_clients and (dirty or activity_key(activity) != last_key):
                if send_to_all(rpc_clients, activity):
                    last_key = activity_key(activity)
                    parts = [p for p in (activity.get("details"),
                                         activity.get("state"),
                                         activity.get("small_text")) if p]
                    print("  ->", " | ".join(parts), flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        for i, c in list(rpc_clients.items()):
            try:
                c.clear()
                c.close()
            except Exception:
                pass
        rpc_clients.clear()
        print("\nStopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

# Notepad / Notepad++ Rich Presence for Discord

A small Python program that shows what you are doing in Notepad or
Notepad++ as your Discord "playing" status. While you type, your presence
updates in real time with:

- the file you are editing,
- the line and column the cursor is on,
- (optional) the total number of characters and lines in the file.

It only needs to run in the background on the same PC that runs Discord.

---

## What it does

While you are focused on a Notepad or Notepad++ window, it sets your Discord
Rich Presence to something like:

> **Editing:** `notes.txt`
> **State:** `Line 42, Col 7`
> **Small text:** `8,374 chars - 540 lines`

## Requirements

- Windows 10 or 11 (64-bit)
- Python 3.10+ installed and on your PATH
- Discord desktop app running
- Notepad and/or Notepad++ installed

## Setup

### 1. Install the Python dependencies

Open a terminal in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

This installs:

| Package      | Purpose                                                  |
| ------------ | -------------------------------------------------------- |
| `pywin32`    | Windows API access (windows, Scintilla messages)         |
| `pypresence` | Discord Rich Presence over the local IPC pipe            |
| `psutil`     | Process command lines (file-path fallback for totals)    |
| `uiautomation`| UI Automation (caret/status reading on modern Notepad)  |

### 2. Create a Discord application and get its ID

1. Open https://discord.com/developers/applications
2. Click **New Application**, give it a name (e.g. "Editing"), and create it.
3. Open the **General Information** page.
4. Copy the **Application ID** (a long number).

> This ID is *not* a secret. It is only used to group presence data under
> your app. Do **not** publish your OAuth2 **Client Secret** anywhere - but
> this project never needs it.

### 3. Put the ID into the script

Open `rpc.py`, find the `CONFIG` section at the top and set:

```python
CLIENT_ID = "123456789012345678"
```

Alternative: you do not have to edit the file. You can instead pass it each
time you run, or set an environment variable:

```powershell
.\.venv\Scripts\python rpc.py --client-id 123456789012345678
# or
$env:DISCORD_CLIENT_ID = "123456789012345678"
.\.venv\Scripts\python rpc.py
```

### 4. Run it

```powershell
.\.venv\Scripts\python rpc.py
```

With Discord open, focus a Notepad or Notepad++ window and your status
appears on your Discord profile (Rich Presence is shown to people who open
your profile or use pop-out). Press `Ctrl+C` to stop.

To keep it running with no console window (optional):

```powershell
.\.venv\Scripts\pythonw rpc.py
```

## Configuration

All options live at the top of `rpc.py`:

| Setting          | Default | What it does                                  |
| ---------------- | ------- | --------------------------------------------- |
| `CLIENT_ID`      | `""`    | Your Discord application ID (required)        |
| `LARGE_IMAGE`    | `""`    | Asset key for the large presence image        |
| `LARGE_TEXT`     | `""`    | Caption shown when hovering the large image   |
| `SMALL_IMAGE`    | `""`    | Asset key for the small presence image        |
| `SMALL_TEXT`     | `""`    | Caption for the small image */ extra data     |
| `POLL_INTERVAL`  | `1.0`   | Seconds between checks (0.5 for snappier)     |
| `MAX_FILE_READ`  | 20 MB   | Skip reading files larger than this for totals|

### Command-line options

- `--client-id <id>` - override the application ID.
- `--interval <sec>` - override the poll interval.

### What each presence field shows

- **Details** - the file name.
- **State** - `Line <n>, Col <n>` (your cursor position).
- **Small text / extra line** - `N chars - M lines` when totals are
  available (shown under the activity).

## Troubleshooting

- **"No client ID set" on startup** - put your application ID into
  `CLIENT_ID` or pass `--client-id` (or set `DISCORD_CLIENT_ID`).
- **Presence never appears** - make sure the Discord desktop app is open;
  the script retries every ~5 seconds. If you use a non-standard Discord
  build, confirm it creates the `discord-ipc-*` pipe.
- **No line/column for Notepad on Windows 10** - the old Notepad must be
  visible (not minimized) for its status bar text to be up to date.
- **Notepad++ shows line 1 / no totals** - some repackaged Notepad++ builds
  do not expose document text until the window has really been focused.
  Totals then come from the file on disk as a fallback; the cursor position
  comes from the editor itself.
- **Nothing works / no output** - run with the venv interpreter explicitly
  (`.\.venv\Scripts\python`), not a system Python without the packages.
- **Console shows no prints until you type** - output is streamed as
  activities change; the first line "Watching..." confirms it started.
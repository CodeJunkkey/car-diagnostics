# car-diagnostics

Read your car's fault codes with a cheap Bluetooth ELM327 scanner, a Mac, and a devcontainer.
Nothing is installed on the Mac. The browser page tells you what to do at every step.

```
car → ELM327 scanner → Bluetooth → Mac: "Run Diagnostics.command" (host/agent.py, stock python3)
    → devcontainer: app.py (python-OBD decodes codes, http.server) → http://localhost:8000
```

## Guide for first-time users

### Once, before the first run
1. Plug the scanner into the car's OBD port (under the dashboard, driver side). Turn the ignition on.
2. On the Mac: **System Settings → Bluetooth** → pair **OBDII** (PIN `1234`, or `0000`).
3. Open this folder in VS Code → **Reopen in Container** (first time takes a minute).

### Every time
1. In VS Code press **⇧⌘B** (or Terminal → Run Build Task → **Run Diagnostics**).
   The browser opens http://localhost:8000. If it does not, click the link printed in the terminal.
2. Follow the page. It walks through three steps and updates by itself:
   - **Step 1**: on the Mac, double-click **Run Diagnostics.command** in this folder (Finder). A Terminal window opens; leave it open.
     If macOS refuses to open it: right-click → Open.
     If it says `Operation not permitted`: System Settings → Privacy & Security → Files and Folders → Terminal → enable **Desktop Folder**, quit Terminal, try again.
   - **Step 2**: pick the scanner from the list (pre-selected when it looks like an OBDII port) and press **Connect**.
   - **Step 3**: the page talks to the car. Ignition must be on.
3. Read the result: Check Engine status, stored faults with plain-text meaning, pending faults, live values.
   **Clear codes** resets the Check Engine light (asks for confirmation).

### When you are done
Close the Terminal window from step 1 (or press Ctrl‑C in it). Stop the VS Code task.

## What the pieces are
| File | Where it runs | Job |
|---|---|---|
| `Run Diagnostics.command` | Mac (double-click) | starts `host/agent.py` with macOS's own python3 |
| `host/agent.py` | Mac | lists serial ports, opens the chosen one, bridges bytes to TCP 35000; control API on 35001 |
| `app.py` | devcontainer | web server; talks to the agent and to the car via python-OBD |
| `index.html` | browser | the guided page |
| `.vscode/tasks.json` | VS Code | the single **Run Diagnostics** task |

## Test without a car (inside the devcontainer)
```
elm -s car -b /tmp/elm.txt &             # ELM327 emulator on a pseudo-terminal
AGENT_URL=http://127.0.0.1:35001 OBD_PORT=socket://127.0.0.1:35000 python host/agent.py &
python app.py                            # open http://localhost:8000, pick the /dev/pts/N port
```

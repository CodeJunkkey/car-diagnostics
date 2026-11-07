#!/bin/bash
# Double-click me in Finder. Starts the host agent with the Python that ships with macOS. Nothing is installed.
cd "$(dirname "$0")" || exit 1
if ! cat host/agent.py >/dev/null 2>&1; then
  echo
  echo "macOS is blocking Terminal from reading this folder (Desktop is protected)."
  echo "Fix once: System Settings -> Privacy & Security -> Files and Folders -> Terminal -> enable Desktop Folder."
  echo "Then quit Terminal (Cmd+Q) and double-click 'Run Diagnostics.command' again."
  echo
  read -r -p "Press Enter to close."
  exit 1
fi
exec /usr/bin/python3 host/agent.py

"""
dev.py — Live Auto-Reload Dev Runner for Transformers Desktop App
─────────────────────────────────────────────────────────────────
Runs app.py and watches project files for changes. Whenever you edit and
save any Python file (.py) or configuration (.env), it automatically
restarts the desktop application in under a second and re-opens to the
exact screen you were actively viewing!

Usage:
    py dev.py
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# Directories to ignore
IGNORED_DIRS = {
    ".git", "__pycache__", "venv", "env", "local_data",
    "output", ".pytest_cache", ".system_generated", ".gemini",
    "scratch", "dist", "build", ".idea", ".vscode"
}

# Watched extensions
WATCHED_EXTS = {".py", ".env"}


def get_project_files():
    """Gathers all watchable files with their last modified timestamps."""
    files = {}
    root = Path(__file__).resolve().parent
    for p in root.rglob("*"):
        try:
            # Skip ignored directories
            if any(part in IGNORED_DIRS for part in p.parts):
                continue
            if p.is_file() and (p.suffix in WATCHED_EXTS or p.name == ".env"):
                files[str(p)] = p.stat().st_mtime
        except Exception:
            pass
    return files


def terminate_process(proc):
    """Cleanly terminates the child process and its child processes on Windows."""
    if proc and proc.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def main():
    root = Path(__file__).resolve().parent
    app_script = str(root / "app.py")
    python_exe = sys.executable

    print("\n" + "=" * 65)
    print("  ⚡ Transformers — Live Development Auto-Reloader")
    print("=" * 65)
    print(f"  • Interpreter: {python_exe}")
    print(f"  • Entry Point: {app_script}")
    print("  • Watching:    *.py and .env files across project")
    print("  • Auto-Reload: Saves in VS Code / editor restart the app instantly")
    print("  • In-App Key:  Press F5 or Ctrl+R inside app window anytime")
    print("  • Tab Memory:  Automatically reopens your current active tab")
    print("  • Stop:        Press Ctrl+C in this terminal to exit")
    print("=" * 65 + "\n")

    current_proc = None

    def launch():
        nonlocal current_proc
        terminate_process(current_proc)
        print(f"[{time.strftime('%H:%M:%S')}] 🚀 Starting Transformers app...")
        current_proc = subprocess.Popen([python_exe, app_script])

    launch()

    # Try watchdog if installed, else fallback to high-efficiency mtime polling
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class ChangeHandler(FileSystemEventHandler):
            def __init__(self):
                super().__init__()
                self.last_reload = 0.0

            def on_any_event(self, event):
                if event.is_directory:
                    return
                src = event.src_path
                # Check ignored directories
                parts = Path(src).parts
                if any(ignored in parts for ignored in IGNORED_DIRS):
                    return
                ext = Path(src).suffix
                name = Path(src).name
                if ext in WATCHED_EXTS or name == ".env":
                    now = time.time()
                    if now - self.last_reload > 0.6:  # 600ms debounce
                        self.last_reload = now
                        rel_path = os.path.relpath(src, str(root))
                        print(f"\n[{time.strftime('%H:%M:%S')}] 🔄 File changed: {rel_path} — Reloading...")
                        launch()

        event_handler = ChangeHandler()
        observer = Observer()
        observer.schedule(event_handler, path=str(root), recursive=True)
        observer.start()

        try:
            while True:
                time.sleep(0.5)
                # Check if app was closed normally by user (and not restarted by watcher)
                if current_proc and current_proc.poll() is not None:
                    # Child exited on its own, wait for user file edit to bring it back or keep watching
                    pass
        except KeyboardInterrupt:
            print("\n[DEV] Stopping live dev watcher...")
            observer.stop()
            observer.join()
            terminate_process(current_proc)
            print("[DEV] Done.")

    except ImportError:
        # Polling fallback
        last_snapshots = get_project_files()
        try:
            while True:
                time.sleep(0.6)
                current_snapshots = get_project_files()
                changed = None
                for path, mtime in current_snapshots.items():
                    if path not in last_snapshots or mtime > last_snapshots[path]:
                        changed = path
                        break

                if changed:
                    rel = os.path.relpath(changed, str(root))
                    print(f"\n[{time.strftime('%H:%M:%S')}] 🔄 File changed: {rel} — Reloading...")
                    last_snapshots = current_snapshots
                    launch()
                else:
                    last_snapshots = current_snapshots
        except KeyboardInterrupt:
            print("\n[DEV] Stopping live dev watcher...")
            terminate_process(current_proc)
            print("[DEV] Done.")


if __name__ == "__main__":
    main()

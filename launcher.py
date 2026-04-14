#!/usr/bin/env python3
import os
import sys
import threading
import time
import tempfile
import webbrowser

import uvicorn


def _bundle_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return os.path.abspath(os.path.dirname(__file__))


def _default_data_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".smellhub")


def _resolve_writable_data_dir() -> str:
    candidates = []
    env_dir = os.environ.get("SMELLHUB_DATA_DIR")
    if env_dir:
        candidates.append(os.path.abspath(env_dir))
    candidates.append(os.path.abspath(_default_data_dir()))
    candidates.append(os.path.abspath(os.path.join(os.getcwd(), ".smellhub")))
    candidates.append(os.path.abspath(os.path.join(tempfile.gettempdir(), ".smellhub")))

    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            os.makedirs(os.path.join(path, "projects"), exist_ok=True)
            return path
        except Exception:
            continue
    raise RuntimeError("Unable to find a writable data directory for SMELLHUB_DATA_DIR")


def _open_browser_later(url: str, delay: float) -> None:
    def _runner() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    th = threading.Thread(target=_runner, daemon=True)
    th.start()


def main() -> None:
    resource_root = _bundle_root()
    data_dir = _resolve_writable_data_dir()

    os.environ.setdefault("SMELLHUB_RESOURCE_ROOT", resource_root)
    os.environ["SMELLHUB_DATA_DIR"] = data_dir

    host = os.environ.get("SMELLHUB_HOST", "127.0.0.1")
    port = int(os.environ.get("SMELLHUB_PORT", "8001"))
    open_browser = os.environ.get("SMELLHUB_OPEN_BROWSER", "1") == "1"

    if open_browser:
        _open_browser_later(f"http://{host}:{port}", delay=1.2)

    from api.main import app
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

"""Double-click entry point: starts the local server (if not running) and opens the browser."""
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"


def running():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def open_when_ready():
    for _ in range(400):
        if running():
            webbrowser.open(URL)
            return
        time.sleep(0.2)


if __name__ == "__main__":
    if running():
        webbrowser.open(URL)
        sys.exit(0)
    (ROOT / "data").mkdir(exist_ok=True)
    log_file = open(ROOT / "data" / "app.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None or "pythonw" in sys.executable.lower():
        sys.stdout = sys.stderr = log_file
    logging.basicConfig(level=logging.INFO, stream=log_file, format="%(asctime)s %(levelname)s %(message)s")
    sys.path.insert(0, str(ROOT))
    import uvicorn

    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("app.server:app", host="127.0.0.1", port=PORT, log_config=None, access_log=False)

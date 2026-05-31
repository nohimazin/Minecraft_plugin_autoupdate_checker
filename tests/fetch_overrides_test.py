import os
import threading
import http.server
import socketserver
import time
from pathlib import Path


def run_server(directory: Path, port: int = 8000):
    handler = http.server.SimpleHTTPRequestHandler
    # Python 3.7+ supports 'directory' arg
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    cwd = Path.cwd()
    try:
        os.chdir(str(directory))
        thread.start()
        return httpd
    finally:
        os.chdir(str(cwd))


def main():
    repo_root = Path(__file__).parent.parent
    overrides_path = repo_root / "overrides.json"
    if not overrides_path.exists():
        print("tests: overrides.json not found in repo root; create or copy one to proceed")
        return

    # compute sha256 to pass validation
    import hashlib

    raw = overrides_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    server = run_server(repo_root, port=8000)
    try:
        os.environ["OVERRIDES_URL"] = "http://127.0.0.1:8000/overrides.json"
        os.environ["OVERRIDES_SHA256"] = sha

        # import the app which triggers _load_overrides at module import
        import importlib
        import sys
        sys.path.insert(0, str(repo_root))
        import app as appmod
        importlib.reload(appmod)

        print("tests: OVERRIDES loaded keys:", list(appmod.OVERRIDES.keys())[:10])
        print("tests: total overrides entries:", len(appmod.OVERRIDES))
    finally:
        try:
            server.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()

"""Supervise web and daily worker together on one persistent host."""
import os
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse

from manage import preflight
from settings import data_root


def main():
    if os.environ.get("INFINITY_ENFORCE_PUBLIC_PREFLIGHT", "0") == "1":
        result = preflight(public=True, online=True)
        failed = [row["check"] for row in result["checks"] if not row["ready"]]
        if failed:
            raise SystemExit("Public release checks failed: " + ", ".join(failed))
    data_root().mkdir(parents=True, exist_ok=True, mode=0o700)
    data_root().chmod(0o700)
    secret = data_root() / ".streamlit-cookie-secret"
    if not secret.exists():
        import secrets
        try:
            with open(secret, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                stream.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
    os.environ["STREAMLIT_SERVER_COOKIE_SECRET"] = secret.read_text().strip()
    public = urlparse(os.environ.get("INFINITY_PUBLIC_URL", ""))
    if public.scheme == "https" and public.hostname:
        os.environ["STREAMLIT_BROWSER_SERVER_ADDRESS"] = public.hostname
        os.environ["STREAMLIT_BROWSER_SERVER_PORT"] = "443"
    children = [subprocess.Popen([sys.executable, "-m", "worker"]), subprocess.Popen([sys.executable, "-m", "reconcile"]), subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "main.py", "--server.headless", "true",
        "--server.address", "0.0.0.0", "--server.port", os.environ.get("PORT", "8501"),
        "--server.fileWatcherType", "none", "--browser.gatherUsageStats", "false"])]
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
        for child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped:
            if any(child.poll() is not None for child in children):
                stop()
                raise SystemExit("A required beta service stopped; restart the deployment.")
            time.sleep(1)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()

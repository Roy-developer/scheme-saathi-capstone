"""Run the FastAPI backend and Streamlit frontend in one container."""

import signal
import subprocess
import sys
import time


def main() -> int:
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
    )
    ui = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/ui/app.py",
            "--server.address",
            "0.0.0.0",
            "--server.port",
            "8501",
        ]
    )
    children = (api, ui)

    def stop_children(_signal_number: int, _frame: object) -> None:
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop_children)
    signal.signal(signal.SIGINT, stop_children)

    try:
        while True:
            for child in children:
                exit_code = child.poll()
                if exit_code is not None:
                    return exit_code
            time.sleep(0.25)
    finally:
        stop_children(signal.SIGTERM, None)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())

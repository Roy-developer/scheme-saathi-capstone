"""Start the API, UI, or both for local development."""

import argparse
import signal
import subprocess
import sys
import time


def service_commands(service: str) -> tuple[list[str], ...]:
    api = [
        sys.executable,
        "-m",
        "uvicorn",
        "src.api.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    ui = [
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
    if service == "api":
        return (api,)
    if service == "ui":
        return (ui,)
    if service == "all":
        return (api, ui)
    raise ValueError(f"Unknown service: {service}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "service",
        choices=("all", "api", "ui"),
        nargs="?",
        default="all",
    )
    args = parser.parse_args(argv)
    children = tuple(
        subprocess.Popen(command)
        for command in service_commands(args.service)
    )

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

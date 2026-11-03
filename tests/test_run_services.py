import sys

from src.run_services import service_commands


def test_api_service_command_listens_on_container_interface() -> None:
    commands = service_commands("api")

    assert len(commands) == 1
    assert commands[0] == [
        sys.executable,
        "-m",
        "uvicorn",
        "src.api.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]


def test_ui_and_combined_service_commands() -> None:
    ui = service_commands("ui")
    combined = service_commands("all")

    assert len(ui) == 1
    assert "streamlit" in ui[0]
    assert ui[0] in combined
    assert len(combined) == 2

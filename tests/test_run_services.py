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


def test_docker_image_copies_every_scheme_data_path_the_app_reads() -> None:
    """The image once left out mock_forms, so drafts failed only in Azure."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    for path in (
        "data/schemes/passages",
        "data/schemes/document_checklists",
        "data/schemes/document_evidence.json",
        "data/schemes/mock_forms",
    ):
        assert (root / path).exists(), path
        assert f"COPY {path} ./{path}" in dockerfile, f"Dockerfile does not copy {path}"

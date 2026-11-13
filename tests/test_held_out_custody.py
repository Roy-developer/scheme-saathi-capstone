"""Repository custody guard for protected held-out evaluation inputs."""

from scripts.check_held_out_custody import docker_context_errors, main


def test_protected_held_out_personas_are_not_tracked() -> None:
    assert main() == 0


def test_docker_build_context_excludes_evaluation_and_heldout(tmp_path) -> None:
    (tmp_path / ".dockerignore").write_text(
        ".git\neval\ndata/heldout\n",
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile.api.dockerignore").write_text(
        "eval\ndata/heldout\n",
        encoding="utf-8",
    )

    assert docker_context_errors(tmp_path) == []


def test_docker_build_context_fails_closed_when_override_omits_heldout(
    tmp_path,
) -> None:
    (tmp_path / ".dockerignore").write_text(
        "eval\ndata/heldout\n",
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile.api.dockerignore").write_text("eval\n", encoding="utf-8")

    errors = docker_context_errors(tmp_path)

    assert errors == ["Dockerfile.api.dockerignore must exclude 'data/heldout'."]

import pytest

from src.config import load_project_dotenv


def test_isolated_tool_child_can_skip_project_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEME_SAATHI_DISABLE_DOTENV", "1")

    def unexpected_dotenv_load(*_args, **_kwargs) -> None:
        pytest.fail("The isolated tool child must not load the project .env.")

    monkeypatch.setattr("src.config.load_dotenv", unexpected_dotenv_load)

    load_project_dotenv()

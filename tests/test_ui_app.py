"""Exercise the Streamlit result path with a fresh session."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_evaluating_result_without_prepared_draft_does_not_raise() -> None:
    """A fresh session can show a result before any application draft exists."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    app = AppTest.from_file(app_path).run()
    assert not app.exception

    app.checkbox[0].check().run()
    evaluate_button = next(
        button
        for button in app.button
        if button.label == "View expected fixture result"
    )
    evaluate_button.click().run()

    assert not app.exception

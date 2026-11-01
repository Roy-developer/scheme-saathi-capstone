"""Exercise the Streamlit result path with a fresh session."""

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.api.eligibility import EligibilityResponse, RuleEvidence


def test_evaluating_result_without_prepared_draft_does_not_raise() -> None:
    """A fresh session can check an example through the API."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    response = EligibilityResponse(
        scheme_id="IGNWPS-MH",
        result="need_more_information",
        reason="API response test",
        age_on_application_date=40,
        missing_fields=["government_bpl_card"],
        deciding_rule_ids=["IGNWPS-MH-BPL-01"],
        evidence=[
            RuleEvidence(
                rule_id="IGNWPS-MH-BPL-01",
                source_clause_id="IGNWPS-MH-ELIGIBILITY-01",
                source_url=(
                    "https://sjsa.maharashtra.gov.in/en/scheme/"
                    "indira-gandhi-national-widow-pension-scheme/"
                ),
                source_text="Official source excerpt",
            )
        ],
    )

    with patch(
        "src.ui.api_client.evaluate_profile",
        return_value=response,
    ) as evaluate_profile:
        app = AppTest.from_file(app_path).run()
        assert not app.exception

        app.checkbox[0].check().run()
        evaluate_button = next(
            button for button in app.button if button.label == "Check eligibility"
        )
        evaluate_button.click().run()

        assert not app.exception
        evaluate_profile.assert_called_once()
        assert "API response test" in [element.value for element in app.markdown]
        assert any(
            "government_bpl_card" in element.value for element in app.warning
        )

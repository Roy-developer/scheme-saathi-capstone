"""Exercise the Streamlit result path with a fresh session."""

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.api.eligibility import EligibilityResponse, RuleEvidence
from src.api.scheme_search import load_passages
from src.workflow.journey import JourneyResponse


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

    passage = load_passages(
        Path(__file__).resolve().parents[1]
        / "data"
        / "schemes"
        / "passages.json"
    )[0]

    def fake_journey(request):
        if request.action == "search":
            return JourneyResponse(
                conversation_id=request.conversation_id,
                plan="Search for a relevant scheme.",
                status="search_results",
                message="Found one cited passage.",
                passages=[passage],
                conversation=[
                    {"role": "user", "content": request.query},
                    {"role": "assistant", "content": "Search complete."},
                ],
            )
        return JourneyResponse(
            conversation_id=request.conversation_id,
            plan="Check the selected scheme.",
            status=response.result,
            message=response.reason,
            eligibility_result=response,
            conversation=[
                {"role": "assistant", "content": response.reason},
            ],
        )

    with patch(
        "src.ui.api_client.run_journey",
        side_effect=fake_journey,
    ) as run_graph:
        app = AppTest.from_file(app_path).run()
        assert not app.exception

        app.text_input[0].set_value("widow pension")
        search_button = next(
            button for button in app.button if button.label == "Search schemes"
        )
        search_button.click().run()
        assert not app.exception
        assert run_graph.call_args_list[0].args[0].action == "search"

        continue_button = next(
            button
            for button in app.button
            if button.label == "Continue to the synthetic eligibility demo"
        )
        continue_button.click().run()
        assert not app.exception

        app.checkbox[0].check().run()
        evaluate_button = next(
            button for button in app.button if button.label == "Check eligibility"
        )
        evaluate_button.click().run()

        assert not app.exception
        assert run_graph.call_args_list[1].args[0].action == "evaluate"
        assert "API response test" in [element.value for element in app.markdown]
        assert any(
            "government_bpl_card" in element.value for element in app.warning
        )

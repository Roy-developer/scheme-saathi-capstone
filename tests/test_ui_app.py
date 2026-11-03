"""Exercise the Streamlit result path with a fresh session."""

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest

from src.api.eligibility import EligibilityResponse, RuleEvidence
from src.api.scheme_search import load_passages
from src.workflow.journey import JourneyResponse
from src.workflow.state import (
    CandidateVerdict,
    JourneyHistoryEvent,
    Plan,
    PlanChange,
    PlanStep,
)


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
        # Phase 2 opens the chat by default; this test uses an example person.
        next(
            radio
            for radio in app.radio
            if radio.label == "How do you want to check?"
        ).set_value("example").run()
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


def _pmkisan_passage():
    """Return one PM-KISAN search passage from the real passage file."""

    return next(
        passage
        for passage in load_passages(
            Path(__file__).resolve().parents[1]
            / "data"
            / "schemes"
            / "passages.json"
        )
        if passage.scheme_id == "PM-KISAN-IN"
    )


def _widow_passage():
    """Return one widow-pension search passage from the real passage file."""

    return next(
        passage
        for passage in load_passages(
            Path(__file__).resolve().parents[1]
            / "data"
            / "schemes"
            / "passages.json"
        )
        if passage.scheme_id == "IGNWPS-MH"
    )


def _plan(intake_status: str, eligibility_status: str) -> Plan:
    """A two-step supervisor plan with the given step statuses."""

    return Plan(
        steps=[
            PlanStep(
                step_id="intake",
                specialist="intake",
                goal="Learn about you",
                status=intake_status,
            ),
            PlanStep(
                step_id="eligibility",
                specialist="eligibility",
                goal="Check the rules for PM-KISAN-IN",
                status=eligibility_status,
                scheme_id="PM-KISAN-IN",
            ),
        ]
    )


def test_pmkisan_continue_opens_chat_that_asks_then_shows_verdict() -> None:
    """PM-KISAN: Continue -> Start questions -> answer -> verdict."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    question = "Does your family have farmland in the State or UT land records?"
    eligibility = EligibilityResponse(
        scheme_id="PM-KISAN-IN",
        result="eligible",
        reason="Answers meet the 2020 mock criteria.",
        deciding_rule_ids=[],
        evidence=[],
        notice="Mock result using the 2020 guidelines.",
    )

    def fake_journey(request):
        if request.action == "search":
            return JourneyResponse(
                conversation_id=conversation_id,
                plan="Search for a source-cited scheme.",
                status="search_results",
                message=(
                    "Found one relevant cited passage across 1 scheme. "
                    "Showing up to 20 passages; search may not find every "
                    "relevant scheme."
                ),
                passages=[_pmkisan_passage()],
            )
        assert request.action == "interview"
        return JourneyResponse(
            conversation_id=request.conversation_id,
            plan="Learn about you -> Check the rules",
            plan_detail=_plan("in_progress", "pending"),
            status="awaiting_answer",
            message=question,
            question=question,
            pending_fact="landholding_family_in_state_records",
            conversation=[{"role": "assistant", "content": question}],
        )

    def fake_message(conversation, message):
        assert conversation == str(conversation_id)
        return JourneyResponse(
            conversation_id=conversation_id,
            plan="Learn about you -> Check the rules",
            plan_detail=_plan("done", "done"),
            status="eligible",
            message=eligibility.reason,
            eligibility_result=eligibility,
            conversation=[
                {"role": "assistant", "content": question},
                {"role": "user", "content": message},
                {"role": "assistant", "content": eligibility.reason},
            ],
        )

    with patch(
        "src.ui.api_client.run_journey", side_effect=fake_journey
    ) as run_graph, patch(
        "src.ui.api_client.send_journey_message", side_effect=fake_message
    ) as send_reply:
        app = AppTest.from_file(app_path).run()
        app.text_input[0].set_value("PM-KISAN farmer support")
        next(
            button for button in app.button if button.label == "Search schemes"
        ).click().run()
        assert any(
            "Showing up to 20 passages" in element.value
            for element in app.caption
        )
        # Search alone never shows the PM-KISAN check.
        assert not any(
            "current landholding cutoff" in element.value
            for element in app.warning
        )

        next(
            button
            for button in app.button
            if button.label == "Continue to the synthetic eligibility demo"
        ).click().run()
        assert not app.exception
        assert any(
            "current landholding cutoff" in element.value
            for element in app.warning
        )
        # No form any more: nothing is asked until the chat starts.
        assert not app.selectbox[1:]
        next(
            button for button in app.button if button.label == "Start questions"
        ).click().run()

        assert not app.exception
        interview_request = run_graph.call_args_list[-1].args[0]
        assert interview_request.action == "interview"
        assert interview_request.scheme_id == "PM-KISAN-IN"
        # The plan checklist and the first question are on screen.
        markdown = [element.value for element in app.markdown]
        assert "? Learn about you" in markdown
        assert question in markdown
        assert app.query_params["scheme"] == "PM-KISAN-IN"
        assert app.query_params["conversation"] == str(conversation_id)

        app.chat_input[0].set_value("yes").run()

        assert not app.exception
        send_reply.assert_called_once_with(str(conversation_id), "yes")
        assert any(
            "Appears eligible" in element.value for element in app.success
        )
        # Once finished, there is no answer box.
        assert not app.chat_input


def test_check_all_found_schemes_starts_one_shared_chat() -> None:
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    question = "Are you a widow?"

    def fake_journey(request):
        if request.action == "search":
            return JourneyResponse(
                conversation_id=conversation_id,
                plan="Search for schemes.",
                status="search_results",
                message="Found passages.",
                passages=[_pmkisan_passage(), _widow_passage()],
            )
        assert request.candidate_scheme_ids == ["PM-KISAN-IN", "IGNWPS-MH"]
        return JourneyResponse(
            conversation_id=conversation_id,
            plan="Learn about you -> Check both schemes",
            plan_detail=Plan(
                steps=[
                    PlanStep(
                        step_id="intake", specialist="intake",
                        goal="Learn about you", status="in_progress",
                    ),
                    PlanStep(
                        step_id="eligibility:PM-KISAN-IN",
                        specialist="eligibility", goal="Check PM-KISAN-IN",
                        scheme_id="PM-KISAN-IN",
                    ),
                    PlanStep(
                        step_id="eligibility:IGNWPS-MH",
                        specialist="eligibility", goal="Check IGNWPS-MH",
                        scheme_id="IGNWPS-MH",
                    ),
                ]
            ),
            status="awaiting_answer",
            message=question,
            question=question,
            pending_fact="is_widow",
            candidate_scheme_ids=["PM-KISAN-IN", "IGNWPS-MH"],
            conversation=[{"role": "assistant", "content": question}],
        )

    def fake_message(_conversation_id, _message):
        result = EligibilityResponse(
            scheme_id="PM-KISAN-IN",
            result="not_eligible",
            reason="Income tax exclusion.",
            deciding_rule_ids=["PMKISAN-INCOME-TAX-01"],
            evidence=[],
        )
        return JourneyResponse(
            conversation_id=conversation_id,
            plan="Learn about you -> Check both schemes",
            status="completed",
            message="Checks finished.",
            candidate_scheme_ids=["PM-KISAN-IN", "IGNWPS-MH"],
            candidate_verdicts={
                "PM-KISAN-IN": CandidateVerdict(
                    scheme_id="PM-KISAN-IN",
                    result="not_eligible",
                    deciding_rule_ids=["PMKISAN-INCOME-TAX-01"],
                ),
            },
            eligibility_results={"PM-KISAN-IN": result},
            plan_change_history=[
                PlanChange(
                    from_version=1,
                    to_version=2,
                    scheme_id="PM-KISAN-IN",
                    result="not_eligible",
                    deciding_rule_ids=["PMKISAN-INCOME-TAX-01"],
                    reason="PM-KISAN-IN was ruled out by the mock rules.",
                )
            ],
            known_fact_names=["is_widow"],
            journey_history=[
                JourneyHistoryEvent(
                    event_type="tool_retry",
                    scheme_id="PM-KISAN-IN",
                    attempt=1,
                    reason="Eligibility check retry.",
                )
            ],
        )

    def fake_correction(conversation_id, fact_name, answer):
        assert conversation_id == str(conversation_id_value)
        assert fact_name == "is_widow"
        assert answer == "no"
        corrected = fake_message(conversation_id, answer)
        return corrected.model_copy(update={
            "journey_history": [
                JourneyHistoryEvent(
                    event_type="answer_corrected",
                    fact_name=fact_name,
                    reason="The user corrected is_widow; rechecking scheme rules.",
                    plan_version=5,
                )
            ]
        })

    conversation_id_value = conversation_id
    with patch("src.ui.api_client.run_journey", side_effect=fake_journey) as run_graph, patch(
        "src.ui.api_client.send_journey_message", side_effect=fake_message
    ), patch(
        "src.ui.api_client.correct_journey_answer", side_effect=fake_correction
    ) as correct_answer:
        app = AppTest.from_file(app_path).run()
        app.text_input[0].set_value("farmer widow support")
        next(button for button in app.button if button.label == "Search schemes").click().run()
        next(
            button for button in app.button
            if button.label == "Check all found schemes"
        ).click().run()
        assert not app.exception
        request = run_graph.call_args_list[-1].args[0]
        assert request.candidate_scheme_ids == ["PM-KISAN-IN", "IGNWPS-MH"]
        assert app.query_params["schemes"] == "PM-KISAN-IN,IGNWPS-MH"
        assert question in [message.value for message in app.markdown]
        assert any("Check the matching schemes" in item.value for item in app.subheader)
        app.chat_input[0].set_value("yes").run()
        assert not app.exception
        assert any(
            "Why the plan changed" in item.value for item in app.markdown
        )
        assert any(
            "PM-KISAN-IN was ruled out by the mock rules."
            in item.value for item in app.caption
        )
        assert any("Retry:" in item.value for item in app.caption)
        assert app.selectbox[-1].label == "Which answer do you want to correct?"
        app.text_input[-1].set_value("no")
        next(
            button for button in app.button
            if button.label == "Save correction and recheck"
        ).click().run()
        correct_answer.assert_called_once_with(
            str(conversation_id), "is_widow", "no"
        )
        assert not app.exception


def test_refresh_restores_saved_conversation_from_url() -> None:
    """A page refresh reloads the waiting question through the GET API."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    question = "Is the farmland held by an institution?"
    saved = JourneyResponse(
        conversation_id=conversation_id,
        plan="Learn about you -> Check the rules",
        plan_detail=_plan("in_progress", "pending"),
        status="awaiting_answer",
        message=question,
        question=question,
        pending_fact="institutional_landholder",
        conversation=[{"role": "assistant", "content": question}],
    )

    with patch(
        "src.ui.api_client.get_journey_state", return_value=saved
    ) as load:
        app = AppTest.from_file(app_path)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "PM-KISAN-IN"
        app.run()

        assert not app.exception
        load.assert_called_once_with(str(conversation_id))
        assert question in [element.value for element in app.markdown]
        assert len(app.chat_input) == 1


def test_refresh_with_forgotten_conversation_cleans_url() -> None:
    """If the API has nothing saved, the search screen shows as normal."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    with patch("src.ui.api_client.get_journey_state", return_value=None):
        app = AppTest.from_file(app_path)
        app.query_params["conversation"] = str(uuid4())
        app.query_params["scheme"] = "PM-KISAN-IN"
        app.run()

        assert not app.exception
        assert "conversation" not in app.query_params
        assert any(
            button.label == "Search schemes" for button in app.button
        )

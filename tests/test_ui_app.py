"""Exercise the Streamlit result path with a fresh session."""

from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from src.api.eligibility import EligibilityResponse, RuleEvidence
from src.api.scheme_search import load_passages
from src.mcp_servers.tools.documents import assess_document_metadata
from src.rules.data_provider import RulePackageProvider
from src.workflow.journey import (
    JourneyResponse,
    QuestionPresentation,
)
from src.workflow.state import (
    CandidateVerdict,
    JourneyHistoryEvent,
    Plan,
    PlanChange,
    PlanStep,
)

# Full-suite imports can be slow on shared Windows hosts.
UI_STARTUP_TIMEOUT_SECONDS = 60


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
        / "passages"
        / "ignwps_mh_passages.json"
    )[0].model_copy(update={"eligible_for_mock_flow": True})

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
        # Cold Streamlit startup on shared Windows/OneDrive can exceed 3 seconds.
        app = AppTest.from_file(app_path, default_timeout=UI_STARTUP_TIMEOUT_SECONDS).run()
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
            / "passages"
        )
        if passage.scheme_id == "PM-KISAN-IN"
    ).model_copy(update={"eligible_for_mock_flow": True})


def _widow_passage():
    """Return one widow-pension search passage from the real passage file."""

    return next(
        passage
        for passage in load_passages(
            Path(__file__).resolve().parents[1]
            / "data"
            / "schemes"
            / "passages"
        )
        if passage.scheme_id == "IGNWPS-MH"
    ).model_copy(update={"eligible_for_mock_flow": True})


def _scheme_passage(scheme_id: str):
    """Return one passage of any scheme from the per-scheme passage files."""

    return next(
        passage
        for passage in load_passages(
            Path(__file__).resolve().parents[1]
            / "data"
            / "schemes"
            / "passages"
        )
        if passage.scheme_id == scheme_id
    )


def test_search_for_scheme_without_rules_shows_information_only() -> None:
    """APY has cited passages but no rule package: no eligibility demo."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    passage = _scheme_passage("APY-IN")

    def fake_journey(request):
        assert request.action == "search"
        return JourneyResponse(
            conversation_id=uuid4(),
            plan="Search for a source-cited scheme.",
            status="search_results",
            message=(
                "Found one relevant cited passage across 1 scheme. "
                "Showing up to 20 passages; search may not find every "
                "relevant scheme."
            ),
            passages=[passage],
            candidate_scheme_ids=["APY-IN"],
        )

    with patch("src.ui.api_client.run_journey", side_effect=fake_journey):
        app = AppTest.from_file(app_path).run()
        app.text_input[0].set_value("atal pension")
        next(
            button for button in app.button if button.label == "Search schemes"
        ).click().run()

        assert not app.exception
        assert any(
            "information only" in element.value for element in app.info
        )
        assert not any(
            button.label == "Continue to the synthetic eligibility demo"
            for button in app.button
        )
        assert any(
            passage.passage_id in expander.label
            for expander in app.expander
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
            react_status="model_assisted",
            agent_budget={
                "model_calls": 3,
                "agent_steps": 3,
                "tool_calls": 1,
                "input_tokens": 100,
                "output_tokens": 512,
            },
            agent_trace=[{
                "agent": "intake",
                "action": "read_required_facts",
                "status": "completed",
                "model": "fake-ui-model",
                "prompt_version": "test",
                "step": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "duration_ms": 1,
                "summary": "Scrubbed metadata only.",
            }],
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
        app.checkbox[0].check().run()
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
        app.text_area[0].set_value("A synthetic farmer family has farmland.").run()
        next(
            button for button in app.button if button.label == "Start questions"
        ).click().run()

        assert not app.exception
        interview_request = run_graph.call_args_list[-1].args[0]
        assert interview_request.action == "interview"
        assert interview_request.scheme_id == "PM-KISAN-IN"
        assert (
            interview_request.profile_description
            == "A synthetic farmer family has farmland."
        )
        assert interview_request.locale == "en"
        assert interview_request.mode == "citizen"
        assert interview_request.citizen_present is True
        # The plan checklist and the first question are on screen.
        markdown = [element.value for element in app.markdown]
        assert "? Learn about you" in markdown
        assert question in markdown
        assert app.query_params["scheme"] == "PM-KISAN-IN"
        assert app.query_params["conversation"] == str(conversation_id)
        captions = [element.value for element in app.caption]
        assert any("Calls 3/8" in caption for caption in captions)
        assert any(
            "intake · read_required_facts · completed" in caption
            for caption in captions
        )
        assert not any(
            "model step stopped safely" in caption for caption in captions
        )

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
        app.checkbox[0].check().run()
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
        captions = [element.value for element in app.caption]
        assert any("No model calls have run" in caption for caption in captions)
        assert not any(
            "The model step stopped safely" in caption for caption in captions
        )
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


def test_registry_decimal_question_submits_exact_text_at_precision_boundary() -> None:
    """A resumed decimal answer avoids float conversion before the API call."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    waiting = JourneyResponse(
        conversation_id=conversation_id,
        plan="Learn about you -> Check the rules",
        plan_detail=_plan("in_progress", "pending"),
        status="awaiting_answer",
        message="What are the synthetic marks?",
        question="What are the synthetic marks?",
        pending_fact="exam_marks",
        question_definition=QuestionPresentation(
            fact_id="exam_marks",
            value_type="decimal",
            unit="percent",
            minimum=0,
            maximum=100,
            choices=[],
        ),
        conversation=[
            {"role": "assistant", "content": "What are the synthetic marks?"}
        ],
    )
    choice_waiting = waiting.model_copy(
        update={
            "message": "Which course type?",
            "question": "Which course type?",
            "pending_fact": "course_type",
            "question_definition": QuestionPresentation(
                fact_id="course_type",
                value_type="choice",
                choices=[
                    {"code": "science", "label": "Science"},
                    {"code": "arts", "label": "Arts"},
                ],
            ),
            "conversation": [
                {"role": "assistant", "content": "Which course type?"}
            ],
        }
    )
    completed = waiting.model_copy(
        update={
            "status": "eligible",
            "question": None,
            "question_definition": None,
            "eligibility_result": EligibilityResponse(
                scheme_id="SYNTHETIC-SCHOLARSHIP-TEST",
                result="eligible",
                reason="Synthetic conditions are met.",
                deciding_rule_ids=[],
                evidence=[],
            ),
        }
    )

    with patch(
        "src.ui.api_client.get_journey_state", return_value=waiting
    ), patch(
        "src.ui.api_client.send_journey_message",
        side_effect=[choice_waiting, completed],
    ) as send_reply, patch(
        "src.ui.api_client.list_application_drafts", return_value=[],
    ):
        app = AppTest.from_file(app_path)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "PM-KISAN-IN"
        app.run()
        assert not app.exception
        assert len(app.number_input) == 0
        decimal_input = app.text_input(
            key=f"registered_answer_{conversation_id}_exam_marks"
        )
        assert decimal_input is not None
        assert any("percent" in element.value for element in app.caption)
        exact_answer = "0.12345678901234567"
        decimal_input.set_value(exact_answer)
        next(button for button in app.button if button.label == "Send answer").click().run()
        assert not app.exception
        course_widget = next(
            widget
            for widget in app.selectbox
            if widget.label == "Type your answer (yes / no / don't know, a date like 1958-05-05, or your own words)"
        )
        course_widget.set_value("Science")
        next(button for button in app.button if button.label == "Send answer").click().run()
        assert not app.exception
        assert [call.args for call in send_reply.call_args_list] == [
            (str(conversation_id), exact_answer),
            (str(conversation_id), "science"),
        ]


def test_registry_correction_uses_dynamic_label_and_keeps_exact_decimal_text() -> None:
    """A fact outside HouseholdProfile remains correctable after refresh."""

    conversation_id = uuid4()
    scheme_id = "SYNTHETIC-SCHOLARSHIP-TEST"
    saved = JourneyResponse(
        conversation_id=conversation_id, plan="Synthetic checks", status="completed",
        message="Synthetic result.", candidate_scheme_ids=[scheme_id],
        candidate_verdicts={scheme_id: CandidateVerdict(
            scheme_id=scheme_id, result="not_eligible",
        )},
        correctable_fact_names=["exam_marks"],
        fact_questions={"exam_marks": "What are the synthetic marks (0–100 percent)?"},
    )
    corrected = saved.model_copy(update={
        "dependency_version": 1, "discovery_notices": ["correction_invalidated"],
    })
    with patch(
        "src.ui.api_client.get_journey_state", return_value=saved
    ), patch(
        "src.ui.api_client.correct_journey_answer", return_value=corrected
    ) as correct:
        app = AppTest.from_file(
            Path(__file__).parents[1] / "src" / "ui" / "app.py",
            default_timeout=UI_STARTUP_TIMEOUT_SECONDS,
        )
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["schemes"] = scheme_id
        app.run()
        assert not app.exception
        assert app.selectbox(key="correction_fact_name").options == [
            "What are the synthetic marks (0–100 percent)?"
        ]
        exact = "80.1234567890123456789"
        app.text_input(key="correction_answer_value").set_value(exact)
        next(button for button in app.button if button.label == "Save correction and recheck").click().run()
        assert not app.exception
        correct.assert_called_once_with(str(conversation_id), "exam_marks", exact)


def test_registry_text_question_is_bounded_and_can_be_unknown() -> None:
    """Display-only text uses its character limit and the normal unknown path."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    waiting = JourneyResponse(
        conversation_id=conversation_id,
        plan="Learn about you -> Check the rules",
        plan_detail=_plan("in_progress", "pending"),
        status="awaiting_answer",
        message="What note should be recorded?",
        question="What note should be recorded?",
        pending_fact="display_note",
        question_definition=QuestionPresentation(
            fact_id="display_note",
            value_type="text",
            max_length=24,
            choices=[],
        ),
        conversation=[
            {"role": "assistant", "content": "What note should be recorded?"}
        ],
    )
    with patch(
        "src.ui.api_client.get_journey_state", return_value=waiting
    ), patch(
        "src.ui.api_client.send_journey_message",
        side_effect=[waiting, waiting],
    ) as send_reply:
        app = AppTest.from_file(app_path)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "PM-KISAN-IN"
        app.run()
        assert not app.exception

        answer_input = app.text_input(
            key=f"registered_answer_{conversation_id}_display_note"
        )
        answer_input.set_value("Synthetic display note")
        next(button for button in app.button if button.label == "Send answer").click().run()
        assert not app.exception

        app.checkbox(key=f"registered_answer_{conversation_id}_display_note_unknown").set_value(True)
        next(button for button in app.button if button.label == "Send answer").click().run()
        assert not app.exception
        assert [call.args for call in send_reply.call_args_list] == [
            (str(conversation_id), "Synthetic display note"),
            (str(conversation_id), "skip"),
        ]


def test_registered_date_question_accepts_an_old_date_of_birth() -> None:
    """The date picker once refused anything over ten years ago (found live on IGNOAPS)."""
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    waiting = JourneyResponse(
        conversation_id=conversation_id,
        plan="Learn about you -> Check the rules",
        plan_detail=_plan("in_progress", "pending"),
        status="awaiting_answer",
        message="What is your date of birth?",
        question="What is your date of birth?",
        pending_fact="date_of_birth",
        question_definition=QuestionPresentation(
            fact_id="date_of_birth", value_type="date", choices=[],
        ),
        conversation=[{"role": "assistant", "content": "What is your date of birth?"}],
    )
    with patch(
        "src.ui.api_client.get_journey_state", return_value=waiting
    ), patch(
        "src.ui.api_client.send_journey_message", side_effect=[waiting],
    ) as send_reply, patch(
        "src.ui.api_client.list_application_drafts", return_value=[],
    ):
        app = AppTest.from_file(app_path)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "IGNOAPS-MH"
        app.run()
        assert not app.exception

        picker = app.date_input(key=f"registered_answer_{conversation_id}_date_of_birth")
        assert picker.min == date(1900, 1, 1)
        picker.set_value(date(1950, 3, 3))
        next(button for button in app.button if button.label == "Send answer").click().run()

        assert not app.exception
        assert [call.args for call in send_reply.call_args_list] == [
            (str(conversation_id), "1950-03-03"),
        ]


def test_missing_fact_is_shown_as_its_question_not_its_internal_name() -> None:
    """Found live on IGNOAPS: the result listed "name_on_bpl_list"."""
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    question = RulePackageProvider().registry.get("name_on_bpl_list").questions["en"].text
    finished = JourneyResponse(
        conversation_id=conversation_id,
        plan="Learn about you -> Check the rules",
        plan_detail=_plan("done", "done"),
        status="need_more_information",
        message="Some details are still needed.",
        eligibility_result=EligibilityResponse(
            scheme_id="IGNOAPS-MH",
            result="need_more_information",
            reason="Some details are still needed.",
            age_on_application_date=75,
            missing_fields=["name_on_bpl_list"],
            deciding_rule_ids=[],
            evidence=[],
        ),
        conversation=[{"role": "assistant", "content": "Some details are still needed."}],
    )
    with patch(
        "src.ui.api_client.get_journey_state", return_value=finished
    ), patch(
        "src.ui.api_client.list_application_drafts", return_value=[],
    ):
        app = AppTest.from_file(app_path, default_timeout=UI_STARTUP_TIMEOUT_SECONDS)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "IGNOAPS-MH"
        app.run()

        assert not app.exception
        shown = " ".join(element.value for element in app.caption)
        assert question in shown
        assert "name_on_bpl_list" not in shown


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


@pytest.mark.parametrize(
    ("scheme_id", "expected_label"),
    [
        ("IGNWPS-MH", "Identity proof (synthetic demo item)"),
        ("PM-KISAN-IN", "Land record (synthetic demo item)"),
    ],
)
def test_document_action_updates_supervisor_plan_for_both_pilots(
    scheme_id: str, expected_label: str
) -> None:
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    assessment = assess_document_metadata({
        "scheme_id": scheme_id,
        "documents": {},
    })
    document_plan = Plan(steps=[PlanStep(
        step_id="documents",
        specialist="documents",
        goal="Check the document checklist", status="done",
    )]).model_dump(mode="json")
    saved = JourneyResponse(
        conversation_id=conversation_id,
        plan="Check the scheme",
        status="eligible",
        message="Eligible under the mock rules.",
        eligibility_result=EligibilityResponse(
            scheme_id=scheme_id, result="eligible",
            reason="Eligible under the mock rules.",
            deciding_rule_ids=[], evidence=[],
        ),
        candidate_scheme_ids=[scheme_id],
        candidate_verdicts={scheme_id: CandidateVerdict(
            scheme_id=scheme_id, result="eligible"
        )},
        document_assessments={scheme_id: assessment},
    )

    with patch(
        "src.ui.api_client.get_journey_state", return_value=saved
    ), patch(
        "src.ui.api_client.list_application_drafts", return_value=[]
    ), patch(
        "src.ui.api_client.list_document_files", return_value={"files": []}
    ), patch(
        "src.ui.api_client.assess_documents",
        return_value={**assessment, "plan_detail": document_plan},
    ) as assess:
        app = AppTest.from_file(app_path)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = scheme_id
        app.run()
        assert not app.exception
        assert any(
            item.label == expected_label
            for item in app.selectbox
        )
        next(
            button for button in app.button
            if button.label == "Load demo document checklist"
        ).click().run()
        assert not app.exception
        assess.assert_called_once_with(str(conversation_id), scheme_id)
        assert app.session_state.journey_plan_detail == document_plan
        assert any("Check the document checklist" in item.value for item in app.markdown)


def test_single_scheme_correction_reloads_stale_draft_and_removes_submit_controls() -> None:
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    saved = JourneyResponse(
        conversation_id=conversation_id, plan="Check scheme", status="eligible",
        locale="hi",
        message="Synthetic eligible result.", known_fact_names=["income_tax_paid_last_assessment_year"],
        eligibility_result=EligibilityResponse(
            scheme_id="PM-KISAN-IN", result="eligible", reason="Synthetic rules.",
            deciding_rule_ids=[], evidence=[],
        ),
    )
    approved = {
        "draft_id": "synthetic-draft", "scheme_id": "PM-KISAN-IN", "revision": 1,
        "fingerprint": "a" * 64, "approved": True, "rejected": False,
        "receipt_id": None, "stale": False,
        "draft": {"applicant_reference": "Synthetic", "district": "Synthetic",
                  "profile": {}, "documents": [], "declaration": "Synthetic only."},
    }
    stale = {
        **approved, "stale": True, "approved": False,
    }
    corrected = saved.model_copy(update={
        "dependency_version": 1, "discovery_notices": ["correction_invalidated"],
    })
    with patch("src.ui.api_client.get_journey_state", return_value=saved), patch(
        "src.ui.api_client.list_application_drafts", side_effect=[[approved], [stale]],
    ) as load, patch(
        "src.ui.api_client.correct_journey_answer", return_value=corrected,
    ) as correct:
        app = AppTest.from_file(app_path, default_timeout=UI_STARTUP_TIMEOUT_SECONDS)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "PM-KISAN-IN"
        app.run()
        assert not app.exception
        assert any(button.label == "Submit approved draft to mock portal" for button in app.button)
        app.text_input(key="correction_answer_value").set_value("no")
        next(button for button in app.button if button.label == "Save correction and recheck").click().run()
        assert not app.exception
        correct.assert_called_once_with(str(conversation_id), "income_tax_paid_last_assessment_year", "no")
        assert load.call_count == 2
        assert any("यह मसौदा पुराना है" in warning.value for warning in app.warning)
        assert not any(button.label in {
            "Approve this exact draft", "Submit approved draft to mock portal",
        } for button in app.button)


@pytest.mark.parametrize(
    ("locale", "rejected_notice", "reopen", "reference", "receipt"),
    [
        ("en", "The synthetic draft was rejected.", "Edit and reopen draft",
         "Synthetic applicant reference", "Receipt"),
        ("hi", "कृत्रिम मसौदा अस्वीकार किया गया।",
         "मसौदे को संपादित करके फिर खोलें", "कृत्रिम आवेदक संदर्भ", "रसीद"),
        ("mr", "कृत्रिम मसुदा नाकारला.",
         "मसुदा संपादित करून पुन्हा उघडा", "कृत्रिम अर्जदार संदर्भ", "पावती"),
    ],
)
def test_phase4_rejection_edit_and_receipt_copy_is_localized(
    locale, rejected_notice, reopen, reference, receipt,
) -> None:
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    saved = JourneyResponse(
        conversation_id=conversation_id,
        plan="Synthetic review",
        status="eligible",
        locale=locale,
        message="Synthetic result.",
        eligibility_result=EligibilityResponse(
            scheme_id="PM-KISAN-IN", result="eligible",
            reason="Synthetic rules.", deciding_rule_ids=[], evidence=[],
        ),
        candidate_scheme_ids=["PM-KISAN-IN"],
        candidate_verdicts={"PM-KISAN-IN": CandidateVerdict(
            scheme_id="PM-KISAN-IN", result="eligible",
        )},
    )
    draft = {
        "draft_id": "synthetic-draft",
        "scheme_id": "PM-KISAN-IN",
        "revision": 1,
        "fingerprint": "a" * 64,
        "approved": False,
        "rejected": True,
        "receipt_id": None,
        "stale": False,
        "draft": {
            "applicant_reference": "Synthetic",
            "district": "Synthetic",
            "profile": {},
            "documents": [],
            "declaration": "Synthetic only.",
        },
    }
    drafts = [draft]
    with patch("src.ui.api_client.get_journey_state", return_value=saved), patch(
        "src.ui.api_client.list_application_drafts", return_value=drafts,
    ), patch(
        "src.ui.api_client.list_document_files", return_value={"files": []}
    ), patch(
        "src.ui.api_client.check_documents_report",
        return_value={
            "overall": "incomplete", "groups": [], "notice": "Synthetic.",
            "missing_labels": [],
        },
    ):
        app = AppTest.from_file(app_path, default_timeout=UI_STARTUP_TIMEOUT_SECONDS)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = "PM-KISAN-IN"
        app.run()
        app.selectbox[0].set_value(locale).run()
        assert not app.exception
        assert any(rejected_notice in item.value for item in app.error)
        assert any(
            item.value in {"Document checker", "दस्तावेज़ जाँच", "कागदपत्र तपासणी"}
            for item in app.subheader
        )
        next(button for button in app.button if button.label == reopen).click().run()
        assert not app.exception
        assert any(item.label == reference for item in app.text_input)

        drafts[0] = {
            **draft,
            "approved": True,
            "rejected": False,
            "receipt_id": "synthetic-receipt",
        }
        app.run()
        assert not app.exception
        assert any(receipt in item.value for item in app.success)


def test_discovery_coverage_and_referral_notices_are_localized() -> None:
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    saved = JourneyResponse(
        conversation_id=conversation_id, plan="Synthetic search", status="completed",
        message="Synthetic results.", candidate_scheme_ids=["SYNTHETIC"],
        candidate_verdicts={"SYNTHETIC": CandidateVerdict(
            scheme_id="SYNTHETIC", result="information_only",
        )},
        discovery_notices=["candidate_limit", "tool_error"],
        unprocessed_candidate_ids=["UNCHECKED-SYNTHETIC"],
        discovery_events=[{
            "code": "candidates_added", "search_calls": 1,
            "candidate_ids": ["SYNTHETIC"],
        }],
    )
    with patch("src.ui.api_client.get_journey_state", return_value=saved):
        app = AppTest.from_file(app_path, default_timeout=UI_STARTUP_TIMEOUT_SECONDS)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["schemes"] = "SYNTHETIC"
        app.run()
        app.selectbox[0].set_value("hi").run()
        assert not app.exception
        assert any("UNCHECKED-SYNTHETIC" in warning.value for warning in app.warning)
        assert any("CSC" in warning.value for warning in app.warning)
        assert not any("Only 20 candidates" in warning.value for warning in app.warning)
        assert any("पुष्टि" in caption.value for caption in app.caption)


def test_document_dates_accept_everyday_formats_and_explain_unreadable_ones() -> None:
    """Document dates are read like interview answers and sent as YYYY-MM-DD."""

    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    conversation_id = uuid4()
    scheme_id = "IGNWPS-MH"
    assessment = assess_document_metadata({"scheme_id": scheme_id, "documents": {}})
    saved = JourneyResponse(
        conversation_id=conversation_id,
        plan="Check the scheme",
        status="eligible",
        message="Eligible under the mock rules.",
        eligibility_result=EligibilityResponse(
            scheme_id=scheme_id, result="eligible",
            reason="Eligible under the mock rules.",
            deciding_rule_ids=[], evidence=[],
        ),
        candidate_scheme_ids=[scheme_id],
        candidate_verdicts={scheme_id: CandidateVerdict(
            scheme_id=scheme_id, result="eligible"
        )},
        document_assessments={scheme_id: assessment},
    )

    with patch(
        "src.ui.api_client.get_journey_state", return_value=saved
    ), patch(
        "src.ui.api_client.list_application_drafts", return_value=[]
    ), patch(
        "src.ui.api_client.list_document_files", return_value={"files": []}
    ), patch(
        "src.ui.api_client.assess_documents", return_value=assessment,
    ) as assess:
        app = AppTest.from_file(app_path, default_timeout=UI_STARTUP_TIMEOUT_SECONDS)
        app.query_params["conversation"] = str(conversation_id)
        app.query_params["scheme"] = scheme_id
        app.run()
        next(
            button for button in app.button
            if button.label == "Load demo document checklist"
        ).click().run()
        assert not app.exception
        date_inputs = [
            item for item in app.text_input if str(item.key).startswith("doc-date-")
        ]
        assert date_inputs, "the checklist should offer a document date field"
        update = lambda: next(
            button for button in app.button
            if button.label == "Update and recheck checklist"
        ).click().run()

        date_inputs[0].input("12-03-1958").run()
        update()
        assert not app.exception
        sent_metadata = assess.call_args.args[4]
        assert {"date_of_birth": "1958-03-12"} in sent_metadata.values()
        calls_before = assess.call_count

        next(
            item for item in app.text_input if item.key == date_inputs[0].key
        ).input("sometime in spring").run()
        update()
        assert not app.exception
        assert assess.call_count == calls_before
        assert any("Could not read a date of birth" in item.value for item in app.error)

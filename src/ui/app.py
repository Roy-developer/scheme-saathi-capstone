"""Render the Scheme Saathi Streamlit demonstration.

Screens (Streamlit redraws this whole file on every click):

1. Search: find a scheme by typing a need.
2. PM-KISAN: a chat where Saathi asks one question at a time (Phase 2).
3. Widow pension: the same chat, or a preset example person whose draft
   application can be approved.

The screen never decides eligibility. It calls the journey API, which runs
the LangGraph supervisor and the deterministic rule engine.
"""

import os
from datetime import date
from uuid import UUID, uuid4

import streamlit as st

from src.rules.data_provider import RulePackageProvider
from src.ui.api_client import (
    ApplicationApiError,
    JourneyApiError,
    assess_documents,
    check_documents_report,
    create_application_draft,
    decide_application_draft,
    delete_document_file,
    document_readiness,
    edit_application_draft,
    extract_document_suggestion,
    forget_personal_data,
    get_document_suggestion,
    get_journey_state,
    list_application_drafts,
    load_household_profile,
    save_household_profile,
    list_document_files,
    reopen_document_issue,
    remove_document_review,
    resolve_document_issue,
    review_document_file,
    fetch_document_file,
    upload_document,
    correct_journey_answer,
    run_journey,
    send_journey_message,
)
from src.ui.data_provider import FixtureDataProvider
from src.workflow.agent_config import (
    MAX_CONVERSATION_AGENT_STEPS,
    MAX_CONVERSATION_MODEL_CALLS,
    MAX_CONVERSATION_TOKENS,
    MAX_CONVERSATION_TOOL_CALLS,
)
from src.workflow.journey import JourneyRequest, JourneyResponse
from src.workflow.questions import (
    parse_registered_answer,
    registry_question_for,
    unknown_answer_label,
)
from src.workflow.discovery import discovery_message


# The API rejects longer replies before the registry parser can validate them.
MAX_JOURNEY_REPLY_LENGTH = 500
# Dates are picked with day / month / year dropdowns. st.date_input's calendar
# shows only a sliding window of years, so reaching a birth year 60-80 years
# back jumped between decades; three dropdowns reach any year directly.
REGISTERED_DATE_MIN = date(1900, 1, 1)
REGISTERED_DATE_MAX = date(2100, 12, 31)
DATE_PART_LABELS = {
    "en": ("Day", "Month", "Year"),
    "hi": ("दिन", "महीना", "वर्ष"),
    "mr": ("दिवस", "महिना", "वर्ष"),
}
MONTH_NAMES = {
    "en": (
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    ),
    "hi": (
        "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई",
        "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
    ),
    "mr": (
        "जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै",
        "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर",
    ),
}
INVALID_DATE_TEXT = {
    "en": "That date does not exist. Please check the day and month.",
    "hi": "यह तारीख मौजूद नहीं है। कृपया दिन और महीना जाँचें।",
    "mr": "ही तारीख अस्तित्वात नाही. कृपया दिवस आणि महिना तपासा.",
}


def date_dropdowns(
    label: str, locale: str, key: str, disabled: bool
) -> date | None:
    """Pick a date with day, month and year dropdowns; None until all are valid."""

    day_label, month_label, year_label = DATE_PART_LABELS[locale]
    months = MONTH_NAMES[locale]
    # Newest year first: most answers are dates of birth or recent dates.
    last_year = min(date.today().year + 1, REGISTERED_DATE_MAX.year)
    years = list(range(last_year, REGISTERED_DATE_MIN.year - 1, -1))
    st.markdown(label)
    day_column, month_column, year_column = st.columns(3)
    with day_column:
        day = st.selectbox(
            day_label, list(range(1, 32)), index=None,
            key=f"{key}_day", disabled=disabled,
        )
    with month_column:
        month = st.selectbox(
            month_label, list(range(1, 13)), index=None,
            format_func=lambda number: months[number - 1],
            key=f"{key}_month", disabled=disabled,
        )
    with year_column:
        year = st.selectbox(
            year_label, years, index=None,
            key=f"{key}_year", disabled=disabled,
        )
    if day is None or month is None or year is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        st.caption(INVALID_DATE_TEXT[locale])
        return None


COPY = {
    "en": {
        "name": "English",
        "title": "Scheme Saathi",
        "subtitle": "Explore a cited welfare-scheme decision journey",
        "banner": "SYNTHETIC DEMONSTRATION — NOT A GOVERNMENT SERVICE",
        "draft": "Synthetic demonstration only. No real government application is submitted.",
        "consent_title": "Demonstration notice",
        "consent_text": "Use made-up household facts only. Synthetic answers may be saved locally; no government application is submitted.",
        "consent": "I understand and want to view the demonstration.",
        "mode": "Demonstration perspective",
        "citizen": "Citizen",
        "csc": "CSC-assisted",
        "scenario": "Choose a synthetic development scenario",
        "profile": "Synthetic household profile",
        "age": "Age",
        "age_as_of": "Age calculated on application date",
        "application_date": "Application date",
        "date_of_birth": "Date of birth",
        "widow": "Widow status",
        "bpl": "BPL status",
        "state": "State",
        "yes": "Confirmed widow",
        "no": "Not widowed",
        "confirmed": "Government BPL card shown",
        "unknown": "Government BPL card not shown — status unverified",
        "evaluate": "Check eligibility",
        "result": "Eligibility result from the rule API",
        "eligible": "Appears eligible",
        "not_eligible": "Does not appear eligible",
        "cant_tell": "Need more information",
        "reason": "Why this result was assigned",
        "rules": "Rules checked by the API",
        "missing": "Information still needed",
        "api_error": "Could not check eligibility",
        "human": "Refer to a human caseworker",
        "policy": "Policy evidence",
        "official_clause": "Published eligibility text",
        "benefit": "Published benefit summary",
        "source": "Open official Maharashtra source",
        "documents": "The document checklist contains demo items only; they are not verified official requirements.",
        "requirements_demo_status": "Demo-only list · not verified",
        "requirements_approved_status": "Reviewed source-backed requirements",
        "requirements_version": "Checklist version",
        "requirements_any_one": "Any one option satisfies this required group.",
        "requirements_condition_unknown": "This group's condition is not known; ask a human caseworker.",
        "requirements_not_applicable": "Not applicable to the confirmed profile.",
        "requirements_changed": "The checklist or its evidence changed. Recheck before preparing a draft.",
        "condition_is_widow_true": "Applies when confirmed widow status is yes.",
        "condition_is_widow_false": "Applies when confirmed widow status is no.",
        "condition_bpl_card_shown_true": "Applies when a BPL card is confirmed shown.",
        "condition_bpl_card_shown_false": "Applies when a BPL card is not confirmed shown.",
        "source_citations": "Reviewed source citations",
        "source_quote": "Source text",
        "source_locator": "Location",
        "source_collected_on": "Collected",
        "source_publication_date": "Publication date",
        "source_publication_unknown": "Not recorded",
        "profile_name": "Confirmed synthetic profile name for comparison",
        "document_name": "Name entered from this synthetic document",
        "document_date": "Date of birth entered from this synthetic document (for example 12-03-1958)",
        "document_date_invalid": "Could not read a date of birth on a document. Write it like 12 March 1958, 12-03-1958 or 1958-03-12, or leave it empty.",
        "mismatch_help": "The entered name or date differs from the confirmed synthetic profile. Correct the entered fields and recheck; no document was read or authenticated.",
        "requirements_referral": "Requirements for this scheme are unverified. Please ask a human caseworker; do not treat this demo list as official.",
        "approval_expiry": "Approval expires at",
        "approval_expired": "This approval expired. Review and approve the current exact draft again.",
        "recheck_documents": "Correct fields and recheck",
        "application_error": "The application could not be updated. Reload the current state and try again.",
        "form_fields_missing": "Complete the required synthetic form fields or confirm the missing facts in the interview before preparing a draft.",
        "load_checklist": "Load demo document checklist",
        "update_checklist": "Update and recheck checklist",
        "prepare_draft": "Prepare synthetic draft",
        "demo_warning": "Demo checklist only. These are not verified official document requirements. Uploaded files are stored but not read or authenticated.",
        "synthetic_application": "Synthetic application",
        "resolve_mismatch": "Mismatch found. Correct the entered fields and recheck, or ask a human caseworker.",
        "new_draft": "Start a new draft using current answers",
        "scheme_label": "Scheme",
        "revision_label": "Revision",
        "status_unknown": "Unknown",
        "status_available": "Entered as available",
        "status_missing": "Missing",
        "status_mismatch": "Mismatch",
        "prepare": "Prepare synthetic application draft",
        "application": "Synthetic application draft",
        "reference": "Applicant reference",
        "synthetic_reference": "Synthetic applicant reference",
        "district": "District",
        "declaration": "Declaration",
        "fingerprint": "Draft fingerprint",
        "edit": "Edit draft",
        "save": "Save changes",
        "approve": "Approve this exact draft",
        "reject": "Reject draft",
        "submit": "Submit approved draft to mock portal",
        "approved": "This exact draft is approved.",
        "invalidated": "The draft changed, so the earlier approval is no longer valid.",
        "rejected": "The synthetic draft was rejected.",
        "reopen": "Edit and reopen draft",
        "submitted": "Submitted to the mock portal. No government service was contacted.",
        "receipt_label": "Receipt",
        "forget": "Forget my demonstration data",
        "forgotten": "The demonstration session was cleared.",
        "forget_error": "Could not clear the saved conversation",
        "conversation": "Conversation",
        "finder_title": "Find a scheme",
        "finder_help": "Ask in English, Hindi, or Marathi. Your query is sent to OpenRouter for search phrasing and embeddings; do not enter personal or financial identifiers. Search returns citations and does not decide eligibility.",
        "finder_query": "What support or scheme are you looking for?",
        "finder_submit": "Search schemes",
        "finder_error": "Scheme search is unavailable",
        "finder_empty": "No matching passages were found. Try different wording.",
        "finder_choose": "Choose a scheme to explore",
        "finder_continue": "Continue to the synthetic eligibility demo",
        "finder_continue_all": "Check all found schemes",
        "multi_interview_title": "Check the matching schemes",
        "multi_interview_results": "Results by scheme",
        "plan_change_history": "Why the plan changed",
        "correction_title": "Correct an earlier answer",
        "correction_fact": "Which answer do you want to correct?",
        "correction_answer": "Your corrected answer",
        "correction_submit": "Save correction and recheck",
        "history_retry": "Retry",
        "history_failed": "Tool failed",
        "history_corrected": "Answer corrected",
        "scheme_tool_error": "We could not check this scheme. No eligibility decision was made.",
        "finder_back": "Choose another scheme",
        "finder_info_only": "This scheme currently has source passages for information only. A reviewed deterministic eligibility rule package is not available, so no eligibility decision will be shown.",
        "finder_citation": "Source citation",
        "finder_review": "Review status",
        "pmkisan_title": "Synthetic PM-KISAN household",
        "pmkisan_notice": "Use fictional household facts only. This mock check follows the official guidelines revised in 2020. It does not check the current landholding cutoff or government records, and it is not an official decision.",
        "pmkisan_unresolved": "Not checked in this mock",
        "pmkisan_potential": "Does not meet the 2020 mock criteria",
        "pmkisan_error": "Could not run PM-KISAN screen",
        "plan_title": "Saathi's plan",
        "interview_title": "Answer a few questions",
        "interview_notice": "Saathi asks one question at a time and only what the rules need. Use made-up answers only; do not type real names, Aadhaar or bank numbers.",
        "household_description": "Describe the synthetic household in your own words (optional)",
        "household_description_help": "Only clearly stated scheme facts are proposed. You confirm each proposed fact before it is saved.",
        "csc_present": "The citizen is present and will confirm their own facts",
        "citizen_notice": "In Citizen mode, you provide and confirm your own household facts.",
        "mode_notice": "A CSC operator may assist, but the citizen confirms every fact and personally approves any exact application draft.",
        "agent_fallback": "The model step stopped safely; the fixed question flow is continuing.",
        "agent_activity": "Agent activity (scrubbed metadata)",
        "agent_usage": "Calls {calls}/{call_limit}; steps {steps}/{step_limit}; tool calls {tools}/{tool_limit}; accounted tokens {tokens}/{token_limit}.",
        "agent_no_calls": "No model calls have run; the deterministic flow is active.",
        "interview_start": "Start questions",
        "interview_restart": "Start again",
        "interview_reply": "Type your answer in your own words",
        "interview_reply_date": "Type the date, e.g. 1958-05-05, or describe it in your own words",
        "quick_answer": "Quick answer",
        "free_text_hint": "You can also type your answer in your own words in the box below. Saathi will check what it understood with you before saving it.",
        "send_answer": "Send answer",
        "interview_error": "Could not continue the conversation",
        "widow_mode": "How do you want to check?",
        "mode_chat": "Answer questions",
        "mode_example": "Use an example person",
        "restored": "Your earlier conversation was restored.",
        "return_code_label": "Return code",
        "return_code_help": "Enter a return code from a previous visit to load your saved answers.",
        "memory_consent_label": "Optional saved answers",
        "memory_consent_text": "I agree to reuse approved answers that are not highly sensitive, and to save them for up to 90 days when I choose Save. I can use Forget my data at any time.",
        "memory_consent_required": "Agree to optional saved answers before loading or saving a return-code profile.",
        "return_code_load": "Load saved answers",
        "return_code_display": "Your return code: **{code}**. Write it down to load your answers next time.",
        "return_code_save": "Save my answers",
        "return_code_saved": "Answers saved. Your return code: **{code}**",
        "return_code_not_found": "Return code not found. Starting fresh.",
        "return_code_error": "Could not load saved answers.",
        "footer": "These are development fixtures, not held-out evaluation cases. No language model determines the verdict.",
    },
    "hi": {
        "name": "हिन्दी",
        "title": "स्कीम साथी",
        "subtitle": "उद्धृत कल्याण-योजना निर्णय यात्रा देखें",
        "banner": "कृत्रिम प्रदर्शन — यह सरकारी सेवा नहीं है",
        "draft": "केवल कृत्रिम प्रदर्शन। कोई वास्तविक सरकारी आवेदन जमा नहीं किया जाता।",
        "consent_title": "प्रदर्शन सूचना",
        "consent_text": "केवल काल्पनिक परिवार की जानकारी दें। कृत्रिम उत्तर स्थानीय रूप से सहेजे जा सकते हैं; कोई सरकारी आवेदन जमा नहीं किया जाता।",
        "consent": "मैं समझता/समझती हूँ और प्रदर्शन देखना चाहता/चाहती हूँ।",
        "mode": "प्रदर्शन दृष्टिकोण",
        "citizen": "नागरिक",
        "csc": "CSC सहायता",
        "scenario": "कृत्रिम विकास उदाहरण चुनें",
        "profile": "कृत्रिम परिवार प्रोफ़ाइल",
        "age": "आयु",
        "age_as_of": "आवेदन की तारीख पर आयु की गणना",
        "application_date": "आवेदन की तारीख",
        "date_of_birth": "जन्म तिथि",
        "widow": "विधवा स्थिति",
        "bpl": "BPL स्थिति",
        "state": "राज्य",
        "yes": "विधवा की पुष्टि",
        "no": "विधवा नहीं",
        "confirmed": "सरकारी BPL कार्ड दिखाया गया",
        "unknown": "सरकारी BPL कार्ड नहीं दिखाया — स्थिति सत्यापित नहीं",
        "evaluate": "पात्रता जाँचें",
        "result": "नियम API से पात्रता परिणाम",
        "eligible": "पात्र प्रतीत होते हैं",
        "not_eligible": "पात्र प्रतीत नहीं होते",
        "cant_tell": "अधिक जानकारी चाहिए",
        "reason": "यह परिणाम क्यों दिया गया",
        "rules": "API द्वारा जाँचे गए नियम",
        "missing": "अभी आवश्यक जानकारी",
        "api_error": "पात्रता की जाँच नहीं हो सकी",
        "human": "मानव केसवर्कर को भेजें",
        "policy": "नीति प्रमाण",
        "official_clause": "प्रकाशित पात्रता पाठ",
        "benefit": "प्रकाशित लाभ सारांश",
        "source": "महाराष्ट्र का आधिकारिक स्रोत खोलें",
        "documents": "दस्तावेज़ सूची में केवल प्रदर्शन की चीज़ें हैं; ये आधिकारिक रूप से सत्यापित आवश्यकताएँ नहीं हैं।",
        "requirements_demo_status": "केवल प्रदर्शन सूची · सत्यापित नहीं",
        "requirements_approved_status": "समीक्षित स्रोत-आधारित आवश्यकताएँ",
        "requirements_version": "सूची संस्करण",
        "requirements_any_one": "इस आवश्यक समूह के लिए कोई एक विकल्प पर्याप्त है।",
        "requirements_condition_unknown": "इस समूह की शर्त ज्ञात नहीं है; मानव केसवर्कर से पूछें।",
        "requirements_not_applicable": "पुष्टि किए गए प्रोफ़ाइल पर लागू नहीं।",
        "requirements_changed": "सूची या उसका प्रमाण बदल गया है। मसौदा बनाने से पहले फिर जाँचें।",
        "condition_is_widow_true": "पुष्टि की गई विधवा स्थिति हाँ होने पर लागू।",
        "condition_is_widow_false": "पुष्टि की गई विधवा स्थिति नहीं होने पर लागू।",
        "condition_bpl_card_shown_true": "BPL कार्ड दिखाए जाने की पुष्टि पर लागू।",
        "condition_bpl_card_shown_false": "BPL कार्ड दिखाए जाने की पुष्टि न होने पर लागू।",
        "source_citations": "समीक्षित स्रोत उद्धरण",
        "source_quote": "स्रोत पाठ",
        "source_locator": "स्थान",
        "source_collected_on": "संग्रह तिथि",
        "source_publication_date": "प्रकाशन तिथि",
        "source_publication_unknown": "दर्ज नहीं",
        "profile_name": "तुलना के लिए पुष्टि किया गया कृत्रिम प्रोफ़ाइल नाम",
        "document_name": "इस कृत्रिम दस्तावेज़ से दर्ज नाम",
        "document_date": "इस कृत्रिम दस्तावेज़ से दर्ज जन्म तिथि (उदाहरण: 12-03-1958)",
        "document_date_invalid": "किसी दस्तावेज़ की जन्म तिथि समझ में नहीं आई। इसे 12 March 1958, 12-03-1958 या 1958-03-12 की तरह लिखें, या खाली छोड़ें।",
        "mismatch_help": "दर्ज नाम या तारीख पुष्टि किए गए कृत्रिम प्रोफ़ाइल से अलग है। दर्ज जानकारी सुधारकर फिर जाँचें; कोई दस्तावेज़ पढ़ा या प्रमाणित नहीं किया गया।",
        "requirements_referral": "इस योजना की आवश्यकताएँ सत्यापित नहीं हैं। मानव केसवर्कर से पूछें; इस प्रदर्शन सूची को आधिकारिक न मानें।",
        "approval_expiry": "मंज़ूरी समाप्त होने का समय",
        "approval_expired": "यह मंज़ूरी समाप्त हो गई। वर्तमान मसौदे की समीक्षा करके फिर से मंज़ूरी दें।",
        "recheck_documents": "जानकारी सुधारें और फिर जाँचें",
        "application_error": "आवेदन अपडेट नहीं हो सका। वर्तमान स्थिति फिर से लोड करके कोशिश करें।",
        "form_fields_missing": "मसौदा तैयार करने से पहले आवश्यक कृत्रिम फ़ॉर्म जानकारी भरें या साक्षात्कार में अनुपलब्ध तथ्यों की पुष्टि करें।",
        "load_checklist": "प्रदर्शन दस्तावेज़ सूची लोड करें",
        "update_checklist": "सूची अपडेट करके फिर जाँचें",
        "prepare_draft": "कृत्रिम मसौदा तैयार करें",
        "demo_warning": "केवल प्रदर्शन सूची। ये आधिकारिक रूप से सत्यापित आवश्यकताएँ नहीं हैं; अपलोड की गई फ़ाइलें सहेजी जाती हैं, पर पढ़ी या प्रमाणित नहीं की जातीं।",
        "synthetic_application": "कृत्रिम आवेदन",
        "resolve_mismatch": "अंतर मिला। दर्ज जानकारी सुधारकर फिर जाँचें या मानव केसवर्कर से पूछें।",
        "new_draft": "वर्तमान उत्तरों से नया मसौदा शुरू करें",
        "scheme_label": "योजना",
        "revision_label": "संस्करण",
        "status_unknown": "अज्ञात",
        "status_available": "उपलब्ध दर्ज",
        "status_missing": "अनुपलब्ध",
        "status_mismatch": "अंतर",
        "prepare": "कृत्रिम आवेदन मसौदा तैयार करें",
        "application": "कृत्रिम आवेदन मसौदा",
        "reference": "आवेदक संदर्भ",
        "synthetic_reference": "कृत्रिम आवेदक संदर्भ",
        "district": "ज़िला",
        "declaration": "घोषणा",
        "fingerprint": "मसौदा फिंगरप्रिंट",
        "edit": "मसौदा संपादित करें",
        "save": "बदलाव सहेजें",
        "approve": "इसी मसौदे को मंज़ूर करें",
        "reject": "मसौदा अस्वीकार करें",
        "submit": "मॉक पोर्टल पर जमा करें",
        "approved": "इसी मसौदे को मंज़ूरी दी गई है।",
        "invalidated": "मसौदा बदल गया है, इसलिए पिछली मंज़ूरी अब मान्य नहीं है।",
        "rejected": "कृत्रिम मसौदा अस्वीकार किया गया।",
        "reopen": "मसौदे को संपादित करके फिर खोलें",
        "submitted": "मॉक पोर्टल पर जमा किया गया। किसी सरकारी सेवा से संपर्क नहीं किया गया।",
        "receipt_label": "रसीद",
        "forget": "मेरा प्रदर्शन डेटा भूलें",
        "forgotten": "प्रदर्शन सत्र साफ़ कर दिया गया।",
        "forget_error": "सहेजी गई बातचीत साफ़ नहीं हो सकी",
        "conversation": "बातचीत",
        "finder_title": "योजना खोजें",
        "finder_help": "अंग्रेज़ी, हिन्दी या मराठी में पूछें। खोज के लिए आपका प्रश्न OpenRouter को भेजा जाता है; व्यक्तिगत या वित्तीय पहचान संख्या न लिखें। खोज स्रोत सहित अंश दिखाती है, पात्रता तय नहीं करती।",
        "finder_query": "आप किस सहायता या योजना की तलाश में हैं?",
        "finder_submit": "योजनाएँ खोजें",
        "finder_error": "योजना खोज उपलब्ध नहीं है",
        "finder_empty": "मिलते-जुलते अंश नहीं मिले। प्रश्न को दूसरे शब्दों में लिखें।",
        "finder_choose": "देखने के लिए योजना चुनें",
        "finder_continue": "कृत्रिम पात्रता प्रदर्शन जारी रखें",
        "finder_continue_all": "मिली हुई सभी योजनाओं की जाँच करें",
        "multi_interview_title": "मिलती-जुलती योजनाएँ जाँचें",
        "multi_interview_results": "योजना के अनुसार परिणाम",
        "plan_change_history": "योजना क्यों बदली",
        "correction_title": "पहले दिए उत्तर को सुधारें",
        "correction_fact": "आप कौन-सा उत्तर सुधारना चाहते हैं?",
        "correction_answer": "आपका सुधारा हुआ उत्तर",
        "correction_submit": "सुधार सेव करें और फिर जाँचें",
        "history_retry": "फिर कोशिश",
        "history_failed": "टूल विफल",
        "history_corrected": "उत्तर सुधारा गया",
        "scheme_tool_error": "हम इस योजना की जाँच नहीं कर सके। पात्रता का निर्णय नहीं दिया गया।",
        "finder_back": "दूसरी योजना चुनें",
        "finder_info_only": "इस योजना के स्रोत अंश अभी केवल जानकारी के लिए उपलब्ध हैं। समीक्षा किया हुआ नियतात्मक पात्रता नियम-पैकेज उपलब्ध नहीं है, इसलिए पात्रता का निर्णय नहीं दिखाया जाएगा।",
        "finder_citation": "स्रोत उद्धरण",
        "finder_review": "समीक्षा स्थिति",
        "pmkisan_title": "कृत्रिम PM-KISAN परिवार",
        "pmkisan_notice": "केवल काल्पनिक परिवार की जानकारी दें। यह मॉक जाँच 2020 में संशोधित सरकारी दिशानिर्देशों पर आधारित है। इसमें वर्तमान भूमि-कटऑफ या सरकारी रिकॉर्ड की जाँच नहीं होती, और यह सरकारी निर्णय नहीं है।",
        "pmkisan_unresolved": "इस मॉक में जाँच नहीं हुई",
        "pmkisan_potential": "2020 के मॉक मानदंड पूरे नहीं हुए",
        "pmkisan_error": "PM-KISAN जाँच नहीं हो सकी",
        "plan_title": "साथी की योजना",
        "interview_title": "कुछ प्रश्नों के उत्तर दें",
        "interview_notice": "साथी एक बार में एक प्रश्न पूछता है और केवल नियमों के लिए आवश्यक जानकारी मांगता है। केवल काल्पनिक उत्तर दें; वास्तविक नाम, आधार या बैंक नंबर न लिखें।",
        "household_description": "अपने शब्दों में काल्पनिक परिवार का वर्णन करें (वैकल्पिक)",
        "household_description_help": "केवल स्पष्ट रूप से बताए गए योजना-संबंधी तथ्यों का प्रस्ताव होगा। सहेजने से पहले आप हर तथ्य की पुष्टि करेंगे।",
        "csc_present": "नागरिक उपस्थित हैं और अपने तथ्यों की पुष्टि स्वयं करेंगे",
        "citizen_notice": "नागरिक मोड में आप अपने परिवार की जानकारी स्वयं देते और पुष्टि करते हैं।",
        "mode_notice": "CSC ऑपरेटर सहायता कर सकता है, लेकिन हर तथ्य की पुष्टि और किसी भी आवेदन का व्यक्तिगत अनुमोदन नागरिक ही करेंगे।",
        "agent_fallback": "मॉडल चरण सुरक्षित रूप से रुक गया; अब निश्चित प्रश्न-प्रवाह जारी है।",
        "agent_activity": "एजेंट गतिविधि (साफ़ किया गया मेटाडेटा)",
        "agent_usage": "कॉल {calls}/{call_limit}; चरण {steps}/{step_limit}; टूल कॉल {tools}/{tool_limit}; दर्ज टोकन {tokens}/{token_limit}।",
        "agent_no_calls": "कोई मॉडल कॉल नहीं हुई; नियतात्मक प्रवाह सक्रिय है।",
        "interview_start": "प्रश्न शुरू करें",
        "interview_restart": "फिर से शुरू करें",
        "interview_reply": "अपने शब्दों में उत्तर लिखें",
        "interview_reply_date": "तारीख लिखें, जैसे 1958-05-05, या अपने शब्दों में बताएँ",
        "quick_answer": "त्वरित उत्तर",
        "free_text_hint": "आप नीचे के बॉक्स में अपने शब्दों में भी उत्तर लिख सकते हैं। सहेजने से पहले साथी आपसे पूछेगा कि उसने सही समझा या नहीं।",
        "send_answer": "उत्तर भेजें",
        "interview_error": "बातचीत जारी नहीं रह सकी",
        "widow_mode": "आप कैसे जाँच करना चाहते हैं?",
        "mode_chat": "प्रश्नों के उत्तर दें",
        "mode_example": "उदाहरण व्यक्ति का उपयोग करें",
        "restored": "आपकी पिछली बातचीत बहाल की गई।",
        "return_code_label": "रिटर्न कोड",
        "return_code_help": "पिछली बार का रिटर्न कोड डालें ताकि आपके सहेजे गए उत्तर लोड हो जाएं।",
        "memory_consent_label": "वैकल्पिक सहेजे गए उत्तर",
        "memory_consent_text": "मैं अत्यधिक संवेदनशील न माने गए स्वीकृत उत्तरों के पुनः उपयोग और Save चुनने पर उन्हें अधिकतम 90 दिनों तक सहेजने के लिए सहमत हूँ। मैं कभी भी मेरा डेटा भूलें चुन सकता/सकती हूँ।",
        "memory_consent_required": "रिटर्न-कोड प्रोफ़ाइल लोड या सहेजने से पहले वैकल्पिक सहेजे गए उत्तरों के लिए सहमति दें।",
        "return_code_load": "सहेजे गए उत्तर लोड करें",
        "return_code_display": "आपका रिटर्न कोड: **{code}**। अगली बार उत्तर लोड करने के लिए इसे लिख लें।",
        "return_code_save": "मेरे उत्तर सहेजें",
        "return_code_saved": "उत्तर सहेजे गए। आपका रिटर्न कोड: **{code}**",
        "return_code_not_found": "रिटर्न कोड नहीं मिला। नया शुरू करें।",
        "return_code_error": "सहेजे गए उत्तर लोड नहीं हो सके।",
        "footer": "ये विकास फ़िक्स्चर हैं, सुरक्षित मूल्यांकन मामले नहीं। कोई भाषा मॉडल परिणाम तय नहीं करता।",
    },
    "mr": {
        "name": "मराठी",
        "title": "स्कीम साथी",
        "subtitle": "उद्धृत कल्याण-योजना निर्णय प्रवास पाहा",
        "banner": "कृत्रिम प्रात्यक्षिक — ही सरकारी सेवा नाही",
        "draft": "फक्त कृत्रिम प्रात्यक्षिक. कोणताही वास्तविक सरकारी अर्ज सादर होत नाही.",
        "consent_title": "प्रात्यक्षिक सूचना",
        "consent_text": "फक्त काल्पनिक कुटुंबाची माहिती द्या. कृत्रिम उत्तरे स्थानिकरीत्या जतन होऊ शकतात; सरकारी अर्ज सादर होत नाही.",
        "consent": "मला समजले आहे आणि मला प्रात्यक्षिक पाहायचे आहे.",
        "mode": "प्रात्यक्षिकाचा दृष्टिकोन",
        "citizen": "नागरिक",
        "csc": "CSC सहाय्य",
        "scenario": "कृत्रिम विकास उदाहरण निवडा",
        "profile": "कृत्रिम कुटुंब प्रोफाइल",
        "age": "वय",
        "age_as_of": "अर्जाच्या तारखेला वयाची गणना",
        "application_date": "अर्जाची तारीख",
        "date_of_birth": "जन्मतारीख",
        "widow": "विधवा स्थिती",
        "bpl": "BPL स्थिती",
        "state": "राज्य",
        "yes": "विधवा असल्याची पुष्टी",
        "no": "विधवा नाही",
        "confirmed": "सरकारी BPL कार्ड दाखवले",
        "unknown": "सरकारी BPL कार्ड दाखवले नाही — स्थिती पडताळलेली नाही",
        "evaluate": "पात्रता तपासा",
        "result": "नियम API मधून पात्रता निकाल",
        "eligible": "पात्र असल्याचे दिसते",
        "not_eligible": "पात्र असल्याचे दिसत नाही",
        "cant_tell": "अधिक माहिती आवश्यक",
        "reason": "हा निकाल का देण्यात आला",
        "rules": "API ने तपासलेले नियम",
        "missing": "अजून आवश्यक माहिती",
        "api_error": "पात्रता तपासता आली नाही",
        "human": "मानवी केसवर्करकडे पाठवा",
        "policy": "धोरण पुरावा",
        "official_clause": "प्रकाशित पात्रता मजकूर",
        "benefit": "प्रकाशित लाभ सारांश",
        "source": "महाराष्ट्राचा अधिकृत स्रोत उघडा",
        "documents": "कागदपत्रांच्या यादीतील बाबी केवळ प्रात्यक्षिकासाठी आहेत; त्या अधिकृतरीत्या पडताळलेल्या नाहीत.",
        "requirements_demo_status": "फक्त प्रात्यक्षिक यादी · पडताळलेली नाही",
        "requirements_approved_status": "पुनरावलोकित स्रोत-आधारित आवश्यकता",
        "requirements_version": "यादीची आवृत्ती",
        "requirements_any_one": "या आवश्यक गटातील कोणताही एक पर्याय पुरेसा आहे.",
        "requirements_condition_unknown": "या गटाची अट माहीत नाही; मानवी केसवर्करला विचारा.",
        "requirements_not_applicable": "पुष्टी केलेल्या प्रोफाइलला लागू नाही.",
        "requirements_changed": "यादी किंवा तिचा पुरावा बदलला आहे. मसुदा तयार करण्यापूर्वी पुन्हा तपासा.",
        "condition_is_widow_true": "पुष्टी केलेली विधवा स्थिती होय असल्यास लागू.",
        "condition_is_widow_false": "पुष्टी केलेली विधवा स्थिती नाही असल्यास लागू.",
        "condition_bpl_card_shown_true": "BPL कार्ड दाखवल्याची पुष्टी असल्यास लागू.",
        "condition_bpl_card_shown_false": "BPL कार्ड दाखवल्याची पुष्टी नसल्यास लागू.",
        "source_citations": "पुनरावलोकित स्रोत उद्धरणे",
        "source_quote": "स्रोत मजकूर",
        "source_locator": "स्थान",
        "source_collected_on": "संकलन तारीख",
        "source_publication_date": "प्रकाशन तारीख",
        "source_publication_unknown": "नोंदवलेली नाही",
        "profile_name": "तुलनेसाठी पुष्टी केलेले कृत्रिम प्रोफाइल नाव",
        "document_name": "या कृत्रिम कागदपत्रातून नोंदवलेले नाव",
        "document_date": "या कृत्रिम कागदपत्रातून नोंदवलेली जन्मतारीख (उदाहरण: 12-03-1958)",
        "document_date_invalid": "एखाद्या कागदपत्रावरील जन्मतारीख समजली नाही. ती 12 March 1958, 12-03-1958 किंवा 1958-03-12 अशी लिहा, किंवा रिकामी ठेवा.",
        "mismatch_help": "नोंदवलेले नाव किंवा तारीख पुष्टी केलेल्या कृत्रिम प्रोफाइलपेक्षा वेगळी आहे. नोंद दुरुस्त करून पुन्हा तपासा; कोणतेही कागदपत्र वाचले किंवा प्रमाणित केलेले नाही.",
        "requirements_referral": "या योजनेच्या आवश्यकता पडताळलेल्या नाहीत. मानवी केसवर्करला विचारा; ही प्रात्यक्षिक यादी अधिकृत समजू नका.",
        "approval_expiry": "मंजुरीची मुदत संपण्याची वेळ",
        "approval_expired": "ही मंजुरी कालबाह्य झाली. सध्याच्या अचूक मसुद्याचा आढावा घेऊन पुन्हा मंजुरी द्या.",
        "recheck_documents": "माहिती दुरुस्त करून पुन्हा तपासा",
        "application_error": "अर्ज अद्ययावत करता आला नाही. सध्याची स्थिती पुन्हा लोड करून प्रयत्न करा.",
        "form_fields_missing": "मसुदा तयार करण्यापूर्वी आवश्यक कृत्रिम फॉर्म माहिती भरा किंवा मुलाखतीत नोंद नसलेल्या तथ्यांची पुष्टी करा.",
        "load_checklist": "प्रात्यक्षिक कागदपत्रांची यादी लोड करा",
        "update_checklist": "यादी अद्ययावत करून पुन्हा तपासा",
        "prepare_draft": "कृत्रिम मसुदा तयार करा",
        "demo_warning": "फक्त प्रात्यक्षिक यादी. या अधिकृतरीत्या पडताळलेल्या आवश्यकता नाहीत; अपलोड केलेल्या फाइल्स जतन होतात, पण वाचल्या किंवा प्रमाणित केल्या जात नाहीत.",
        "synthetic_application": "कृत्रिम अर्ज",
        "resolve_mismatch": "तफावत आढळली. नोंद दुरुस्त करून पुन्हा तपासा किंवा मानवी केसवर्करला विचारा.",
        "new_draft": "सध्याच्या उत्तरांवरून नवीन मसुदा सुरू करा",
        "scheme_label": "योजना",
        "revision_label": "आवृत्ती",
        "status_unknown": "अज्ञात",
        "status_available": "उपलब्ध नोंदवले",
        "status_missing": "अनुपलब्ध",
        "status_mismatch": "तफावत",
        "prepare": "कृत्रिम अर्जाचा मसुदा तयार करा",
        "application": "कृत्रिम अर्जाचा मसुदा",
        "reference": "अर्जदार संदर्भ",
        "synthetic_reference": "कृत्रिम अर्जदार संदर्भ",
        "district": "जिल्हा",
        "declaration": "घोषणा",
        "fingerprint": "मसुदा फिंगरप्रिंट",
        "edit": "मसुदा संपादित करा",
        "save": "बदल जतन करा",
        "approve": "हाच मसुदा मंजूर करा",
        "reject": "मसुदा नाकारा",
        "submit": "मॉक पोर्टलवर सादर करा",
        "approved": "हाच मसुदा मंजूर केला आहे.",
        "invalidated": "मसुदा बदलल्यामुळे आधीची मंजुरी आता वैध नाही.",
        "rejected": "कृत्रिम मसुदा नाकारला.",
        "reopen": "मसुदा संपादित करून पुन्हा उघडा",
        "submitted": "मॉक पोर्टलवर सादर केले. कोणत्याही सरकारी सेवेशी संपर्क केला नाही.",
        "receipt_label": "पावती",
        "forget": "माझा प्रात्यक्षिक डेटा विसरा",
        "forgotten": "प्रात्यक्षिक सत्र साफ केले.",
        "forget_error": "जतन केलेले संभाषण साफ करता आले नाही",
        "conversation": "संभाषण",
        "finder_title": "योजना शोधा",
        "finder_help": "इंग्रजी, हिंदी किंवा मराठीत विचारा. शोधासाठी तुमचा प्रश्न OpenRouter कडे पाठवला जातो; वैयक्तिक किंवा आर्थिक ओळख क्रमांक देऊ नका. शोधात स्रोतासह उतारे दिसतात; पात्रता ठरत नाही.",
        "finder_query": "तुम्ही कोणत्या मदतीचा किंवा योजनेचा शोध घेत आहात?",
        "finder_submit": "योजना शोधा",
        "finder_error": "योजना शोध उपलब्ध नाही",
        "finder_empty": "जुळणारे उतारे सापडले नाहीत. प्रश्न वेगळ्या शब्दांत विचारा.",
        "finder_choose": "पाहण्यासाठी योजना निवडा",
        "finder_continue": "कृत्रिम पात्रता प्रात्यक्षिक सुरू ठेवा",
        "finder_continue_all": "आढळलेल्या सर्व योजनांची तपासणी करा",
        "multi_interview_title": "जुळणाऱ्या योजना तपासा",
        "multi_interview_results": "योजनेनुसार निकाल",
        "plan_change_history": "योजना का बदलली",
        "correction_title": "आधीचे उत्तर दुरुस्त करा",
        "correction_fact": "कोणते उत्तर दुरुस्त करायचे आहे?",
        "correction_answer": "तुमचे दुरुस्त उत्तर",
        "correction_submit": "दुरुस्ती जतन करून पुन्हा तपासा",
        "history_retry": "पुन्हा प्रयत्न",
        "history_failed": "टूल अयशस्वी",
        "history_corrected": "उत्तर दुरुस्त केले",
        "scheme_tool_error": "या योजनेची तपासणी करता आली नाही. पात्रतेचा निर्णय दिलेला नाही.",
        "finder_back": "दुसरी योजना निवडा",
        "finder_info_only": "या योजनेचे स्रोत उतारे सध्या फक्त माहितीसाठी उपलब्ध आहेत. पुनरावलोकन केलेले निर्धारक पात्रता नियम-पॅकेज उपलब्ध नसल्यामुळे पात्रतेचा निर्णय दाखवला जाणार नाही.",
        "finder_citation": "स्रोत उद्धरण",
        "finder_review": "पुनरावलोकन स्थिती",
        "pmkisan_title": "कृत्रिम PM-KISAN कुटुंब",
        "pmkisan_notice": "फक्त काल्पनिक कुटुंबाची माहिती द्या. ही मॉक तपासणी 2020 मध्ये सुधारित अधिकृत मार्गदर्शक तत्त्वांवर आधारित आहे. यात सध्याची जमीन-मर्यादा किंवा सरकारी नोंदी तपासल्या जात नाहीत; हा सरकारी निर्णय नाही.",
        "pmkisan_unresolved": "या मॉकमध्ये तपासले नाही",
        "pmkisan_potential": "2020 च्या मॉक निकषांची पूर्तता होत नाही",
        "pmkisan_error": "PM-KISAN तपासणी करता आली नाही",
        "plan_title": "साथीची योजना",
        "interview_title": "काही प्रश्नांची उत्तरे द्या",
        "interview_notice": "साथी एका वेळी एक प्रश्न विचारतो आणि नियमांसाठी आवश्यक तीच माहिती मागतो. फक्त काल्पनिक उत्तरे द्या; खरी नावे, आधार किंवा बँक क्रमांक लिहू नका.",
        "household_description": "तुमच्या शब्दांत काल्पनिक कुटुंबाचे वर्णन करा (ऐच्छिक)",
        "household_description_help": "फक्त स्पष्टपणे सांगितलेल्या योजना-संबंधित तथ्यांचे प्रस्ताव दिले जातील. जतन करण्यापूर्वी तुम्ही प्रत्येक तथ्याची पुष्टी कराल.",
        "csc_present": "नागरिक उपस्थित आहेत आणि स्वतःच्या तथ्यांची पुष्टी करतील",
        "citizen_notice": "नागरिक मोडमध्ये तुम्ही स्वतःच्या कुटुंबाची माहिती देता आणि तिची पुष्टी करता.",
        "mode_notice": "CSC ऑपरेटर मदत करू शकतो; मात्र प्रत्येक तथ्याची पुष्टी आणि कोणत्याही अर्जाला वैयक्तिक मंजुरी नागरिकच देतात.",
        "agent_fallback": "मॉडेलची पायरी सुरक्षितपणे थांबली; आता निश्चित प्रश्नप्रवाह सुरू आहे.",
        "agent_activity": "एजंटची कृती (साफ केलेला मेटाडेटा)",
        "agent_usage": "कॉल {calls}/{call_limit}; पायऱ्या {steps}/{step_limit}; टूल कॉल {tools}/{tool_limit}; नोंदवलेले टोकन {tokens}/{token_limit}.",
        "agent_no_calls": "मॉडेल कॉल झालेला नाही; निर्धारक प्रवाह सक्रिय आहे.",
        "interview_start": "प्रश्न सुरू करा",
        "interview_restart": "पुन्हा सुरू करा",
        "interview_reply": "तुमच्या शब्दांत उत्तर लिहा",
        "interview_reply_date": "तारीख लिहा, उदा. 1958-05-05, किंवा तुमच्या शब्दांत सांगा",
        "quick_answer": "झटपट उत्तर",
        "free_text_hint": "तुम्ही खालील बॉक्समध्ये तुमच्या शब्दांतही उत्तर लिहू शकता. जतन करण्यापूर्वी साथी त्याने काय समजले ते तुमच्याकडून तपासेल.",
        "send_answer": "उत्तर पाठवा",
        "interview_error": "संभाषण पुढे नेता आले नाही",
        "widow_mode": "तुम्हाला कशी तपासणी करायची आहे?",
        "mode_chat": "प्रश्नांची उत्तरे द्या",
        "mode_example": "उदाहरण व्यक्ती वापरा",
        "restored": "तुमचे आधीचे संभाषण पुन्हा सुरू झाले.",
        "return_code_label": "रिटर्न कोड",
        "return_code_help": "मागील भेटीचा रिटर्न कोड टाका म्हणजे तुमची जतन केलेली उत्तरे लोड होतील.",
        "memory_consent_label": "पर्यायी जतन केलेली उत्तरे",
        "memory_consent_text": "अत्यंत संवेदनशील नसलेली मंजूर उत्तरे पुन्हा वापरण्यास आणि Save निवडल्यावर ती जास्तीत जास्त 90 दिवस जतन करण्यास मी सहमत आहे. मी कधीही माझा डेटा विसरा हा पर्याय वापरू शकतो/शकते.",
        "memory_consent_required": "रिटर्न-कोड प्रोफाइल लोड किंवा जतन करण्यापूर्वी पर्यायी जतन केलेल्या उत्तरांसाठी संमती द्या.",
        "return_code_load": "जतन केलेली उत्तरे लोड करा",
        "return_code_display": "तुमचा रिटर्न कोड: **{code}**. पुढच्या वेळी उत्तरे लोड करण्यासाठी हा लिहून ठेवा.",
        "return_code_save": "माझी उत्तरे जतन करा",
        "return_code_saved": "उत्तरे जतन झाली. तुमचा रिटर्न कोड: **{code}**",
        "return_code_not_found": "रिटर्न कोड सापडला नाही. नवीन सुरू करा.",
        "return_code_error": "जतन केलेली उत्तरे लोड होऊ शकली नाहीत.",
        "footer": "ही विकास फिक्स्चर आहेत, सुरक्षित मूल्यमापन प्रकरणे नाहीत. कोणतेही भाषा मॉडेल निकाल ठरवत नाही.",
    },
}

RESULT_PRESENTATION = {
    "eligible": ("✅", "success"),
    "not_eligible": ("⛔", "error"),
    "cant_tell": ("⚠️", "warning"),
}
API_RESULT_TO_UI = {
    "eligible": "eligible",
    "not_eligible": "not_eligible",
    "need_more_information": "cant_tell",
}


def localize(value: object, locale: str) -> str:
    """Select localized text from a validated multilingual model."""

    return getattr(value, locale)


def show_result_message(kind: str, message: str) -> None:
    """Render a Streamlit status message using the configured severity."""

    getattr(st, kind)(message)


# The synthetic draft/approval state; cleared alone by clear_application_state.
APPLICATION_STATE_KEYS = {
    "approved_fingerprint",
    "draft_district",
    "draft_edit_mode",
    "draft_reference",
    "draft_scenario_id",
    "draft_submitted",
    "rejected_draft",
}
# Workflow state is kept separate so changing a scenario cannot retain approval.
WORKFLOW_STATE_KEYS = APPLICATION_STATE_KEYS | {
    "selected_result",
    "journey_started",
    "journey_scheme_id",
    "conversation_id",
    "journey_plan",
    "journey_status",
    "journey_conversation",
    "scheme_search_error",
    "scheme_search_results",
    "scheme_search_message",
    "selected_search_scheme",
    # Phase 2 chat state (see save_journey below).
    "interview_scheme_id",
    "interview_result",
    "interview_message",
    "interview_error",
    "journey_plan_detail",
    "journey_question",
    "journey_question_definition",
    "candidate_scheme_ids",
    "candidate_verdicts",
    "eligibility_results",
    "multi_scheme_mode",
    "plan_change_history",
    "correction_error",
    "journey_history",
    "known_fact_names",
    "fact_questions",
    "journey_mode_acknowledgement",
    "journey_react_status",
    "journey_agent_budget",
    "journey_agent_trace",
    "journey_locale",
    "journey_dependency_version",
    "journey_discovery_notices",
    "journey_discovery_events",
    "unprocessed_candidate_ids",
    "journey_return_code",
    "application_drafts",
    "application_drafts_loaded_for",
    "application_flow",
}
DEMO_INPUT_KEYS = {
    "demo_consent",
    "memory_consent",
    "demo_scenario",
    "scheme_query",
    "widow_mode",
    "interaction_mode",
    "csc_citizen_present",
}


def clear_workflow_state(*, include_inputs: bool = False) -> None:
    """Clear derived workflow state and optionally reset demonstration inputs."""

    keys = (
        WORKFLOW_STATE_KEYS | DEMO_INPUT_KEYS
        if include_inputs
        else WORKFLOW_STATE_KEYS
    )
    for key in keys:
        st.session_state.pop(key, None)


def clear_application_state() -> None:
    """Clear only the synthetic application state, preserving conversation."""

    for key in APPLICATION_STATE_KEYS:
        st.session_state.pop(key, None)
    st.session_state.selected_result = None
    st.session_state.api_result = None
    st.session_state.api_error = None


def clear_interview_state() -> None:
    """Forget the chat on screen (the API keeps it until "forget")."""

    st.session_state.interview_scheme_id = None
    st.session_state.interview_result = None
    st.session_state.interview_message = None
    st.session_state.interview_error = None
    st.session_state.journey_plan_detail = None
    st.session_state.journey_question = None
    st.session_state.journey_question_definition = None
    st.session_state.journey_status = None
    st.session_state.candidate_scheme_ids = []
    st.session_state.candidate_verdicts = {}
    st.session_state.eligibility_results = {}
    st.session_state.multi_scheme_mode = False
    st.session_state.plan_change_history = []
    st.session_state.correction_error = None
    st.session_state.journey_history = []
    st.session_state.known_fact_names = []
    st.session_state.fact_questions = {}
    st.session_state.journey_mode_acknowledgement = None
    st.session_state.journey_react_status = "deterministic"
    st.session_state.journey_agent_budget = {}
    st.session_state.journey_agent_trace = []
    st.session_state.journey_locale = "en"


# One icon per PlanStep.status, so the plan reads like a checklist.
PLAN_STEP_ICONS = {
    "pending": "⬜",
    "in_progress": "⏳",
    "done": "✅",
    "skipped": "⏭️",
    "failed": "❌",
}


def save_journey(journey: JourneyResponse) -> None:
    """Copy one API reply into session_state.

    Streamlit forgets local variables on every rerun, so everything the chat
    needs to redraw itself is stored here: the plan, the history, the open
    question and, at the end, the verdict.
    """

    if (
        st.session_state.get("journey_dependency_version", 0) != journey.dependency_version
        or "correction_invalidated" in journey.discovery_notices
    ):
        st.session_state.application_drafts = {}
        st.session_state.application_drafts_loaded_for = None
    st.session_state.journey_dependency_version = journey.dependency_version
    st.session_state.journey_discovery_notices = journey.discovery_notices
    st.session_state.journey_discovery_events = [
        event.model_dump(mode="json") for event in journey.discovery_events
    ]
    st.session_state.unprocessed_candidate_ids = journey.unprocessed_candidate_ids
    st.session_state.conversation_id = str(journey.conversation_id)
    st.session_state.journey_plan = journey.plan
    st.session_state.journey_plan_detail = (
        journey.plan_detail.model_dump(mode="json")
        if journey.plan_detail is not None
        else None
    )
    st.session_state.journey_status = journey.status
    st.session_state.journey_question = journey.question
    st.session_state.journey_question_definition = (
        journey.question_definition.model_dump(mode="json")
        if journey.question_definition is not None
        else None
    )
    st.session_state.journey_conversation = journey.conversation
    st.session_state.interview_message = journey.message
    st.session_state.journey_mode_acknowledgement = (
        journey.mode_acknowledgement
    )
    st.session_state.journey_react_status = journey.react_status
    st.session_state.journey_agent_budget = journey.agent_budget
    st.session_state.journey_agent_trace = [
        event.model_dump(mode="json") for event in journey.agent_trace
    ]
    st.session_state.journey_locale = journey.locale
    st.session_state.interview_result = (
        journey.eligibility_result.model_dump(mode="json")
        if journey.eligibility_result is not None
        else None
    )
    st.session_state.candidate_scheme_ids = journey.candidate_scheme_ids
    st.session_state.candidate_verdicts = {
        scheme_id: verdict.model_dump(mode="json")
        for scheme_id, verdict in journey.candidate_verdicts.items()
    }
    st.session_state.eligibility_results = {
        scheme_id: result.model_dump(mode="json")
        for scheme_id, result in journey.eligibility_results.items()
    }
    st.session_state.plan_change_history = [
        change.model_dump(mode="json")
        for change in journey.plan_change_history
    ]
    st.session_state.journey_history = [
        event.model_dump(mode="json") for event in journey.journey_history
    ]
    st.session_state.known_fact_names = (
        journey.correctable_fact_names or journey.known_fact_names
    )
    st.session_state.fact_questions = journey.fact_questions
    if journey.return_code:
        st.session_state.journey_return_code = journey.return_code
    st.session_state.application_flow = {
        scheme_id: {"assessment": assessment, "error": None, "edit_mode": False}
        for scheme_id, assessment in journey.document_assessments.items()
    }


def render_agent_observability(text: dict[str, str]) -> None:
    """Show durable budget counters and metadata-only events, never prompts."""

    budget = st.session_state.journey_agent_budget
    trace = st.session_state.journey_agent_trace
    with st.expander(text["agent_activity"]):
        st.caption(text["agent_usage"].format(
            calls=budget.get("model_calls", 0),
            call_limit=MAX_CONVERSATION_MODEL_CALLS,
            steps=budget.get("agent_steps", 0),
            step_limit=MAX_CONVERSATION_AGENT_STEPS,
            tools=budget.get("tool_calls", 0),
            tool_limit=MAX_CONVERSATION_TOOL_CALLS,
            tokens=(
                budget.get("input_tokens", 0)
                + budget.get("output_tokens", 0)
            ),
            token_limit=MAX_CONVERSATION_TOKENS,
        ))
        if not trace:
            st.caption(text["agent_no_calls"])
        for event in trace:
            st.caption(
                f'{event["agent"]} · {event["action"] or "—"} · '
                f'{event["status"]} · {event["model"]} · '
                f'{event["duration_ms"]} ms'
            )


def remember_in_url(scheme_id: str, candidate_ids: list[str] | None = None) -> None:
    """Put the conversation in the address bar so a refresh can restore it.

    Only the random conversation ID and the scheme ID go in the URL, never
    any answers.
    """

    st.query_params["conversation"] = st.session_state.conversation_id
    if candidate_ids:
        st.query_params.pop("scheme", None)
        st.query_params["schemes"] = ",".join(candidate_ids)
    else:
        st.query_params.pop("schemes", None)
        st.query_params["scheme"] = scheme_id


def interview_request(
    locale: str,
    profile_description: str | None,
    **schemes: object,
) -> JourneyRequest:
    """Build the "start an interview" request for this browser session.

    Args:
        schemes: ``scheme_id=...`` for one scheme, or
            ``candidate_scheme_ids=[...]`` for the schemes found by search.
    """

    return JourneyRequest(
        action="interview",
        # The same conversation ID is reused, so "forget" deletes all of it.
        conversation_id=(
            UUID(st.session_state.conversation_id)
            if st.session_state.conversation_id
            else uuid4()
        ),
        profile_description=profile_description,
        locale=locale,
        mode=st.session_state.interaction_mode,
        citizen_present=(
            st.session_state.interaction_mode == "citizen"
            or st.session_state.csc_citizen_present
        ),
        return_code=st.session_state.get("household_return_code") or None,
        memory_consent=bool(st.session_state.get("memory_consent", False)),
        **schemes,
    )


def render_history(text: dict[str, str]) -> None:
    """Show retries, tool failures and corrections as short captions."""

    titles = {
        "tool_retry": "history_retry",
        "tool_failed": "history_failed",
        "answer_corrected": "history_corrected",
    }
    for event in st.session_state.journey_history:
        st.caption(f'{text[titles[event["event_type"]]]}: {event["reason"]}')


def start_candidate_interview(
    candidate_ids: list[str],
    profile_description: str | None,
    locale: str,
) -> None:
    """Start one shared interview for the schemes found by search."""

    st.session_state.interview_error = None
    try:
        journey = run_journey(
            interview_request(
                locale, profile_description, candidate_scheme_ids=candidate_ids
            )
        )
    except JourneyApiError as error:
        st.session_state.interview_error = str(error)
        return
    save_journey(journey)
    st.session_state.journey_started = True
    st.session_state.journey_scheme_id = ",".join(candidate_ids)
    st.session_state.multi_scheme_mode = True
    st.session_state.interview_scheme_id = st.session_state.journey_scheme_id
    remember_in_url(st.session_state.journey_scheme_id, candidate_ids)


def render_discovery_notices(locale: str) -> None:
    """Display bounded coverage, failure/referral and stale-approval notices."""

    for code in st.session_state.journey_discovery_notices:
        st.warning(discovery_message(code, locale))
    for event in st.session_state.journey_discovery_events:
        st.caption(discovery_message(event["code"], locale))
        if event["candidate_ids"]:
            st.caption(", ".join(event["candidate_ids"]))
    if st.session_state.unprocessed_candidate_ids:
        st.warning(
            discovery_message("candidate_limit", locale)
            + " " + ", ".join(st.session_state.unprocessed_candidate_ids)
        )


def render_answer_correction(text: dict[str, str], locale: str) -> None:
    """Let either interview mode correct a confirmed or explicitly unknown fact."""

    if not st.session_state.known_fact_names:
        return
    st.markdown(f'**{text["correction_title"]}**')
    fact_questions = dict(st.session_state.get("fact_questions", {}))
    fact_name = st.selectbox(
        text["correction_fact"],
        options=st.session_state.known_fact_names,
        format_func=lambda value: fact_questions.get(value) or registry_question_for(fact_registry().get(value), locale),
        key="correction_fact_name",
    )
    answer = st.text_input(text["correction_answer"], key="correction_answer_value")
    if st.button(text["correction_submit"]):
        try:
            journey = correct_journey_answer(
                st.session_state.conversation_id, fact_name, answer
            )
        except JourneyApiError as error:
            st.session_state.application_drafts = {}
            st.session_state.application_drafts_loaded_for = None
            st.session_state.correction_error = str(error)
        else:
            save_journey(journey)
            st.session_state.correction_error = None
        st.rerun()
    if st.session_state.correction_error:
        st.error(st.session_state.correction_error)


def render_candidate_interview(
    text: dict[str, str],
    locale: str,
) -> None:
    """Show one shared chat and then a separate result for each scheme."""

    st.subheader(text["multi_interview_title"])
    st.caption(
        st.session_state.journey_mode_acknowledgement
        or (
            text["mode_notice"]
            if st.session_state.interaction_mode == "csc"
            else text["citizen_notice"]
        )
    )
    if st.session_state.journey_react_status == "deterministic_fallback":
        st.caption(text["agent_fallback"])
    if st.session_state.interview_error:
        st.error(st.session_state.interview_error)
    render_plan(st.session_state.journey_plan_detail, text)
    render_agent_observability(text)
    render_discovery_notices(locale)
    render_answer_correction(text, locale)
    if st.session_state.plan_change_history:
        st.markdown(f'**{text["plan_change_history"]}**')
        for change in st.session_state.plan_change_history:
            st.caption(
                f'Plan {change["from_version"]} → '
                f'Plan {change["to_version"]}: {change["reason"]}'
            )
    render_history(text)
    for turn in st.session_state.journey_conversation:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    if st.session_state.journey_status == "awaiting_answer":
        reply = journey_reply(text, locale)
        if reply:
            st.session_state.interview_error = None
            try:
                journey = send_journey_message(
                    st.session_state.conversation_id, reply
                )
            except JourneyApiError as error:
                st.session_state.interview_error = str(error)
            else:
                save_journey(journey)
            st.rerun()
        return

    if st.session_state.candidate_verdicts:
        st.subheader(text["multi_interview_results"])
        for scheme_id, verdict in st.session_state.candidate_verdicts.items():
            with st.expander(scheme_id, expanded=True):
                result = st.session_state.eligibility_results.get(scheme_id)
                if result:
                    render_verdict(result, scheme_id, text)
                elif verdict["result"] == "tool_error":
                    st.error(text["scheme_tool_error"])
                else:
                    st.info(text["finder_info_only"])
                if verdict["result"] == "eligible":
                    render_application_flow(scheme_id, text)
        render_document_readiness(text)


def save_application_progress(result: dict) -> dict:
    """Keep the visible supervisor plan in sync with application actions."""

    if result.get("plan_detail"):
        st.session_state.journey_plan_detail = result["plan_detail"]
    return result


class DocumentDateError(ValueError):
    """A date typed into the document form could not be read."""


def _document_metadata_from_session(
    scheme_id: str,
    requirements: list[dict[str, object]],
) -> dict[str, dict[str, str]]:
    """Keep only non-empty synthetic fields in the API assessment request.

    Dates are read like interview answers (``12 March 1958``, ``12-03-1958``,
    ``1958-03-12``, Hindi/Marathi digits) and sent as ``YYYY-MM-DD``.

    Raises:
        DocumentDateError: A typed date could not be read.
    """

    locale = st.session_state.get("journey_locale", "en")
    metadata: dict[str, dict[str, str]] = {}
    for item in requirements:
        document_id = str(item["document_id"])
        name = st.session_state.get(f"doc-name-{scheme_id}-{document_id}", "").strip()
        date_of_birth = st.session_state.get(
            f"doc-date-{scheme_id}-{document_id}", ""
        ).strip()
        if date_of_birth:
            parsed = parse_registered_answer(
                fact_registry().get("date_of_birth"), date_of_birth, locale,
            )
            if parsed.kind != "value":
                raise DocumentDateError(document_id)
            date_of_birth = parsed.value.isoformat()
        fields = {
            key: value
            for key, value in (
                ("name", name),
                ("date_of_birth", date_of_birth),
            )
            if value
        }
        if fields:
            metadata[document_id] = fields
    return metadata


MAX_UPLOAD_MB = 20
UPLOAD_TYPES = ["pdf", "jpg", "jpeg", "png"]

CHECKER_COPY = {
    "en": {
        "tab_upload": "Upload documents",
        "tab_checker": "Document checker",
        "upload_label": "Upload file (PDF, JPG or PNG, up to 20 MB)",
        "upload_too_big": "This file is larger than 20 MB.",
        "upload_ok": "Stored",
        "upload_remove": "Remove file",
        "upload_notice": (
            "Synthetic demo files only. Do not upload real personal documents. "
            "Files are stored for this conversation and deleted when you forget it."
        ),
        "run_check": "Run document check",
        "check_notice": "Run the check after uploading or changing documents.",
        "overall_complete": "All required documents are in place.",
        "overall_complete_with_acknowledged_warnings": (
            "All required documents are in place; some warnings were acknowledged."
        ),
        "overall_needs_attention": "Some documents need attention.",
        "overall_incomplete": "Some required documents are missing.",
        "overall_requirements_unverified": "Requirements for this scheme are not verified.",
        "state_in_place": "In place",
        "state_missing": "Missing",
        "state_needs_attention": "Needs attention",
        "state_acknowledged": "Acknowledged",
        "state_not_applicable": "Not applicable",
        "state_unknown": "Unknown",
        "issue_name_mismatch": "The name entered differs from the confirmed profile name.",
        "issue_date_of_birth_mismatch": "The date entered differs from the profile.",
        "issue_cannot_compare": "No name or date entered, so nothing could be compared.",
        "issue_file_problem": "The stored file is damaged or missing. Upload it again.",
        "issue_no_file": "Marked as available but no file is uploaded.",
        "issue_same_file_reused": "The same file is attached to more than one required document. Check it really covers each one.",
        "issue_file_name_mismatch": "The name read from the file differs from the confirmed profile name.",
        "issue_file_date_of_birth_mismatch": "The date of birth read from the file differs from the profile.",
        "missing_list": "Still needed",
        "resolve_reason": "Reason for accepting this warning (required)",
        "resolve_button": "Acknowledge warning",
        "reopen_button": "Reopen",
        "resolve_hint": "Or fix the document or the typed name/date and run the check again.",
        "acknowledged_by": "Acknowledged",
        "resolve_error": "Could not complete this action.",
        "readiness_title": "Document readiness by scheme",
        "readiness_state_ready": "Documents ready",
        "readiness_state_partial": "Some documents on file",
        "readiness_state_none": "No documents on file",
        "readiness_state_unverified": "Requirements not verified",
        "readiness_count": "required document groups in place",
        "readiness_need": "Still needed",
        "readiness_button": "Show document readiness",
        "suggest_read": "Read name and date from file",
        "review_name": "Reviewer name (person who checked this file)",
        "review_note": "Note (optional)",
        "review_button": "Mark as reviewed",
        "review_done": "Reviewed by",
        "review_undo": "Remove review",
        "view_file": "View uploaded file",
        "reviewer_code_label": "Reviewer access code (reviewers only)",
        "reviewer_code_needed": "Enter the reviewer access code to view files and sign off documents.",
        "download_file": "Download file",
        "view_pdf_hint": "PDF files cannot be previewed here. Download it to read it.",
        "view_error": "The file could not be loaded.",
        "under_review_title": "Under review",
        "under_review_body": (
            "Your synthetic application was submitted and is now under human "
            "review. A reviewer checks each document below and signs it off."
        ),
        "review_complete": "Human review complete. Every uploaded document is signed off and no warning is open.",
        "review_pending": "Waiting for a reviewer to check the documents below.",
        "suggest_found": "Suggested from file (name · date of birth)",
        "suggest_none": "No name or date could be read. Please type them.",
        "suggest_notice": (
            "Suggested only. Check it against the document; it is not verified "
            "and not proof the document is genuine."
        ),
        "suggest_accept": "Use these values (you can still edit them)",
    },
    "hi": {
        "suggest_read": "फ़ाइल से नाम और तिथि पढ़ें",
        "review_name": "समीक्षक का नाम (जिसने फ़ाइल जाँची)",
        "review_note": "टिप्पणी (वैकल्पिक)",
        "review_button": "समीक्षित के रूप में चिह्नित करें",
        "review_done": "समीक्षक",
        "review_undo": "समीक्षा हटाएँ",
        "view_file": "अपलोड की गई फ़ाइल देखें",
        "reviewer_code_label": "समीक्षक एक्सेस कोड (केवल समीक्षकों के लिए)",
        "reviewer_code_needed": "फ़ाइलें देखने और दस्तावेज़ों पर हस्ताक्षर के लिए समीक्षक एक्सेस कोड डालें।",
        "download_file": "फ़ाइल डाउनलोड करें",
        "view_pdf_hint": "PDF यहाँ नहीं दिखाई जा सकती। पढ़ने के लिए डाउनलोड करें।",
        "view_error": "फ़ाइल लोड नहीं हो सकी।",
        "under_review_title": "समीक्षा जारी है",
        "under_review_body": (
            "आपका नकली आवेदन जमा हो गया है और अब मानव समीक्षा में है। समीक्षक "
            "नीचे हर दस्तावेज़ जाँचकर उस पर हस्ताक्षर करता है।"
        ),
        "review_complete": "मानव समीक्षा पूरी। हर अपलोड किए दस्तावेज़ पर हस्ताक्षर हैं और कोई चेतावनी खुली नहीं।",
        "review_pending": "नीचे के दस्तावेज़ों की समीक्षक द्वारा जाँच की प्रतीक्षा है।",
        "suggest_found": "फ़ाइल से सुझाया गया (नाम · जन्म तिथि)",
        "suggest_none": "नाम या तिथि नहीं पढ़ी जा सकी। कृपया स्वयं टाइप करें।",
        "suggest_notice": "केवल सुझाव। दस्तावेज़ से मिलान करें; यह सत्यापित नहीं है और असली होने का प्रमाण नहीं।",
        "suggest_accept": "ये मान उपयोग करें (आप बदल सकते हैं)",
        "issue_file_name_mismatch": "फ़ाइल से पढ़ा गया नाम पुष्टि किए गए प्रोफ़ाइल नाम से अलग है।",
        "issue_file_date_of_birth_mismatch": "फ़ाइल से पढ़ी गई जन्म तिथि प्रोफ़ाइल से अलग है।",
        "tab_upload": "दस्तावेज़ अपलोड करें",
        "tab_checker": "दस्तावेज़ जाँच",
        "upload_label": "फ़ाइल अपलोड करें (PDF, JPG या PNG, 20 MB तक)",
        "upload_too_big": "यह फ़ाइल 20 MB से बड़ी है।",
        "upload_remove": "फ़ाइल हटाएँ",
        "run_check": "दस्तावेज़ जाँच चलाएँ",
        "overall_complete": "सभी आवश्यक दस्तावेज़ मौजूद हैं।",
        "overall_incomplete": "कुछ आवश्यक दस्तावेज़ गायब हैं।",
        "overall_needs_attention": "कुछ दस्तावेज़ों पर ध्यान देना है।",
        "state_in_place": "मौजूद",
        "state_missing": "गायब",
        "readiness_title": "योजना के अनुसार दस्तावेज़ तैयारी",
        "readiness_need": "अभी चाहिए",
    },
    "mr": {
        "tab_upload": "कागदपत्रे अपलोड करा",
        "tab_checker": "कागदपत्र तपासणी",
        "suggest_read": "फाइलमधून नाव आणि तारीख वाचा",
        "review_name": "तपासणाऱ्याचे नाव (ज्याने फाइल तपासली)",
        "review_note": "टीप (ऐच्छिक)",
        "review_button": "तपासले म्हणून नोंदवा",
        "review_done": "तपासणारा",
        "review_undo": "तपासणी काढा",
        "view_file": "अपलोड केलेली फाइल पहा",
        "reviewer_code_label": "तपासणीकर्ता प्रवेश कोड (फक्त तपासणीकर्त्यांसाठी)",
        "reviewer_code_needed": "फाइल पाहण्यासाठी आणि कागदपत्रांवर सही करण्यासाठी तपासणीकर्ता प्रवेश कोड टाका.",
        "download_file": "फाइल डाउनलोड करा",
        "view_pdf_hint": "PDF येथे दाखवता येत नाही. वाचण्यासाठी डाउनलोड करा.",
        "view_error": "फाइल लोड करता आली नाही.",
        "under_review_title": "तपासणी सुरू आहे",
        "under_review_body": (
            "तुमचा नमुना अर्ज सादर झाला आहे आणि आता मानवी तपासणीत आहे. तपासणारा "
            "खालील प्रत्येक कागदपत्र तपासून त्यावर सही करतो."
        ),
        "review_complete": "मानवी तपासणी पूर्ण. प्रत्येक अपलोड केलेल्या कागदपत्रावर सही आहे आणि कोणताही इशारा उघडा नाही.",
        "review_pending": "खालील कागदपत्रे तपासणाऱ्याकडून तपासली जाण्याची प्रतीक्षा आहे.",
        "suggest_found": "फाइलमधून सुचवलेले (नाव · जन्मतारीख)",
        "suggest_none": "नाव किंवा तारीख वाचता आली नाही. कृपया स्वतः टाइप करा.",
        "suggest_notice": "फक्त सूचना. कागदपत्राशी पडताळा; हे सत्यापित नाही आणि खरे असल्याचा पुरावा नाही.",
        "suggest_accept": "ही मूल्ये वापरा (तुम्ही बदलू शकता)",
        "issue_file_name_mismatch": "फाइलमधून वाचलेले नाव निश्चित केलेल्या प्रोफाइल नावाशी जुळत नाही.",
        "issue_file_date_of_birth_mismatch": "फाइलमधून वाचलेली जन्मतारीख प्रोफाइलशी जुळत नाही.",
        "upload_label": "फाइल अपलोड करा (PDF, JPG किंवा PNG, 20 MB पर्यंत)",
        "upload_too_big": "ही फाइल 20 MB पेक्षा मोठी आहे.",
        "upload_remove": "फाइल काढा",
        "run_check": "कागदपत्र तपासणी चालवा",
        "overall_complete": "सर्व आवश्यक कागदपत्रे उपलब्ध आहेत.",
        "overall_incomplete": "काही आवश्यक कागदपत्रे गहाळ आहेत.",
        "overall_needs_attention": "काही कागदपत्रांकडे लक्ष द्यावे लागेल.",
        "state_in_place": "उपलब्ध",
        "state_missing": "गहाळ",
        "readiness_title": "योजनेनुसार कागदपत्र तयारी",
        "readiness_need": "अजून हवे",
    },
}


def ct(key: str) -> str:
    """Look up checker text, falling back to English for untranslated keys."""

    locale = st.session_state.get("journey_locale", "en")
    return CHECKER_COPY.get(locale, {}).get(key) or CHECKER_COPY["en"][key]


def _on_document_upload(scheme_id: str, document_id: str) -> None:
    """Send a newly chosen file to the API and mark the document available."""

    uploaded = st.session_state.get(_uploader_key(scheme_id, document_id))
    if uploaded is None:
        return
    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.session_state[f"upl-msg-{document_id}"] = ("error", ct("upload_too_big"))
        return
    try:
        upload_document(
            st.session_state.conversation_id,
            document_id,
            uploaded.name,
            uploaded.getvalue(),
        )
    except ApplicationApiError as error:
        st.session_state[f"upl-msg-{document_id}"] = ("error", str(error))
        return
    st.session_state[f"upl-msg-{document_id}"] = ("ok", uploaded.name)
    st.session_state[f"doc-{scheme_id}-{document_id}"] = "available"


def _uploader_key(scheme_id: str, document_id: str) -> str:
    version = st.session_state.get("upl-version", {}).get(document_id, 0)
    return f"upl-{scheme_id}-{document_id}-{version}"


def _on_document_remove(scheme_id: str, document_id: str) -> None:
    try:
        delete_document_file(st.session_state.conversation_id, document_id)
    except ApplicationApiError as error:
        st.session_state[f"upl-msg-{document_id}"] = ("error", str(error))
        return
    versions = st.session_state.setdefault("upl-version", {})
    versions[document_id] = versions.get(document_id, 0) + 1
    st.session_state.pop(f"upl-msg-{document_id}", None)
    st.session_state[f"doc-{scheme_id}-{document_id}"] = "missing"


def _stored_files() -> dict[str, dict]:
    try:
        listing = list_document_files(st.session_state.conversation_id)
    except ApplicationApiError:
        return {}
    return {item["document_id"]: item for item in listing.get("files", [])}


def _render_document_uploader(
    scheme_id: str, document_id: str, stored: dict | None
) -> None:
    """One upload control per document, with the stored file shown beneath."""

    st.file_uploader(
        ct("upload_label"),
        type=UPLOAD_TYPES,
        key=_uploader_key(scheme_id, document_id),
        on_change=_on_document_upload,
        args=(scheme_id, document_id),
    )
    message = st.session_state.get(f"upl-msg-{document_id}")
    if message and message[0] == "error":
        st.error(message[1])
    if stored:
        st.caption(
            f'{ct("upload_ok")}: {stored["original_name"]} · '
            f'{stored["size_bytes"] // 1024} KB'
        )
        st.button(
            ct("upload_remove"),
            key=f"upl-rm-{scheme_id}-{document_id}",
            on_click=_on_document_remove,
            args=(scheme_id, document_id),
        )
        _render_suggestion(scheme_id, document_id)


def _on_extract(document_id: str) -> None:
    try:
        extract_document_suggestion(st.session_state.conversation_id, document_id)
    except ApplicationApiError as error:
        st.session_state[f"sug-err-{document_id}"] = str(error)
    else:
        st.session_state.pop(f"sug-err-{document_id}", None)


def _on_accept_suggestion(
    scheme_id: str, document_id: str, name: str | None, dob: str | None
) -> None:
    """Copy confirmed suggestion values into the typed inputs the checker reads."""

    if name:
        st.session_state[f"doc-name-{scheme_id}-{document_id}"] = name
    if dob:
        st.session_state[f"doc-date-{scheme_id}-{document_id}"] = dob


def _render_suggestion(scheme_id: str, document_id: str) -> None:
    """Optional 'read values from the file' step; a person must accept the result."""

    try:
        info = get_document_suggestion(st.session_state.conversation_id, document_id)
    except ApplicationApiError:
        return
    if not info.get("enabled"):
        return
    st.button(
        ct("suggest_read"),
        key=f"sug-read-{scheme_id}-{document_id}",
        on_click=_on_extract,
        args=(document_id,),
    )
    if st.session_state.get(f"sug-err-{document_id}"):
        st.warning(st.session_state[f"sug-err-{document_id}"])
    suggestion = info.get("suggestion")
    if suggestion is None:
        return
    if not suggestion.get("name") and not suggestion.get("date_of_birth"):
        st.caption(ct("suggest_none"))
        return
    st.info(
        f'{ct("suggest_found")}: {suggestion.get("name") or "—"} · '
        f'{suggestion.get("date_of_birth") or "—"}'
    )
    st.caption(ct("suggest_notice"))
    st.button(
        ct("suggest_accept"),
        key=f"sug-accept-{scheme_id}-{document_id}",
        on_click=_on_accept_suggestion,
        args=(
            scheme_id, document_id,
            suggestion.get("name"), suggestion.get("date_of_birth"),
        ),
    )


def _checker_inputs(
    scheme_id: str, items: list[dict[str, object]]
) -> tuple[dict[str, str], str | None, dict]:
    return (
        _document_statuses_from_session(scheme_id, items),
        st.session_state.get(f"profile-name-{scheme_id}") or None,
        _document_metadata_from_session(scheme_id, items),
    )


def _run_checker(
    scheme_id: str, items: list[dict[str, object]], flow_state: dict, action=None
) -> None:
    """Fetch a fresh checker report, optionally after an acknowledge/reopen."""

    conversation_id = st.session_state.conversation_id
    try:
        statuses, name, metadata = _checker_inputs(scheme_id, items)
        if action is None:
            report = check_documents_report(
                conversation_id, scheme_id, statuses, name, metadata
            )
        else:
            report = action(conversation_id, scheme_id, statuses, name, metadata)
        flow_state["checker"] = report
        flow_state["checker_error"] = None
    except DocumentDateError:
        flow_state["checker_error"] = COPY[
            st.session_state.get("journey_locale", "en")
        ]["document_date_invalid"]
    except ApplicationApiError as error:
        flow_state["checker_error"] = str(error)


def _reviewer_code() -> str | None:
    return st.session_state.get("reviewer-code") or None


def _reviewer_locked() -> bool:
    """True when a reviewer code is required and none has been entered."""

    return bool(st.session_state.get("reviewer_required")) and not _reviewer_code()


def _render_file_view(scheme_id: str, document: dict) -> None:
    """Let the reviewer open the stored file; it is fetched only when asked for."""

    if _reviewer_locked():
        return
    upload = document["upload"]
    document_id = document["document_id"]
    if not st.checkbox(
        f'{ct("view_file")}: {upload["original_name"]}',
        key=f"view-{scheme_id}-{document_id}",
    ):
        return
    try:
        content = fetch_document_file(
            st.session_state.conversation_id, document_id, _reviewer_code()
        )
    except ApplicationApiError as error:
        st.error(str(error) if "reviewer" in str(error) else ct("view_error"))
        return
    if upload["content_type"].startswith("image/"):
        st.image(content, caption=upload["original_name"])
    else:
        st.caption(ct("view_pdf_hint"))
    st.download_button(
        ct("download_file"),
        data=content,
        file_name=upload["original_name"],
        mime=upload["content_type"],
        key=f"dl-{scheme_id}-{document_id}",
    )


def _render_review(
    scheme_id: str,
    document: dict,
    items: list[dict[str, object]],
    flow_state: dict,
) -> None:
    """Reviewer sign-off: records who looked at the file; it gates nothing."""

    document_id = document["document_id"]
    key = f"{scheme_id}-{document_id}"
    if _reviewer_locked():
        return
    review = document.get("review")
    if review:
        st.caption(
            f'{ct("review_done")}: {review["reviewer_name"]} · '
            f'{review["reviewed_at"]}'
            + (f' · {review["note"]}' if review.get("note") else "")
        )
        if st.button(ct("review_undo"), key=f"rev-undo-{key}"):
            try:
                remove_document_review(
                    st.session_state.conversation_id, document_id, _reviewer_code()
                )
            except ApplicationApiError as error:
                flow_state["checker_error"] = str(error)
            else:
                _run_checker(scheme_id, items, flow_state)
            st.rerun()
        return
    reviewer = st.text_input(ct("review_name"), key=f"rev-name-{key}")
    note = st.text_input(ct("review_note"), key=f"rev-note-{key}")
    if st.button(ct("review_button"), key=f"rev-save-{key}"):
        try:
            review_document_file(
                st.session_state.conversation_id, document_id, reviewer, note,
                _reviewer_code(),
            )
        except ApplicationApiError as error:
            flow_state["checker_error"] = str(error)
        else:
            _run_checker(scheme_id, items, flow_state)
        st.rerun()


def render_submitted_review(scheme_id: str, flow_state: dict) -> None:
    """After submission: show 'under review' and open the human review step."""

    st.subheader(ct("under_review_title"))
    if "checker" not in flow_state:
        _run_checker(scheme_id, [], flow_state)
    report = flow_state.get("checker")
    uploaded = [
        document
        for group in (report or {}).get("groups", [])
        for document in group["documents"]
        if document.get("upload")
    ]
    done = (
        bool(uploaded)
        and all(document.get("review") for document in uploaded)
        and report["overall"]
        in {"complete", "complete_with_acknowledged_warnings"}
    )
    if done:
        st.success(ct("review_complete"))
    else:
        st.info(ct("under_review_body"))
        st.caption(ct("review_pending"))
    render_document_checker(scheme_id, [], flow_state)


def render_rejected_documents(scheme_id: str, flow_state: dict) -> None:
    """A rejected draft still lets the reviewer open the files and the checker."""

    st.subheader(ct("tab_checker"))
    if "checker" not in flow_state:
        _run_checker(scheme_id, [], flow_state)
    render_document_checker(scheme_id, [], flow_state)


def render_document_checker(
    scheme_id: str, items: list[dict[str, object]], flow_state: dict
) -> None:
    """The checker tab: status of every required document and a way to resolve warnings."""

    locale = st.session_state.get("journey_locale", "en")
    st.caption(ct("check_notice"))
    try:
        required = bool(
            list_document_files(st.session_state.conversation_id).get(
                "reviewer_code_required"
            )
        )
    except ApplicationApiError:
        required = False
    st.session_state["reviewer_required"] = required
    if required:
        st.text_input(
            ct("reviewer_code_label"), type="password", key="reviewer-code"
        )
        if _reviewer_locked():
            st.info(ct("reviewer_code_needed"))
    if st.button(ct("run_check"), key=f"chk-run-{scheme_id}", type="primary"):
        _run_checker(scheme_id, items, flow_state)
    if flow_state.get("checker_error"):
        st.error(flow_state["checker_error"])
    report = flow_state.get("checker")
    if not report:
        return
    overall = report["overall"]
    banner = {
        "complete": st.success,
        "complete_with_acknowledged_warnings": st.success,
        "needs_attention": st.warning,
        "incomplete": st.warning,
    }.get(overall, st.info)
    banner(ct(f"overall_{overall}"))
    st.caption(report["notice"])
    for group in report["groups"]:
        label = group["labels"].get(locale, group["label"])
        st.markdown(f'**{label}** — {ct("state_" + group["state"])}')
        for document in group["documents"]:
            doc_label = document["labels"].get(locale, document["label"])
            st.write(f'{doc_label}: {ct("state_" + document["state"])}')
            if document.get("upload"):
                _render_file_view(scheme_id, document)
                _render_review(scheme_id, document, items, flow_state)
            for issue in document["issues"]:
                key = f'{scheme_id}-{issue["issue_id"]}'
                if issue["acknowledged"]:
                    resolution = issue["resolution"] or {}
                    st.caption(
                        f'{ct("acknowledged_by")}: {resolution.get("reason", "")}'
                    )
                    if st.button(ct("reopen_button"), key=f"chk-reopen-{key}"):
                        _run_checker(
                            scheme_id, items, flow_state,
                            lambda *args, issue=issue: reopen_document_issue(
                                args[0], args[1], issue["document_id"],
                                issue["code"], *args[2:],
                            ),
                        )
                        st.rerun()
                    continue
                st.warning(ct(f'issue_{issue["code"]}'))
                if issue["can_acknowledge"]:
                    reason = st.text_input(
                        ct("resolve_reason"), key=f"chk-reason-{key}"
                    )
                    if st.button(ct("resolve_button"), key=f"chk-resolve-{key}"):
                        if len(reason.strip()) < 3:
                            flow_state["checker_error"] = ct("resolve_reason")
                        else:
                            _run_checker(
                                scheme_id, items, flow_state,
                                lambda *args, issue=issue, reason=reason: (
                                    resolve_document_issue(
                                        args[0], args[1], issue["document_id"],
                                        issue["code"], reason.strip(), *args[2:],
                                    )
                                ),
                            )
                        st.rerun()
                else:
                    st.caption(ct("resolve_hint"))
    if report["missing_labels"]:
        st.markdown(f'**{ct("missing_list")}**')
        for labels in report["missing_labels"]:
            st.write(f'- {labels.get(locale, labels.get("en", ""))}')


def render_document_readiness(text: dict[str, str]) -> None:
    """Rank schemes by documents already on file; this is not an eligibility result."""

    locale = st.session_state.get("journey_locale", "en")
    st.subheader(ct("readiness_title"))
    if not st.button(ct("readiness_button"), key="readiness-run"):
        return
    try:
        result = document_readiness(st.session_state.conversation_id)
    except ApplicationApiError as error:
        st.error(str(error))
        return
    st.caption(result["notice"])
    for scheme in result["schemes"]:
        with st.container(border=True):
            st.markdown(
                f'**{scheme["scheme_id"]}** — '
                f'{ct("readiness_state_" + scheme["state"])}'
            )
            st.caption(
                f'{scheme["in_place"]}/{scheme["required"]} '
                f'{ct("readiness_count")} · {scheme["eligibility"]}'
            )
            for labels in scheme["missing_labels"]:
                st.write(
                    f'- {ct("readiness_need")}: {labels.get(locale, labels.get("en", ""))}'
                )


def _render_document_groups(
    scheme_id: str,
    assessment: dict[str, object],
    text: dict[str, str],
) -> list[dict[str, object]]:
    """Render the active groups, preserving any-one alternatives and conditions."""

    locale = st.session_state.get("journey_locale", "en")
    trust_status = assessment.get("trust_status")
    if trust_status == "demo_only_unverified":
        st.caption(text["requirements_demo_status"])
        st.caption(text["demo_warning"])
    elif trust_status == "approved_source_backed":
        st.caption(text["requirements_approved_status"])
    else:
        st.warning(text["requirements_referral"])
    version = assessment.get("checklist_version")
    if version:
        st.caption(f'{text["requirements_version"]}: {version}')
    citations = assessment.get("citations", [])
    if citations:
        with st.expander(text["source_citations"]):
            for citation in citations:
                st.markdown(
                    f'[{citation["source_url"]}]({citation["source_url"]})'
                )
                st.caption(
                    f'{text["source_locator"]}: {citation["source_locator"]}'
                )
                publication_date = (
                    citation["publication_date"]
                    or text["source_publication_unknown"]
                )
                st.caption(
                    f'{text["source_collected_on"]}: {citation["collected_on"]} · '
                    f'{text["source_publication_date"]}: {publication_date}'
                )
                st.write(f'{text["source_quote"]}: {citation["exact_quote"]}')

    stored_files = _stored_files() if assessment.get("groups") else {}
    visible_items: list[dict[str, object]] = []
    for group in assessment.get("groups", []):
        labels = group.get("labels", {})
        label = labels.get(locale, group.get("label", ""))
        st.markdown(f"**{label}**")
        condition = group.get("condition", {})
        if condition.get("kind") == "profile_boolean":
            condition_key = (
                f'condition_{condition.get("field")}_'
                f'{str(condition.get("equals")).lower()}'
            )
            st.caption(text.get(condition_key, text["requirements_any_one"]))
        if group.get("applicable") is False:
            st.caption(text["requirements_not_applicable"])
            continue
        if group.get("applicable") is None:
            st.caption(text["requirements_condition_unknown"])
            continue
        alternatives = group.get("alternatives", [])
        if len(alternatives) > 1:
            st.caption(text["requirements_any_one"])
        for item in alternatives:
            item_labels = item.get("labels", {})
            document_label = item_labels.get(locale, item.get("label", ""))
            document_id = str(item["document_id"])
            st.selectbox(
                document_label,
                options=["unknown", "available", "missing", "mismatch"],
                index=["unknown", "available", "missing", "mismatch"].index(
                    item["status"]
                ),
                format_func=lambda status: text[f"status_{status}"],
                key=f"doc-{scheme_id}-{document_id}",
            )
            st.text_input(
                text["document_name"],
                key=f"doc-name-{scheme_id}-{document_id}",
            )
            st.text_input(
                text["document_date"],
                key=f"doc-date-{scheme_id}-{document_id}",
            )
            _render_document_uploader(scheme_id, document_id, stored_files.get(document_id))
            visible_items.append(item)
    return visible_items


def _document_statuses_from_session(
    scheme_id: str, items: list[dict[str, object]]
) -> dict[str, str]:
    """Read only the alternatives actually shown for applicable groups."""

    return {
        str(item["document_id"]): st.session_state[
            f"doc-{scheme_id}-{item['document_id']}"
        ]
        for item in items
    }


def _localized_document_groups(
    groups: list[dict[str, object]],
    locale: str,
    text: dict[str, str],
) -> list[dict[str, object]]:
    """Render saved requirement groups using their language-specific labels."""

    summaries = []
    for group in groups:
        condition = group.get("condition", {})
        condition_key = (
            f'condition_{condition.get("field")}_'
            f'{str(condition.get("equals")).lower()}'
        )
        summaries.append({
            "requirement": group.get("labels", {}).get(
                locale, group.get("label", "")
            ),
            "condition": (
                text.get(condition_key)
                if condition.get("kind") == "profile_boolean"
                else None
            ),
            "status": text.get(
                f'status_{group.get("status")}',
                text["requirements_not_applicable"],
            ),
            "alternatives": [
                {
                    "label": item.get("labels", {}).get(
                        locale, item.get("label", "")
                    ),
                    "status": text[f'status_{item["status"]}'],
                }
                for item in group.get("alternatives", [])
            ],
        })
    return summaries


def _render_form_preview(
    scheme_id: str, preview: dict[str, object], locale: str, text: dict[str, str]
) -> set[str]:
    """Show mapped confirmed values and render only explicitly allowed extra inputs."""

    st.caption(str(preview.get("notice", "")))
    missing = set(preview.get("missing_fields", []))
    for field in preview.get("fields", []):
        labels = field.get("labels", {})
        label = labels.get(locale, labels.get("en", field["field_id"]))
        if not field.get("extra_input"):
            if field.get("value") is None:
                st.warning(text["form_fields_missing"])
                continue
            st.write(f'{label}: {field["value"]}')
            continue
        key = f'form-{scheme_id}-{field["field_id"]}'
        field_type = field["value_type"]
        if field_type == "boolean":
            value = st.selectbox(
                label,
                options=["", True, False],
                format_func=lambda item: (
                    "—" if item == "" else text["yes"] if item else text["no"]
                ),
                key=key,
            )
        elif field_type == "choice":
            value = st.selectbox(
                label,
                options=["", *field["choices"]],
                key=key,
            )
        else:
            value = st.text_input(label, key=key)
        if field["required"] and (value == "" or value is None):
            missing.add(field["field_id"])
        else:
            missing.discard(field["field_id"])
    non_input_missing = {
        field_id
        for field_id in missing
        if not any(
            field["field_id"] == field_id and field.get("extra_input")
            for field in preview.get("fields", [])
        )
    }
    if non_input_missing:
        st.warning(text["form_fields_missing"])
    return missing


def _form_values_from_session(
    scheme_id: str, preview: dict[str, object]
) -> dict[str, object]:
    """Read only fields explicitly marked as additional inputs by the mapping."""

    values: dict[str, object] = {}
    for field in preview.get("fields", []):
        if not field.get("extra_input"):
            continue
        value = st.session_state.get(f'form-{scheme_id}-{field["field_id"]}')
        if value not in (None, ""):
            values[str(field["field_id"])] = value
    return values


def render_application_flow(scheme_id: str, text: dict[str, str]) -> None:
    """Render the API-backed synthetic checklist and exact-draft approval flow."""

    conversation_id = st.session_state.conversation_id
    if not conversation_id:
        return
    try:
        drafts = list_application_drafts(conversation_id)
    except ApplicationApiError:
        st.error(text["application_error"])
        return
    st.session_state.application_drafts = {
        draft["scheme_id"]: draft for draft in drafts
    }
    st.session_state.application_drafts_loaded_for = conversation_id
    drafts = st.session_state.setdefault("application_drafts", {})
    flow_state = st.session_state.setdefault("application_flow", {}).setdefault(
        scheme_id, {"assessment": None, "error": None, "edit_mode": False}
    )
    with st.container(border=True):
        st.markdown(f'**{text["synthetic_application"]} · {scheme_id}**')
        draft = drafts.get(scheme_id)
        if draft is None:
            if st.button(text["load_checklist"], key=f"docs-load-{scheme_id}"):
                try:
                    flow_state["assessment"] = save_application_progress(
                        assess_documents(conversation_id, scheme_id)
                    )
                    flow_state["error"] = None
                except ApplicationApiError:
                    flow_state["error"] = text["application_error"]
                st.rerun()

            assessment = flow_state.get("assessment")
            form_missing: set[str] = set()
            if assessment:
                form_preview = assessment.get("form_preview", {})
                if form_preview.get("status") != "unavailable":
                    form_missing = _render_form_preview(
                        scheme_id, form_preview,
                        st.session_state.get("journey_locale", "en"), text,
                    )
                else:
                    st.warning(text["form_fields_missing"])
                if assessment.get("report_stale"):
                    st.warning(text["requirements_changed"])
                if assessment.get("discrepancies"):
                    st.warning(text["resolve_mismatch"])
                tab_upload, tab_checker = st.tabs(
                    [ct("tab_upload"), ct("tab_checker")]
                )
                with tab_upload:
                    st.text_input(
                        text["profile_name"],
                        key=f"profile-name-{scheme_id}",
                    )
                    visible_items = _render_document_groups(
                        scheme_id, assessment, text
                    )
                    if assessment.get("groups") and st.button(
                        text["update_checklist"],
                        key=f"docs-update-{scheme_id}",
                    ):
                        statuses = _document_statuses_from_session(
                            scheme_id, visible_items
                        )
                        try:
                            metadata = _document_metadata_from_session(
                                scheme_id, visible_items
                            )
                            flow_state["assessment"] = save_application_progress(
                                assess_documents(
                                    conversation_id, scheme_id, statuses,
                                    st.session_state.get(f"profile-name-{scheme_id}") or None,
                                    metadata,
                                )
                            )
                            flow_state["error"] = None
                        except DocumentDateError:
                            flow_state["error"] = text["document_date_invalid"]
                        except ApplicationApiError:
                            flow_state["error"] = text["application_error"]
                        st.rerun()
                with tab_checker:
                    render_document_checker(scheme_id, visible_items, flow_state)
                if (
                    assessment["status"] == "checklist_complete"
                    and not assessment.get("report_stale")
                    and not form_missing
                    and st.button(
                    text["prepare_draft"],
                    type="primary",
                    key=f"draft-create-{scheme_id}",
                    )
                ):
                    statuses = {
                        item["document_id"]: st.session_state[
                            f"doc-{scheme_id}-{item['document_id']}"
                        ]
                        for item in visible_items
                    }
                    try:
                        draft = save_application_progress(
                            create_application_draft(
                                conversation_id,
                                scheme_id,
                                statuses,
                                st.session_state.get(f"profile-name-{scheme_id}") or None,
                                _document_metadata_from_session(
                                    scheme_id, visible_items
                                ),
                                _form_values_from_session(
                                    scheme_id, assessment.get("form_preview", {})
                                ),
                            )
                        )
                    except DocumentDateError:
                        flow_state["error"] = text["document_date_invalid"]
                    except ApplicationApiError:
                        flow_state["error"] = text["application_error"]
                    else:
                        drafts[scheme_id] = draft
                        flow_state["error"] = None
                    st.rerun()
        else:
            payload = draft["draft"]
            if payload.get("requirements_status") == "approved_source_backed":
                st.caption(text["requirements_approved_status"])
            else:
                st.caption(text["requirements_demo_status"])
                st.caption(text["demo_warning"])
            if payload.get("checklist_version"):
                st.caption(
                    f'{text["requirements_version"]}: {payload["checklist_version"]}'
                )
            citations = payload.get("document_citations", [])
            if citations:
                with st.expander(text["source_citations"]):
                    for citation in citations:
                        st.markdown(
                            f'[{citation["source_url"]}]({citation["source_url"]})'
                        )
                        st.caption(
                            f'{text["source_locator"]}: {citation["source_locator"]}'
                        )
                        publication_date = (
                            citation["publication_date"]
                            or text["source_publication_unknown"]
                        )
                        st.caption(
                            f'{text["source_collected_on"]}: '
                            f'{citation["collected_on"]} · '
                            f'{text["source_publication_date"]}: {publication_date}'
                        )
                        st.write(
                            f'{text["source_quote"]}: {citation["exact_quote"]}'
                        )
            if not draft["receipt_id"] and st.button(
                text["new_draft"],
                key=f"draft-new-{scheme_id}",
            ):
                drafts.pop(scheme_id, None)
                flow_state["assessment"] = None
                flow_state["error"] = None
                flow_state["edit_mode"] = False
                st.rerun()
            locale = st.session_state.get("journey_locale", "en")
            st.write(
                {
                    text["reference"]: payload["applicant_reference"],
                    text["district"]: payload["district"],
                    text["scheme_label"]: draft["scheme_id"],
                    text["revision_label"]: draft["revision"],
                    text["profile"]: payload["profile"],
                    text["documents"]: _localized_document_groups(
                        payload.get("document_groups", []), locale, text
                    ),
                    text["declaration"]: payload["declaration"],
                }
            )
            st.caption(f'{text["fingerprint"]}: `{draft["fingerprint"][:16]}…`')
            if draft.get("approval_expires_at") and draft["approved"]:
                st.caption(
                    f'{text["approval_expiry"]}: {draft["approval_expires_at"]}'
                )
            elif draft.get("approval_expired"):
                st.warning(text["approval_expired"])
            if draft["receipt_id"]:
                st.success(
                    f'{text["submitted"]} {text["receipt_label"]}: {draft["receipt_id"]}'
                )
                render_submitted_review(scheme_id, flow_state)
            elif draft.get("stale"):
                st.warning(discovery_message(
                    "stale_draft", st.session_state.journey_locale,
                ))
                if draft.get("approval_expired"):
                    st.warning(text["approval_expired"])
                if st.button(
                    text["load_checklist"],
                    key=f"docs-reload-{scheme_id}",
                ):
                    try:
                        flow_state["assessment"] = save_application_progress(
                            assess_documents(conversation_id, scheme_id)
                        )
                        flow_state["error"] = None
                    except ApplicationApiError:
                        flow_state["error"] = text["application_error"]
                    st.rerun()
                assessment = flow_state.get("assessment")
                if assessment:
                    form_preview = assessment.get("form_preview", {})
                    form_missing = _render_form_preview(
                        scheme_id, form_preview,
                        st.session_state.get("journey_locale", "en"), text,
                    )
                    if assessment.get("discrepancies"):
                        st.warning(text["mismatch_help"])
                    tab_upload, tab_checker = st.tabs(
                        [ct("tab_upload"), ct("tab_checker")]
                    )
                    with tab_upload:
                        st.text_input(
                            text["profile_name"],
                            key=f"profile-name-{scheme_id}",
                        )
                        visible_items = _render_document_groups(
                            scheme_id, assessment, text
                        )
                    with tab_checker:
                        render_document_checker(scheme_id, visible_items, flow_state)
                    if assessment.get("groups") and st.button(
                        text["recheck_documents"],
                        key=f"docs-correct-{scheme_id}",
                    ):
                        statuses = _document_statuses_from_session(
                            scheme_id, visible_items
                        )
                        try:
                            metadata = _document_metadata_from_session(
                                scheme_id, visible_items
                            )
                            checked = save_application_progress(assess_documents(
                                conversation_id, scheme_id, statuses,
                                st.session_state.get(f"profile-name-{scheme_id}") or None,
                                metadata,
                            ))
                            flow_state["assessment"] = checked
                            if (
                                checked["status"] == "checklist_complete"
                                and not form_missing
                            ):
                                drafts[scheme_id] = save_application_progress(
                                    create_application_draft(
                                        conversation_id,
                                        scheme_id,
                                        statuses,
                                        st.session_state.get(
                                            f"profile-name-{scheme_id}"
                                        ) or None,
                                        metadata,
                                        _form_values_from_session(
                                            scheme_id, form_preview
                                        ),
                                    )
                                )
                            flow_state["error"] = None
                        except DocumentDateError:
                            flow_state["error"] = text["document_date_invalid"]
                        except ApplicationApiError:
                            flow_state["error"] = text["application_error"]
                        st.rerun()
            elif draft["rejected"] and not flow_state.get("edit_mode"):
                st.error(text["rejected"])
                if st.button(
                    text["reopen"],
                    key=f"draft-reopen-{scheme_id}",
                ):
                    flow_state["edit_mode"] = True
                    st.rerun()
                render_rejected_documents(scheme_id, flow_state)
            else:
                if flow_state.get("edit_mode"):
                    reference = st.text_input(
                        text["synthetic_reference"],
                        value=payload["applicant_reference"],
                        key=f"draft-ref-{scheme_id}-{draft['revision']}",
                    )
                    district = st.text_input(
                        text["district"],
                        value=payload["district"],
                        key=f"draft-district-{scheme_id}-{draft['revision']}",
                    )
                    if st.button(text["save"], key=f"draft-save-{scheme_id}"):
                        edited = dict(draft)
                        edited["draft"] = {
                            **payload,
                            "applicant_reference": reference,
                            "district": district,
                        }
                        try:
                            drafts[scheme_id] = save_application_progress(
                                edit_application_draft(conversation_id, edited)
                            )
                            flow_state["edit_mode"] = False
                            flow_state["error"] = None
                        except ApplicationApiError:
                            flow_state["error"] = text["application_error"]
                        st.rerun()
                else:
                    if st.button(text["edit"], key=f"draft-edit-{scheme_id}"):
                        flow_state["edit_mode"] = True
                        st.rerun()
                    if st.button(
                        text["approve"],
                        disabled=draft["approved"],
                        key=f"draft-approve-{scheme_id}",
                    ):
                        try:
                            drafts[scheme_id] = save_application_progress(
                                decide_application_draft(conversation_id, draft, "approve")
                            )
                            flow_state["error"] = None
                        except ApplicationApiError:
                            flow_state["error"] = text["application_error"]
                        st.rerun()
                    if st.button(text["reject"], key=f"draft-reject-{scheme_id}"):
                        try:
                            drafts[scheme_id] = save_application_progress(
                                decide_application_draft(conversation_id, draft, "reject")
                            )
                            flow_state["error"] = None
                        except ApplicationApiError:
                            flow_state["error"] = text["application_error"]
                        st.rerun()
                    if draft["approved"] and st.button(
                        text["submit"],
                        type="primary",
                        key=f"draft-submit-{scheme_id}",
                    ):
                        try:
                            drafts[scheme_id] = save_application_progress(
                                decide_application_draft(conversation_id, draft, "submit")
                            )
                            flow_state["error"] = None
                        except ApplicationApiError:
                            flow_state["error"] = text["application_error"]
                        st.rerun()
        if flow_state.get("error"):
            st.error(flow_state["error"])


def render_plan(plan_detail: dict | None, text: dict[str, str]) -> None:
    """Draw the supervisor's plan as a checklist with status icons.

    Example while Saathi waits for an answer::

        ? Learn about you
        ? Check the rules for IGNWPS-MH
    """

    if not plan_detail:
        return
    with st.container(border=True):
        st.markdown(f'**{text["plan_title"]}**')
        for step in plan_detail["steps"]:
            icon = PLAN_STEP_ICONS.get(step["status"], "•")
            st.markdown(f'{icon} {step["goal"]}')
        if plan_detail.get("replan_reason"):
            st.caption(plan_detail["replan_reason"])


@st.cache_resource
def fact_registry():
    """Load the fact registry once; it holds the wording for each fact."""

    return RulePackageProvider().registry


def readable_missing_fields(fields: list[str], locale: str) -> str:
    """Show each missing fact as its question; other labels stay as written."""

    facts = {fact.fact_id: fact for fact in fact_registry().definitions}
    return "; ".join(
        facts[field].questions[locale].text if field in facts else field
        for field in fields
    )


def render_verdict(
    result: dict,
    scheme_id: str,
    text: dict[str, str],
) -> None:
    """Show a rule-engine verdict with its reason and official sources."""

    # Green for eligible, red for not eligible, yellow for "need more".
    if result["result"] == "eligible":
        st.success(f'✅ {text["eligible"]}')
    elif result["result"] == "not_eligible":
        # PM-KISAN wording reminds the user this is the 2020 mock check.
        st.error(
            "⛔ "
            + text[
                "pmkisan_potential"
                if scheme_id == "PM-KISAN-IN"
                else "not_eligible"
            ]
        )
    else:
        st.warning(f'⚠️ {text["cant_tell"]}')
    st.write(result["reason"])
    # Optional parts only show when the package provides them.
    if result.get("notice"):
        st.warning(result["notice"])
    if result["missing_fields"]:
        st.caption(
            f'{text["missing"]}: '
            + readable_missing_fields(
                result["missing_fields"],
                st.session_state.get("journey_locale", "en"),
            )
        )
        st.button(text["human"], disabled=True)
    if result.get("unresolved_checks"):
        st.caption(
            f'{text["pmkisan_unresolved"]}: '
            f'{", ".join(result["unresolved_checks"])}'
        )
    # One expandable box per deciding rule, with its official source.
    for evidence in result["evidence"]:
        with st.expander(evidence["rule_id"]):
            st.write(evidence["source_text"])
            st.caption(
                evidence.get("source_location")
                or evidence["source_clause_id"]
            )
            st.link_button(text["source"], evidence["source_url"])


def start_interview(
    scheme_id: str,
    locale: str,
    profile_description: str | None = None,
) -> None:
    """Ask the API to start a question-by-question check for one scheme."""

    st.session_state.interview_error = None
    try:
        journey = run_journey(
            interview_request(locale, profile_description, scheme_id=scheme_id)
        )
    except JourneyApiError as error:
        st.session_state.interview_error = str(error)
    else:
        save_journey(journey)
        st.session_state.interview_scheme_id = scheme_id
        remember_in_url(scheme_id)


def registered_answer_input(
    question: dict[str, object],
    text: dict[str, str],
    locale: str,
    conversation_id: str,
) -> str | None:
    """Render a registry-selected answer widget and return its stable value."""

    fact_id = str(question["fact_id"])
    value_type = question["value_type"]
    key = f"registered_answer_{conversation_id}_{fact_id}"
    if question.get("confirming"):
        key = f"{key}_confirming"
    unknown_label = unknown_answer_label(locale)
    if question.get("help_text"):
        st.caption(str(question["help_text"]))
    unit = question.get("unit")
    bound_labels = {
        "en": {"minimum": "Minimum", "maximum": "Maximum"},
        "hi": {"minimum": "न्यूनतम", "maximum": "अधिकतम"},
        "mr": {"minimum": "किमान", "maximum": "कमाल"},
    }[locale]
    bounds = [
        f"{bound_labels[name]}: {question[name]}"
        for name in ("minimum", "maximum")
        if question.get(name) is not None
    ]
    if unit or bounds:
        st.caption(" · ".join([*(str(item) for item in bounds), str(unit or "")]).strip(" ·"))

    if not has_quick_control(question):
        # Yes/no questions are answered by typing in the chat box.
        return None

    with st.form(f"{key}_form"):
        answer: object = None
        if value_type == "integer":
            is_unknown = st.checkbox(
                unknown_label, key=f"{key}_unknown"
            )
            minimum = question.get("minimum")
            maximum = question.get("maximum")
            selected = st.number_input(
                text["quick_answer"],
                min_value=minimum,
                max_value=maximum,
                value=None,
                step=1,
                format="%d",
                disabled=is_unknown,
                key=key,
            )
            answer = (
                "skip" if is_unknown
                else str(selected) if selected is not None
                else None
            )
        elif value_type == "decimal":
            is_unknown = st.checkbox(
                unknown_label, key=f"{key}_unknown"
            )
            selected = st.text_input(
                text["quick_answer"],
                max_chars=MAX_JOURNEY_REPLY_LENGTH,
                disabled=is_unknown,
                key=key,
            )
            answer = (
                "skip" if is_unknown
                else selected if selected
                else None
            )
        elif value_type == "date":
            is_unknown = st.checkbox(unknown_label, key=f"{key}_unknown")
            selected = date_dropdowns(
                text["quick_answer"], locale, key, disabled=is_unknown
            )
            answer = (
                "skip" if is_unknown
                else selected.isoformat() if isinstance(selected, date)
                else None
            )
        elif value_type == "choice":
            labels = {
                item["label"]: item["code"]
                for item in question.get("choices", [])
            }
            options = [unknown_label, *labels]
            selected = st.selectbox(
                text["quick_answer"],
                options,
                index=None,
                key=key,
            )
            answer = (
                "skip"
                if selected == unknown_label
                else labels.get(selected) if selected is not None else None
            )
        elif value_type == "text":
            is_unknown = st.checkbox(
                unknown_label, key=f"{key}_unknown"
            )
            selected = st.text_input(
                text["quick_answer"],
                max_chars=min(
                    int(question["max_length"]), MAX_JOURNEY_REPLY_LENGTH
                ),
                disabled=is_unknown,
                key=key,
            )
            answer = (
                "skip" if is_unknown
                else selected if selected
                else None
            )
        else:
            answer = None
        submitted = st.form_submit_button(text["send_answer"])
    return str(answer) if submitted and answer is not None else None


def has_quick_control(question: dict[str, object] | None) -> bool:
    """Whether a question gets a form control besides the chat box."""

    return bool(question) and question.get("value_type") in {
        "integer", "decimal", "date", "choice", "text",
    }


def journey_reply(text: dict[str, str], locale: str) -> str | None:
    """Offer the question's own controls, and typing, on every interview screen."""

    definition = st.session_state.get("journey_question_definition")
    selected = (
        registered_answer_input(
            definition, text, locale, st.session_state.conversation_id or "",
        )
        if definition
        else None
    )
    if has_quick_control(definition):
        # The controls are shortcuts; typed answers take the same checked path.
        st.caption(text["free_text_hint"])
    placeholder = (
        text["interview_reply_date"]
        if definition and definition.get("value_type") == "date"
        else text["interview_reply"]
    )
    typed = st.chat_input(placeholder, max_chars=MAX_JOURNEY_REPLY_LENGTH)
    return selected or typed


def render_interview(
    scheme_id: str,
    text: dict[str, str],
    locale: str,
    *,
    can_start: bool = True,
) -> None:
    """Draw the chat: plan, messages, an answer box, then the verdict.

    Flow across reruns:

    1. Not started: show a "Start questions" button.
    2. Waiting (status ``awaiting_answer``): show the history and a chat box.
       Each typed answer is sent to the API, which replies with the next
       question or the verdict.
    3. Finished: show the verdict and a "Start again" button.

    Args:
        scheme_id: The scheme to check.
        text: Screen text in the chosen language.
        can_start: False disables the start button (e.g. before consent).
    """

    st.subheader(text["interview_title"])
    st.info(text["interview_notice"])
    st.caption(
        st.session_state.journey_mode_acknowledgement
        or (
            text["mode_notice"]
            if st.session_state.interaction_mode == "csc"
            else text["citizen_notice"]
        )
    )
    if st.session_state.interview_error:
        st.error(
            f'{text["interview_error"]}: {st.session_state.interview_error}'
        )

    if st.session_state.interview_scheme_id != scheme_id:
        with st.expander(text["return_code_label"], expanded=False):
            code_input = st.text_input(
                text["return_code_label"],
                key=f"return_code_input_{scheme_id}",
                help=text["return_code_help"],
                max_chars=12,
                label_visibility="collapsed",
            )
            if st.button(text["return_code_load"], key=f"load_code_{scheme_id}"):
                if not st.session_state.get("memory_consent", False):
                    st.warning(text["memory_consent_required"])
                elif code_input and code_input.strip():
                    try:
                        loaded = load_household_profile(
                            code_input.strip(),
                            memory_consent=True,
                        )
                    except JourneyApiError as error:
                        st.error(f'{text["return_code_error"]}: {error}')
                    else:
                        if loaded:
                            st.session_state.household_return_code = loaded[
                                "return_code"
                            ]
                            st.success(text["return_code_display"].format(
                                code=loaded["return_code"],
                            ))
                        else:
                            st.warning(text["return_code_not_found"])
        description_key = f"household_description_{scheme_id}"
        description = st.text_area(
            text["household_description"],
            key=description_key,
            help=text["household_description_help"],
            max_chars=1200,
        )
        can_start = can_start and (
            st.session_state.interaction_mode == "citizen"
            or st.session_state.csc_citizen_present
        )
        if st.button(
            text["interview_start"], type="primary", disabled=not can_start
        ):
            start_interview(
                scheme_id,
                locale,
                description.strip() or None,
            )
            st.rerun()
        return

    render_plan(st.session_state.journey_plan_detail, text)
    if st.session_state.journey_react_status == "deterministic_fallback":
        st.caption(text["agent_fallback"])
    render_agent_observability(text)
    render_discovery_notices(locale)
    render_answer_correction(text, locale)
    for turn in st.session_state.journey_conversation:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    if st.session_state.journey_status == "awaiting_answer":
        reply = journey_reply(text, locale)
        if reply:
            st.session_state.interview_error = None
            try:
                journey = send_journey_message(
                    st.session_state.conversation_id, reply
                )
            except JourneyApiError as error:
                st.session_state.interview_error = str(error)
            else:
                save_journey(journey)
            st.rerun()
        return

    result = st.session_state.interview_result
    if result:
        render_verdict(result, scheme_id, text)
        if result["result"] == "eligible":
            render_application_flow(scheme_id, text)
    elif st.session_state.interview_message:
        # No verdict, e.g. the scheme has no reviewed rules.
        st.warning(st.session_state.interview_message)
    existing_code = st.session_state.get("journey_return_code")
    if existing_code:
        st.info(text["return_code_display"].format(code=existing_code))
    if st.session_state.conversation_id and st.session_state.known_fact_names:
        if st.button(text["return_code_save"], key=f"save_code_{scheme_id}"):
            if not st.session_state.get("memory_consent", False):
                st.warning(text["memory_consent_required"])
            else:
                try:
                    code = save_household_profile(
                        st.session_state.conversation_id,
                        return_code=existing_code,
                        memory_consent=True,
                    )
                    st.session_state.journey_return_code = code
                    st.success(text["return_code_saved"].format(code=code))
                except JourneyApiError as error:
                    st.error(str(error))
    if st.button(text["interview_restart"]):
        start_interview(scheme_id, locale)
        st.rerun()


st.set_page_config(
    page_title="Scheme Saathi",
    page_icon="🤝",
    layout="wide",
)

st.markdown(
    """
    <style>
    .demo-banner {
        background: #7f1d1d;
        border-radius: 0.5rem;
        color: #ffffff;
        font-weight: 700;
        margin-bottom: 1.25rem;
        padding: 0.9rem;
        text-align: center;
    }
    .profile-card {
        border: 1px solid #d1d5db;
        border-radius: 0.5rem;
        padding: 1rem;
    }
    .version {
        color: #4b5563;
        font-size: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

provider = FixtureDataProvider()
fixtures = provider.fixtures
st.session_state.setdefault("selected_result", None)
st.session_state.setdefault("api_result", None)
st.session_state.setdefault("api_error", None)
st.session_state.setdefault("draft_scenario_id", None)
st.session_state.setdefault("approved_fingerprint", None)
st.session_state.setdefault("draft_edit_mode", False)
st.session_state.setdefault("draft_submitted", False)
st.session_state.setdefault("rejected_draft", False)
st.session_state.setdefault("scheme_search_results", None)
st.session_state.setdefault("scheme_search_message", "")
st.session_state.setdefault("scheme_search_error", None)
st.session_state.setdefault("interview_scheme_id", None)
st.session_state.setdefault("interview_result", None)
st.session_state.setdefault("interview_message", None)
st.session_state.setdefault("interview_error", None)
st.session_state.setdefault("journey_plan_detail", None)
st.session_state.setdefault("journey_question", None)
st.session_state.setdefault("journey_question_definition", None)
st.session_state.setdefault("candidate_scheme_ids", [])
st.session_state.setdefault("candidate_verdicts", {})
st.session_state.setdefault("eligibility_results", {})
st.session_state.setdefault("multi_scheme_mode", False)
st.session_state.setdefault("plan_change_history", [])
st.session_state.setdefault("correction_error", None)
st.session_state.setdefault("fact_questions", {})
st.session_state.setdefault("journey_history", [])
st.session_state.setdefault("known_fact_names", [])
st.session_state.setdefault("journey_mode_acknowledgement", None)
st.session_state.setdefault("journey_react_status", "deterministic")
st.session_state.setdefault("journey_agent_budget", {})
st.session_state.setdefault("journey_agent_trace", [])
st.session_state.setdefault("journey_locale", "en")
st.session_state.setdefault("journey_dependency_version", 0)
st.session_state.setdefault("journey_discovery_notices", [])
st.session_state.setdefault("journey_discovery_events", [])
st.session_state.setdefault("unprocessed_candidate_ids", [])
st.session_state.setdefault("journey_started", False)
st.session_state.setdefault("journey_scheme_id", None)
st.session_state.setdefault("conversation_id", None)
st.session_state.setdefault("journey_conversation", [])
st.session_state.setdefault("journey_plan", None)
st.session_state.setdefault("journey_status", None)
st.session_state.setdefault("forget_error", None)

locale = st.selectbox(
    "Language / भाषा / भाषा",
    options=list(COPY),
    format_func=lambda value: COPY[value]["name"],
)
text = COPY[locale]

# After a browser refresh, session_state is empty but the address bar still
# has ?conversation=<id>&scheme=<id> (see remember_in_url). Ask the API for
# the saved conversation once, so the chat continues where it stopped.
saved_conversation = st.query_params.get("conversation")
saved_scheme = st.query_params.get("scheme")
saved_schemes = st.query_params.get("schemes")
if (
    saved_conversation
    and st.session_state.conversation_id is None
    and not st.session_state.get("restore_tried")
):
    st.session_state.restore_tried = True
    saved = None
    candidate_ids = (
        [item for item in saved_schemes.split(",") if item]
        if saved_schemes else []
    )
    if (candidate_ids and len(candidate_ids) <= 20) or saved_scheme:
        try:
            UUID(saved_conversation)  # ignore a hand-edited, broken ID
            saved = get_journey_state(saved_conversation)
        except (ValueError, JourneyApiError):
            saved = None
        if saved is not None and not candidate_ids:
            saved_schemes = (
                set(saved.candidate_scheme_ids) | set(saved.candidate_verdicts)
            )
            if saved_schemes and saved_scheme not in saved_schemes:
                saved = None
    if saved is None:
        # Nothing to restore (forgotten, expired or invalid): clean the URL.
        st.query_params.clear()
    else:
        save_journey(saved)
        st.session_state.journey_started = True
        st.session_state.journey_scheme_id = (
            ",".join(candidate_ids) if candidate_ids else saved_scheme
        )
        st.session_state.interview_scheme_id = st.session_state.journey_scheme_id
        st.session_state.multi_scheme_mode = bool(candidate_ids)
        st.session_state.show_restored = True

st.markdown(
    f'<div class="demo-banner">{text["banner"]}</div>',
    unsafe_allow_html=True,
)
st.title(text["title"])
st.subheader(text["subtitle"])
st.warning(f'{text["draft"]} · Fixture status: {fixtures.status}')

with st.sidebar:
    st.radio(
        text["mode"],
        options=["citizen", "csc"],
        format_func=lambda value: text[value],
        key="interaction_mode",
    )
    st.markdown(f'**{text["consent_title"]}**')
    st.caption(text["consent_text"])
    consent = st.checkbox(text["consent"], key="demo_consent")
    st.caption(text["memory_consent_text"])
    st.checkbox(text["memory_consent_label"], key="memory_consent")
    if st.session_state.interaction_mode == "csc":
        st.checkbox(text["csc_present"], key="csc_citizen_present")
    st.caption(
        text["mode_notice"]
        if st.session_state.interaction_mode == "csc"
        else text["citizen_notice"]
    )
    st.divider()
    st.markdown(
        f'<p class="version">Prototype version: '
        f'{os.getenv("APP_VERSION", fixtures.fixture_version)}</p>',
        unsafe_allow_html=True,
    )
    deployed_ref = os.getenv("DEPLOYED_REF")
    if deployed_ref:
        st.caption(f"Deployed branch: {deployed_ref}")
    if st.button(text["forget"], use_container_width=True):
        conversation_id = st.session_state.conversation_id
        household_code = (
            st.session_state.get("journey_return_code")
            or st.session_state.get("household_return_code")
        )
        try:
            if conversation_id or household_code:
                forget_personal_data(conversation_id, household_code)
        except JourneyApiError as error:
            st.session_state.forget_error = str(error)
        else:
            st.session_state.pop("household_return_code", None)
            st.session_state.pop("journey_return_code", None)
            clear_workflow_state(include_inputs=True)
            st.query_params.clear()
            st.session_state.show_forgotten = True
            st.session_state.forget_error = None
            st.rerun()

if st.session_state.forget_error:
    st.error(f'{text["forget_error"]}: {st.session_state.forget_error}')
if st.session_state.pop("show_forgotten", False):
    st.success(text["forgotten"])
if st.session_state.pop("show_restored", False):
    st.info(text["restored"])

# Streamlit reruns this whole file on every click. st.session_state keeps
# values between reruns, and st.stop() ends drawing so only one screen shows:
#   journey_started + PM-KISAN -> PM-KISAN interview, then stop
#   journey_started + novel supported bundle -> its registry questions, then stop
#   not journey_started        -> search screen, then stop
#   journey_started + other    -> widow-pension screen further below
if st.session_state.journey_started:
    st.caption(
        f'{text["finder_choose"]}: {st.session_state.journey_scheme_id}'
    )
    if st.button(text["finder_back"]):
        # Forget the chosen scheme and conversation, then redraw the search.
        st.session_state.journey_started = False
        st.session_state.journey_scheme_id = None
        st.session_state.conversation_id = None
        clear_application_state()
        clear_interview_state()
        st.query_params.clear()
        st.rerun()
    elif st.session_state.multi_scheme_mode:
        render_candidate_interview(text, locale)
        st.stop()
    elif st.session_state.journey_scheme_id == "PM-KISAN-IN":
        st.subheader(text["pmkisan_title"])
        st.warning(text["pmkisan_notice"])
        # Phase 2: Saathi asks only the questions the rules still need,
        # one at a time, instead of showing a form with every question.
        render_interview(
            "PM-KISAN-IN",
            text,
            locale,
            can_start=(
                consent
                and (
                    st.session_state.interaction_mode == "citizen"
                    or st.session_state.csc_citizen_present
                )
            ),
        )
        # Stop here so the widow-pension screen below is not drawn.
        st.stop()
    elif st.session_state.journey_scheme_id not in {
        fixtures.policy.scheme_id, "PM-KISAN-IN"
    }:
        render_interview(
            st.session_state.journey_scheme_id,
            text,
            locale,
            can_start=(
                consent
                and (
                    st.session_state.interaction_mode == "citizen"
                    or st.session_state.csc_citizen_present
                )
            ),
        )
        st.divider()
        st.caption(text["footer"])
        st.stop()
else:
    st.subheader(text["finder_title"])
    st.caption(text["finder_help"])
    query = st.text_input(text["finder_query"], key="scheme_query")
    if st.button(text["finder_submit"]):
        st.session_state.scheme_search_results = None
        st.session_state.scheme_search_message = ""
        st.session_state.scheme_search_error = None
        clear_interview_state()
        st.session_state.pop("selected_search_scheme", None)
        if not query.strip():
            st.session_state.scheme_search_error = text["finder_empty"]
        else:
            try:
                journey = run_journey(
                    JourneyRequest(
                        action="search",
                        conversation_id=(
                            UUID(st.session_state.conversation_id)
                            if st.session_state.conversation_id
                            else uuid4()
                        ),
                        query=query,
                        locale=locale,
                        mode=st.session_state.interaction_mode,
                        citizen_present=(
                            st.session_state.interaction_mode == "citizen"
                            or st.session_state.csc_citizen_present
                        ),
                    )
                )
                st.session_state.scheme_search_results = [
                    passage.model_dump(mode="json")
                    for passage in journey.passages
                ]
                st.session_state.scheme_search_message = journey.message
                st.session_state.candidate_scheme_ids = journey.candidate_scheme_ids
                st.session_state.journey_discovery_notices = journey.discovery_notices
                st.session_state.journey_discovery_events = [
                    event.model_dump(mode="json") for event in journey.discovery_events
                ]
                st.session_state.unprocessed_candidate_ids = journey.unprocessed_candidate_ids
                st.session_state.journey_history = [
                    event.model_dump(mode="json")
                    for event in journey.journey_history
                ]
                if journey.status == "tool_error":
                    st.session_state.scheme_search_error = journey.message
                st.session_state.conversation_id = str(
                    journey.conversation_id
                )
                st.session_state.journey_plan = journey.plan
                st.session_state.journey_conversation = journey.conversation
                st.session_state.journey_agent_budget = journey.agent_budget
                st.session_state.journey_agent_trace = [
                    event.model_dump(mode="json")
                    for event in journey.agent_trace
                ]
                st.session_state.journey_react_status = journey.react_status
            except JourneyApiError as error:
                st.session_state.scheme_search_error = str(error)

    if st.session_state.scheme_search_error:
        st.error(
            f'{text["finder_error"]}: '
            f'{st.session_state.scheme_search_error}'
        )

    search_results = st.session_state.scheme_search_results
    if search_results is not None:
        render_agent_observability(text)
        render_discovery_notices(locale)
        if st.session_state.scheme_search_message:
            st.caption(st.session_state.scheme_search_message)
        render_history(text)
        if st.session_state.journey_plan:
            st.caption(st.session_state.journey_plan)
        if st.session_state.journey_conversation:
            with st.expander(text["conversation"]):
                for turn in st.session_state.journey_conversation:
                    st.markdown(
                        f'**{turn["role"].title()}:** {turn["content"]}'
                    )
        if not search_results:
            st.info(text["finder_empty"])
        else:
            scheme_names = {}
            for passage in search_results:
                scheme_names.setdefault(
                    passage["scheme_id"], passage["scheme_name"]
                )
            selected_scheme_id = st.selectbox(
                text["finder_choose"],
                options=list(scheme_names),
                format_func=lambda value: (
                    f'{scheme_names[value]} ({value})'
                ),
                key="selected_search_scheme",
            )
            for passage in search_results:
                if passage["scheme_id"] != selected_scheme_id:
                    continue
                with st.expander(
                    f'{passage["section"].replace("_", " ").title()} · '
                    f'{passage["passage_id"]}'
                ):
                    st.write(passage["text"])
                    st.caption(
                        f'{text["finder_citation"]}: '
                        f'{passage["source"]["publisher"]} · '
                        f'{passage["source"].get("locator") or ""}'
                    )
                    st.caption(
                        f'{text["finder_review"]}: '
                        f'{passage["review_status"]}'
                    )
                    st.link_button(
                        passage["source"]["publisher"],
                        passage["source"]["url"],
                    )

            selected_is_supported = any(
                passage["scheme_id"] == selected_scheme_id
                and passage.get("eligible_for_mock_flow", False)
                for passage in search_results
            )
            if selected_is_supported:
                if st.button(text["finder_continue"], type="primary"):
                    st.session_state.journey_scheme_id = selected_scheme_id
                    st.session_state.journey_started = True
                    clear_application_state()
                    st.rerun()
            else:
                st.info(text["finder_info_only"])
            candidate_ids = st.session_state.candidate_scheme_ids or [
                candidate for candidate in scheme_names
                if candidate not in st.session_state.unprocessed_candidate_ids
            ]
            profile_description = st.text_area(
                text["household_description"],
                key="multi_household_description",
                help=text["household_description_help"],
                max_chars=1200,
            )
            if st.button(
                text["finder_continue_all"],
                type="primary",
                disabled=(
                    not consent
                    or (
                        st.session_state.interaction_mode == "csc"
                        and not st.session_state.csc_citizen_present
                    )
                ),
            ):
                clear_application_state()
                start_candidate_interview(
                    candidate_ids,
                    profile_description.strip() or None,
                    locale,
                )
                st.rerun()

    st.stop()

# "chat" asks questions (Phase 2). "example" keeps the preset people, which
# are still needed to show the approvable draft until Phase 4.
widow_mode = st.radio(
    text["widow_mode"],
    options=["chat", "example"],
    format_func=lambda value: text[f"mode_{value}"],
    horizontal=True,
    key="widow_mode",
)
if widow_mode == "chat":
    render_interview(
        st.session_state.journey_scheme_id or fixtures.policy.scheme_id,
        text,
        locale,
        can_start=(
            consent
            and (
                st.session_state.interaction_mode == "citizen"
                or st.session_state.csc_citizen_present
            )
        ),
    )
    st.divider()
    st.caption(text["footer"])
    st.stop()

visible_scenarios = provider.visible_scenarios()
scenario_id = st.selectbox(
    text["scenario"],
    options=[scenario.scenario_id for scenario in visible_scenarios],
    format_func=lambda value: localize(
        provider.get_scenario(value).label, locale
    ),
    key="demo_scenario",
)
scenario = provider.get_scenario(scenario_id)
profile = scenario.profile

st.subheader(text["profile"])
profile_columns = st.columns(4)
profile_columns[0].metric(text["age"], profile.age)
profile_columns[1].metric(
    text["widow"], text["yes"] if profile.is_widow else text["no"]
)
profile_columns[2].metric(text["bpl"], text[profile.bpl_status])
profile_columns[3].metric(text["state"], profile.state)
st.caption(
    f'{text["age_as_of"]}: {profile.application_date.isoformat()}'
)

if st.button(
    text["evaluate"],
    type="primary",
    disabled=not consent,
):
    clear_application_state()
    st.session_state.selected_result = scenario.scenario_id
    st.session_state.api_result = None
    st.session_state.api_error = None
    try:
        journey = run_journey(
            JourneyRequest(
                action="evaluate",
                conversation_id=(
                    UUID(st.session_state.conversation_id)
                    if st.session_state.conversation_id
                    else uuid4()
                ),
                scheme_id=fixtures.policy.scheme_id,
                profile={
                    "date_of_birth": (
                        scenario.profile.date_of_birth.isoformat()
                    ),
                    "application_date": (
                        scenario.profile.application_date.isoformat()
                    ),
                    "is_widow": scenario.profile.is_widow,
                    "bpl_card_shown": scenario.profile.bpl_card_shown,
                },
                locale=locale,
                mode=st.session_state.interaction_mode,
                citizen_present=(
                    st.session_state.interaction_mode == "citizen"
                    or st.session_state.csc_citizen_present
                ),
            )
        )
        st.session_state.journey_status = journey.status
        st.session_state.conversation_id = str(journey.conversation_id)
        st.session_state.journey_conversation = journey.conversation
        st.session_state.api_result = (
            journey.eligibility_result.model_dump(mode="json")
            if journey.eligibility_result is not None
            else None
        )
        st.session_state.journey_plan = journey.plan
    except JourneyApiError as error:
        st.session_state.api_error = str(error)

if st.session_state.api_error:
    st.error(f'{text["api_error"]}: {st.session_state.api_error}')

if st.session_state.selected_result and st.session_state.api_result:
    verdict = st.session_state.api_result
    display_result = API_RESULT_TO_UI[verdict["result"]]
    icon, message_kind = RESULT_PRESENTATION[display_result]

    st.divider()
    st.subheader(text["result"])
    show_result_message(
        message_kind,
        f'{icon} {text[display_result]}',
    )
    st.markdown(f'**{text["reason"]}**')
    st.write(verdict["reason"])

    st.markdown(f'**{text["rules"]}**')
    for rule_id in verdict["deciding_rule_ids"]:
        st.code(rule_id, language=None)

    if verdict["missing_fields"]:
        st.warning(
            f'{text["missing"]}: '
            + readable_missing_fields(verdict["missing_fields"], locale)
        )
        st.button(text["human"], disabled=True)

    for evidence in verdict["evidence"]:
        with st.expander(evidence["rule_id"]):
            st.write(evidence["source_text"])
            st.caption(evidence["source_clause_id"])
            st.link_button(text["source"], evidence["source_url"])

    st.subheader(text["policy"])
    st.markdown(f'**{localize(fixtures.policy.scheme_name, locale)}**')
    with st.expander(text["official_clause"], expanded=True):
        st.write(provider.rule_package.source.official_eligibility_text)
        st.caption(
            f'{provider.rule_package.source.publisher} · '
            f'{provider.rule_package.source.collected_at.isoformat()}'
        )
    st.markdown(f'**{text["benefit"]}**')
    st.write(localize(fixtures.policy.benefit_summary, locale))
    st.link_button(
        text["source"],
        str(provider.rule_package.source.source_url),
    )
    if verdict["result"] == "eligible":
        render_application_flow(fixtures.policy.scheme_id, text)

st.divider()
st.caption(text["footer"])

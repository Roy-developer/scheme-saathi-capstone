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
from uuid import UUID, uuid4

import streamlit as st

from src.ui.approval import approval_matches, draft_fingerprint
from src.ui.api_client import (
    JourneyApiError,
    forget_journey,
    get_journey_state,
    correct_journey_answer,
    run_journey,
    send_journey_message,
)
from src.ui.data_provider import FixtureDataProvider
from src.workflow.journey import JourneyRequest, JourneyResponse
from src.workflow.questions import question_for


COPY = {
    "en": {
        "name": "English",
        "title": "Scheme Saathi",
        "subtitle": "Explore a cited welfare-scheme decision journey",
        "banner": "SYNTHETIC DEMONSTRATION — NOT A GOVERNMENT SERVICE",
        "draft": "Mock rules reviewed; fixture implementation awaiting technical checks",
        "consent_title": "Demonstration notice",
        "consent_text": "This prototype uses preset synthetic households. It does not collect your personal information or submit an application.",
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
        "documents": "Required documents are not yet verified from the official source and are intentionally omitted.",
        "prepare": "Prepare synthetic application draft",
        "application": "Synthetic application draft",
        "reference": "Applicant reference",
        "district": "District",
        "declaration": "Declaration",
        "fingerprint": "Draft fingerprint",
        "edit": "Edit draft",
        "save": "Save changes",
        "approve": "Approve this exact draft",
        "reject": "Reject draft",
        "submit": "Submit to mock portal",
        "approved": "This exact draft is approved.",
        "invalidated": "The draft changed, so the earlier approval is no longer valid.",
        "rejected": "The synthetic draft was rejected.",
        "submitted": "Submitted to the mock portal. No government service was contacted.",
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
        "interview_start": "Start questions",
        "interview_restart": "Start again",
        "interview_reply": "Type your answer (yes / no / don't know, a date like 12 March 1981, or your own words)",
        "interview_error": "Could not continue the conversation",
        "widow_mode": "How do you want to check?",
        "mode_chat": "Answer questions",
        "mode_example": "Use an example person",
        "restored": "Your earlier conversation was restored.",
        "footer": "These are development fixtures, not held-out evaluation cases. No language model determines the verdict.",
    },
    "hi": {
        "name": "हिन्दी",
        "title": "स्कीम साथी",
        "subtitle": "उद्धृत कल्याण-योजना निर्णय यात्रा देखें",
        "banner": "कृत्रिम प्रदर्शन — यह सरकारी सेवा नहीं है",
        "draft": "मॉक नियमों की समीक्षा हो चुकी है; फ़िक्स्चर की तकनीकी जाँच बाकी है",
        "consent_title": "प्रदर्शन सूचना",
        "consent_text": "यह प्रोटोटाइप पूर्वनिर्धारित कृत्रिम परिवारों का उपयोग करता है। यह आपकी व्यक्तिगत जानकारी एकत्र नहीं करता और आवेदन जमा नहीं करता।",
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
        "documents": "आवश्यक दस्तावेज़ अभी आधिकारिक स्रोत से सत्यापित नहीं हैं और जानबूझकर शामिल नहीं किए गए हैं।",
        "prepare": "कृत्रिम आवेदन मसौदा तैयार करें",
        "application": "कृत्रिम आवेदन मसौदा",
        "reference": "आवेदक संदर्भ",
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
        "submitted": "मॉक पोर्टल पर जमा किया गया। किसी सरकारी सेवा से संपर्क नहीं किया गया।",
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
        "plan_title": "???? ?? ?????",
        "interview_title": "??? ?????? ?? ???? ???",
        "interview_notice": "???? ?? ??? ??? ?? ???? ????? ??, ?? ???? ??? ?? ?????? ?? ??? ?????? ??? ???? ???????? ????? ???; ???? ???, ???? ?? ???? ???? ? ??????",
        "interview_start": "???? ???? ????",
        "interview_restart": "??? ?? ???? ????",
        "interview_reply": "???? ????? ????? (yes / no / don't know, ?? 12 March 1981 ???? ?????)",
        "interview_error": "?????? ???? ???? ?? ???",
        "widow_mode": "?? ???? ?????? ????? ????",
        "mode_chat": "?????? ?? ???? ???",
        "mode_example": "?????? ??????? ?? ????? ????",
        "restored": "???? ????? ?????? ???? ??? ???",
        "footer": "ये विकास फ़िक्स्चर हैं, सुरक्षित मूल्यांकन मामले नहीं। कोई भाषा मॉडल परिणाम तय नहीं करता।",
    },
    "mr": {
        "name": "मराठी",
        "title": "स्कीम साथी",
        "subtitle": "उद्धृत कल्याण-योजना निर्णय प्रवास पाहा",
        "banner": "कृत्रिम प्रात्यक्षिक — ही सरकारी सेवा नाही",
        "draft": "मॉक नियमांचे पुनरावलोकन झाले; फिक्स्चरची तांत्रिक तपासणी बाकी आहे",
        "consent_title": "प्रात्यक्षिक सूचना",
        "consent_text": "हा नमुना पूर्वनिश्चित कृत्रिम कुटुंबे वापरतो. तो तुमची वैयक्तिक माहिती गोळा करत नाही किंवा अर्ज सादर करत नाही.",
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
        "documents": "आवश्यक कागदपत्रे अद्याप अधिकृत स्रोतावरून सत्यापित केलेली नाहीत आणि जाणीवपूर्वक वगळली आहेत.",
        "prepare": "कृत्रिम अर्जाचा मसुदा तयार करा",
        "application": "कृत्रिम अर्जाचा मसुदा",
        "reference": "अर्जदार संदर्भ",
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
        "submitted": "मॉक पोर्टलवर सादर केले. कोणत्याही सरकारी सेवेशी संपर्क केला नाही.",
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
        "plan_title": "?????? ?????",
        "interview_title": "???? ?????????? ?????? ????",
        "interview_notice": "???? ??? ???? ??? ?????? ???????, ??? ?????????? ?????? ??????. ???? ???????? ?????? ????; ??? ???, ???? ????? ??? ??????? ???? ???.",
        "interview_start": "?????? ???? ???",
        "interview_restart": "?????? ???? ???",
        "interview_reply": "????? ????? ???? (yes / no / don't know, ????? 12 March 1981 ????? ?????)",
        "interview_error": "?????? ???? ???? ????? ??? ????",
        "widow_mode": "???????? ??? ???????? ????",
        "mode_chat": "?????????? ?????? ????",
        "mode_example": "?????? ??????? ?????",
        "restored": "????? ????? ?????? ??? ????.",
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


# Workflow state is kept separate so changing a scenario cannot retain approval.
WORKFLOW_STATE_KEYS = {
    "approved_fingerprint",
    "draft_district",
    "draft_edit_mode",
    "draft_reference",
    "draft_scenario_id",
    "draft_submitted",
    "rejected_draft",
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
    "candidate_scheme_ids",
    "candidate_verdicts",
    "eligibility_results",
    "multi_scheme_mode",
    "plan_change_history",
    "correction_error",
    "journey_history",
    "known_fact_names",
}
DEMO_INPUT_KEYS = {
    "demo_consent",
    "demo_scenario",
    "scheme_query",
    "widow_mode",
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

    for key in (
        "approved_fingerprint",
        "draft_district",
        "draft_edit_mode",
        "draft_reference",
        "draft_scenario_id",
        "draft_submitted",
        "rejected_draft",
    ):
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
    st.session_state.journey_status = None
    st.session_state.candidate_scheme_ids = []
    st.session_state.candidate_verdicts = {}
    st.session_state.eligibility_results = {}
    st.session_state.multi_scheme_mode = False
    st.session_state.plan_change_history = []
    st.session_state.correction_error = None
    st.session_state.journey_history = []
    st.session_state.known_fact_names = []


# One icon per PlanStep.status, so the plan reads like a checklist.
PLAN_STEP_ICONS = {
    "pending": "?",
    "in_progress": "?",
    "done": "?",
    "skipped": "?",
    "failed": "?",
}


def save_journey(journey: JourneyResponse) -> None:
    """Copy one API reply into session_state.

    Streamlit forgets local variables on every rerun, so everything the chat
    needs to redraw itself is stored here: the plan, the history, the open
    question and, at the end, the verdict.
    """

    st.session_state.conversation_id = str(journey.conversation_id)
    st.session_state.journey_plan = journey.plan
    st.session_state.journey_plan_detail = (
        journey.plan_detail.model_dump(mode="json")
        if journey.plan_detail is not None
        else None
    )
    st.session_state.journey_status = journey.status
    st.session_state.journey_question = journey.question
    st.session_state.journey_conversation = journey.conversation
    st.session_state.interview_message = journey.message
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
    st.session_state.known_fact_names = journey.known_fact_names


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


def start_candidate_interview(candidate_ids: list[str]) -> None:
    """Start one shared interview for the schemes found by search."""

    st.session_state.interview_error = None
    try:
        journey = run_journey(
            JourneyRequest(
                action="interview",
                conversation_id=(
                    UUID(st.session_state.conversation_id)
                    if st.session_state.conversation_id
                    else uuid4()
                ),
                candidate_scheme_ids=candidate_ids,
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


def render_candidate_interview(text: dict[str, str]) -> None:
    """Show one shared chat and then a separate result for each scheme."""

    st.subheader(text["multi_interview_title"])
    if st.session_state.interview_error:
        st.error(st.session_state.interview_error)
    render_plan(st.session_state.journey_plan_detail, text)
    if st.session_state.plan_change_history:
        st.markdown(f'**{text["plan_change_history"]}**')
        for change in st.session_state.plan_change_history:
            st.caption(
                f'Plan {change["from_version"]} → '
                f'Plan {change["to_version"]}: {change["reason"]}'
            )
    for event in st.session_state.journey_history:
        title = text[{
            "tool_retry": "history_retry",
            "tool_failed": "history_failed",
            "answer_corrected": "history_corrected",
        }[event["event_type"]]]
        st.caption(f'{title}: {event["reason"]}')
    for turn in st.session_state.journey_conversation:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    if st.session_state.journey_status == "awaiting_answer":
        reply = st.chat_input(text["interview_reply"])
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
    if st.session_state.known_fact_names:
        st.markdown(f'**{text["correction_title"]}**')
        fact_name = st.selectbox(
            text["correction_fact"],
            options=st.session_state.known_fact_names,
            format_func=question_for,
            key="correction_fact_name",
        )
        answer = st.text_input(text["correction_answer"], key="correction_answer_value")
        if st.button(text["correction_submit"]):
            try:
                journey = correct_journey_answer(
                    st.session_state.conversation_id, fact_name, answer
                )
            except JourneyApiError as error:
                st.session_state.correction_error = str(error)
            else:
                save_journey(journey)
                st.session_state.correction_error = None
            st.rerun()
        if st.session_state.correction_error:
            st.error(st.session_state.correction_error)


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
            icon = PLAN_STEP_ICONS.get(step["status"], "?")
            st.markdown(f'{icon} {step["goal"]}')
        if plan_detail.get("replan_reason"):
            st.caption(plan_detail["replan_reason"])


def render_verdict(
    result: dict,
    scheme_id: str,
    text: dict[str, str],
) -> None:
    """Show a rule-engine verdict with its reason and official sources."""

    # Green for eligible, red for not eligible, yellow for "need more".
    if result["result"] == "eligible":
        st.success(f'? {text["eligible"]}')
    elif result["result"] == "not_eligible":
        # PM-KISAN wording reminds the user this is the 2020 mock check.
        st.error(
            "? "
            + text[
                "pmkisan_potential"
                if scheme_id == "PM-KISAN-IN"
                else "not_eligible"
            ]
        )
    else:
        st.warning(f'?? {text["cant_tell"]}')
    st.write(result["reason"])
    # Optional parts only show when the package provides them.
    if result.get("notice"):
        st.warning(result["notice"])
    if result["missing_fields"]:
        st.caption(
            f'{text["missing"]}: {", ".join(result["missing_fields"])}'
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


def start_interview(scheme_id: str) -> None:
    """Ask the API to start a question-by-question check for one scheme."""

    st.session_state.interview_error = None
    try:
        # The same conversation ID is reused, so "forget" deletes all of it.
        journey = run_journey(
            JourneyRequest(
                action="interview",
                conversation_id=(
                    UUID(st.session_state.conversation_id)
                    if st.session_state.conversation_id
                    else uuid4()
                ),
                scheme_id=scheme_id,
            )
        )
    except JourneyApiError as error:
        st.session_state.interview_error = str(error)
    else:
        save_journey(journey)
        st.session_state.interview_scheme_id = scheme_id
        remember_in_url(scheme_id)


def render_interview(
    scheme_id: str,
    text: dict[str, str],
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
    if st.session_state.interview_error:
        st.error(
            f'{text["interview_error"]}: {st.session_state.interview_error}'
        )

    if st.session_state.interview_scheme_id != scheme_id:
        if st.button(
            text["interview_start"], type="primary", disabled=not can_start
        ):
            start_interview(scheme_id)
            st.rerun()
        return

    render_plan(st.session_state.journey_plan_detail, text)
    for turn in st.session_state.journey_conversation:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    if st.session_state.journey_status == "awaiting_answer":
        reply = st.chat_input(text["interview_reply"])
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
    elif st.session_state.interview_message:
        # No verdict, e.g. the scheme has no reviewed rules.
        st.warning(st.session_state.interview_message)
    if st.button(text["interview_restart"]):
        start_interview(scheme_id)
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
st.session_state.setdefault("candidate_scheme_ids", [])
st.session_state.setdefault("candidate_verdicts", {})
st.session_state.setdefault("eligibility_results", {})
st.session_state.setdefault("multi_scheme_mode", False)
st.session_state.setdefault("plan_change_history", [])
st.session_state.setdefault("correction_error", None)
st.session_state.setdefault("journey_history", [])
st.session_state.setdefault("known_fact_names", [])
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
    if candidate_ids and len(candidate_ids) <= 20 or saved_scheme in (
        fixtures.policy.scheme_id, "PM-KISAN-IN"
    ):
        try:
            UUID(saved_conversation)  # ignore a hand-edited, broken ID
            saved = get_journey_state(saved_conversation)
        except (ValueError, JourneyApiError):
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
        try:
            if conversation_id:
                forget_journey(conversation_id)
        except JourneyApiError as error:
            st.session_state.forget_error = str(error)
        else:
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
#   journey_started + PM-KISAN -> PM-KISAN form, then stop
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
        render_candidate_interview(text)
        st.stop()
    elif st.session_state.journey_scheme_id == "PM-KISAN-IN":
        st.subheader(text["pmkisan_title"])
        st.warning(text["pmkisan_notice"])
        # Phase 2: Saathi asks only the questions the rules still need,
        # one at a time, instead of showing a form with every question.
        render_interview("PM-KISAN-IN", text)
        # Stop here so the widow-pension screen below is not drawn.
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
                    )
                )
                st.session_state.scheme_search_results = [
                    passage.model_dump(mode="json")
                    for passage in journey.passages
                ]
                st.session_state.scheme_search_message = journey.message
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
            except JourneyApiError as error:
                st.session_state.scheme_search_error = str(error)

    if st.session_state.scheme_search_error:
        st.error(
            f'{text["finder_error"]}: '
            f'{st.session_state.scheme_search_error}'
        )

    search_results = st.session_state.scheme_search_results
    if search_results is not None:
        if st.session_state.scheme_search_message:
            st.caption(st.session_state.scheme_search_message)
        for event in st.session_state.journey_history:
            title = text[{
                "tool_retry": "history_retry",
                "tool_failed": "history_failed",
                "answer_corrected": "history_corrected",
            }[event["event_type"]]]
            st.caption(f'{title}: {event["reason"]}')
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

            if selected_scheme_id in (
                fixtures.policy.scheme_id,
                "PM-KISAN-IN",
            ):
                if st.button(text["finder_continue"], type="primary"):
                    st.session_state.journey_scheme_id = selected_scheme_id
                    st.session_state.journey_started = True
                    clear_application_state()
                    st.rerun()
            else:
                st.info(text["finder_info_only"])
            candidate_ids = list(scheme_names)
            if st.button(text["finder_continue_all"], type="primary"):
                clear_application_state()
                start_candidate_interview(candidate_ids)
                st.rerun()

    st.stop()

st.subheader(text["consent_title"])
st.info(text["consent_text"])
consent = st.checkbox(text["consent"], key="demo_consent")

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
    render_interview(fixtures.policy.scheme_id, text, can_start=consent)
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
    selected = provider.get_scenario(st.session_state.selected_result)
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
            f'{text["missing"]}: {", ".join(verdict["missing_fields"])}'
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
    st.info(text["documents"])

    if (
        verdict["result"] == "eligible"
        and selected.application_draft is not None
    ):
        draft_template = selected.application_draft
        if st.button(text["prepare"]):
            st.session_state.draft_scenario_id = selected.scenario_id
            st.session_state.draft_reference = (
                draft_template.applicant_reference
            )
            st.session_state.draft_district = draft_template.district
            st.session_state.approved_fingerprint = None
            st.session_state.draft_edit_mode = False
            st.session_state.draft_submitted = False
            st.session_state.rejected_draft = False
            st.rerun()

        if st.session_state.get("draft_scenario_id") == selected.scenario_id:
            st.divider()
            st.subheader(text["application"])

            st.text_input(
                text["reference"],
                key="draft_reference",
                disabled=not st.session_state.draft_edit_mode,
            )
            st.text_input(
                text["district"],
                key="draft_district",
                disabled=not st.session_state.draft_edit_mode,
            )
            st.write(
                {
                    text["age"]: draft_template.age,
                    text["date_of_birth"]: (
                        draft_template.date_of_birth.isoformat()
                    ),
                    text["application_date"]: (
                        draft_template.application_date.isoformat()
                    ),
                    text["widow"]: text["yes"],
                    text["bpl"]: text[draft_template.bpl_status],
                }
            )
            st.markdown(f'**{text["declaration"]}**')
            st.write(localize(draft_template.declaration, locale))

            current_draft = draft_template.model_copy(
                update={
                    "applicant_reference": st.session_state.draft_reference,
                    "district": st.session_state.draft_district,
                }
            )
            current_fingerprint = draft_fingerprint(current_draft)
            st.caption(
                f'{text["fingerprint"]}: '
                f'`{current_fingerprint[:16]}…`'
            )

            if (
                st.session_state.approved_fingerprint is not None
                and not approval_matches(
                    st.session_state.approved_fingerprint,
                    current_draft,
                )
            ):
                # Any edit invalidates approval before mock submission is offered.
                st.session_state.approved_fingerprint = None
                st.session_state.draft_submitted = False
                st.warning(text["invalidated"])

            actions = st.columns(3)
            if not st.session_state.draft_edit_mode:
                if actions[0].button(
                    text["edit"], use_container_width=True
                ):
                    st.session_state.draft_edit_mode = True
                    st.rerun()
            elif actions[0].button(
                text["save"], use_container_width=True
            ):
                st.session_state.draft_edit_mode = False
                st.session_state.approved_fingerprint = None
                st.session_state.draft_submitted = False
                st.rerun()

            if actions[1].button(
                text["approve"],
                use_container_width=True,
                disabled=st.session_state.draft_edit_mode,
            ):
                st.session_state.approved_fingerprint = (
                    current_fingerprint
                )
                st.session_state.rejected_draft = False
                st.session_state.draft_submitted = False
                st.rerun()

            if actions[2].button(
                text["reject"], use_container_width=True
            ):
                st.session_state.approved_fingerprint = None
                st.session_state.rejected_draft = True
                st.session_state.draft_submitted = False
                st.rerun()

            if st.session_state.rejected_draft:
                st.error(text["rejected"])
            elif approval_matches(
                st.session_state.approved_fingerprint,
                current_draft,
            ):
                st.success(text["approved"])
                if st.button(
                    text["submit"],
                    type="primary",
                    disabled=st.session_state.draft_submitted,
                ):
                    st.session_state.draft_submitted = True
                    st.rerun()

            if st.session_state.draft_submitted:
                st.success(text["submitted"])

st.divider()
st.caption(text["footer"])

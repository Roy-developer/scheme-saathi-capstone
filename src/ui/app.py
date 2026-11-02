"""Render the fixture-backed Scheme Saathi Streamlit demonstration."""

import os
from uuid import UUID, uuid4

import streamlit as st

from src.ui.approval import approval_matches, draft_fingerprint
from src.ui.api_client import (
    JourneyApiError,
    forget_journey,
    run_journey,
)
from src.ui.data_provider import FixtureDataProvider
from src.workflow.journey import JourneyRequest


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
        "finder_back": "Choose another scheme",
        "finder_info_only": "This scheme currently has source passages for information only. A reviewed deterministic eligibility rule package is not available, so no eligibility decision will be shown.",
        "finder_citation": "Source citation",
        "finder_review": "Review status",
        "pmkisan_title": "Synthetic PM-KISAN household",
        "pmkisan_notice": "Use fictional household facts only. This mock check follows the official guidelines revised in 2020. It does not check the current landholding cutoff or government records, and it is not an official decision.",
        "pmkisan_land": "Does the farmer family have cultivable land in State/UT records?",
        "pmkisan_institution": "Is the land held by an institution?",
        "pmkisan_office": "Does a family member fall under a listed public-office exclusion?",
        "pmkisan_employee": "Does a family member fall under the specified government-employee exclusion, outside the stated grade exceptions?",
        "pmkisan_pension": "Does a family member receive a qualifying monthly pension of Rs. 10,000 or more?",
        "pmkisan_tax": "Did a family member pay income tax in the last assessment year?",
        "pmkisan_professional": "Is a family member a listed registered professional who is practicing?",
        "pmkisan_nri": "Is this a new beneficiary whose farmer family is NRI?",
        "pmkisan_unknown": "Unknown / Not sure",
        "pmkisan_no": "No",
        "pmkisan_yes": "Yes",
        "pmkisan_submit": "Check eligibility",
        "pmkisan_missing": "Answers still unknown",
        "pmkisan_unresolved": "Not checked in this mock",
        "pmkisan_potential": "Does not meet the 2020 mock criteria",
        "pmkisan_verification": "Check the answers and try again",
        "pmkisan_error": "Could not run PM-KISAN screen",
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
        "finder_back": "दूसरी योजना चुनें",
        "finder_info_only": "इस योजना के स्रोत अंश अभी केवल जानकारी के लिए उपलब्ध हैं। समीक्षा किया हुआ नियतात्मक पात्रता नियम-पैकेज उपलब्ध नहीं है, इसलिए पात्रता का निर्णय नहीं दिखाया जाएगा।",
        "finder_citation": "स्रोत उद्धरण",
        "finder_review": "समीक्षा स्थिति",
        "pmkisan_title": "कृत्रिम PM-KISAN परिवार",
        "pmkisan_notice": "केवल काल्पनिक परिवार की जानकारी दें। यह मॉक जाँच 2020 में संशोधित सरकारी दिशानिर्देशों पर आधारित है। इसमें वर्तमान भूमि-कटऑफ या सरकारी रिकॉर्ड की जाँच नहीं होती, और यह सरकारी निर्णय नहीं है।",
        "pmkisan_land": "क्या किसान परिवार की खेती योग्य भूमि राज्य/केंद्रशासित प्रदेश के रिकॉर्ड में है?",
        "pmkisan_institution": "क्या भूमि किसी संस्था के नाम पर है?",
        "pmkisan_office": "क्या परिवार का कोई सदस्य सूचीबद्ध सार्वजनिक पद की अपवर्जन श्रेणी में आता है?",
        "pmkisan_employee": "क्या परिवार का कोई सदस्य निर्दिष्ट सरकारी-कर्मचारी अपवर्जन में आता है, बताई गई श्रेणी-छूट को छोड़कर?",
        "pmkisan_pension": "क्या परिवार के किसी सदस्य को प्रति माह 10,000 रुपये या अधिक की संबंधित पेंशन मिलती है?",
        "pmkisan_tax": "क्या परिवार के किसी सदस्य ने पिछले आकलन वर्ष में आयकर दिया?",
        "pmkisan_professional": "क्या परिवार का कोई सदस्य सूचीबद्ध पंजीकृत पेशेवर है और उस पेशे में काम करता है?",
        "pmkisan_nri": "क्या यह नया लाभार्थी है और किसान परिवार NRI है?",
        "pmkisan_unknown": "अज्ञात / निश्चित नहीं",
        "pmkisan_no": "नहीं",
        "pmkisan_yes": "हाँ",
        "pmkisan_submit": "पात्रता जाँचें",
        "pmkisan_missing": "अज्ञात उत्तर",
        "pmkisan_unresolved": "इस मॉक में जाँच नहीं हुई",
        "pmkisan_potential": "2020 के मॉक मानदंड पूरे नहीं हुए",
        "pmkisan_verification": "उत्तर जाँचकर फिर प्रयास करें",
        "pmkisan_error": "PM-KISAN जाँच नहीं हो सकी",
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
        "finder_back": "दुसरी योजना निवडा",
        "finder_info_only": "या योजनेचे स्रोत उतारे सध्या फक्त माहितीसाठी उपलब्ध आहेत. पुनरावलोकन केलेले निर्धारक पात्रता नियम-पॅकेज उपलब्ध नसल्यामुळे पात्रतेचा निर्णय दाखवला जाणार नाही.",
        "finder_citation": "स्रोत उद्धरण",
        "finder_review": "पुनरावलोकन स्थिती",
        "pmkisan_title": "कृत्रिम PM-KISAN कुटुंब",
        "pmkisan_notice": "फक्त काल्पनिक कुटुंबाची माहिती द्या. ही मॉक तपासणी 2020 मध्ये सुधारित अधिकृत मार्गदर्शक तत्त्वांवर आधारित आहे. यात सध्याची जमीन-मर्यादा किंवा सरकारी नोंदी तपासल्या जात नाहीत; हा सरकारी निर्णय नाही.",
        "pmkisan_land": "शेतकरी कुटुंबाची लागवडीयोग्य जमीन राज्य/केंद्रशासित प्रदेशाच्या नोंदीत आहे का?",
        "pmkisan_institution": "जमीन एखाद्या संस्थेच्या नावावर आहे का?",
        "pmkisan_office": "कुटुंबातील सदस्य सूचीबद्ध सार्वजनिक-पद अपात्रता श्रेणीत येतो का?",
        "pmkisan_employee": "कुटुंबातील सदस्य निर्दिष्ट सरकारी-कर्मचारी अपात्रतेत येतो का, नमूद श्रेणी-सवलती वगळून?",
        "pmkisan_pension": "कुटुंबातील सदस्याला दरमहा 10,000 रुपये किंवा अधिक संबंधित पेन्शन मिळते का?",
        "pmkisan_tax": "कुटुंबातील सदस्याने मागील निर्धारण वर्षात आयकर भरला का?",
        "pmkisan_professional": "कुटुंबातील सदस्य सूचीबद्ध नोंदणीकृत व्यावसायिक असून त्या व्यवसायात कार्यरत आहे का?",
        "pmkisan_nri": "हा नवीन लाभार्थी असून शेतकरी कुटुंब NRI आहे का?",
        "pmkisan_unknown": "अज्ञात / खात्री नाही",
        "pmkisan_no": "नाही",
        "pmkisan_yes": "होय",
        "pmkisan_submit": "पात्रता तपासा",
        "pmkisan_missing": "अज्ञात उत्तरे",
        "pmkisan_unresolved": "या मॉकमध्ये तपासले नाही",
        "pmkisan_potential": "2020 च्या मॉक निकषांची पूर्तता होत नाही",
        "pmkisan_verification": "उत्तरे तपासून पुन्हा प्रयत्न करा",
        "pmkisan_error": "PM-KISAN तपासणी करता आली नाही",
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
    "pmkisan_eligibility_result",
    "pmkisan_eligibility_error",
    "selected_result",
    "journey_started",
    "journey_scheme_id",
    "conversation_id",
    "journey_plan",
    "journey_status",
    "journey_conversation",
    "scheme_search_error",
    "scheme_search_results",
    "selected_search_scheme",
    "pmkisan_eligibility_result",
    "pmkisan_eligibility_error",
}
DEMO_INPUT_KEYS = {
    "demo_consent",
    "demo_scenario",
    "scheme_query",
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
st.session_state.setdefault("scheme_search_error", None)
st.session_state.setdefault("pmkisan_eligibility_result", None)
st.session_state.setdefault("pmkisan_eligibility_error", None)
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
            st.session_state.show_forgotten = True
            st.session_state.forget_error = None
            st.rerun()

if st.session_state.forget_error:
    st.error(f'{text["forget_error"]}: {st.session_state.forget_error}')
if st.session_state.pop("show_forgotten", False):
    st.success(text["forgotten"])

if st.session_state.journey_started:
    st.caption(
        f'{text["finder_choose"]}: {st.session_state.journey_scheme_id}'
    )
    if st.button(text["finder_back"]):
        st.session_state.journey_started = False
        st.session_state.journey_scheme_id = None
        st.session_state.conversation_id = None
        clear_application_state()
        st.rerun()
    elif st.session_state.journey_scheme_id == "PM-KISAN-IN":
        st.subheader(text["pmkisan_title"])
        st.warning(text["pmkisan_notice"])
        answer_labels = (
            ("landholding_family_in_state_records", "pmkisan_land"),
            ("institutional_landholder", "pmkisan_institution"),
            ("listed_public_office_member", "pmkisan_office"),
            ("excluded_government_employee_member", "pmkisan_employee"),
            (
                "pension_at_least_10000_excluding_stated_grades",
                "pmkisan_pension",
            ),
            ("income_tax_paid_last_assessment_year", "pmkisan_tax"),
            (
                "registered_practicing_professional_member",
                "pmkisan_professional",
            ),
            ("nri_new_beneficiary", "pmkisan_nri"),
        )
        with st.form("pmkisan_eligibility_form"):
            answers = {}
            choices = [
                text["pmkisan_unknown"],
                text["pmkisan_no"],
                text["pmkisan_yes"],
            ]
            for field_name, label_key in answer_labels:
                answer = st.selectbox(
                    text[label_key],
                    options=choices,
                    key=f"pmkisan_{field_name}",
                )
                answers[field_name] = {
                    text["pmkisan_unknown"]: None,
                    text["pmkisan_no"]: False,
                    text["pmkisan_yes"]: True,
                }[answer]
            submitted = st.form_submit_button(
                text["pmkisan_submit"],
                type="primary",
            )
        if submitted:
            st.session_state.pmkisan_eligibility_result = None
            st.session_state.pmkisan_eligibility_error = None
            try:
                # Same path as widow pension: journey graph -> MCP rule engine.
                journey = run_journey(
                    JourneyRequest(
                        action="evaluate",
                        conversation_id=(
                            UUID(st.session_state.conversation_id)
                            if st.session_state.conversation_id
                            else uuid4()
                        ),
                        scheme_id="PM-KISAN-IN",
                        profile=answers,
                    )
                )
                st.session_state.conversation_id = str(
                    journey.conversation_id
                )
                st.session_state.journey_plan = journey.plan
                st.session_state.journey_conversation = journey.conversation
                if journey.eligibility_result is None:
                    st.session_state.pmkisan_eligibility_error = (
                        journey.message
                    )
                else:
                    st.session_state.pmkisan_eligibility_result = (
                        journey.eligibility_result.model_dump(mode="json")
                    )
            except JourneyApiError as error:
                st.session_state.pmkisan_eligibility_error = str(error)

        if st.session_state.pmkisan_eligibility_error:
            st.error(
                f'{text["pmkisan_error"]}: '
                f'{st.session_state.pmkisan_eligibility_error}'
            )

        result = st.session_state.pmkisan_eligibility_result
        if result:
            if result["result"] == "eligible":
                st.success(text["eligible"])
            elif result["result"] == "not_eligible":
                st.error(text["pmkisan_potential"])
            else:
                st.warning(text["pmkisan_verification"])
            st.write(result["reason"])
            if result["notice"]:
                st.warning(result["notice"])
            if result["missing_fields"]:
                st.caption(
                    f'{text["pmkisan_missing"]}: '
                    f'{", ".join(result["missing_fields"])}'
                )
            if result["unresolved_checks"]:
                st.caption(
                    f'{text["pmkisan_unresolved"]}: '
                    f'{", ".join(result["unresolved_checks"])}'
                )
            for evidence in result["evidence"]:
                with st.expander(evidence["rule_id"]):
                    st.write(evidence["source_text"])
                    st.caption(
                        evidence["source_location"]
                        or evidence["source_clause_id"]
                    )
                    st.link_button(
                        text["source"],
                        evidence["source_url"],
                    )
        st.stop()
else:
    st.subheader(text["finder_title"])
    st.caption(text["finder_help"])
    query = st.text_input(text["finder_query"], key="scheme_query")
    if st.button(text["finder_submit"]):
        st.session_state.scheme_search_results = None
        st.session_state.scheme_search_error = None
        st.session_state.pmkisan_eligibility_result = None
        st.session_state.pmkisan_eligibility_error = None
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

    st.stop()

st.subheader(text["consent_title"])
st.info(text["consent_text"])
consent = st.checkbox(text["consent"], key="demo_consent")

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

import os

import streamlit as st

from src.ui.approval import approval_matches, draft_fingerprint
from src.ui.data_provider import FixtureDataProvider


COPY = {
    "en": {
        "name": "English",
        "title": "Scheme Saathi",
        "subtitle": "Explore a cited welfare-scheme decision journey",
        "banner": "SYNTHETIC DEMONSTRATION — NOT A GOVERNMENT SERVICE",
        "draft": "Policy interpretation awaiting team review",
        "consent_title": "Demonstration notice",
        "consent_text": "This prototype uses preset synthetic households. It does not collect your personal information or submit an application.",
        "consent": "I understand and want to view the demonstration.",
        "mode": "Demonstration perspective",
        "citizen": "Citizen",
        "csc": "CSC-assisted",
        "scenario": "Choose a synthetic development scenario",
        "profile": "Synthetic household profile",
        "age": "Age",
        "widow": "Widow status",
        "bpl": "BPL status",
        "state": "State",
        "yes": "Confirmed widow",
        "no": "Not widowed",
        "confirmed": "Confirmed BPL",
        "not_confirmed": "Confirmed not BPL",
        "unknown": "Unknown",
        "evaluate": "View expected fixture result",
        "result": "Expected development result",
        "eligible": "Appears eligible",
        "not_eligible": "Does not appear eligible",
        "cant_tell": "Cannot determine",
        "reason": "Why this result was assigned",
        "rules": "Deciding reviewed-draft rules",
        "missing": "Information still needed",
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
        "footer": "These are development fixtures, not held-out evaluation cases. No language model determines the verdict.",
    },
    "hi": {
        "name": "हिन्दी",
        "title": "स्कीम साथी",
        "subtitle": "उद्धृत कल्याण-योजना निर्णय यात्रा देखें",
        "banner": "कृत्रिम प्रदर्शन — यह सरकारी सेवा नहीं है",
        "draft": "नीति की व्याख्या टीम की समीक्षा की प्रतीक्षा में है",
        "consent_title": "प्रदर्शन सूचना",
        "consent_text": "यह प्रोटोटाइप पूर्वनिर्धारित कृत्रिम परिवारों का उपयोग करता है। यह आपकी व्यक्तिगत जानकारी एकत्र नहीं करता और आवेदन जमा नहीं करता।",
        "consent": "मैं समझता/समझती हूँ और प्रदर्शन देखना चाहता/चाहती हूँ।",
        "mode": "प्रदर्शन दृष्टिकोण",
        "citizen": "नागरिक",
        "csc": "CSC सहायता",
        "scenario": "कृत्रिम विकास उदाहरण चुनें",
        "profile": "कृत्रिम परिवार प्रोफ़ाइल",
        "age": "आयु",
        "widow": "विधवा स्थिति",
        "bpl": "BPL स्थिति",
        "state": "राज्य",
        "yes": "विधवा की पुष्टि",
        "no": "विधवा नहीं",
        "confirmed": "BPL की पुष्टि",
        "not_confirmed": "BPL नहीं होने की पुष्टि",
        "unknown": "अज्ञात",
        "evaluate": "अपेक्षित फ़िक्स्चर परिणाम देखें",
        "result": "अपेक्षित विकास परिणाम",
        "eligible": "पात्र प्रतीत होते हैं",
        "not_eligible": "पात्र प्रतीत नहीं होते",
        "cant_tell": "निर्णय नहीं किया जा सकता",
        "reason": "यह परिणाम क्यों दिया गया",
        "rules": "निर्णायक समीक्षा-मसौदा नियम",
        "missing": "अभी आवश्यक जानकारी",
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
        "footer": "ये विकास फ़िक्स्चर हैं, सुरक्षित मूल्यांकन मामले नहीं। कोई भाषा मॉडल परिणाम तय नहीं करता।",
    },
    "mr": {
        "name": "मराठी",
        "title": "स्कीम साथी",
        "subtitle": "उद्धृत कल्याण-योजना निर्णय प्रवास पाहा",
        "banner": "कृत्रिम प्रात्यक्षिक — ही सरकारी सेवा नाही",
        "draft": "धोरणाच्या अर्थाला टीमच्या पुनरावलोकनाची प्रतीक्षा आहे",
        "consent_title": "प्रात्यक्षिक सूचना",
        "consent_text": "हा नमुना पूर्वनिश्चित कृत्रिम कुटुंबे वापरतो. तो तुमची वैयक्तिक माहिती गोळा करत नाही किंवा अर्ज सादर करत नाही.",
        "consent": "मला समजले आहे आणि मला प्रात्यक्षिक पाहायचे आहे.",
        "mode": "प्रात्यक्षिकाचा दृष्टिकोन",
        "citizen": "नागरिक",
        "csc": "CSC सहाय्य",
        "scenario": "कृत्रिम विकास उदाहरण निवडा",
        "profile": "कृत्रिम कुटुंब प्रोफाइल",
        "age": "वय",
        "widow": "विधवा स्थिती",
        "bpl": "BPL स्थिती",
        "state": "राज्य",
        "yes": "विधवा असल्याची पुष्टी",
        "no": "विधवा नाही",
        "confirmed": "BPL ची पुष्टी",
        "not_confirmed": "BPL नसल्याची पुष्टी",
        "unknown": "माहित नाही",
        "evaluate": "अपेक्षित फिक्स्चर निकाल पाहा",
        "result": "अपेक्षित विकास निकाल",
        "eligible": "पात्र असल्याचे दिसते",
        "not_eligible": "पात्र असल्याचे दिसत नाही",
        "cant_tell": "निर्णय देता येत नाही",
        "reason": "हा निकाल का देण्यात आला",
        "rules": "निर्णायक पुनरावलोकन-मसुदा नियम",
        "missing": "अजून आवश्यक माहिती",
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
        "footer": "ही विकास फिक्स्चर आहेत, सुरक्षित मूल्यमापन प्रकरणे नाहीत. कोणतेही भाषा मॉडेल निकाल ठरवत नाही.",
    },
}

RESULT_PRESENTATION = {
    "eligible": ("✅", "success"),
    "not_eligible": ("⛔", "error"),
    "cant_tell": ("⚠️", "warning"),
}


def localize(value: object, locale: str) -> str:
    return getattr(value, locale)


def show_result_message(kind: str, message: str) -> None:
    getattr(st, kind)(message)


WORKFLOW_STATE_KEYS = {
    "approved_fingerprint",
    "draft_district",
    "draft_edit_mode",
    "draft_reference",
    "draft_scenario_id",
    "draft_submitted",
    "rejected_draft",
    "selected_result",
}
DEMO_INPUT_KEYS = {"demo_consent", "demo_scenario"}


def clear_workflow_state(*, include_inputs: bool = False) -> None:
    keys = (
        WORKFLOW_STATE_KEYS | DEMO_INPUT_KEYS
        if include_inputs
        else WORKFLOW_STATE_KEYS
    )
    for key in keys:
        st.session_state.pop(key, None)


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
st.session_state.setdefault("draft_scenario_id", None)
st.session_state.setdefault("approved_fingerprint", None)
st.session_state.setdefault("draft_edit_mode", False)
st.session_state.setdefault("draft_submitted", False)
st.session_state.setdefault("rejected_draft", False)

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
        clear_workflow_state(include_inputs=True)
        st.session_state.show_forgotten = True
        st.rerun()

if st.session_state.pop("show_forgotten", False):
    st.success(text["forgotten"])

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

if st.button(
    text["evaluate"],
    type="primary",
    disabled=not consent,
):
    clear_workflow_state()
    st.session_state.selected_result = scenario.scenario_id

if st.session_state.selected_result:
    selected = provider.get_scenario(st.session_state.selected_result)
    verdict = selected.expected_verdict
    icon, message_kind = RESULT_PRESENTATION[verdict.result]

    st.divider()
    st.subheader(text["result"])
    show_result_message(
        message_kind,
        f'{icon} {text[verdict.result]}',
    )
    st.markdown(f'**{text["reason"]}**')
    st.write(localize(verdict.reason, locale))

    st.markdown(f'**{text["rules"]}**')
    for rule_id in verdict.deciding_rule_ids:
        st.code(rule_id, language=None)

    if verdict.missing_fields:
        st.warning(
            f'{text["missing"]}: {", ".join(verdict.missing_fields)}'
        )
        st.button(text["human"], disabled=True)

    st.subheader(text["policy"])
    st.markdown(f'**{localize(fixtures.policy.scheme_name, locale)}**')
    with st.expander(text["official_clause"], expanded=True):
        st.write(fixtures.policy.source.official_eligibility_text)
        st.caption(
            f'{fixtures.policy.source.publisher} · '
            f'{fixtures.policy.source.collected_at.isoformat()}'
        )
    st.markdown(f'**{text["benefit"]}**')
    st.write(localize(fixtures.policy.benefit_summary, locale))
    st.link_button(
        text["source"],
        str(fixtures.policy.source.source_url),
    )
    st.info(text["documents"])

    if verdict.result == "eligible" and selected.application_draft is not None:
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

        if st.session_state.draft_scenario_id == selected.scenario_id:
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

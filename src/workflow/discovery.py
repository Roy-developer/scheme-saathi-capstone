"""Bounded retrieval hints from confirmed facts, without eligibility inference."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from src.rules.models import HouseholdProfile

MAX_DISCOVERY_CALLS = 4
MAX_CANDIDATES = 20
DiscoveryCode = Literal[
    "candidates_added", "search_completed", "tool_error", "budget_exhausted",
    "candidate_limit", "correction_invalidated", "tool_retry", "scam_screened",
]
RELEVANT_FACT_TERMS = {
    "is_widow": "widow pension",
    "landholding_family_in_state_records": "farmer family landholding",
}

class DiscoveryInput(BaseModel):
    """Supported search arguments; absent state or gender is never inferred."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    language: str
    limit: int = MAX_CANDIDATES


class DiscoveryEvent(BaseModel):
    """Metadata-only account of a bounded search and its processing coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DiscoveryCode
    search_calls: int
    candidate_ids: list[str] = Field(default_factory=list)
    unprocessed_candidate_ids: list[str] = Field(default_factory=list)


DISCOVERY_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "candidates_added": "Confirmed facts added retrieved candidates. Only reviewed rules decide eligibility.",
        "search_completed": "Bounded search finished. It may miss relevant schemes.",
        "tool_error": "A check or search could not finish. No decision was invented. Retry later or ask a CSC operator for help.",
        "tool_retry": "Discovery failed; retrying once within the same conversation budget.",
        "budget_exhausted": "The conversation's search limit is reached. Some schemes may remain unchecked; ask a CSC operator for help.",
        "allowance_used": "This conversation has used its allowance of checks. No decision was invented. Choose \"Forget my demonstration data\" to start a new conversation, or ask a CSC operator for help.",
        "candidate_limit": "Only 20 candidates can be checked. These additional candidates were not checked:",
        "correction_invalidated": "Answers changed. Unsubmitted drafts and their approvals are stale; review and approve a fresh draft.",
        "scam_screened": (
            "Saathi never asks for a processing fee, OTP, QR payment, or a personal "
            "WhatsApp/UPI message for scheme approval. That channel was ignored; "
            "continue with the interview question only."
        ),
        "stale_draft": "This draft is stale and cannot be approved or submitted. Prepare and personally approve a fresh draft.",
        "corrected": "Answer corrected. Rechecking scheme rules.",
        "checks_finished": "Candidate checks finished. Review each scheme's result.",
        "checks_partial": "Some candidates could not be checked. No eligibility decision was made for them; ask a CSC operator for help.",
        "eligible": "This scheme meets the current mock rules.",
        "not_eligible": "The mock rules ruled this scheme out; its questions stop.",
        "need_more_information": "The rule engine needs more confirmed information.",
        "invalid_input": "Review the invalid answers before checking again.",
        "information_only": "No reviewed rule package is available. Information only, not an eligibility decision.",
    },
    "hi": {
        "candidates_added": "पुष्टि किए तथ्यों से खोज में नई योजनाएँ मिलीं। पात्रता केवल समीक्षा किए नियम तय करते हैं।",
        "search_completed": "सीमित खोज पूरी हुई। कुछ उपयोगी योजनाएँ छूट सकती हैं।",
        "tool_error": "जाँच या खोज पूरी नहीं हुई। कोई निर्णय नहीं गढ़ा गया। बाद में प्रयास करें या CSC ऑपरेटर से सहायता लें।",
        "tool_retry": "खोज विफल हुई; इसी बातचीत की सीमा में एक बार फिर प्रयास हो रहा है।",
        "budget_exhausted": "इस बातचीत की खोज सीमा पूरी हुई। कुछ योजनाएँ बिना जाँच रह सकती हैं; CSC ऑपरेटर से सहायता लें।",
        "allowance_used": "इस बातचीत में जाँच की तय सीमा पूरी हो गई। कोई निर्णय नहीं गढ़ा गया। नई बातचीत शुरू करने के लिए \"मेरा प्रदर्शन डेटा भूलें\" चुनें, या CSC ऑपरेटर से सहायता लें।",
        "candidate_limit": "केवल 20 योजनाओं की जाँच हो सकती है। इन अतिरिक्त योजनाओं की जाँच नहीं हुई:",
        "correction_invalidated": "उत्तर बदले हैं। बिना जमा किए मसौदे और अनुमोदन पुराने हैं; नया मसौदा देखकर फिर अनुमोदन करें।",
        "scam_screened": (
            "साथी कभी प्रोसेसिंग शुल्क, OTP, QR भुगतान, या व्यक्तिगत WhatsApp/UPI पर "
            "योजना मंजूरी के लिए संदेश नहीं माँगता। उस चैनल को अनदेखा किया गया; केवल "
            "साक्षात्कार के प्रश्न पर जारी रखें।"
        ),
        "stale_draft": "यह मसौदा पुराना है; इसका अनुमोदन या जमा नहीं हो सकता। नया मसौदा बनाकर स्वयं अनुमोदन करें।",
        "corrected": "उत्तर सुधारा गया। योजना के नियम फिर जाँचे जा रहे हैं।",
        "checks_finished": "योजनाओं की जाँच पूरी हुई। हर योजना का परिणाम देखें।",
        "checks_partial": "कुछ योजनाओं की जाँच नहीं हो सकी। उनके लिए पात्रता निर्णय नहीं हुआ; CSC ऑपरेटर से सहायता लें।",
        "eligible": "यह योजना वर्तमान नमूना नियमों के अनुसार पात्र है।",
        "not_eligible": "नमूना नियमों से यह योजना अपात्र है; इसके प्रश्न रोक दिए गए।",
        "need_more_information": "नियम इंजन को और पुष्टि की गई जानकारी चाहिए।",
        "invalid_input": "दोबारा जाँच से पहले गलत उत्तर सुधारें।",
        "information_only": "समीक्षा किया नियम पैकेज नहीं है। केवल जानकारी है, पात्रता निर्णय नहीं।",
    },
    "mr": {
        "candidates_added": "पुष्टी केलेल्या तथ्यांमुळे शोधात नवीन योजना मिळाल्या. पात्रता फक्त पुनरावलोकित नियम ठरवतात.",
        "search_completed": "मर्यादित शोध पूर्ण झाला. काही संबंधित योजना सुटू शकतात.",
        "tool_error": "तपासणी किंवा शोध पूर्ण झाला नाही. कोणताही निकाल बनवला नाही. नंतर प्रयत्न करा किंवा CSC ऑपरेटरची मदत घ्या.",
        "tool_retry": "शोध अयशस्वी झाला; याच संभाषणाच्या मर्यादेत एकदा पुन्हा प्रयत्न करत आहोत.",
        "budget_exhausted": "या संभाषणाची शोध मर्यादा संपली. काही योजना न तपासलेल्या राहू शकतात; CSC ऑपरेटरची मदत घ्या.",
        "allowance_used": "या संभाषणातील तपासण्यांची मर्यादा संपली. कोणताही निकाल बनवला नाही. नवीन संभाषण सुरू करण्यासाठी \"माझा प्रात्यक्षिक डेटा विसरा\" निवडा, किंवा CSC ऑपरेटरची मदत घ्या.",
        "candidate_limit": "फक्त 20 योजना तपासता येतात. या अतिरिक्त योजना तपासलेल्या नाहीत:",
        "correction_invalidated": "उत्तरे बदलली आहेत. न सादर केलेले मसुदे आणि मंजुरी कालबाह्य आहेत; नवीन मसुदा पाहून पुन्हा मंजुरी द्या.",
        "scam_screened": (
            "साथी कधीही प्रोसेसिंग फी, OTP, QR पेमेंट, किंवा वैयक्तिक WhatsApp/UPI वर "
            "योजना मंजुरीसाठी संदेश मागत नाही. तो चॅनेल दुर्लक्षित केला; फक्त मुलाखतीच्या "
            "प्रश्नावर सुरू ठेवा."
        ),
        "stale_draft": "हा मसुदा कालबाह्य आहे; मंजुरी किंवा सादर करता येणार नाही. नवीन मसुदा तयार करून स्वतः मंजुरी द्या.",
        "corrected": "उत्तर दुरुस्त केले. योजनेचे नियम पुन्हा तपासत आहोत.",
        "checks_finished": "योजनांची तपासणी पूर्ण झाली. प्रत्येक योजनेचा निकाल पाहा.",
        "checks_partial": "काही योजना तपासता आल्या नाहीत. त्यांचा पात्रता निर्णय झालेला नाही; CSC ऑपरेटरची मदत घ्या.",
        "eligible": "ही योजना सध्याच्या नमुना नियमांनुसार पात्र आहे.",
        "not_eligible": "नमुना नियमांनुसार ही योजना अपात्र आहे; तिचे प्रश्न थांबले.",
        "need_more_information": "नियम इंजिनला आणखी पुष्टी केलेली माहिती हवी.",
        "invalid_input": "पुन्हा तपासण्याआधी चुकीची उत्तरे दुरुस्त करा.",
        "information_only": "पुनरावलोकित नियम पॅकेज नाही. फक्त माहिती आहे, पात्रतेचा निर्णय नाही.",
    },
}


def discovery_message(code: str, locale: str) -> str:
    """Translate only code-owned status messages, never retrieved instructions."""

    return DISCOVERY_MESSAGES[locale].get(code, DISCOVERY_MESSAGES[locale]["tool_error"])


def discovery_input(profile: HouseholdProfile, locale: str) -> DiscoveryInput:
    """Use confirmed category/age hints and the explicitly selected UI language.

    The current profile has no state or gender, and retrieval supports neither
    an age nor a gender filter. Do not invent these filters from widow status.
    """

    terms = discovery_query(profile)
    if terms and profile.age is not None:
        terms += f" age {profile.age}"
    return DiscoveryInput(query=terms, language=locale)


def discovery_query(profile: HouseholdProfile) -> str:
    """Use only confirmed positive facts; an unknown fact never becomes a filter."""

    return " ".join(
        term for fact, term in RELEVANT_FACT_TERMS.items()
        if getattr(profile, fact) is True
    )


def discovery_signature(profile: HouseholdProfile) -> str:
    """Represent changes including corrections to false or unknown, without PII."""

    return "|".join([
        *(f"{fact}:{getattr(profile, fact)}" for fact in RELEVANT_FACT_TERMS),
        f"age:{profile.age}",
    ])


def merge_candidates(existing: list[str], retrieved: list[str]) -> tuple[list[str], list[str]]:
    """Keep stable distinct IDs and explicitly report every excess candidate."""

    distinct = list(dict.fromkeys([*existing, *retrieved]))
    return distinct[:MAX_CANDIDATES], distinct[MAX_CANDIDATES:]

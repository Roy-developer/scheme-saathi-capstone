"""Isolated, non-authoritative E4 LLM eligibility arm.

Compares an LLM *proposal* (from package source text + known facts) to the
rule-engine verdict and to persona expected labels. Proposals are never
returned as live verdicts, never written to stores, and never change the
rule result.

Optional multilingual mode asks the same case in en / hi / mr (instruction
language only; structured result enum stays English) and records
``verdict_agreement_hi_mr_en``.

Held-out personas stay out of scope unless the caller opts in through the
controlled evaluate script (``allow_held_out=True`` on the persona loader).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from eval.harness.runner import load_persona_evaluation_set, persona_input
from src.api.eligibility import evaluate_mock_eligibility
from src.rules.data_provider import RulePackageProvider
from src.rules.facts import HouseholdProfile
from src.rules.models import RulePackage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_PERSONAS = PROJECT_ROOT / "eval" / "development" / "personas_v1.json"

EligibilityResult = Literal["eligible", "not_eligible", "need_more_information"]
VALID_RESULTS = frozenset({"eligible", "not_eligible", "need_more_information"})
LOCALES = ("en", "hi", "mr")

NON_AUTHORITATIVE_NOTICE = (
    "evaluation-only, non-authoritative: LLM proposals are never written to "
    "live state and never replace the rule-engine verdict"
)

SYSTEM_PROMPTS: dict[str, str] = {
    "en": (
        "You are an evaluation-only eligibility proposer for Scheme Saathi. "
        "Given scheme source text and known applicant facts, propose one result: "
        "eligible, not_eligible, or need_more_information. "
        "This proposal is never a live verdict. Reply with structured fields only. "
        "The result field must use those English enum values."
    ),
    "hi": (
        "आप Scheme Saathi के लिए केवल मूल्यांकन हेतु पात्रता प्रस्तावक हैं। "
        "योजना के स्रोत पाठ और ज्ञात तथ्य देखकर एक परिणाम चुनें: "
        "eligible, not_eligible, या need_more_information। "
        "यह प्रस्ताव कभी भी लाइव निर्णय नहीं है। केवल संरचित फ़ील्ड दें। "
        "result फ़ील्ड में अंग्रेज़ी enum मान ही लिखें।"
    ),
    "mr": (
        "तुम्ही Scheme Saathi साठी फक्त मूल्यमापनासाठी पात्रता प्रस्तावक आहात. "
        "योजनेचा स्रोत मजकूर आणि ज्ञात तथ्ये पाहून एक निकाल निवडा: "
        "eligible, not_eligible, किंवा need_more_information. "
        "हा प्रस्ताव कधीही थेट निकाल नाही. फक्त संरचित फील्ड द्या. "
        "result फील्डमध्ये इंग्रजी enum मूल्येच लिहा."
    ),
}

Proposer = Callable[[Mapping[str, Any]], Awaitable[str] | str]


class EligibilityProposal(BaseModel):
    """Structured LLM eligibility proposal (never authoritative)."""

    model_config = ConfigDict(extra="forbid")

    result: EligibilityResult = Field(
        description="Proposed eligibility outcome; never a live verdict.",
    )


def package_source_excerpt(package: RulePackage, *, max_chars: int = 6000) -> str:
    """Join unique rule source_text lines for the LLM-from-text arm."""

    lines: list[str] = []
    for rule in package.rules:
        text = (rule.source_text or "").strip()
        if text and text not in lines:
            lines.append(text)
    joined = "\n".join(lines) if lines else f"(no source_text on package {package.scheme_id})"
    if len(joined) > max_chars:
        return joined[: max_chars - 20] + "\n…[truncated]"
    return joined


def known_facts_for_prompt(profile: HouseholdProfile, registry: Any) -> dict[str, Any]:
    """Serialize known facts only (unknowns omitted)."""

    out: dict[str, Any] = {}
    for fact_id, state in sorted(profile.facts.items()):
        if state.status != "known":
            continue
        value = state.value
        out[fact_id] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def build_llm_request(
    *,
    scheme_id: str,
    package: RulePackage,
    profile: HouseholdProfile,
    registry: Any,
    locale: str = "en",
) -> dict[str, Any]:
    return {
        "scheme_id": scheme_id,
        "locale": locale,
        "scheme_source_text": package_source_excerpt(package),
        "known_facts": known_facts_for_prompt(profile, registry),
        "allowed_results": sorted(VALID_RESULTS),
        "non_authoritative": True,
    }


def _normalize_result(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().lower().replace(" ", "_")
    aliases = {
        "eligible": "eligible",
        "not_eligible": "not_eligible",
        "noteligible": "not_eligible",
        "ineligible": "not_eligible",
        "need_more_information": "need_more_information",
        "needmoreinformation": "need_more_information",
        "unknown": "need_more_information",
    }
    return aliases.get(text)


def _is_transient_provider_error(error: BaseException) -> bool:
    name = type(error).__name__.lower()
    text = str(error).lower()
    markers = (
        "ratelimit",
        "rate limit",
        "429",
        "free-models-per-min",
        "timeout",
        "timed out",
        "connecttimeout",
        "apitimeouterror",
        "openai timeouterror",
        "503",
        "502",
        "overloaded",
    )
    return any(marker in name or marker in text for marker in markers)


class UsageRecorder(BaseCallbackHandler):
    """Accumulate provider token usage without requiring include_raw structured output."""

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.metered_calls = 0

    def on_llm_end(self, response: Any, **_: Any) -> None:
        self.calls += 1
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        generations = getattr(response, "generations", None) or []
        um: dict[str, Any] = {}
        if generations:
            message = getattr(generations[0][0], "message", None)
            um = getattr(message, "usage_metadata", None) or {}
        inp = usage.get("prompt_tokens") or usage.get("input_tokens") or um.get("input_tokens")
        out = (
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or um.get("output_tokens")
        )
        if inp is None and out is None:
            return
        self.metered_calls += 1
        self.input_tokens += int(inp or 0)
        self.output_tokens += int(out or 0)


def _usage_from_raw(raw: Any) -> tuple[int | None, int | None]:
    """Best-effort token counts from LangChain include_raw structured output."""

    message = raw
    if isinstance(raw, Mapping):
        message = raw.get("raw") or raw.get("parsed") or raw
    meta = getattr(message, "response_metadata", None) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    um = getattr(message, "usage_metadata", None) or {}
    inp = usage.get("prompt_tokens") or usage.get("input_tokens") or um.get("input_tokens")
    out = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or um.get("output_tokens")
    )
    try:
        return (int(inp) if inp is not None else None, int(out) if out is not None else None)
    except (TypeError, ValueError):
        return (None, None)


async def propose_with_chat_model(
    model: BaseChatModel,
    request: Mapping[str, Any],
    *,
    locale: str = "en",
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Ask a live (or test double) chat model for one structured proposal."""

    started = time.perf_counter()
    payload = json.dumps(dict(request), ensure_ascii=False, sort_keys=True)
    system = SYSTEM_PROMPTS.get(locale, SYSTEM_PROMPTS["en"])
    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        recorder = UsageRecorder()
        try:
            # Prefer plain structured output: include_raw can hang on some free routes.
            # Token counts come from the UsageRecorder callback instead.
            runnable = model.with_structured_output(EligibilityProposal)
            proposal = await asyncio.wait_for(
                runnable.ainvoke(
                    [
                        SystemMessage(content=system),
                        HumanMessage(content=payload),
                    ],
                    config={"callbacks": [recorder]},
                ),
                timeout=75,
            )
            if isinstance(proposal, EligibilityProposal):
                result = proposal.result
            elif isinstance(proposal, dict):
                result = _normalize_result(proposal.get("result"))
            else:
                result = _normalize_result(getattr(proposal, "result", None))
            latency_ms = int((time.perf_counter() - started) * 1000)
            inp = recorder.input_tokens if recorder.metered_calls else None
            out = recorder.output_tokens if recorder.metered_calls else None
            if result not in VALID_RESULTS:
                return {
                    "result": None,
                    "error": f"invalid result {result!r}",
                    "latency_ms": latency_ms,
                    "provider_error": False,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "token_metered": recorder.metered_calls > 0,
                    "locale": locale,
                }
            return {
                "result": result,
                "error": None,
                "latency_ms": latency_ms,
                "provider_error": False,
                "input_tokens": inp,
                "output_tokens": out,
                "token_metered": recorder.metered_calls > 0,
                "locale": locale,
            }
        except Exception as error:  # noqa: BLE001 — eval arm must record failures
            last_error = f"{type(error).__name__}: {error}"
            transient = _is_transient_provider_error(error) or isinstance(
                error, (asyncio.TimeoutError, TimeoutError),
            )
            if attempt < max_attempts and transient:
                delay = min(45.0, 6.0 * attempt)
                await asyncio.sleep(delay)
                continue
            return {
                "result": None,
                "error": last_error,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "provider_error": transient,
                "input_tokens": (
                    recorder.input_tokens if recorder.metered_calls else None
                ),
                "output_tokens": (
                    recorder.output_tokens if recorder.metered_calls else None
                ),
                "token_metered": recorder.metered_calls > 0,
                "locale": locale,
            }
    return {
        "result": None,
        "error": last_error or "unknown provider failure",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "provider_error": True,
        "input_tokens": None,
        "output_tokens": None,
        "token_metered": False,
        "locale": locale,
    }


async def _call_proposer(
    proposer: Proposer | BaseChatModel,
    request: Mapping[str, Any],
    *,
    locale: str = "en",
) -> dict[str, Any]:
    if isinstance(proposer, BaseChatModel):
        return await propose_with_chat_model(proposer, request, locale=locale)
    started = time.perf_counter()
    # Scripted proposers may ignore locale; pass it on the request copy.
    payload = dict(request)
    payload["locale"] = locale
    raw = proposer(payload)
    if isinstance(raw, Awaitable):
        raw = await raw
    latency_ms = int((time.perf_counter() - started) * 1000)
    if isinstance(raw, Mapping):
        result = _normalize_result(raw.get("result"))
        error = raw.get("error")
        provider_error = bool(raw.get("provider_error"))
        input_tokens = raw.get("input_tokens")
        output_tokens = raw.get("output_tokens")
        token_metered = bool(raw.get("token_metered"))
    else:
        result = _normalize_result(raw)
        error = None if result in VALID_RESULTS else f"invalid result {raw!r}"
        provider_error = False
        input_tokens = output_tokens = None
        token_metered = False
    return {
        "result": result,
        "error": error,
        "latency_ms": latency_ms,
        "provider_error": provider_error,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "token_metered": token_metered,
        "locale": locale,
    }


def _pct(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


async def run_llm_eligibility_ablation(
    *,
    proposer: Proposer | BaseChatModel,
    eval_path: Path = DEV_PERSONAS,
    allow_held_out: bool = False,
    scheme_ids: set[str] | None = None,
    limit: int | None = None,
    model_name: str | None = None,
    locales: Sequence[str] = ("en",),
    pace_seconds: float = 0.0,
    usd_per_million_input: float = 0.0,
    usd_per_million_output: float = 0.0,
    cost_route: str = "openrouter_free",
) -> dict[str, Any]:
    """Compare LLM proposals to rules and expected labels on a persona set.

    The rule engine is always authoritative for the recorded ``rule_result``.
    LLM outputs only feed agreement / boundary-error counts.
    When ``locales`` has en+hi+mr, also records verdict_agreement_hi_mr_en.
    """

    active_locales = tuple(locales) or ("en",)
    for locale in active_locales:
        if locale not in SYSTEM_PROMPTS:
            raise ValueError(f"Unsupported locale {locale!r}; want {sorted(SYSTEM_PROMPTS)}")

    evaluation_set = load_persona_evaluation_set(
        eval_path, allow_held_out=allow_held_out,
    )
    provider = RulePackageProvider()
    registry = provider.registry
    cases: list[dict[str, Any]] = []
    latencies: list[int] = []
    input_tokens_total = 0
    output_tokens_total = 0
    token_cases = 0
    calls_made = 0

    for persona in evaluation_set.personas:
        profile = persona_input(persona, registry)
        for scheme_id, expected in persona.expected_by_scheme.items():
            if scheme_ids is not None and scheme_id not in scheme_ids:
                continue
            package = provider.get(scheme_id)
            rule = evaluate_mock_eligibility(profile, package, registry=registry)
            base_request = build_llm_request(
                scheme_id=scheme_id,
                package=package,
                profile=profile,
                registry=registry,
            )
            locale_results: dict[str, Any] = {}
            locale_errors: dict[str, Any] = {}
            case_input_tokens = 0
            case_output_tokens = 0
            case_latency = 0
            any_provider_error = False

            for locale in active_locales:
                request = json.loads(json.dumps({**base_request, "locale": locale}))
                if calls_made and pace_seconds > 0:
                    await asyncio.sleep(pace_seconds)
                proposal = await _call_proposer(proposer, request, locale=locale)
                calls_made += 1
                locale_results[locale] = proposal.get("result")
                if proposal.get("error"):
                    locale_errors[locale] = proposal.get("error")
                if proposal.get("provider_error") or (
                    proposal.get("result") is None and proposal.get("error")
                ):
                    any_provider_error = True
                if isinstance(proposal.get("latency_ms"), int):
                    case_latency += int(proposal["latency_ms"])
                    latencies.append(int(proposal["latency_ms"]))
                inp = proposal.get("input_tokens")
                out = proposal.get("output_tokens")
                if proposal.get("token_metered") or (
                    isinstance(inp, int) and isinstance(out, int)
                ):
                    case_input_tokens += int(inp or 0)
                    case_output_tokens += int(out or 0)
                    input_tokens_total += int(inp or 0)
                    output_tokens_total += int(out or 0)
                    token_cases += 1

            primary = locale_results.get("en")
            if primary is None and active_locales:
                primary = locale_results.get(active_locales[0])
            expected_result = expected.result
            scored_locales = {
                loc: val for loc, val in locale_results.items() if val is not None
            }
            multilingual = len(active_locales) > 1
            all_agree = (
                len(scored_locales) == len(active_locales)
                and len(set(scored_locales.values())) == 1
            ) if multilingual else None

            boundary_llm = primary is not None and primary != expected_result
            case = {
                "persona_id": persona.persona_id,
                "scheme_id": scheme_id,
                "expected_result": expected_result,
                "rule_result": rule.result,
                "llm_result": primary,
                "locale_results": locale_results,
                "locale_errors": locale_errors or None,
                "llm_error": locale_errors.get("en") or next(iter(locale_errors.values()), None),
                "llm_latency_ms": case_latency,
                "input_tokens": case_input_tokens or None,
                "output_tokens": case_output_tokens or None,
                "provider_error": any_provider_error,
                "agree_llm_rules": primary == rule.result,
                "agree_llm_expected": primary == expected_result,
                "agree_rules_expected": rule.result == expected_result,
                "boundary_error_llm": boundary_llm,
                "boundary_error_rules": rule.result != expected_result,
                "verdict_agreement_hi_mr_en": all_agree,
                "authoritative": False,
                "written_to_live_state": False,
            }
            cases.append(case)
            print(
                f"E4 LLM {len(cases)}: {persona.persona_id}/{scheme_id} "
                f"rule={rule.result} llm={primary} "
                f"agree_locales={all_agree} err={any_provider_error}",
                file=sys.stderr,
                flush=True,
            )
            if limit is not None and len(cases) >= limit:
                break
        if limit is not None and len(cases) >= limit:
            break

    count = len(cases)
    scored = [c for c in cases if c["llm_result"] is not None]
    provider_errors = sum(1 for c in cases if c["provider_error"])
    agree_llm_rules = sum(1 for c in scored if c["agree_llm_rules"])
    agree_llm_expected = sum(1 for c in scored if c["agree_llm_expected"])
    boundary_llm = sum(1 for c in cases if c["boundary_error_llm"])
    boundary_rules = sum(1 for c in cases if c["boundary_error_rules"])
    latencies_sorted = sorted(latencies)
    median_latency = (
        latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else None
    )
    p95_latency = (
        latencies_sorted[int(0.95 * (len(latencies_sorted) - 1))]
        if latencies_sorted
        else None
    )
    scored_n = len(scored)

    multi_cases = [c for c in cases if c["verdict_agreement_hi_mr_en"] is not None]
    multi_agree = sum(1 for c in multi_cases if c["verdict_agreement_hi_mr_en"])
    total_cost = (
        (input_tokens_total / 1_000_000.0) * usd_per_million_input
        + (output_tokens_total / 1_000_000.0) * usd_per_million_output
    )
    cost_per_case = (total_cost / count) if count else 0.0

    return {
        "notice": NON_AUTHORITATIVE_NOTICE,
        "arm": "llm_eligibility_from_text",
        "eval_set": str(eval_path),
        "model": model_name,
        "locales": list(active_locales),
        "case_count": count,
        "scored_case_count": scored_n,
        "provider_error_count": provider_errors,
        "model_calls": calls_made,
        "agree_llm_rules": agree_llm_rules,
        "disagree_llm_rules": scored_n - agree_llm_rules,
        "agree_llm_expected": agree_llm_expected,
        "boundary_error_count_llm": boundary_llm,
        "boundary_error_count_rules": boundary_rules,
        "boundary_error_rate_llm": _pct(boundary_llm, scored_n),
        "boundary_error_rate_rules": _pct(boundary_rules, count),
        "verdict_agreement_hi_mr_en": {
            "locales": list(active_locales),
            "cases_scored": len(multi_cases),
            "all_three_agree": multi_agree if len(active_locales) >= 3 else multi_agree,
            "rate": _pct(multi_agree, len(multi_cases)),
            "note": (
                "Instruction language varies by locale; structured result enum "
                "remains English eligible/not_eligible/need_more_information."
                if len(active_locales) > 1
                else "Single-locale run; multilingual agreement not measured."
            ),
        },
        "cost": {
            "currency": "USD",
            "route": cost_route,
            "usd_per_million_input": usd_per_million_input,
            "usd_per_million_output": usd_per_million_output,
            "input_tokens_total": input_tokens_total,
            "output_tokens_total": output_tokens_total,
            "token_metered_calls": token_cases,
            "total_usd": round(total_cost, 6),
            "cost_per_case_usd": round(cost_per_case, 6),
            "note": (
                "Token counts from LangChain on_llm_end usage callbacks. "
                + (
                    "Free OpenRouter route priced at $0 unless rates are overridden."
                    if cost_route == "openrouter_free"
                    else "Cost uses provided per-million rates."
                )
            ),
        },

        "median_latency_ms": median_latency,
        "p95_latency_ms": p95_latency,
        "cases": cases,
    }

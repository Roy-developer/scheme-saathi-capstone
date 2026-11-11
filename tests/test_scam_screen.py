"""Unit coverage for contextual scam screening and clean-case false positives."""

from __future__ import annotations

from src.workflow.scam_screen import (
    CLEAN_SCAM_SCREEN_CASES,
    apply_scam_screen,
    scam_warning_for_locale,
    screen_scam_text,
)


def test_attack_lures_still_flag() -> None:
    attacks = [
        "Pay ₹500 processing fee to UPI ID scam@paytm to unlock your widow pension application.",
        "Visit https://pm-kisan-gov-in-verify.example/otp and enter your OTP to continue.",
        "Message +91 98765 43210 on WhatsApp and pay ₹200 for fast pension approval.",
        "Scan this QR and pay ₹99 KYC fee to unlock PM-KISAN installment.",
    ]
    for text in attacks:
        assert screen_scam_text(text).flagged is True, text


def test_clean_citizen_messages_do_not_flag() -> None:
    for text in CLEAN_SCAM_SCREEN_CASES:
        assert screen_scam_text(text).flagged is False, text


def test_apply_scam_screen_increments_guardrail_metric() -> None:
    from src.observability.metrics import GUARDRAIL_BLOCKS_TOTAL

    before = GUARDRAIL_BLOCKS_TOTAL.labels(
        guardrail="scam_screen", reason="flagged"
    )._value.get()
    result = apply_scam_screen(
        "Message WhatsApp and pay ₹200 for fast pension approval."
    )
    assert result.flagged is True
    after = GUARDRAIL_BLOCKS_TOTAL.labels(
        guardrail="scam_screen", reason="flagged"
    )._value.get()
    assert after == before + 1


def test_scam_warning_locales() -> None:
    assert "WhatsApp" in scam_warning_for_locale("en")
    assert scam_warning_for_locale("hi")
    assert scam_warning_for_locale("mr")

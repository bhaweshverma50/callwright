"""Launch template set (T102, FR-046, data-model section 6)."""

from __future__ import annotations

from collections import Counter

from app.agents import variables
from app.llms.service import load_catalog
from app.templates.jobs import load_seed

EXPECTED = [
    (1, "banking-collections", "banking", "outbound", "single_prompt"),
    (2, "banking-loan-telesales", "banking", "outbound", "single_prompt"),
    (3, "telecom-plan-upgrade", "telecom", "outbound", "single_prompt"),
    (4, "ecommerce-credit-offer", "ecommerce", "outbound", "single_prompt"),
    (5, "healthcare-triage-booking", "healthcare", "inbound", "single_prompt"),
    (6, "automotive-roadside-ev", "automotive", "inbound", "single_prompt"),
    (7, "healthcare-previsit-checkin", "healthcare", "outbound", "single_prompt"),
    (8, "banking-customer-line", "banking", "inbound", "single_prompt"),
    (9, "collections-return-call", "banking", "inbound", "single_prompt"),
    (10, "healthcare-appointment-booking", "healthcare", "inbound", "flow"),
    (11, "insurance-claim-intake", "insurance", "inbound", "flow"),
    (12, "utilities-payment-collection", "utilities", "outbound", "flow"),
    (13, "realestate-lead-qualification", "real_estate", "outbound", "flow"),
    (14, "logistics-delivery-reschedule", "logistics", "outbound", "flow"),
    (15, "ecommerce-order-support", "ecommerce", "inbound", "single_prompt"),
    (16, "telecom-support-line", "telecom", "inbound", "single_prompt"),
    (17, "insurance-renewal-reminder", "insurance", "outbound", "single_prompt"),
    (18, "hospitality-reservations", "hospitality", "inbound", "single_prompt"),
    (19, "hospitality-post-stay-feedback", "hospitality", "outbound", "single_prompt"),
    (20, "logistics-delivery-support", "logistics", "inbound", "single_prompt"),
    (21, "realestate-listing-inquiry", "real_estate", "inbound", "single_prompt"),
    (22, "automotive-service-reminder", "automotive", "outbound", "single_prompt"),
    (23, "automotive-test-drive-booking", "automotive", "inbound", "flow"),
    (24, "banking-kyc-verification", "banking", "outbound", "flow"),
    (25, "telecom-nps-survey", "telecom", "outbound", "flow"),
    (26, "utilities-outage-reporting", "utilities", "inbound", "flow"),
]
VARIABLES = {
    "banking-collections": ["company_name", "customer_name", "loan_type", "overdue_amount", "due_date"],
    "banking-loan-telesales": [
        "company_name",
        "customer_name",
        "offer_amount",
        "interest_rate",
        "tenure_months",
    ],
    "telecom-plan-upgrade": ["company_name", "customer_name", "current_plan", "offer_plan"],
    "ecommerce-credit-offer": ["company_name", "customer_name", "credit_limit"],
    "healthcare-triage-booking": ["company_name"],
    "automotive-roadside-ev": ["company_name"],
    "healthcare-previsit-checkin": [
        "company_name",
        "patient_name",
        "appointment_date",
        "appointment_time",
        "doctor_name",
    ],
    "banking-customer-line": ["company_name", "branch_hours", "card_helpline"],
    "collections-return-call": [
        "company_name",
        "customer_name",
        "account_last_four",
        "overdue_amount",
        "due_date",
    ],
}
SEEDS = sorted(load_seed(), key=lambda t: t["sort_order"])


def test_launch_set_in_order() -> None:
    got = [(t["sort_order"], t["id"], t["category"], t["direction"], t["agent_type"]) for t in SEEDS]
    assert got == EXPECTED
    assert Counter(t["category"] for t in SEEDS) == {
        "automotive": 3,
        "banking": 5,
        "ecommerce": 2,
        "healthcare": 3,
        "telecom": 3,
        "insurance": 2,
        "real_estate": 2,
        "hospitality": 2,
        "logistics": 2,
        "utilities": 2,
    }
    assert Counter(t["agent_type"] for t in SEEDS) == {"single_prompt": 17, "flow": 9}


def test_carried_fields() -> None:
    llm = load_catalog()
    for seed in SEEDS:
        cfg = seed["config"]
        base = {"agent_name", "language", "llm", "prompt", "stt", "tts", "dynamic_variables"}
        # A flow's Start node owns the greeting and who speaks first; its graph replaces them.
        extra = {"graph"} if seed["agent_type"] == "flow" else {"begin_message", "start_speaker"}
        assert set(cfg) == base | extra, seed["id"]
        assert cfg["language"] == "en-US"
        assert "## Identity" in cfg["prompt"], seed["id"]
        assert cfg["llm"] == {"provider": "azure_openai", "model": "gpt-5.1"}
        model = llm.model(cfg["llm"]["provider"], cfg["llm"]["model"])
        assert model is not None and model.temperature.is_fixed and "temperature" not in cfg["llm"]
        assert cfg["stt"] == {"provider": "deepgram", "model": None}
        assert cfg["tts"] == {"provider": "elevenlabs", "model": "eleven_multilingual_v2"}
        assert "voice_id" not in cfg["tts"]


def test_variables_declared_with_defaults() -> None:
    for seed in SEEDS:
        cfg = seed["config"]
        declared = {v["name"]: v.get("default") for v in cfg["dynamic_variables"]}
        if seed["id"] in VARIABLES:
            assert list(declared) == VARIABLES[seed["id"]], seed["id"]
        assert declared, seed["id"]
        assert all(isinstance(d, str) and d for d in declared.values()), seed["id"]
        used = variables.extract([cfg["prompt"], cfg.get("begin_message")])
        assert used.invalid == (), seed["id"]
        for name in used.names:
            assert name in declared, (seed["id"], name)

"""Launch template set (T102, FR-046, data-model section 6)."""

from __future__ import annotations

from collections import Counter

from app.agents import variables
from app.llms.service import load_catalog
from app.templates.jobs import load_seed

EXPECTED = [
    (1, "banking-collections", "banking", "Loan payment reminder", "outbound"),
    (2, "banking-loan-telesales", "banking", "Personal loan offer", "outbound"),
    (3, "telecom-plan-upgrade", "telecom", "Mobile plan upgrade", "outbound"),
    (4, "ecommerce-credit-offer", "ecommerce", "Shopping credit and membership", "outbound"),
    (5, "healthcare-triage-booking", "healthcare", "Symptom triage and booking", "inbound"),
    (6, "automotive-roadside-ev", "automotive", "Roadside and EV assistance", "inbound"),
    (7, "healthcare-previsit-checkin", "healthcare", "Pre-visit patient check-in", "outbound"),
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
}
SEEDS = sorted(load_seed(), key=lambda t: t["sort_order"])


def test_exactly_seven_in_order() -> None:
    assert [(t["sort_order"], t["id"], t["category"], t["name"], t["direction"]) for t in SEEDS] == EXPECTED
    assert Counter(t["category"] for t in SEEDS) == {
        "automotive": 1,
        "banking": 2,
        "ecommerce": 1,
        "healthcare": 2,
        "telecom": 1,
    }


def test_carried_fields() -> None:
    llm = load_catalog()
    for seed in SEEDS:
        cfg = seed["config"]
        assert set(cfg) == {
            "agent_name",
            "language",
            "llm",
            "prompt",
            "begin_message",
            "start_speaker",
            "stt",
            "tts",
            "dynamic_variables",
        }, seed["id"]
        assert cfg["language"] == "en-US" and cfg["start_speaker"] == "agent"
        assert cfg["llm"] == {"provider": "azure_openai", "model": "gpt-5.1"}
        model = llm.model(cfg["llm"]["provider"], cfg["llm"]["model"])
        assert model is not None and model.temperature.is_fixed and "temperature" not in cfg["llm"]
        assert cfg["stt"] == {"provider": "deepgram", "model": None}
        assert cfg["tts"] == {"provider": "elevenlabs", "model": "eleven_flash_v2_5"}
        assert "voice_id" not in cfg["tts"]


def test_variables_declared_with_defaults() -> None:
    for seed in SEEDS:
        cfg = seed["config"]
        declared = {v["name"]: v.get("default") for v in cfg["dynamic_variables"]}
        assert list(declared) == VARIABLES[seed["id"]], seed["id"]
        assert declared["company_name"], seed["id"]
        assert all(isinstance(d, str) and d for d in declared.values()), seed["id"]
        used = variables.extract([cfg["prompt"], cfg["begin_message"]])
        assert used.invalid == (), seed["id"]
        for name in used.names:
            assert name in declared, (seed["id"], name)

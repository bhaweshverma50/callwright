"""Cost view mapping (006 T024, FR-015, US2 scenario 8). Written before ``calls.cost_view``."""

from __future__ import annotations

from decimal import Decimal

from app.billing.service import breakdown_json
from app.calls.cost_view import cost_view
from app.pricing import engine
from app.pricing.engine import Components, Selection, Usage
from tests.unit.pricing.test_engine import REFERENCE_COMPONENTS, REFERENCE_USAGE, _catalog


def _stored(
    components: Components = REFERENCE_COMPONENTS, usage: Usage = REFERENCE_USAGE
) -> dict[str, object]:
    quote = engine.price(components, usage, _catalog())
    assert quote.call is not None
    return breakdown_json(quote.call, "call_ref")


def test_reference_call_header() -> None:
    view = cost_view(_stored())
    header = view["header"]
    assert header["duration_s"] == 271
    assert round(header["billed_minutes"], 2) == 4.52
    assert round(header["avg_rate_per_min_usd"], 3) == 0.106
    assert header["total_usd"] == 0.477
    assert view["catalog_version"] == "1"


def test_reference_call_lines_sum_to_total() -> None:
    view = cost_view(_stored())
    assert [line["component"] for line in view["lines"]] == ["stt", "llm", "tts", "platform"]
    total = sum(Decimal(str(line["cost_usd"])) for line in view["lines"])
    assert total == Decimal("0.477")
    llm = next(line for line in view["lines"] if line["component"] == "llm")
    assert llm["provider"] == "azure_openai"
    assert llm["model"] == "gpt-5-mini"
    assert llm["rate_per_min_usd"] == 0.0015
    assert round(llm["billed_minutes"], 4) == 5.1174


def test_reference_call_llm_surcharge_multiplier() -> None:
    surcharges = cost_view(_stored())["surcharges"]
    assert len(surcharges) == 1
    llm = surcharges[0]
    assert llm["component"] == "llm"
    assert llm["label"] == "Model token surcharge"
    assert llm["multiplier"] == 1.13
    assert 0.0008 < llm["surcharge_usd"] < 0.001


def test_nc_line_omitted_when_zero() -> None:
    components = Components(
        stt=Selection("deepgram", "nova-3"),
        llm=Selection("azure_openai", "gpt-5-mini"),
        tts=Selection("elevenlabs", "eleven_flash_v2_5"),
        nc=Selection("sanas", "vi"),
    )
    view = cost_view(_stored(components))
    assert "nc" not in [line["component"] for line in view["lines"]]


def test_nc_line_kept_when_priced() -> None:
    components = Components(
        stt=Selection("deepgram", "nova-3"),
        llm=Selection("azure_openai", "gpt-5-mini"),
        tts=Selection("elevenlabs", "eleven_flash_v2_5"),
        nc=Selection("acme_nc", "pro"),
    )
    view = cost_view(_stored(components))
    assert "nc" in [line["component"] for line in view["lines"]]


def test_no_surcharge_lines_within_bundle() -> None:
    usage = Usage(duration_ms=60_000, llm_input_tokens=1_000, llm_output_tokens=50, tts_chars=100)
    assert cost_view(_stored(usage=usage))["surcharges"] == []


def test_zero_second_call_has_zero_rate() -> None:
    view = cost_view(_stored(usage=Usage(duration_ms=0)))
    assert view["header"]["duration_s"] == 0
    assert view["header"]["avg_rate_per_min_usd"] == 0
    assert view["header"]["total_usd"] == 0


def test_none_when_not_priced() -> None:
    assert cost_view(None) is None

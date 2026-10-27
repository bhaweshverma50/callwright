"""Contract tests for the evaluator catalog, custom checks and trials (007 T025, T055, T057, T086)."""

from __future__ import annotations

import httpx

from app.evaluators.registry import builtin_id
from tests.conftest import Account, signup
from tests.contract.conftest import check
from tests.fakes.fake_llm import FakeLlm
from tests.quality_support import scripted_call
from tests.runtime_support import Runtime, idem, owner_sql

PHRASE = {"pattern": "guaranteed", "mode": "forbidden", "target": "agent"}
QUESTION = {"question": "Did the agent confirm the caller's appointment day?", "pass_when": "yes"}


async def test_list_get_and_builtins_are_read_only(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    assert check(await client.get("/v1/evaluators", headers=h)).status_code == 200
    evl = builtin_id("latency_slo")
    got = check(await client.get(f"/v1/evaluators/{evl}", headers=h)).json()
    assert got["name"] == "latency_slo" and got["versions"][0]["version"] == 1
    assert "rules" in got["versions"][0]["definition"]
    assert (
        check(await client.patch(f"/v1/evaluators/{evl}", json={"display_name": "x"}, headers=h)).status_code
        == 403
    )
    assert check(await client.delete(f"/v1/evaluators/{evl}", headers=h)).status_code == 403


async def test_custom_create_derives_name_and_conflicts(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    body = {
        "display_name": "No guarantees",
        "description": "  ",
        "evaluator_type": "phrase_check",
        "config": PHRASE,
    }
    created = check(await client.post("/v1/evaluators", json=body, headers=h))
    assert created.status_code == 201, created.text
    e = created.json()
    assert (e["name"], e["current_version"], e["description"], e["cost_class"]) == (
        "no_guarantees",
        1,
        None,
        "free",
    )
    assert e["config"] == {**PHRASE, "is_regex": False, "case_sensitive": False}
    dup = check(await client.post("/v1/evaluators", json=body, headers=h))
    assert (
        dup.status_code == 409
        and dup.json()["detail"] == "You already have a custom check named no_guarantees"
    )
    builtin = check(
        await client.post("/v1/evaluators", json={**body, "display_name": "Latency SLO"}, headers=h)
    )
    assert builtin.status_code == 409
    # Another workspace may use the same name.
    other = await signup(client, client._transport.app)  # type: ignore[attr-defined]
    assert check(await client.post("/v1/evaluators", json=body, headers=other.headers)).status_code == 201
    # Soft delete frees the name; the old row keeps its versions.
    assert check(await client.delete(f"/v1/evaluators/{e['id']}", headers=h)).status_code == 204
    again = check(await client.post("/v1/evaluators", json=body, headers=h))
    assert again.status_code == 201 and again.json()["id"] != e["id"]
    deleted = check(await client.get(f"/v1/evaluators/{e['id']}", headers=h)).json()
    assert deleted["deleted_at"] is not None and deleted["versions"][0]["version"] == 1
    listed = check(await client.get("/v1/evaluators", params={"kind": "custom"}, headers=h)).json()["items"]
    assert [x["id"] for x in listed] == [again.json()["id"]]
    with_deleted = check(
        await client.get("/v1/evaluators", params={"kind": "custom", "include_deleted": "true"}, headers=h)
    )
    assert len(with_deleted.json()["items"]) == 2


async def test_custom_validation(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers

    async def post(**kw: object) -> httpx.Response:
        body = {"display_name": "Check", "evaluator_type": "phrase_check", "config": PHRASE, **kw}
        return check(await client.post("/v1/evaluators", json=body, headers=h))

    bad = await post(config={**PHRASE, "pattern": r"(a)\1", "is_regex": True})
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/config/pattern"
    assert "not valid" in bad.json()["errors"][0]["message"]
    assert (await post(display_name="!!!")).status_code == 422
    judge = await post(evaluator_type="llm_judge_custom", config={**QUESTION, "judge_model": "free/text"})
    assert judge.status_code == 422 and judge.json()["errors"][0]["pointer"] == "/config/judge_model"
    short = await post(evaluator_type="llm_judge_custom", config={"question": "ok?", "pass_when": "yes"})
    assert short.status_code == 422
    good = await post(display_name="Confirms day", evaluator_type="llm_judge_custom", config=QUESTION)
    assert good.status_code == 201 and good.json()["cost_class"] == "llm_judge"
    assert good.json()["config"]["judge_model"]  # defaulted to the default judge


async def test_versioning_on_config_edit_only(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    body = {"display_name": "Confirms DOB", "evaluator_type": "llm_judge_custom", "config": QUESTION}
    e = check(await client.post("/v1/evaluators", json=body, headers=h)).json()
    renamed = check(
        await client.patch(
            f"/v1/evaluators/{e['id']}", json={"display_name": "Confirms date of birth"}, headers=h
        )
    )
    assert renamed.status_code == 200 and renamed.json()["current_version"] == 1
    same = check(await client.patch(f"/v1/evaluators/{e['id']}", json={"config": e["config"]}, headers=h))
    assert same.json()["current_version"] == 1
    edited = {**e["config"], "question": "Did the agent confirm the caller's date of birth?"}
    v2 = check(await client.patch(f"/v1/evaluators/{e['id']}", json={"config": edited}, headers=h))
    assert v2.status_code == 200 and v2.json()["current_version"] == 2
    versions = check(await client.get(f"/v1/evaluators/{e['id']}", headers=h)).json()["versions"]
    assert [v["version"] for v in versions] == [1, 2] and versions[0]["definition"]["question"] == QUESTION[
        "question"
    ]


async def test_fifty_custom_limit(client: httpx.AsyncClient, account: Account) -> None:
    h = account.headers
    for i in range(50):
        r = await client.post(
            "/v1/evaluators",
            json={
                "display_name": f"Check {chr(97 + i // 26)}{chr(97 + i % 26)}",
                "evaluator_type": "phrase_check",
                "config": PHRASE,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
    over = check(
        await client.post(
            "/v1/evaluators",
            json={"display_name": "One more", "evaluator_type": "phrase_check", "config": PHRASE},
            headers=h,
        )
    )
    assert over.status_code == 409


async def test_trials(
    client: httpx.AsyncClient, account: Account, runtime: Runtime, quality: FakeLlm
) -> None:
    h = account.headers
    lines = [
        ("agent", "Hello."),
        ("user", "Will I be approved?"),
        ("agent", "Approval is guaranteed for you."),
    ]
    call = await scripted_call(runtime, account.workspace_id, lines=lines)
    phrase = check(
        await client.post(
            "/v1/evaluators/trial",
            json={
                "evaluator_type": "phrase_check",
                "call_id": call.call_id,
                "config": {
                    "pattern": "guarantee(d)?",
                    "mode": "forbidden",
                    "target": "agent",
                    "is_regex": True,
                },
            },
            headers={**h, **idem()},
        )
    )
    assert phrase.status_code == 200
    assert phrase.json()["verdict"] == "fail" and phrase.json()["evidence"]["turn_indices"] == [2]
    assert phrase.json()["charged_usd"] is None
    key = idem()
    judge_body = {
        "evaluator_type": "llm_judge_custom",
        "call_id": call.call_id,
        "config": {"question": "Did the agent say approval is guaranteed?", "pass_when": "no"},
    }
    judged = check(await client.post("/v1/evaluators/trial", json=judge_body, headers={**h, **key}))
    assert judged.status_code == 200 and judged.json()["verdict"] == "fail"  # answer yes, pass on no
    assert judged.json()["charged_usd"] > 0
    replay = check(await client.post("/v1/evaluators/trial", json=judge_body, headers={**h, **key}))
    assert replay.json() == judged.json()
    assert owner_sql(
        "select count(*) from usage_events where feature_key = 'eval.llm_judge_custom' and ref_id = %s",
        (call.call_id,),
    ) == [(1,)]
    missing = check(
        await client.post(
            "/v1/evaluators/trial",
            json={**judge_body, "call_id": "call_01ARZ3NDEKTSV4RRFFQ69G5FAV"},
            headers={**h, **idem()},
        )
    )
    assert missing.status_code == 404
    invalid = check(
        await client.post(
            "/v1/evaluators/trial", json={**judge_body, "config": {"question": "x"}}, headers={**h, **idem()}
        )
    )
    assert invalid.status_code == 422

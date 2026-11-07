from __future__ import annotations

from callwright_contract.variables import DOTTED_PLACEHOLDER, NAME, render


def test_render() -> None:
    variables = {"customer_name": "Priya", "order_id": "A1"}
    assert render("Hi {{customer_name}}, order {{ order_id }}.", variables) == "Hi Priya, order A1."
    assert render("{{missing}}|{{ 9bad }}", variables) == "|{{ 9bad }}"


def test_name_rule() -> None:
    assert NAME.match("_a1") and NAME.match("a" * 64)
    assert not NAME.match("1a") and not NAME.match("a" * 65) and not NAME.match("a-b")


def test_dotted_placeholder_reads_one_level() -> None:
    names = [m.group(1) for m in DOTTED_PLACEHOLDER.finditer("{{task_result.email}} {{ a }} {{a.b.c}}")]
    assert names == ["task_result.email", "a"]

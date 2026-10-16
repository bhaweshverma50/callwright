"""Template catalog reads and the template-to-config overlay (T073, T074, research R16).

Templates are global rows written by the sync job (``templates/jobs.py``) from
``templates/seed/*.yaml``. A template's ``config`` is a partial AgentConfig plus ``agent_name``
(the suggested agent name). ``partial_config`` turns it into an overlay for
``agents.service.create_agent`` and replaces components the catalog no longer offers with the
language defaults, reporting each replacement as a ``component_replaced`` warning.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import defaults
from app.llms.service import load_catalog as load_llm_catalog
from app.templates.models import Template
from app.voices.catalog import load_catalog as load_voice_catalog

CATEGORIES: dict[str, str] = {
    "automotive": "Automotive",
    "banking": "Banking",
    "ecommerce": "E-commerce",
    "healthcare": "Healthcare",
    "telecom": "Telecom",
}


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_templates(
    session: AsyncSession, *, category: str | None = None, search: str | None = None
) -> list[Template]:
    query = select(Template).where(Template.is_active.is_(True))
    if category:
        query = query.where(Template.category == category)
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        query = query.where(or_(Template.name.ilike(pattern), Template.description.ilike(pattern)))
    rows = await session.execute(query.order_by(Template.sort_order, Template.id))
    return list(rows.scalars())


async def get_template(
    session: AsyncSession, template_id: str, *, active_only: bool = True
) -> Template | None:
    template = await session.get(Template, template_id)
    if template is None or (active_only and not template.is_active):
        return None
    return template


async def categories(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Template.category, func.count())
        .where(Template.is_active.is_(True))
        .group_by(Template.category)
    )
    counts = {str(cat): int(n) for cat, n in rows}
    return [
        {"id": cat, "label": label, "count": counts[cat]}
        for cat, label in CATEGORIES.items()
        if counts.get(cat)
    ]


def summary_json(template: Template) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "icon": template.icon,
        "direction": template.direction,
        "language": str(template.config.get("language") or defaults.DEFAULT_LANGUAGE),
    }


def detail_json(template: Template) -> dict[str, Any]:
    return {**summary_json(template), "config": copy.deepcopy(template.config)}


def partial_config(template_config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The template's AgentConfig overlay and the components replaced with language defaults."""
    config = {k: copy.deepcopy(v) for k, v in template_config.items() if k != "agent_name"}
    warnings: list[dict[str, str]] = []
    language = str(config.get("language") or defaults.DEFAULT_LANGUAGE)
    vc = load_voice_catalog()
    lc = load_llm_catalog()
    if vc.language(language) is None:
        warnings.append(
            _replaced("/language", f"The template language {language} is not offered; English (US) is used.")
        )
        language = defaults.DEFAULT_LANGUAGE
        config["language"] = language
    llm = config.get("llm")
    if isinstance(llm, dict):
        model = lc.model(str(llm.get("provider")), str(llm.get("model")))
        if model is None or model.withdrawn:
            config["llm"] = {k: v for k, v in defaults.llm_defaults().items() if k != "temperature"}
            warnings.append(
                _replaced(
                    "/llm/model", "The template's model is no longer offered; the default model is used."
                )
            )
        elif model.temperature.is_fixed:
            llm.pop("temperature", None)
    stt = config.get("stt")
    if isinstance(stt, dict):
        provider = vc.stt_provider(str(stt.get("provider")))
        model_id = stt.get("model")
        if provider is None or not provider.covers(model_id if isinstance(model_id, str) else None, language):
            config["stt"] = defaults.stt_defaults(language)
            warnings.append(
                _replaced(
                    "/stt",
                    "The template's speech recognition does not support this language; the default is used.",
                )
            )
    tts = config.get("tts")
    if isinstance(tts, dict):
        provider_t = vc.tts_provider(str(tts.get("provider")))
        model_t = provider_t.model(str(tts.get("model"))) if provider_t is not None else None
        voice = tts.get("voice_id")
        if provider_t is None or model_t is None or model_t.withdrawn:
            config["tts"] = {
                k: v
                for k, v in defaults.tts_defaults(language).items()
                if k in ("provider", "model", "voice_id")
            }
            warnings.append(
                _replaced(
                    "/tts/voice_id",
                    "The template's voice is no longer offered; the default voice for the language is used.",
                )
            )
        elif isinstance(voice, str) and not provider_t.owns_voice(voice):
            tts["voice_id"] = provider_t.voice_for(language)
            warnings.append(
                _replaced(
                    "/tts/voice_id",
                    "The template's voice is no longer offered; the default voice for the language is used.",
                )
            )
        elif "voice_id" not in tts:
            tts["voice_id"] = provider_t.voice_for(language)
    return config, warnings


def _replaced(pointer: str, message: str) -> dict[str, str]:
    return {"pointer": pointer, "code": "component_replaced", "message": message}

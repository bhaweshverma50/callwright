"""Process-wide services for 007's post-call work (analysis, evaluator runs).

``install(settings)`` is called by ``create_app`` and by the jobs worker's startup. It builds
the ``llms`` client, the judge, the embedder (005) and registers the offline fake replies used
when no vendor key is configured. Tests replace parts with ``install(..., llm=FakeLlm(...))``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.evaluators.judge import CompletionClient, Judge


@dataclass
class QualityRuntime:
    settings: Settings
    llm: CompletionClient
    embedder: Any = None  # app.knowledge.embeddings.EmbeddingAdapter
    queue: Any = None  # app.core.queue.JobQueue for follow-up jobs (evaluate_call)

    @property
    def judge(self) -> Judge:
        return Judge(
            self.llm, timeout_s=self.settings.eval_timeout_s, cutoff=self.settings.eval_judge_pass_cutoff
        )


_runtime: QualityRuntime | None = None


def install(
    settings: Settings | None = None,
    *,
    llm: CompletionClient | None = None,
    embedder: Any = None,
    queue: Any = None,
) -> QualityRuntime:
    global _runtime
    from app.evals import fakes
    from app.knowledge.embeddings import build_embedder
    from app.llms.client import LlmClient

    settings = settings or get_settings()
    fakes.register()
    _runtime = QualityRuntime(
        settings=settings,
        llm=llm or LlmClient(settings),
        embedder=embedder if embedder is not None else build_embedder(settings),
        queue=queue,
    )
    return _runtime


def runtime() -> QualityRuntime:
    return _runtime or install()


def set_queue(queue: Any) -> None:
    runtime().queue = queue

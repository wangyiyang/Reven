from uuid import uuid4

import pytest
from reven.rss.screening import (
    KeywordSignal,
    ModelJudgement,
    RssScreeningEngine,
    ScreeningDocument,
)


class RecordingJudge:
    def __init__(self) -> None:
        self.titles: list[str] = []

    async def judge(self, document: ScreeningDocument, evidence: dict[str, object]) -> ModelJudgement:
        self.titles.append(document.title)
        assert evidence["rules_version"] == "rss-v1"
        return ModelJudgement(True, 0.91, "与智能体工程高度相关")


class FailingJudge:
    async def judge(self, document: ScreeningDocument, evidence: dict[str, object]) -> ModelJudgement:
        raise RuntimeError("model unavailable")


@pytest.mark.anyio
async def test_screening_exposes_each_layer_and_limits_model_calls() -> None:
    judge = RecordingJudge()
    engine = RssScreeningEngine(judge=judge)
    documents = (
        ScreeningDocument(uuid4(), "AI agent architecture", "A practical guide"),
        ScreeningDocument(uuid4(), "Weekly promotion", "Sponsored post"),
        ScreeningDocument(uuid4(), "Gardening", "How to grow tomatoes"),
    )
    keywords = (
        KeywordSignal("AI agent", "positive", (1.0, 0.0)),
        KeywordSignal("sponsored", "negative", (0.0, 1.0)),
    )

    decisions = await engine.screen(documents, keywords, ((1.0, 0.0), (0.0, 1.0), (0.1, 1.0)))

    relevant, sponsored, unrelated = decisions
    assert relevant.status == "candidate"
    assert relevant.positive_literal_matches == ("AI agent",)
    assert relevant.bm25_score > 0
    assert relevant.positive_embedding_score == 1.0
    assert relevant.model_status == "completed"
    assert relevant.reason == "与智能体工程高度相关"
    assert sponsored.status == "filtered"
    assert sponsored.negative_literal_matches == ("sponsored",)
    assert unrelated.status == "filtered"
    assert judge.titles == ["AI agent architecture"]


@pytest.mark.anyio
async def test_negative_semantic_match_alone_never_unconditionally_deletes() -> None:
    engine = RssScreeningEngine()
    document = ScreeningDocument(uuid4(), "Autonomous systems", "Agent reliability")
    keywords = (
        KeywordSignal("agent", "positive", (1.0, 0.0)),
        KeywordSignal("risk", "negative", (0.99, 0.01)),
    )

    decision = (await engine.screen((document,), keywords, ((1.0, 0.0),)))[0]

    assert decision.positive_embedding_score == 1.0
    assert decision.negative_embedding_score > 0.99
    assert decision.status == "candidate"
    assert "反向语义" in decision.reason


@pytest.mark.anyio
async def test_optional_model_failure_keeps_deterministic_decision() -> None:
    engine = RssScreeningEngine(judge=FailingJudge())
    document = ScreeningDocument(uuid4(), "AI agent architecture", "Practical guide")
    keyword = KeywordSignal("AI agent", "positive", (1.0, 0.0))

    decision = (await engine.screen((document,), (keyword,), ((1.0, 0.0),)))[0]

    assert decision.status == "candidate"
    assert decision.model_status == "failed"
    assert decision.model_score is None
    assert "正向" in decision.reason

"""Explainable layered RSS screening without persisting item vectors."""

import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from reven.rss.normalization import normalize_keyword

RULES_VERSION = "rss-v1"
BM25_CANDIDATE_THRESHOLD = 0.2
EMBEDDING_CANDIDATE_THRESHOLD = 0.55
MODEL_REVIEW_CONCURRENCY = 4


@dataclass(frozen=True)
class ScreeningDocument:
    item_id: UUID
    title: str
    summary: str


@dataclass(frozen=True)
class KeywordSignal:
    term: str
    kind: str
    vector: tuple[float, ...] | None


@dataclass(frozen=True)
class ModelJudgement:
    recommended: bool
    score: float
    reason: str


@dataclass(frozen=True)
class ScreeningDecision:
    item_id: UUID
    status: str
    positive_literal_matches: tuple[str, ...]
    negative_literal_matches: tuple[str, ...]
    bm25_score: float
    positive_embedding_score: float
    negative_embedding_score: float
    model_status: str
    model_score: float | None
    reason: str
    rules_version: str = RULES_VERSION


class BoundaryJudge(Protocol):
    async def judge(self, document: ScreeningDocument, evidence: dict[str, object]) -> ModelJudgement: ...


class RssScreeningEngine:
    def __init__(self, *, judge: BoundaryJudge | None = None) -> None:
        self._judge = judge

    async def screen(
        self,
        documents: tuple[ScreeningDocument, ...],
        keywords: tuple[KeywordSignal, ...],
        item_vectors: tuple[tuple[float, ...], ...],
    ) -> tuple[ScreeningDecision, ...]:
        if len(documents) != len(item_vectors):
            raise ValueError("RSS 文档与临时向量数量不一致")
        positive = tuple(keyword for keyword in keywords if keyword.kind == "positive")
        negative = tuple(keyword for keyword in keywords if keyword.kind == "negative")
        bm25 = _bm25_scores(documents, tuple(keyword.term for keyword in positive))
        decisions = tuple(
            _base_decision(document, item_vectors[index], positive, negative, bm25[index])
            for index, document in enumerate(documents)
        )
        judge = self._judge
        if judge is None:
            return decisions
        limiter = asyncio.Semaphore(MODEL_REVIEW_CONCURRENCY)

        async def review(index: int, decision: ScreeningDecision) -> ScreeningDecision:
            if not _needs_model(decision):
                return decision
            async with limiter:
                try:
                    judgement = await judge.judge(documents[index], _evidence(decision))
                    return _with_judgement(decision, judgement)
                except Exception:
                    return _with_model_failure(decision)

        return tuple(await asyncio.gather(*(review(index, decision) for index, decision in enumerate(decisions))))


def _base_decision(
    document: ScreeningDocument,
    item_vector: tuple[float, ...],
    positive: tuple[KeywordSignal, ...],
    negative: tuple[KeywordSignal, ...],
    bm25_score: float,
) -> ScreeningDecision:
    text = normalize_keyword(f"{document.title} {document.summary}")
    positive_matches = tuple(keyword.term for keyword in positive if normalize_keyword(keyword.term) in text)
    negative_matches = tuple(keyword.term for keyword in negative if normalize_keyword(keyword.term) in text)
    positive_score = _max_similarity(item_vector, positive)
    negative_score = _max_similarity(item_vector, negative)
    positive_signal = (
        bool(positive_matches)
        or bm25_score >= BM25_CANDIDATE_THRESHOLD
        or (positive_score >= EMBEDDING_CANDIDATE_THRESHOLD)
    )
    blocked_by_literal = bool(negative_matches) and not positive_matches and positive_score < 0.8
    status = "candidate" if positive_signal and not blocked_by_literal else "filtered"
    return ScreeningDecision(
        document.item_id,
        status,
        positive_matches,
        negative_matches,
        bm25_score,
        positive_score,
        negative_score,
        "skipped",
        None,
        _reason(status, negative_matches, positive_score, negative_score),
    )


def _reason(
    status: str,
    negative_matches: tuple[str, ...],
    positive_score: float,
    negative_score: float,
) -> str:
    if status == "filtered" and negative_matches:
        return "命中反向字面规则，且没有足够正向信号"
    if status == "filtered":
        return "未达到正向字面、BM25 或 Embedding 候选阈值"
    if negative_score >= positive_score - 0.05:
        return "正向信号成立；反向语义仅作为风险提示，保留人工判断"
    return "正向字面、BM25 或 Embedding 信号达到候选阈值"


def _needs_model(decision: ScreeningDecision) -> bool:
    if decision.status != "candidate":
        return False
    strength = max(
        1.0 if decision.positive_literal_matches else 0.0,
        decision.bm25_score,
        decision.positive_embedding_score,
    )
    return 0.45 <= strength <= 0.65 or strength >= 0.85


def _evidence(decision: ScreeningDecision) -> dict[str, object]:
    return {
        "rules_version": decision.rules_version,
        "positive_literal_matches": decision.positive_literal_matches,
        "negative_literal_matches": decision.negative_literal_matches,
        "bm25_score": decision.bm25_score,
        "positive_embedding_score": decision.positive_embedding_score,
        "negative_embedding_score": decision.negative_embedding_score,
    }


def _with_judgement(decision: ScreeningDecision, judgement: ModelJudgement) -> ScreeningDecision:
    return ScreeningDecision(
        decision.item_id,
        "candidate" if judgement.recommended else "filtered",
        decision.positive_literal_matches,
        decision.negative_literal_matches,
        decision.bm25_score,
        decision.positive_embedding_score,
        decision.negative_embedding_score,
        "completed",
        judgement.score,
        judgement.reason,
        decision.rules_version,
    )


def _with_model_failure(decision: ScreeningDecision) -> ScreeningDecision:
    return ScreeningDecision(
        decision.item_id,
        decision.status,
        decision.positive_literal_matches,
        decision.negative_literal_matches,
        decision.bm25_score,
        decision.positive_embedding_score,
        decision.negative_embedding_score,
        "failed",
        None,
        decision.reason,
        decision.rules_version,
    )


def _max_similarity(vector: tuple[float, ...], keywords: tuple[KeywordSignal, ...]) -> float:
    vectors = tuple(keyword.vector for keyword in keywords if keyword.vector is not None)
    if not vectors:
        return 0.0
    return max(_cosine(vector, keyword_vector) for keyword_vector in vectors)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding 维度不一致")
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    if denominator == 0:
        return 0.0
    return sum(first * second for first, second in zip(left, right, strict=True)) / denominator


def _bm25_scores(documents: tuple[ScreeningDocument, ...], terms: tuple[str, ...]) -> tuple[float, ...]:
    query = [token for term in terms for token in _tokens(term)]
    tokenized = [_tokens(f"{document.title} {document.summary}") for document in documents]
    if not documents or not query:
        return tuple(0.0 for _document in documents)
    average_length = sum(len(tokens) for tokens in tokenized) / len(tokenized) or 1.0
    frequencies = Counter(token for tokens in tokenized for token in set(tokens))
    raw = [_bm25_document(tokens, query, frequencies, len(documents), average_length) for tokens in tokenized]
    return tuple(value / (value + 1.0) for value in raw)


def _bm25_document(
    document: list[str],
    query: list[str],
    document_frequencies: Counter[str],
    document_count: int,
    average_length: float,
) -> float:
    counts = Counter(document)
    score = 0.0
    for token in set(query):
        frequency = counts[token]
        if frequency == 0:
            continue
        document_frequency = document_frequencies[token]
        inverse = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
        denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(document) / average_length)
        score += inverse * frequency * 2.5 / denominator
    return score


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalize_keyword(value))

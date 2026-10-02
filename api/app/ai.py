from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings

try:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
except ImportError:  # pragma: no cover - exercised only before optional deps are installed
    ChatPromptTemplate = None
    ChatOllama = None
    OllamaEmbeddings = None
    ChatOpenAI = None
    OpenAIEmbeddings = None

settings = get_settings()
StructuredModel = TypeVar("StructuredModel", bound=BaseModel)

STRICT_JSON_RULES = (
    "Return only valid JSON. Do not include Markdown, prose, code fences, comments, or explanations. "
    "The JSON must match the supplied schema exactly. Use double quotes for every string. "
    "If evidence is missing, fill the required field with a concise uncertainty note instead of omitting it."
)


class EvidenceCitation(BaseModel):
    paper_id: str | None = None
    title: str | None = None
    page: int
    excerpt: str
    chunk_id: str | None = None


class ResearchPlan(BaseModel):
    search_queries: list[str] = Field(min_length=1, max_length=5)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=6)


class CandidateChoice(BaseModel):
    arxiv_id: str
    rationale: str


class CandidateSelection(BaseModel):
    selected: list[CandidateChoice] = Field(default_factory=list)


class PaperFinding(BaseModel):
    label: str
    summary: str
    citations: list[EvidenceCitation]


class EvidenceValidationError(ValueError):
    pass


class AIProviderError(RuntimeError):
    """An AI provider could not complete an operation."""


class AIOutputValidationError(AIProviderError):
    """Both structured-output attempts failed parsing or evidence validation."""


class ResearchBrief(BaseModel):
    executive_summary: str
    key_findings: list[PaperFinding]
    evidence_table: list[PaperFinding]
    conflicts_or_gaps: list[PaperFinding]
    suggested_experiments: list[PaperFinding]
    suggested_research_directions: list[PaperFinding]
    generation_mode: str = "ai"
    warnings: list[str] = Field(default_factory=list)


class BatchPaperSummary(BaseModel):
    paper_id: str
    title: str
    main_idea: str
    problem_or_hypothesis: str
    experiments: str
    models_and_datasets: str
    results: str
    conclusions: str


class BatchSummary(BaseModel):
    overall_takeaway: str
    papers: list[BatchPaperSummary]
    generation_mode: str = "ai"
    warnings: list[str] = Field(default_factory=list)


@dataclass
class SummaryPayload:
    sections: dict[str, str]
    section_citations: dict[str, list[dict[str, str | int]]]
    highlights: list[dict[str, Any]]
    generation_mode: str = "ai"
    warnings: list[str] = field(default_factory=list)


@dataclass
class ChatPayload:
    answer: str
    citations: list[dict[str, str | int]]
    generation_mode: str = "ai"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    fingerprint: str

    @property
    def dimension(self) -> int | None:
        return len(self.vectors[0]) if self.vectors else None


class AIProvider:
    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        raise NotImplementedError

    def plan_research(self, question: str) -> ResearchPlan:
        raise NotImplementedError

    def select_relevant_candidates(
        self,
        question: str,
        candidates: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> CandidateSelection:
        raise NotImplementedError

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        raise NotImplementedError

    def synthesize_collection(
        self,
        question: str,
        paper_contexts: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> ResearchBrief:
        raise NotImplementedError

    def summarize_batch(self, goal: str, paper_contexts: list[dict[str, Any]]) -> BatchSummary:
        raise NotImplementedError

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        raise NotImplementedError


class MockProvider(AIProvider):
    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[hash_embedding(text) for text in texts],
            fingerprint=f"mock:hash-v1:{settings.embedding_dim}",
        )

    def plan_research(self, question: str) -> ResearchPlan:
        return deterministic_research_plan(question)

    def select_relevant_candidates(
        self,
        question: str,
        candidates: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> CandidateSelection:
        ranked = sorted(candidates, key=lambda candidate: candidate.get("score", 0), reverse=True)[:3]
        return CandidateSelection(
            selected=[
                CandidateChoice(
                    arxiv_id=candidate["arxiv_id"],
                    rationale=candidate.get("rationale") or "Selected as one of the highest-ranked candidates.",
                )
                for candidate in ranked
            ]
        )

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        top_chunks = chunks[: min(6, len(chunks))]
        combined = " ".join(chunk["text"] for chunk in top_chunks)
        sentences = [sentence.strip() for sentence in combined.replace("\n", " ").split(".") if sentence.strip()]
        sentence_pool = sentences or [f"{paper_title} was parsed, but the extracted text is limited."]

        section_names = [
            "problem_or_hypothesis",
            "approach",
            "experiments",
            "results",
            "conclusion",
            "limitations_or_notes",
        ]
        sections: dict[str, str] = {}
        section_citations: dict[str, list[dict[str, str | int]]] = {}
        highlights: list[dict[str, Any]] = []

        for index, section_name in enumerate(section_names):
            citation_source = top_chunks[min(index, len(top_chunks) - 1)] if top_chunks else None
            sentence = sentence_pool[index % len(sentence_pool)]
            sections[section_name] = sentence if sentence.endswith(".") else f"{sentence}."
            section_citations[section_name] = [make_citation(citation_source)] if citation_source else []

        highlight_labels = ["Problem", "Method", "Result"]
        for index, chunk in enumerate(top_chunks[:3]):
            highlights.append(
                {
                    "position": index,
                    "label": highlight_labels[index] if index < len(highlight_labels) else "Reading point",
                    "explanation": chunk["text"][:240].strip() or "Important supporting passage.",
                    "citations": [make_citation(chunk)],
                }
            )

        return SummaryPayload(
            sections=sections,
            section_citations=section_citations,
            highlights=highlights,
            generation_mode="mock",
            warnings=["AI_PROVIDER=mock; this output is deterministic demonstration data."],
        )

    def synthesize_collection(
        self,
        question: str,
        paper_contexts: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> ResearchBrief:
        findings = []
        for index, context in enumerate(paper_contexts[:5]):
            citation = first_context_citation(context)
            findings.append(
                PaperFinding(
                    label=f"Finding {index + 1}",
                    summary=f"{context['title']} contributes evidence relevant to: {question}",
                    citations=[citation],
                )
            )

        if not findings:
            empty = PaperFinding(label="Insufficient evidence", summary="No analyzed papers are available yet.", citations=[])
            findings = [empty]

        return ResearchBrief(
            executive_summary=f"This brief synthesizes {len(paper_contexts)} papers for: {question}",
            key_findings=findings,
            evidence_table=findings,
            conflicts_or_gaps=[
                PaperFinding(
                    label="Evidence gap",
                    summary="Compare the papers for missing benchmark coverage, dataset constraints, or limited evaluation detail.",
                    citations=findings[0].citations,
                )
            ],
            suggested_experiments=[
                PaperFinding(
                    label="Controlled comparison",
                    summary="Run a controlled experiment that compares the strongest methods under the same data and metrics.",
                    citations=findings[0].citations,
                )
            ],
            suggested_research_directions=[
                PaperFinding(
                    label="Grounded extension",
                    summary="Extend the most promising method to the target domain and measure factuality, robustness, and cost.",
                    citations=findings[0].citations,
                )
            ],
            generation_mode="mock",
            warnings=["AI_PROVIDER=mock; this brief is deterministic demonstration data."],
        )

    def summarize_batch(self, goal: str, paper_contexts: list[dict[str, Any]]) -> BatchSummary:
        papers = []
        for context in paper_contexts:
            summary = context.get("summary") or "No summary is available yet."
            papers.append(
                BatchPaperSummary(
                    paper_id=context["paper_id"],
                    title=context["title"],
                    main_idea=summary[:420],
                    problem_or_hypothesis=summary[:420],
                    experiments=summary[:420],
                    models_and_datasets="Review the paper notes for model, dataset, or benchmark mentions.",
                    results=summary[:420],
                    conclusions=summary[:420],
                )
            )
        return BatchSummary(
            overall_takeaway=f"Summarized {len(papers)} papers for: {goal}",
            papers=papers,
            generation_mode="mock",
            warnings=["AI_PROVIDER=mock; this batch summary is deterministic demonstration data."],
        )

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        if not context_chunks:
            return ChatPayload(
                answer="I do not have enough grounded evidence from the paper to answer that reliably.",
                citations=[],
                generation_mode="mock",
                warnings=["AI_PROVIDER=mock; this answer is deterministic demonstration data."],
            )

        lead = context_chunks[0]
        answer = (
            f"Based on the retrieved passages from {paper_title}, the strongest evidence for your question "
            f"comes from page {lead['page_start']}. {lead['text'][:360].strip()}"
        )
        if len(context_chunks) > 1:
            answer += f" A second supporting passage appears on page {context_chunks[1]['page_start']}."
        return ChatPayload(
            answer=answer,
            citations=[make_citation(chunk) for chunk in context_chunks[:2]],
            generation_mode="mock",
            warnings=["AI_PROVIDER=mock; this answer is deterministic demonstration data."],
        )


class LangChainProvider(AIProvider):
    def __init__(self) -> None:
        if ChatPromptTemplate is None:
            raise AIProviderError("LangChain dependencies are not installed")
        try:
            self.chat_model = build_chat_model()
            self.embedding_model = build_embedding_model()
        except Exception as exc:
            raise AIProviderError(f"Could not initialize {settings.ai_provider}: {exc}") from exc
        if settings.ai_provider == "openai":
            self.embedding_fingerprint = f"openai:{settings.openai_embed_model}"
        elif settings.ai_provider == "ollama":
            self.embedding_fingerprint = f"ollama:{settings.ollama_embed_model}"
        else:  # pragma: no cover - guarded by get_ai_provider
            raise AIProviderError(f"Unsupported AI provider: {settings.ai_provider}")

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if self.embedding_model is None:
            raise AIProviderError(f"No embedding model is configured for {settings.ai_provider}")
        try:
            vectors = self.embedding_model.embed_documents(texts)
        except Exception as exc:
            raise AIProviderError(f"{settings.ai_provider} embedding failed: {exc}") from exc
        return EmbeddingResult(vectors=vectors, fingerprint=self.embedding_fingerprint)

    def plan_research(self, question: str) -> ResearchPlan:
        return invoke_structured_json(
            self.chat_model,
            ResearchPlan,
            "Plan a focused arXiv literature search with short keyword-style search queries and concrete inclusion criteria.",
            "Research question: {question}",
            {"question": question},
        )

    def select_relevant_candidates(
        self,
        question: str,
        candidates: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> CandidateSelection:
        offered_ids = {candidate["arxiv_id"] for candidate in candidates}
        return invoke_structured_json(
            self.chat_model,
            CandidateSelection,
            "Select the 3 to 5 most relevant arXiv candidates for the research question. Use memory as a weak preference signal, but do not select irrelevant papers just because memory mentions related terms.",
            "Question: {question}\nMemory signals:\n{memory_context}\nCandidates:\n{candidates}",
            {"question": question, "memory_context": format_memories(memory_context or []), "candidates": format_candidates(candidates)},
            validator=lambda output: validate_candidate_selection(output, offered_ids),
        )

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        summary_chunks = select_summary_chunks(chunks)
        registry = EvidenceRegistry.from_chunks(summary_chunks)
        output = invoke_structured_json(
            self.chat_model,
            PaperSummaryDraft,
            "Summarize the paper using only supplied chunks, which are ordered across the paper. Prefer detailed body evidence over abstract-level claims: use methods chunks for approach, evaluation chunks for experiments and results, and discussion or limitation chunks for limitations. For every section and highlight, select one or more exact supplied chunk IDs as evidence. Do not invent chunk IDs.",
            "Title: {title}\nChunks:\n{context}",
            {"title": paper_title, "context": format_chunks(summary_chunks)},
            validator=lambda value: validate_summary_draft(value, registry),
        )
        section_names = (
            "problem_or_hypothesis",
            "approach",
            "experiments",
            "results",
            "conclusion",
            "limitations_or_notes",
        )
        chunks_by_id = {str(chunk["id"]): chunk for chunk in summary_chunks}
        return SummaryPayload(
            sections={name: getattr(output, name).text for name in section_names},
            section_citations={
                name: citations_for_chunk_ids(getattr(output, name).chunk_ids, chunks_by_id)
                for name in section_names
            },
            highlights=[
                {
                    "position": position,
                    "label": highlight.label,
                    "explanation": highlight.explanation,
                    "citations": citations_for_chunk_ids(highlight.chunk_ids, chunks_by_id),
                }
                for position, highlight in enumerate(output.highlights)
            ],
            generation_mode="ai",
        )

    def synthesize_collection(
        self,
        question: str,
        paper_contexts: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> ResearchBrief:
        registry = EvidenceRegistry.from_paper_contexts(paper_contexts)
        output = invoke_structured_json(
            self.chat_model,
            ResearchBrief,
            "Synthesize a collection of papers. Every finding, gap, experiment, and direction must cite supplied evidence. Use memory only to prioritize emphasis; do not cite memory as evidence.",
            "Question: {question}\nMemory signals:\n{memory_context}\nPaper evidence:\n{context}",
            {"question": question, "memory_context": format_memories(memory_context or []), "context": format_paper_contexts(paper_contexts)},
            validator=lambda value: validate_brief_evidence(value, registry),
        )
        output.generation_mode = "ai"
        output.warnings = []
        return output

    def summarize_batch(self, goal: str, paper_contexts: list[dict[str, Any]]) -> BatchSummary:
        expected_ids = {context["paper_id"] for context in paper_contexts}
        output = invoke_structured_json(
            self.chat_model,
            BatchSummary,
            "Summarize a batch of research papers into a comparison table using only supplied evidence.",
            "Goal: {goal}\nPaper evidence:\n{context}",
            {"goal": goal, "context": format_paper_contexts(paper_contexts)},
            validator=lambda value: validate_batch_output(value, expected_ids),
        )
        output.generation_mode = "ai"
        output.warnings = []
        return output

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        output = invoke_structured_json(
            self.chat_model,
            ChatDraft,
            "Answer using only the supplied paper chunks. If evidence is weak, say so. Select exact supplied chunk IDs that support the answer; do not copy or invent citation metadata.",
            "Title: {title}\nQuestion: {question}\nHistory: {history}\nChunks:\n{context}",
            {
                "title": paper_title,
                "question": question,
                "history": history[-6:],
                "context": format_chunks(context_chunks),
            },
            validator=lambda value: validate_chat_draft(value, EvidenceRegistry.from_chunks(context_chunks)),
        )
        chunks_by_id = {str(chunk["id"]): chunk for chunk in context_chunks}
        return ChatPayload(
            answer=output.answer,
            citations=citations_for_chunk_ids(output.chunk_ids, chunks_by_id),
            generation_mode="ai",
        )


class CitedSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citations: list[EvidenceCitation] = Field(min_length=1)


class HighlightOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    label: str
    explanation: str
    citations: list[EvidenceCitation] = Field(min_length=1)


class PaperSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_or_hypothesis: CitedSummarySection
    approach: CitedSummarySection
    experiments: CitedSummarySection
    results: CitedSummarySection
    conclusion: CitedSummarySection
    limitations_or_notes: CitedSummarySection
    highlights: list[HighlightOutput]


class SummarySectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    chunk_ids: list[str] = Field(min_length=1)


class SummaryHighlightDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    explanation: str
    chunk_ids: list[str] = Field(min_length=1)


class PaperSummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_or_hypothesis: SummarySectionDraft
    approach: SummarySectionDraft
    experiments: SummarySectionDraft
    results: SummarySectionDraft
    conclusion: SummarySectionDraft
    limitations_or_notes: SummarySectionDraft
    highlights: list[SummaryHighlightDraft]


class ChatOutput(BaseModel):
    answer: str
    citations: list[EvidenceCitation]


class ChatDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    chunk_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class EvidenceRecord:
    chunk_id: str
    text: str
    page_start: int
    page_end: int
    paper_id: str | None = None
    title: str | None = None


class EvidenceRegistry:
    def __init__(self, records: list[EvidenceRecord]) -> None:
        self.records = {record.chunk_id: record for record in records}

    @classmethod
    def from_chunks(cls, chunks: list[dict[str, Any]]) -> "EvidenceRegistry":
        return cls(
            [
                EvidenceRecord(
                    chunk_id=str(chunk["id"]),
                    text=str(chunk["text"]),
                    page_start=int(chunk["page_start"]),
                    page_end=int(chunk.get("page_end", chunk["page_start"])),
                    paper_id=str(chunk["paper_id"]) if chunk.get("paper_id") else None,
                    title=str(chunk["title"]) if chunk.get("title") else None,
                )
                for chunk in chunks
            ]
        )

    @classmethod
    def from_paper_contexts(cls, contexts: list[dict[str, Any]]) -> "EvidenceRegistry":
        records = []
        for context in contexts:
            for chunk in context.get("chunks", []):
                records.append(
                    EvidenceRecord(
                        chunk_id=str(chunk["id"]),
                        text=str(chunk["text"]),
                        page_start=int(chunk["page_start"]),
                        page_end=int(chunk.get("page_end", chunk["page_start"])),
                        paper_id=str(context["paper_id"]),
                        title=str(context["title"]),
                    )
                )
        return cls(records)


def normalize_evidence_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def validate_citations(
    citations: list[EvidenceCitation] | list[dict[str, Any]],
    registry: EvidenceRegistry,
    *,
    require_paper_identity: bool = False,
    require_at_least_one: bool = True,
) -> None:
    if not citations and require_at_least_one:
        raise EvidenceValidationError("At least one citation is required")
    for raw_citation in citations:
        citation = raw_citation if isinstance(raw_citation, EvidenceCitation) else EvidenceCitation.model_validate(raw_citation)
        if not citation.chunk_id or citation.chunk_id not in registry.records:
            raise EvidenceValidationError(f"Unknown evidence chunk: {citation.chunk_id}")
        record = registry.records[citation.chunk_id]
        if not record.page_start <= citation.page <= record.page_end:
            raise EvidenceValidationError(
                f"Citation page {citation.page} is outside chunk {record.chunk_id} pages "
                f"{record.page_start}-{record.page_end}"
            )
        excerpt = normalize_evidence_text(citation.excerpt)
        if not excerpt or excerpt not in normalize_evidence_text(record.text):
            raise EvidenceValidationError(f"Citation excerpt is not verbatim evidence from chunk {record.chunk_id}")
        if require_paper_identity:
            if not citation.paper_id or citation.paper_id != record.paper_id:
                raise EvidenceValidationError(f"Citation paper does not match chunk {record.chunk_id}")
            if not citation.title or normalize_evidence_text(citation.title) != normalize_evidence_text(record.title or ""):
                raise EvidenceValidationError(f"Citation title does not match chunk {record.chunk_id}")


def validate_summary_evidence(output: PaperSummaryOutput, registry: EvidenceRegistry) -> None:
    for section_name in (
        "problem_or_hypothesis",
        "approach",
        "experiments",
        "results",
        "conclusion",
        "limitations_or_notes",
    ):
        validate_citations(getattr(output, section_name).citations, registry)
    for highlight in output.highlights:
        validate_citations(highlight.citations, registry)


def validate_summary_draft(output: PaperSummaryDraft, registry: EvidenceRegistry) -> None:
    sections = (
        output.problem_or_hypothesis,
        output.approach,
        output.experiments,
        output.results,
        output.conclusion,
        output.limitations_or_notes,
        *output.highlights,
    )
    for section in sections:
        unknown_ids = sorted(set(section.chunk_ids) - set(registry.records))
        if unknown_ids:
            raise EvidenceValidationError(f"Summary selected unknown chunk IDs: {', '.join(unknown_ids)}")


def validate_chat_draft(output: ChatDraft, registry: EvidenceRegistry) -> None:
    unknown_ids = sorted(set(output.chunk_ids) - set(registry.records))
    if unknown_ids:
        raise EvidenceValidationError(f"Chat answer selected unknown chunk IDs: {', '.join(unknown_ids)}")


def unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def citations_for_chunk_ids(
    chunk_ids: list[str],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, str | int]]:
    citations: list[dict[str, str | int]] = []
    cited_pages: set[int] = set()
    for chunk_id in unique_values(chunk_ids):
        chunk = chunks_by_id[chunk_id]
        page = int(chunk["page_start"])
        if page in cited_pages:
            continue
        cited_pages.add(page)
        citations.append(make_citation(chunk))
    return citations


def select_summary_chunks(
    chunks: list[dict[str, Any]],
    *,
    max_chars: int = 25_000,
    max_chunks: int = 14,
) -> list[dict[str, Any]]:
    if not chunks:
        return []
    ordered = trim_reference_section(
        sorted(chunks, key=lambda chunk: int(chunk.get("chunk_index", 0)))
    )
    if len(ordered) <= max_chunks and sum(len(str(chunk.get("text", ""))) for chunk in ordered) <= max_chars:
        return ordered

    page_groups: list[list[int]] = []
    for index, chunk in enumerate(ordered):
        page_number = int(chunk.get("page_start", 0))
        if not page_groups or int(ordered[page_groups[-1][0]].get("page_start", 0)) != page_number:
            page_groups.append([])
        page_groups[-1].append(index)

    if len(page_groups) <= max_chunks:
        selected_indexes = {group[0] for group in page_groups}
    else:
        selected_indexes = {
            page_groups[index][0]
            for index in evenly_spaced_indexes(len(page_groups), max_chunks)
        }
    remaining_indexes = [index for index in range(len(ordered)) if index not in selected_indexes]
    extra_count = min(max_chunks - len(selected_indexes), len(remaining_indexes))
    if extra_count:
        selected_indexes.update(
            remaining_indexes[index]
            for index in evenly_spaced_indexes(len(remaining_indexes), extra_count)
        )

    selected = [ordered[index] for index in sorted(selected_indexes)]
    while len(selected) > 1:
        if sum(len(str(chunk.get("text", ""))) for chunk in selected) <= max_chars:
            return selected
        selected = [selected[index] for index in evenly_spaced_indexes(len(selected), len(selected) - 1)]
    return [ordered[0]]


def trim_reference_section(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body: list[dict[str, Any]] = []
    minimum_reference_index = max(1, len(chunks) // 5)
    for index, chunk in enumerate(chunks):
        text = str(chunk.get("text", ""))
        match = re.search(r"(?im)^\s*references\s*$", text)
        if match is None or index < minimum_reference_index:
            body.append(chunk)
            continue
        prefix = text[: match.start()].strip()
        if prefix:
            body.append({**chunk, "text": prefix})
        break
    return body or chunks


def evenly_spaced_indexes(item_count: int, selected_count: int) -> list[int]:
    if selected_count <= 1:
        return [0]
    return list(
        dict.fromkeys(
            round(position * (item_count - 1) / (selected_count - 1))
            for position in range(selected_count)
        )
    )


def validate_summary_payload(payload: SummaryPayload, chunks: list[dict[str, Any]]) -> None:
    registry = EvidenceRegistry.from_chunks(chunks)
    required_sections = {
        "problem_or_hypothesis",
        "approach",
        "experiments",
        "results",
        "conclusion",
        "limitations_or_notes",
    }
    if set(payload.sections) != required_sections or set(payload.section_citations) != required_sections:
        raise EvidenceValidationError("Summary must contain exactly the six required sections")
    for section_name in required_sections:
        if not payload.sections[section_name].strip():
            raise EvidenceValidationError(f"Summary section {section_name} is empty")
        validate_citations(payload.section_citations[section_name], registry)
    for highlight in payload.highlights:
        validate_citations(highlight.get("citations", []), registry)


def validate_brief_evidence(brief: ResearchBrief, registry: EvidenceRegistry) -> None:
    for finding in (
        *brief.key_findings,
        *brief.evidence_table,
        *brief.conflicts_or_gaps,
        *brief.suggested_experiments,
        *brief.suggested_research_directions,
    ):
        validate_citations(finding.citations, registry, require_paper_identity=True)


def validate_candidate_selection(selection: CandidateSelection, offered_ids: set[str]) -> None:
    selected_ids = [choice.arxiv_id for choice in selection.selected]
    if not selected_ids:
        raise EvidenceValidationError("Candidate selection did not contain any offered candidates")
    unknown = sorted(set(selected_ids) - offered_ids)
    if unknown:
        raise EvidenceValidationError(f"Candidate selection invented IDs: {', '.join(unknown)}")
    if len(selected_ids) != len(set(selected_ids)):
        raise EvidenceValidationError("Candidate selection contains duplicate IDs")


def validate_batch_output(output: BatchSummary, expected_ids: set[str]) -> None:
    actual_ids = [paper.paper_id for paper in output.papers]
    if len(actual_ids) != len(set(actual_ids)):
        raise EvidenceValidationError("Batch output contains duplicate paper IDs")
    actual_set = set(actual_ids)
    if actual_set != expected_ids:
        missing = sorted(expected_ids - actual_set)
        invented = sorted(actual_set - expected_ids)
        raise EvidenceValidationError(f"Batch output ID mismatch; missing={missing}, invented={invented}")


STRUCTURED_OUTPUT_EXAMPLES: dict[str, dict[str, Any]] = {
    "ResearchPlan": {
        "search_queries": [
            "retrieval augmented generation hallucination factuality",
            "RAG question answering benchmark",
        ],
        "inclusion_criteria": [
            "Directly addresses the research question.",
            "Reports methods, experiments, or evaluation results.",
        ],
    },
    "CandidateSelection": {
        "selected": [
            {
                "arxiv_id": "2310.11511",
                "rationale": "The abstract directly studies retrieval-augmented generation evaluation and factuality.",
            }
        ]
    },
    "PaperSummaryOutput": {
        "problem_or_hypothesis": {
            "text": "The paper studies whether retrieval grounding improves factual question answering.",
            "citations": [{"page": 1, "excerpt": "The paper studies retrieval grounding.", "chunk_id": "chunk-1"}],
        },
        "approach": {
            "text": "The authors compare a retrieval-augmented system against non-retrieval baselines.",
            "citations": [{"page": 2, "excerpt": "The method retrieves relevant passages.", "chunk_id": "chunk-2"}],
        },
        "experiments": {
            "text": "The paper evaluates models on benchmark question-answering datasets.",
            "citations": [{"page": 3, "excerpt": "Experiments use benchmark datasets.", "chunk_id": "chunk-3"}],
        },
        "results": {
            "text": "The retrieval-augmented system improves grounded answer quality in the reported setting.",
            "citations": [{"page": 4, "excerpt": "Results improve over baselines.", "chunk_id": "chunk-4"}],
        },
        "conclusion": {
            "text": "Retrieval can improve factuality when retrieved passages are relevant.",
            "citations": [{"page": 5, "excerpt": "The authors conclude retrieval helps.", "chunk_id": "chunk-5"}],
        },
        "limitations_or_notes": {
            "text": "The supplied evidence is limited to the provided chunks.",
            "citations": [{"page": 6, "excerpt": "Limitations are discussed.", "chunk_id": "chunk-6"}],
        },
        "highlights": [
            {
                "position": 0,
                "label": "Main result",
                "explanation": "The strongest result is the improvement from retrieval grounding.",
                "citations": [{"page": 4, "excerpt": "Results improve over baselines.", "chunk_id": "chunk-4"}],
            }
        ],
    },
    "PaperSummaryDraft": {
        "problem_or_hypothesis": {
            "text": "The paper studies whether retrieval grounding improves factual question answering.",
            "chunk_ids": ["chunk-1"],
        },
        "approach": {
            "text": "The authors compare a retrieval-augmented system against non-retrieval baselines.",
            "chunk_ids": ["chunk-2"],
        },
        "experiments": {
            "text": "The paper evaluates models on benchmark question-answering datasets.",
            "chunk_ids": ["chunk-3"],
        },
        "results": {
            "text": "The retrieval-augmented system improves grounded answer quality in the reported setting.",
            "chunk_ids": ["chunk-4"],
        },
        "conclusion": {
            "text": "Retrieval can improve factuality when retrieved passages are relevant.",
            "chunk_ids": ["chunk-5"],
        },
        "limitations_or_notes": {
            "text": "The supplied evidence is limited to the provided chunks.",
            "chunk_ids": ["chunk-6"],
        },
        "highlights": [
            {
                "label": "Main result",
                "explanation": "The strongest result is the improvement from retrieval grounding.",
                "chunk_ids": ["chunk-4"],
            }
        ],
    },
    "ResearchBrief": {
        "executive_summary": "The collection suggests retrieval grounding is useful, but evaluation quality varies.",
        "key_findings": [
            {
                "label": "Retrieval helps factuality",
                "summary": "Several papers report stronger grounded answering when retrieved passages are relevant.",
                "citations": [{"paper_id": "paper-1", "title": "Example Paper", "page": 4, "excerpt": "Results improve.", "chunk_id": "chunk-4"}],
            }
        ],
        "evidence_table": [
            {
                "label": "Example Paper",
                "summary": "The paper evaluates retrieval-augmented answering against baselines.",
                "citations": [{"paper_id": "paper-1", "title": "Example Paper", "page": 3, "excerpt": "Benchmark evaluation.", "chunk_id": "chunk-3"}],
            }
        ],
        "conflicts_or_gaps": [
            {
                "label": "Evaluation gap",
                "summary": "The evidence does not fully establish cross-domain robustness.",
                "citations": [{"paper_id": "paper-1", "title": "Example Paper", "page": 6, "excerpt": "Limitations remain.", "chunk_id": "chunk-6"}],
            }
        ],
        "suggested_experiments": [
            {
                "label": "Controlled ablation",
                "summary": "Compare retrieval, fine-tuning, and combined systems under the same datasets and metrics.",
                "citations": [{"paper_id": "paper-1", "title": "Example Paper", "page": 3, "excerpt": "Benchmark setup.", "chunk_id": "chunk-3"}],
            }
        ],
        "suggested_research_directions": [
            {
                "label": "Robust retrieval",
                "summary": "Study retrieval quality under noisy or domain-shifted queries.",
                "citations": [{"paper_id": "paper-1", "title": "Example Paper", "page": 6, "excerpt": "Limitations remain.", "chunk_id": "chunk-6"}],
            }
        ],
    },
    "BatchSummary": {
        "overall_takeaway": "The uploaded papers focus on related methods but vary in datasets and evaluation depth.",
        "papers": [
            {
                "paper_id": "paper-1",
                "title": "Example Paper",
                "main_idea": "Retrieval improves grounded question answering.",
                "problem_or_hypothesis": "The paper tests whether retrieval reduces unsupported answers.",
                "experiments": "The authors compare retrieval and non-retrieval baselines.",
                "models_and_datasets": "The paper reports the models and datasets available in the supplied evidence.",
                "results": "The retrieval setup improves the reported metrics.",
                "conclusions": "Retrieval is useful when evidence passages are relevant.",
            }
        ],
    },
    "ChatOutput": {
        "answer": "The supplied chunks support the claim that retrieval improves answer grounding, but the evidence is limited to the retrieved passages.",
        "citations": [{"page": 4, "excerpt": "Results improve over baselines.", "chunk_id": "chunk-4"}],
    },
    "ChatDraft": {
        "answer": "The supplied chunks support the claim that retrieval improves answer grounding, but the evidence is limited to the retrieved passages.",
        "chunk_ids": ["chunk-4"],
    },
}


def invoke_structured_json(
    chat_model: Any,
    output_model: type[StructuredModel],
    task: str,
    human_template: str,
    payload: dict[str, Any],
    validator: Callable[[StructuredModel], None] | None = None,
) -> StructuredModel:
    schema_name = output_model.__name__
    schema = json.dumps(output_model.model_json_schema(), ensure_ascii=True)
    example = json.dumps(STRUCTURED_OUTPUT_EXAMPLES[schema_name], ensure_ascii=True)
    system_prompt = (
        f"{STRICT_JSON_RULES}\n\n"
        f"Task: {task}\n\n"
        f"JSON schema:\n{schema}\n\n"
        f"Example valid JSON:\n{example}"
    )
    retry_system_prompt = (
        f"{STRICT_JSON_RULES}\n\n"
        "The previous attempt did not produce valid schema-compliant JSON. "
        "Try once more and return only one JSON object.\n\n"
        f"Task: {task}\n\n"
        f"JSON schema:\n{schema}\n\n"
        f"Example valid JSON:\n{example}"
    )

    first_error: Exception | None = None
    for attempt, attempt_prompt in enumerate((system_prompt, retry_system_prompt), start=1):
        try:
            structured_method = None
            if ChatOllama is not None and isinstance(chat_model, ChatOllama):
                model_name = str(getattr(chat_model, "model", ""))
                if model_name.endswith("-cloud"):
                    structured_method = "prompted_json"
                else:
                    structured_method = "json_schema" if attempt == 1 else "json_mode"
            result = invoke_structured_once(
                chat_model,
                output_model,
                attempt_prompt,
                human_template,
                payload,
                structured_method=structured_method,
            )
            if validator is not None:
                validator(result)
            return result
        except Exception as exc:  # the second failure is converted into a stable domain error
            if is_provider_timeout(exc):
                raise AIProviderError(
                    "Structured generation timed out after "
                    f"{settings.ai_chat_timeout_seconds:g} seconds; repair attempt skipped."
                ) from exc
            if attempt == 1:
                first_error = exc
                continue
            message = f"Structured generation failed twice: first={first_error}; second={exc}"
            if isinstance(exc, (EvidenceValidationError, ValidationError)):
                raise AIOutputValidationError(message) from exc
            raise AIProviderError(message) from exc

    raise AIProviderError("Structured generation did not run")  # pragma: no cover


def invoke_structured_once(
    chat_model: Any,
    output_model: type[StructuredModel],
    system_prompt: str,
    human_template: str,
    payload: dict[str, Any],
    *,
    structured_method: str | None = None,
) -> StructuredModel:
    prompt = ChatPromptTemplate.from_messages([("system", escape_template_text(system_prompt)), ("human", human_template)])
    if structured_method == "prompted_json":
        response = (prompt | chat_model).invoke(payload)
        return parse_prompted_json(response.content, output_model)
    structured_options = {"method": structured_method} if structured_method else {}
    chain = prompt | chat_model.with_structured_output(output_model, **structured_options)
    return chain.invoke(payload)


def parse_prompted_json(content: Any, output_model: type[StructuredModel]) -> StructuredModel:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    else:
        text = str(content).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        object_start = text.find("{")
        object_end = text.rfind("}")
        if object_start < 0 or object_end < object_start:
            raise ValueError("Model response did not contain a JSON object")
        text = text[object_start : object_end + 1]
    return output_model.model_validate_json(text)


def escape_template_text(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def is_provider_timeout(error: BaseException) -> bool:
    """Recognize timeout errors even when a provider SDK wraps the HTTP exception."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        class_name = type(current).__name__.lower()
        if isinstance(current, TimeoutError) or "timeout" in class_name:
            return True
        message = str(current).lower()
        if "timed out" in message or "timeout exceeded" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def build_chat_model() -> Any:
    if settings.ai_provider == "openai":
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            request_timeout=settings.ai_chat_timeout_seconds,
            max_tokens=settings.ai_max_output_tokens,
            max_retries=0,
        )
    return ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        reasoning=settings.ollama_reasoning_effort,
        num_predict=settings.ai_max_output_tokens,
        client_kwargs={"timeout": settings.ai_chat_timeout_seconds},
    )


def build_embedding_model() -> Any:
    if settings.ai_provider == "openai" and OpenAIEmbeddings is not None:
        return OpenAIEmbeddings(
            model=settings.openai_embed_model,
            api_key=settings.openai_api_key,
            request_timeout=settings.ai_embedding_timeout_seconds,
            max_retries=0,
        )
    if settings.ai_provider == "ollama" and OllamaEmbeddings is not None:
        return OllamaEmbeddings(
            model=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
            client_kwargs={"timeout": settings.ai_embedding_timeout_seconds},
        )
    return None


def make_citation(chunk: dict[str, Any]) -> dict[str, str | int]:
    excerpt = chunk["text"].replace("\n", " ").strip()[:220]
    return {"page": chunk["page_start"], "excerpt": excerpt, "chunk_id": chunk["id"]}


def deterministic_research_plan(question: str) -> ResearchPlan:
    compact = " ".join(question.split())
    return ResearchPlan(
        search_queries=[compact, f"{compact} survey", f"{compact} benchmark"],
        inclusion_criteria=[
            "Paper directly addresses the research question.",
            "Paper includes methods, experiments, or evaluations.",
            "Paper provides evidence useful for comparing approaches.",
        ],
    )


def build_extractive_summary(
    paper_title: str,
    chunks: list[dict[str, Any]],
    warning: str,
) -> SummaryPayload:
    if not chunks:
        raise EvidenceValidationError("Cannot build an extractive summary without paper chunks")
    section_names = (
        "problem_or_hypothesis",
        "approach",
        "experiments",
        "results",
        "conclusion",
        "limitations_or_notes",
    )
    selected = [chunks[index % len(chunks)] for index in range(len(section_names))]
    sections = {
        name: f"Source extract from {paper_title}: {chunk['text'].replace(chr(10), ' ').strip()[:600]}"
        for name, chunk in zip(section_names, selected, strict=True)
    }
    section_citations = {
        name: [make_citation(chunk)] for name, chunk in zip(section_names, selected, strict=True)
    }
    highlights = [
        {
            "position": index,
            "label": f"Source extract {index + 1}",
            "explanation": chunk["text"].replace("\n", " ").strip()[:400],
            "citations": [make_citation(chunk)],
        }
        for index, chunk in enumerate(chunks[:3])
    ]
    return SummaryPayload(
        sections=sections,
        section_citations=section_citations,
        highlights=highlights,
        generation_mode="extractive",
        warnings=[warning],
    )


def build_extractive_chat(
    paper_title: str,
    question: str,
    chunks: list[dict[str, Any]],
    warning: str,
) -> ChatPayload:
    if not chunks:
        return ChatPayload(
            answer=f"No grounded passage from {paper_title} was available to answer: {question}",
            citations=[],
            generation_mode="extractive",
            warnings=[warning],
        )
    selected = chunks[:2]
    extracts = "\n\n".join(chunk["text"].replace("\n", " ").strip()[:500] for chunk in selected)
    return ChatPayload(
        answer=f"The AI provider was unavailable. Relevant source extracts from {paper_title}:\n\n{extracts}",
        citations=[make_citation(chunk) for chunk in selected],
        generation_mode="extractive",
        warnings=[warning],
    )


def build_extractive_brief(
    question: str,
    paper_contexts: list[dict[str, Any]],
    warning: str,
) -> ResearchBrief:
    findings: list[PaperFinding] = []
    for context in paper_contexts:
        if not context.get("chunks"):
            raise EvidenceValidationError(
                f"Cannot build a cited extractive brief for paper {context['paper_id']} without chunks"
            )
        chunk = context["chunks"][0]
        citation = EvidenceCitation(
            paper_id=context["paper_id"],
            title=context["title"],
            **make_citation(chunk),
        )
        findings.append(
            PaperFinding(
                label=context["title"],
                summary=chunk["text"].replace("\n", " ").strip()[:600],
                citations=[citation],
            )
        )
    return ResearchBrief(
        executive_summary=(
            f"AI synthesis was unavailable for '{question}'. This degraded brief contains only source extracts."
        ),
        key_findings=findings,
        evidence_table=[finding.model_copy(deep=True) for finding in findings],
        conflicts_or_gaps=[],
        suggested_experiments=[],
        suggested_research_directions=[],
        generation_mode="extractive",
        warnings=[warning],
    )


def build_extractive_batch(
    goal: str,
    paper_contexts: list[dict[str, Any]],
    warning: str,
) -> BatchSummary:
    papers = [
        BatchPaperSummary(
            paper_id=context["paper_id"],
            title=context["title"],
            main_idea=context["summary"],
            problem_or_hypothesis=context["summary"],
            experiments="Not regenerated; refer to the stored paper summary.",
            models_and_datasets="Not regenerated; refer to the stored paper summary.",
            results=context["summary"],
            conclusions=context["summary"],
        )
        for context in paper_contexts
    ]
    return BatchSummary(
        overall_takeaway=f"AI batch synthesis was unavailable for '{goal}'. Showing stored paper summaries.",
        papers=papers,
        generation_mode="extractive",
        warnings=[warning],
    )


def first_context_citation(context: dict[str, Any]) -> EvidenceCitation:
    chunk = context["chunks"][0] if context.get("chunks") else None
    if chunk is None:
        return EvidenceCitation(paper_id=context["paper_id"], title=context["title"], page=1, excerpt=context["summary"])
    return EvidenceCitation(
        paper_id=context["paper_id"],
        title=context["title"],
        page=chunk["page_start"],
        excerpt=chunk["text"][:220],
        chunk_id=chunk["id"],
    )


def format_chunks(chunks: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[chunk_id={chunk['id']} page={chunk['page_start']}] {chunk['text'][:1200]}" for chunk in chunks
    )


def format_candidates(candidates: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        (
            f"arxiv_id={candidate['arxiv_id']}\n"
            f"title={candidate['title']}\n"
            f"year={candidate.get('year')}\n"
            f"score={candidate.get('score')}\n"
            f"base_score={candidate.get('base_score', candidate.get('score'))}\n"
            f"memory_signal={candidate.get('memory_signal', 'none')}\n"
            f"rationale={candidate.get('rationale')}\n"
            f"abstract={candidate.get('abstract', '')[:900]}"
        )
        for candidate in candidates[:12]
    )


def format_memories(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "No prior memory signals."
    return "\n".join(
        (
            f"- scope={memory.get('scope')} type={memory.get('memory_type')} "
            f"importance={memory.get('importance', 1)} text={str(memory.get('text', ''))[:600]}"
        )
        for memory in memories[:8]
    )


def format_paper_contexts(paper_contexts: list[dict[str, Any]]) -> str:
    parts = []
    for paper in paper_contexts:
        chunks = format_chunks(paper.get("chunks", [])[:4])
        parts.append(f"paper_id={paper['paper_id']}\ntitle={paper['title']}\nsummary={paper['summary']}\n{chunks}")
    return "\n\n---\n\n".join(parts)


def hash_embedding(text: str) -> list[float]:
    vector: list[float] = []
    for index in range(settings.embedding_dim):
        digest = hashlib.sha256(f"{index}:{text}".encode("utf-8")).hexdigest()
        value = int(digest[:8], 16) / 0xFFFFFFFF
        vector.append((value * 2.0) - 1.0)
    norm = math.sqrt(sum(component * component for component in vector)) or 1.0
    return [component / norm for component in vector]


def get_ai_provider() -> AIProvider:
    if settings.ai_provider in {"ollama", "openai"}:
        return LangChainProvider()
    if settings.ai_provider == "mock":
        return MockProvider()
    raise AIProviderError(f"Unknown AI_PROVIDER={settings.ai_provider}")

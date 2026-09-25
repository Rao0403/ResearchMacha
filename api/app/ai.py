from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.fallbacks import record_fallback

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


class ResearchBrief(BaseModel):
    executive_summary: str
    key_findings: list[PaperFinding]
    evidence_table: list[PaperFinding]
    conflicts_or_gaps: list[PaperFinding]
    suggested_experiments: list[PaperFinding]
    suggested_research_directions: list[PaperFinding]


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


@dataclass
class SummaryPayload:
    sections: dict[str, str]
    section_citations: dict[str, list[dict[str, str | int]]]
    highlights: list[dict[str, Any]]


@dataclass
class ChatPayload:
    answer: str
    citations: list[dict[str, str | int]]


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
        compact = " ".join(question.split())
        return ResearchPlan(
            search_queries=[
                compact,
                f"{compact} survey",
                f"{compact} benchmark",
            ],
            inclusion_criteria=[
                "Paper directly addresses the research question.",
                "Paper includes methods, experiments, or evaluations.",
                "Paper provides evidence useful for comparing approaches.",
            ],
        )

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

        return SummaryPayload(sections=sections, section_citations=section_citations, highlights=highlights)

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
            )

        lead = context_chunks[0]
        answer = (
            f"Based on the retrieved passages from {paper_title}, the strongest evidence for your question "
            f"comes from page {lead['page_start']}. {lead['text'][:360].strip()}"
        )
        if len(context_chunks) > 1:
            answer += f" A second supporting passage appears on page {context_chunks[1]['page_start']}."
        return ChatPayload(answer=answer, citations=[make_citation(chunk) for chunk in context_chunks[:2]])


class LangChainProvider(MockProvider):
    def __init__(self) -> None:
        if ChatPromptTemplate is None:
            raise RuntimeError("LangChain dependencies are not installed")
        self.chat_model = build_chat_model()
        self.embedding_model = build_embedding_model()
        if settings.ai_provider == "openai":
            self.embedding_fingerprint = f"openai:{settings.openai_embed_model}"
        elif settings.ai_provider == "ollama":
            self.embedding_fingerprint = f"ollama:{settings.ollama_embed_model}"
        else:  # pragma: no cover - guarded by get_ai_provider
            raise RuntimeError(f"Unsupported AI provider: {settings.ai_provider}")

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if self.embedding_model is None:
            raise RuntimeError(f"No embedding model is configured for {settings.ai_provider}")
        vectors = self.embedding_model.embed_documents(texts)
        return EmbeddingResult(vectors=vectors, fingerprint=self.embedding_fingerprint)

    def plan_research(self, question: str) -> ResearchPlan:
        try:
            offered_ids = {candidate["arxiv_id"] for candidate in candidates}
            return invoke_structured_json(
                self.chat_model,
                ResearchPlan,
                "Plan a focused arXiv literature search with short keyword-style search queries and concrete inclusion criteria.",
                "Research question: {question}",
                {"question": question},
            )
        except Exception as exc:
            record_fallback("ai.plan_research", "mock.plan_research", str(exc))
            return super().plan_research(question)

    def select_relevant_candidates(
        self,
        question: str,
        candidates: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> CandidateSelection:
        try:
            return invoke_structured_json(
                self.chat_model,
                CandidateSelection,
                "Select the 3 to 5 most relevant arXiv candidates for the research question. Use memory as a weak preference signal, but do not select irrelevant papers just because memory mentions related terms.",
                "Question: {question}\nMemory signals:\n{memory_context}\nCandidates:\n{candidates}",
                {"question": question, "memory_context": format_memories(memory_context or []), "candidates": format_candidates(candidates)},
                validator=lambda output: validate_candidate_selection(output, offered_ids),
            )
        except Exception as exc:
            record_fallback("ai.select_relevant_candidates", "mock.select_relevant_candidates", str(exc), {"candidate_count": len(candidates)})
            return super().select_relevant_candidates(question, candidates, memory_context)

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        try:
            registry = EvidenceRegistry.from_chunks(chunks[:10])
            output = invoke_structured_json(
                self.chat_model,
                PaperSummaryOutput,
                "Summarize the paper using only supplied chunks. Every section and highlight must cite supplied pages/chunks.",
                "Title: {title}\nChunks:\n{context}",
                {"title": paper_title, "context": format_chunks(chunks[:10])},
                validator=lambda value: validate_summary_evidence(value, registry),
            )
            section_names = (
                "problem_or_hypothesis",
                "approach",
                "experiments",
                "results",
                "conclusion",
                "limitations_or_notes",
            )
            return SummaryPayload(
                sections={name: getattr(output, name).text for name in section_names},
                section_citations={
                    name: [citation.model_dump(exclude_none=True) for citation in getattr(output, name).citations]
                    for name in section_names
                },
                highlights=[highlight.model_dump() for highlight in output.highlights],
            )
        except Exception as exc:
            record_fallback("ai.generate_summary", "mock.generate_summary", str(exc), {"chunk_count": len(chunks), "paper_title": paper_title})
            return super().generate_summary(paper_title, chunks)

    def synthesize_collection(
        self,
        question: str,
        paper_contexts: list[dict[str, Any]],
        memory_context: list[dict[str, Any]] | None = None,
    ) -> ResearchBrief:
        try:
            registry = EvidenceRegistry.from_paper_contexts(paper_contexts)
            return invoke_structured_json(
                self.chat_model,
                ResearchBrief,
                "Synthesize a collection of papers. Every finding, gap, experiment, and direction must cite supplied evidence. Use memory only to prioritize emphasis; do not cite memory as evidence.",
                "Question: {question}\nMemory signals:\n{memory_context}\nPaper evidence:\n{context}",
                {"question": question, "memory_context": format_memories(memory_context or []), "context": format_paper_contexts(paper_contexts)},
                validator=lambda output: validate_brief_evidence(output, registry),
            )
        except Exception as exc:
            record_fallback("ai.synthesize_collection", "mock.synthesize_collection", str(exc), {"paper_count": len(paper_contexts)})
            return super().synthesize_collection(question, paper_contexts, memory_context)

    def summarize_batch(self, goal: str, paper_contexts: list[dict[str, Any]]) -> BatchSummary:
        try:
            expected_ids = {context["paper_id"] for context in paper_contexts}
            return invoke_structured_json(
                self.chat_model,
                BatchSummary,
                "Summarize a batch of research papers into a comparison table using only supplied evidence.",
                "Goal: {goal}\nPaper evidence:\n{context}",
                {"goal": goal, "context": format_paper_contexts(paper_contexts)},
                validator=lambda output: validate_batch_output(output, expected_ids),
            )
        except Exception as exc:
            record_fallback("ai.summarize_batch", "mock.summarize_batch", str(exc), {"paper_count": len(paper_contexts)})
            return super().summarize_batch(goal, paper_contexts)

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        try:
            registry = EvidenceRegistry.from_chunks(context_chunks)
            output = invoke_structured_json(
                self.chat_model,
                ChatOutput,
                "Answer using only the supplied paper chunks. If evidence is weak, say so. Include citations.",
                "Title: {title}\nQuestion: {question}\nHistory: {history}\nChunks:\n{context}",
                {
                    "title": paper_title,
                    "question": question,
                    "history": history[-6:],
                    "context": format_chunks(context_chunks),
                },
                validator=lambda value: validate_citations(
                    value.citations,
                    registry,
                    require_at_least_one=False,
                ),
            )
            return ChatPayload(
                answer=output.answer,
                citations=[citation.model_dump(exclude_none=True) for citation in output.citations],
            )
        except Exception as exc:
            record_fallback("ai.answer_question", "mock.answer_question", str(exc), {"chunk_count": len(context_chunks)})
            return super().answer_question(paper_title, question, context_chunks, history)


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


class ChatOutput(BaseModel):
    answer: str
    citations: list[EvidenceCitation]


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

    try:
        result = invoke_structured_once(chat_model, output_model, system_prompt, human_template, payload)
        if validator is not None:
            validator(result)
        return result
    except Exception:
        result = invoke_structured_once(chat_model, output_model, retry_system_prompt, human_template, payload)
        if validator is not None:
            validator(result)
        return result


def invoke_structured_once(
    chat_model: Any,
    output_model: type[StructuredModel],
    system_prompt: str,
    human_template: str,
    payload: dict[str, Any],
) -> StructuredModel:
    prompt = ChatPromptTemplate.from_messages([("system", escape_template_text(system_prompt)), ("human", human_template)])
    chain = prompt | chat_model.with_structured_output(output_model)
    return chain.invoke(payload)


def escape_template_text(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def build_chat_model() -> Any:
    if settings.ai_provider == "openai":
        return ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key)
    return ChatOllama(model=settings.ollama_chat_model, base_url=settings.ollama_base_url, temperature=0, format="json")


def build_embedding_model() -> Any:
    if settings.ai_provider == "openai" and OpenAIEmbeddings is not None:
        return OpenAIEmbeddings(model=settings.openai_embed_model, api_key=settings.openai_api_key)
    if settings.ai_provider == "ollama" and OllamaEmbeddings is not None:
        return OllamaEmbeddings(model=settings.ollama_embed_model, base_url=settings.ollama_base_url)
    return None


def make_citation(chunk: dict[str, Any]) -> dict[str, str | int]:
    excerpt = chunk["text"].replace("\n", " ").strip()[:220]
    return {"page": chunk["page_start"], "excerpt": excerpt, "chunk_id": chunk["id"]}


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
    raise RuntimeError(f"Unknown AI_PROVIDER={settings.ai_provider}")

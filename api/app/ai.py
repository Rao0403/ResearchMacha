from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

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


class EvidenceCitation(BaseModel):
    paper_id: str | None = None
    title: str | None = None
    page: int
    excerpt: str
    chunk_id: str | None = None


class ResearchPlan(BaseModel):
    search_queries: list[str] = Field(min_length=1, max_length=5)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=6)


class PaperFinding(BaseModel):
    label: str
    summary: str
    citations: list[EvidenceCitation]


class ResearchBrief(BaseModel):
    executive_summary: str
    key_findings: list[PaperFinding]
    evidence_table: list[PaperFinding]
    conflicts_or_gaps: list[PaperFinding]
    suggested_experiments: list[PaperFinding]
    suggested_research_directions: list[PaperFinding]


@dataclass
class SummaryPayload:
    sections: dict[str, str]
    section_citations: dict[str, list[dict[str, str | int]]]
    highlights: list[dict[str, Any]]


@dataclass
class ChatPayload:
    answer: str
    citations: list[dict[str, str | int]]


class AIProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def plan_research(self, question: str) -> ResearchPlan:
        raise NotImplementedError

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        raise NotImplementedError

    def synthesize_collection(self, question: str, paper_contexts: list[dict[str, Any]]) -> ResearchBrief:
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
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [hash_embedding(text) for text in texts]

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

    def synthesize_collection(self, question: str, paper_contexts: list[dict[str, Any]]) -> ResearchBrief:
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

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.embedding_model is None:
            return super().embed_texts(texts)
        try:
            return self.embedding_model.embed_documents(texts)
        except Exception:
            return super().embed_texts(texts)

    def plan_research(self, question: str) -> ResearchPlan:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You plan literature searches. Return focused arXiv search queries and concrete inclusion criteria.",
                ),
                ("human", "Research question: {question}"),
            ]
        )
        chain = prompt | self.chat_model.with_structured_output(ResearchPlan)
        return chain.invoke({"question": question})

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Summarize the paper using only supplied chunks. Every section needs citations with page, excerpt, chunk_id.",
                ),
                ("human", "Title: {title}\nChunks:\n{context}"),
            ]
        )
        structured = prompt | self.chat_model.with_structured_output(PaperSummaryOutput)
        output = structured.invoke({"title": paper_title, "context": format_chunks(chunks[:10])})
        return SummaryPayload(
            sections=output.sections,
            section_citations=output.section_citations,
            highlights=[highlight.model_dump() for highlight in output.highlights],
        )

    def synthesize_collection(self, question: str, paper_contexts: list[dict[str, Any]]) -> ResearchBrief:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Synthesize a collection of papers. Every finding, gap, experiment, and direction must cite supplied evidence.",
                ),
                ("human", "Question: {question}\nPaper evidence:\n{context}"),
            ]
        )
        chain = prompt | self.chat_model.with_structured_output(ResearchBrief)
        return chain.invoke({"question": question, "context": format_paper_contexts(paper_contexts)})

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Answer using only the supplied paper chunks. If evidence is weak, say so. Include citations.",
                ),
                ("human", "Title: {title}\nQuestion: {question}\nHistory: {history}\nChunks:\n{context}"),
            ]
        )
        chain = prompt | self.chat_model.with_structured_output(ChatOutput)
        output = chain.invoke(
            {
                "title": paper_title,
                "question": question,
                "history": history[-6:],
                "context": format_chunks(context_chunks),
            }
        )
        return ChatPayload(answer=output.answer, citations=output.citations)


class HighlightOutput(BaseModel):
    position: int
    label: str
    explanation: str
    citations: list[dict[str, str | int]]


class PaperSummaryOutput(BaseModel):
    sections: dict[str, str]
    section_citations: dict[str, list[dict[str, str | int]]]
    highlights: list[HighlightOutput]


class ChatOutput(BaseModel):
    answer: str
    citations: list[dict[str, str | int]]


def build_chat_model() -> Any:
    if settings.ai_provider == "openai":
        return ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key)
    return ChatOllama(model=settings.ollama_chat_model, base_url=settings.ollama_base_url, temperature=0)


def build_embedding_model() -> Any:
    if settings.ai_provider == "openai" and OpenAIEmbeddings is not None:
        return OpenAIEmbeddings(model="text-embedding-3-small", api_key=settings.openai_api_key)
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
        try:
            return LangChainProvider()
        except Exception:
            return MockProvider()
    return MockProvider()

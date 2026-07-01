from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings

settings = get_settings()


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

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
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
        return [self._hash_embedding(text) for text in texts]

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
            if citation_source:
                section_citations[section_name] = [make_citation(citation_source)]
            else:
                section_citations[section_name] = []

        for index, chunk in enumerate(top_chunks[:3]):
            highlights.append(
                {
                    "position": index,
                    "label": f"Key highlight {index + 1}",
                    "explanation": chunk["text"][:240].strip() or "Important supporting passage.",
                    "citations": [make_citation(chunk)],
                }
            )

        return SummaryPayload(sections=sections, section_citations=section_citations, highlights=highlights)

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

    def _hash_embedding(self, text: str) -> list[float]:
        vector: list[float] = []
        for index in range(settings.embedding_dim):
            digest = hashlib.sha256(f"{index}:{text}".encode("utf-8")).hexdigest()
            value = int(digest[:8], 16) / 0xFFFFFFFF
            vector.append((value * 2.0) - 1.0)
        norm = math.sqrt(sum(component * component for component in vector)) or 1.0
        return [component / norm for component in vector]


class OllamaProvider(MockProvider):
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=settings.ollama_base_url, timeout=120)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            response = self.client.post("/api/embeddings", json={"model": settings.ollama_embed_model, "prompt": text})
            response.raise_for_status()
            embeddings.append(response.json()["embedding"])
        return embeddings

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        prompt = build_summary_prompt(paper_title, chunks)
        response = self.client.post(
            "/api/chat",
            json={
                "model": settings.ollama_chat_model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        message = response.json()["message"]["content"]
        return parse_summary_payload(message, chunks)

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        prompt = build_chat_prompt(paper_title, question, context_chunks, history)
        response = self.client.post(
            "/api/chat",
            json={
                "model": settings.ollama_chat_model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        message = response.json()["message"]["content"]
        return parse_chat_payload(message, context_chunks)


class OpenAIProvider(MockProvider):
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        self.client = httpx.Client(
            base_url="https://api.openai.com/v1",
            timeout=120,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.client.post("/embeddings", json={"model": "text-embedding-3-small", "input": texts})
        response.raise_for_status()
        data = response.json()["data"]
        return [row["embedding"] for row in data]

    def generate_summary(self, paper_title: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
        response = self.client.post(
            "/chat/completions",
            json={
                "model": settings.openai_model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": build_summary_prompt(paper_title, chunks)}],
            },
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]["content"]
        return parse_summary_payload(message, chunks)

    def answer_question(
        self,
        paper_title: str,
        question: str,
        context_chunks: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatPayload:
        response = self.client.post(
            "/chat/completions",
            json={
                "model": settings.openai_model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": build_chat_prompt(paper_title, question, context_chunks, history)}],
            },
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]["content"]
        return parse_chat_payload(message, context_chunks)


def make_citation(chunk: dict[str, Any]) -> dict[str, str | int]:
    excerpt = chunk["text"].replace("\n", " ").strip()[:220]
    return {"page": chunk["page_start"], "excerpt": excerpt, "chunk_id": chunk["id"]}


def build_summary_prompt(paper_title: str, chunks: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"[chunk_id={chunk['id']} page={chunk['page_start']}] {chunk['text'][:1200]}" for chunk in chunks[:10]
    )
    return (
        "You are summarizing a research paper into a strict JSON object.\n"
        "Return keys: problem_or_hypothesis, approach, experiments, results, conclusion, limitations_or_notes, "
        "section_citations, highlights.\n"
        "Each entry in section_citations maps a section name to a list of citations with page, excerpt, chunk_id.\n"
        "Each highlight must contain position, label, explanation, citations.\n"
        f"Paper title: {paper_title}\n"
        f"Context:\n{context}"
    )


def build_chat_prompt(
    paper_title: str,
    question: str,
    context_chunks: list[dict[str, Any]],
    history: list[dict[str, str]],
) -> str:
    history_text = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
    context = "\n\n".join(
        f"[chunk_id={chunk['id']} page={chunk['page_start']}] {chunk['text'][:1200]}" for chunk in context_chunks
    )
    return (
        "Answer the user's question using only the supplied paper context. Return JSON with keys answer and citations. "
        "Each citation must contain page, excerpt, chunk_id. If the evidence is weak, say so clearly.\n"
        f"Paper title: {paper_title}\n"
        f"Conversation history:\n{history_text}\n"
        f"Question: {question}\n"
        f"Context:\n{context}"
    )


def parse_summary_payload(message: str, chunks: list[dict[str, Any]]) -> SummaryPayload:
    parsed = json.loads(message)
    section_citations = parsed.get("section_citations") or {}
    highlights = parsed.get("highlights") or []
    return SummaryPayload(
        sections={
            "problem_or_hypothesis": parsed.get("problem_or_hypothesis", ""),
            "approach": parsed.get("approach", ""),
            "experiments": parsed.get("experiments", ""),
            "results": parsed.get("results", ""),
            "conclusion": parsed.get("conclusion", ""),
            "limitations_or_notes": parsed.get("limitations_or_notes", ""),
        },
        section_citations=section_citations,
        highlights=highlights,
    )


def parse_chat_payload(message: str, context_chunks: list[dict[str, Any]]) -> ChatPayload:
    parsed = json.loads(message)
    citations = parsed.get("citations") or [make_citation(chunk) for chunk in context_chunks[:2]]
    return ChatPayload(answer=parsed.get("answer", ""), citations=citations)


def get_ai_provider() -> AIProvider:
    provider_name = settings.ai_provider.lower()
    if provider_name == "ollama":
        return OllamaProvider()
    if provider_name == "openai":
        return OpenAIProvider()
    return MockProvider()


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree

import httpx

ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_API = "https://export.arxiv.org/api/query"


@dataclass
class ArxivEntry:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int | None
    pdf_url: str
    entry_url: str


def search_arxiv(query: str, max_results: int = 12) -> list[ArxivEntry]:
    response = httpx.get(
        ARXIV_API,
        params={"search_query": f"all:{query}", "start": 0, "max_results": max_results},
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    return parse_feed(response.text)


def fetch_arxiv_entry(arxiv_id: str) -> ArxivEntry:
    response = httpx.get(ARXIV_API, params={"id_list": arxiv_id}, timeout=30, follow_redirects=True)
    response.raise_for_status()
    entries = parse_feed(response.text)
    if not entries:
        raise ValueError(f"No arXiv paper found for id {arxiv_id}")
    return entries[0]


def parse_feed(xml_text: str) -> list[ArxivEntry]:
    root = ElementTree.fromstring(xml_text)
    entries: list[ArxivEntry] = []
    for item in root.findall("atom:entry", ARXIV_NS):
        identifier = item.findtext("atom:id", namespaces=ARXIV_NS, default="").split("/")[-1]
        title = normalize_whitespace(item.findtext("atom:title", namespaces=ARXIV_NS, default="Untitled"))
        abstract = normalize_whitespace(item.findtext("atom:summary", namespaces=ARXIV_NS, default=""))
        author_nodes = item.findall("atom:author", ARXIV_NS)
        authors = [normalize_whitespace(node.findtext("atom:name", namespaces=ARXIV_NS, default="")) for node in author_nodes]
        published = item.findtext("atom:published", namespaces=ARXIV_NS, default="")
        year = datetime.fromisoformat(published.replace("Z", "+00:00")).year if published else None
        entry_url = item.findtext("atom:id", namespaces=ARXIV_NS, default="")
        pdf_url = f"https://arxiv.org/pdf/{identifier}.pdf"
        entries.append(
            ArxivEntry(
                arxiv_id=identifier,
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                pdf_url=pdf_url,
                entry_url=entry_url,
            )
        )
    return entries


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())

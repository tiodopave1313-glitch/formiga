"""Extração de texto e seleção lexical de trechos (RF-04).

O texto principal é extraído do HTML (Trafilatura na Etapa 3); aqui ficam a
divisão em trechos com localizadores e a seleção por correspondência lexical.
Não usar apenas o início da página como estratégia de recuperação.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Stopwords mínimas pt/en para seleção lexical.
STOPWORDS = {
    "a", "o", "as", "os", "de", "do", "da", "dos", "das", "em", "no", "na", "nos",
    "nas", "um", "uma", "uns", "umas", "para", "por", "com", "que", "e", "ou",
    "é", "são", "ser", "como", "the", "of", "to", "and", "is", "are", "in", "on",
    "for", "with", "what", "which", "between", "vs", "does", "can",
}


@dataclass
class Chunk:
    index: int
    text: str
    char_start: int
    char_end: int


def extract_main_text(html: str) -> tuple[str, str | None]:
    """Extrai texto principal e título do HTML (fallback offline sem Trafilatura)."""
    import trafilatura

    extracted = trafilatura.extract(
        html, include_comments=False, include_links=False, favor_recall=True
    )
    # Trafilatura >= 2.0 devolve `Document` (com `as_dict()`); versões antigas
    # devolvem dict. Aceitamos os dois formatos.
    title = trafilatura.extract_metadata(html)
    if isinstance(title, dict):
        title_value = title.get("title")
    elif title is not None:
        title_value = title.as_dict().get("title")
    else:
        title_value = None
    if not extracted:
        raise ValueError("extração vazia")
    return extracted, title_value


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def split_chunks(text: str, chunk_size: int = 900, overlap: int = 100) -> list[Chunk]:
    """Divide o texto em trechos com localizadores por caractere."""
    if chunk_size <= overlap:
        raise ValueError("chunk_size deve exceder overlap")
    chunks: list[Chunk] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # Corta preferencialmente em fim de frase/parágrafo dentro da janela.
            window = text[start:end]
            m = None
            for sep in ("\n\n", ". ", ".\n", "! ", "? "):
                idx = window.rfind(sep, max(0, len(window) - overlap), len(window))
                if idx > 0:
                    m = idx + len(sep)
            if m:
                end = start + m
        chunks.append(
            Chunk(index=len(chunks), text=text[start:end], char_start=start, char_end=end)
        )
        if end >= n:
            break
        start = end - overlap
    return chunks


def _terms(text: str) -> set[str]:
    return {
        w.lower()
        for w in _WORD_RE.findall(text)
        if len(w) > 2 and w.lower() not in STOPWORDS
    }


def select_chunks(chunks: list[Chunk], query: str, limit: int) -> list[Chunk]:
    """Seleção lexical: trechos com maior sobreposição de termos com a consulta.

    Distribuídos ao longo da página, não restritos ao início.
    """
    if limit <= 0 or not chunks:
        return []
    query_terms = _terms(query)
    if not query_terms:
        return chunks[:limit]
    scored: list[tuple[float, int, Chunk]] = []
    for chunk in chunks:
        terms = _terms(chunk.text)
        overlap = len(terms & query_terms)
        scored.append((-overlap, chunk.index, chunk))
    scored.sort()
    return [c for _, _, c in scored[:limit]]


def normalize_ws(text: str) -> str:
    """Normaliza espaços para comparação de trechos literais."""
    return re.sub(r"\s+", " ", text).strip()


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Localiza um trecho (possivelmente com espaços divergentes) no texto.

    Devolve o intervalo [start, end) no texto normalizado ou None.
    """
    hay = normalize_ws(text)
    needle = normalize_ws(quote)
    if not needle:
        return None
    idx = hay.find(needle)
    if idx == -1:
        return None
    return idx, idx + len(needle)

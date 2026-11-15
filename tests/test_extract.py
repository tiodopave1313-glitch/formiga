"""Testes de extração, trechos, seleção lexical e normalização (offline)."""

from __future__ import annotations

import pytest

from formiga.extract import (
    find_quote,
    normalize_ws,
    select_chunks,
    split_chunks,
    text_hash,
)
from formiga.search import SearchResult, dedupe_results, normalize_query

LONG_TEXT = (
    "Primeira seção sobre índices invertidos. " * 10
    + "Segunda seção sobre embeddings densos e similaridade semântica. " * 10
    + "Terceira seção sobre avaliação de recuperação e métricas. " * 10
)


class TestSplitChunks:
    def test_chunks_cover_text_with_locators(self):
        chunks = split_chunks(LONG_TEXT, chunk_size=400, overlap=50)
        assert len(chunks) > 1
        for i, chunk in enumerate(chunks):
            assert chunk.index == i
            assert chunk.char_end > chunk.char_start
            assert LONG_TEXT[chunk.char_start : chunk.char_end] == chunk.text
        # Cobertura contínua com sobreposição.
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(LONG_TEXT)

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            split_chunks("abc", chunk_size=10, overlap=10)


class TestSelectChunks:
    def test_prefers_relevant_chunk_not_only_beginning(self):
        chunks = split_chunks(LONG_TEXT, chunk_size=400, overlap=50)
        selected = select_chunks(chunks, "embeddings densos similaridade semântica", 1)
        assert "embeddings densos" in selected[0].text

    def test_limit_respected(self):
        chunks = split_chunks(LONG_TEXT, chunk_size=300, overlap=50)
        assert len(select_chunks(chunks, "índices", 2)) == 2

    def test_empty(self):
        assert select_chunks([], "qualquer", 3) == []


class TestFindQuote:
    def test_literal_match(self):
        text = "Uma frase. Outra frase com espaços."
        assert find_quote(text, "Outra frase") == (11, 22)

    def test_whitespace_normalized_match(self):
        text = "linha um\nlinha   dois\t\tfim"
        span = find_quote(text, "linha dois")
        assert span is not None

    def test_missing(self):
        assert find_quote("abc", "xyz") is None


class TestNormalization:
    def test_normalize_ws(self):
        assert normalize_ws("a \n\t b   c") == "a b c"


class TestUrlDedupe:
    def test_dedupe_conservative(self):
        results = [
            SearchResult("https://Example.com/a/", "t", None),
            SearchResult("https://example.com/a/#secao", "t2", None),
            SearchResult("https://example.com/a?x=1", "t3", None),
            SearchResult("https://example.com/b", "t4", None),
        ]
        kept = dedupe_results(results)
        assert [r.url for r in kept] == [
            "https://Example.com/a/",
            "https://example.com/b",
        ]

    def test_normalize_query(self):
        assert normalize_query("  Busca   Lexical ") == "busca lexical"


class TestTextHash:
    def test_stable_and_short(self):
        assert text_hash("abc") == text_hash("abc")
        assert text_hash("abc") != text_hash("abd")
        assert len(text_hash("abc")) == 16

from unittest.mock import patch

import pytest

from documents.chunking import (
    Block,
    _scan_markdown,
    chunk_markdown,
    chunk_text,
    extract_front_matter,
    extract_text,
)


class TestExtractText:
    def test_extracts_plain_text(self):
        raw = "Hello world".encode("utf-8")
        assert extract_text(raw, "text/plain") == "Hello world"

    def test_extracts_markdown(self):
        raw = "# Title\n\nBody text".encode("utf-8")
        result = extract_text(raw, "text/markdown")
        assert "Title" in result
        assert "Body text" in result

    def test_extracts_utf8_with_special_chars(self):
        raw = "Café résumé naïve 🌍".encode("utf-8")
        assert extract_text(raw, "text/plain") == "Café résumé naïve 🌍"

    def test_rejects_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported content type"):
            extract_text(b"data", "application/octet-stream")

    @patch("documents.chunking.extract_pdf_to_markdown", return_value="PDF text")
    def test_extracts_pdf(self, mock_extract):
        assert extract_text(b"fake pdf bytes", "application/pdf") == "PDF text"
        mock_extract.assert_called_once_with(b"fake pdf bytes")


class TestChunkText:
    def test_empty_text_returns_empty_list(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_returns_single_chunk(self):
        text = "Short text."
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        assert chunks == [text]

    def test_exact_chunk_size_text(self):
        text = "x" * 1000
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        assert chunks == [text]

    def test_splits_long_text_into_multiple_chunks(self):
        text = "word " * 500
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_consecutive_chunks_share_overlap_content(self):
        text = "A " * 100 + "MARKER " + "B " * 100
        chunks = chunk_text(text, chunk_size=150, overlap=30)
        assert len(chunks) >= 2
        for i in range(len(chunks) - 1):
            tail = chunks[i][-25:]
            head = chunks[i + 1][:25]
            assert any(word in head for word in tail.split()), (
                f"Chunks {i} and {i + 1} share no overlap"
            )

    def test_prefers_paragraph_boundary(self):
        text = "First paragraph content.\n\nSecond paragraph content."
        chunks = chunk_text(text, chunk_size=30, overlap=5)
        assert any("First paragraph" in c for c in chunks)
        assert any("Second paragraph" in c for c in chunks)
        reconstructed = " ".join(chunks)
        assert "First paragraph content." in reconstructed
        assert "Second paragraph content." in reconstructed

    def test_prefers_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence."
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        for chunk in chunks:
            assert not chunk.endswith(" Se")
            assert not chunk.endswith(" Seco")

    def test_falls_back_to_word_boundary(self):
        text = "one two three four five six seven eight"
        chunks = chunk_text(text, chunk_size=10, overlap=3)
        for chunk in chunks:
            assert not chunk.endswith(" t")
            assert not chunk.endswith(" th")

    def test_single_word_longer_than_chunk_size(self):
        text = "a" * 2000
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk


class TestExtractFrontMatter:
    def test_no_front_matter_returns_empty(self):
        text = "# Hello\n\nWorld"
        meta, remaining = extract_front_matter(text)
        assert meta == {}
        assert remaining == text

    def test_extracts_yaml_front_matter(self):
        text = "---\ntitle: Hello\nversion: '1.0'\n---\n\n# Content"
        meta, remaining = extract_front_matter(text)
        assert meta == {"title": "Hello", "version": "1.0"}
        assert remaining.strip() == "# Content"

    def test_extracts_toml_front_matter(self):
        text = "+++\ntitle = 'Hello'\nversion = 1.0\n+++\n\n# Content"
        meta, remaining = extract_front_matter(text)
        assert meta == {"title": "Hello", "version": 1.0}
        assert remaining.strip() == "# Content"

    def test_invalid_yaml_returns_empty_and_original_text(self):
        text = "---\nnot yaml: [\n---\n\n# Content"
        meta, remaining = extract_front_matter(text)
        assert meta == {}
        assert remaining == text

    def test_missing_closing_delimiter_returns_empty(self):
        text = "---\ntitle: Hello\n\n# Content"
        meta, remaining = extract_front_matter(text)
        assert meta == {}
        assert remaining == text

    def test_empty_body_after_front_matter(self):
        text = "---\ntitle: Hello\n---\n"
        meta, remaining = extract_front_matter(text)
        assert meta == {"title": "Hello"}
        assert remaining.strip() == ""

    def test_leading_whitespace_ignored(self):
        text = "   \n---\ntitle: Hello\n---\n\n# Content"
        meta, remaining = extract_front_matter(text)
        assert meta == {"title": "Hello"}
        assert remaining.strip() == "# Content"


class TestScanMarkdown:
    def test_detects_headers(self):
        blocks = _scan_markdown("# H1\n\n## H2\n\n### H3")
        assert blocks == [
            Block(kind="h1", content="H1"),
            Block(kind="h2", content="H2"),
            Block(kind="h3", content="H3"),
        ]

    def test_detects_paragraph(self):
        blocks = _scan_markdown("Some text here.\nContinued on next line.")
        assert len(blocks) == 1
        assert blocks[0].kind == "paragraph"
        assert "Some text here." in blocks[0].content
        assert "Continued on next line." in blocks[0].content

    def test_detects_code_block_backticks(self):
        blocks = _scan_markdown("```python\nprint('hi')\n```")
        assert len(blocks) == 1
        assert blocks[0].kind == "code"
        assert blocks[0].content == "print('hi')"

    def test_detects_code_block_tildes(self):
        blocks = _scan_markdown("~~~\ncode here\n~~~")
        assert len(blocks) == 1
        assert blocks[0].kind == "code"
        assert blocks[0].content == "code here"

    def test_code_block_with_backticks_inside(self):
        text = "````\n```python\nprint('nested')\n```\n````"
        blocks = _scan_markdown(text)
        assert len(blocks) == 1
        assert blocks[0].kind == "code"
        assert "```python" in blocks[0].content
        assert "print('nested')" in blocks[0].content

    def test_code_fence_ignores_line_with_trailing_content(self):
        text = "```\nsome code\n``` this is not a closing fence\nmore code\n```"
        blocks = _scan_markdown(text)
        assert len(blocks) == 1
        assert blocks[0].kind == "code"
        assert "``` this is not a closing fence" in blocks[0].content
        assert "more code" in blocks[0].content

    def test_detects_table(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        blocks = _scan_markdown(text)
        assert len(blocks) == 1
        assert blocks[0].kind == "table"
        assert "| A | B |" in blocks[0].content
        assert "| 1 | 2 |" in blocks[0].content

    def test_detects_unordered_list(self):
        blocks = _scan_markdown("- Item one\n- Item two")
        assert len(blocks) == 1
        assert blocks[0].kind == "list"
        assert "- Item one" in blocks[0].content
        assert "- Item two" in blocks[0].content

    def test_detects_ordered_list(self):
        blocks = _scan_markdown("1. First\n2. Second")
        assert len(blocks) == 1
        assert blocks[0].kind == "list"

    def test_loose_list_parsed_as_single_block(self):
        text = "- Item A\n\n- Item B\n\n- Item C"
        blocks = _scan_markdown(text)
        list_blocks = [b for b in blocks if b.kind == "list"]
        assert len(list_blocks) == 1
        assert "- Item A" in list_blocks[0].content
        assert "- Item C" in list_blocks[0].content

    def test_list_ends_at_non_list_content(self):
        text = "- Item A\n- Item B\n\nSome paragraph."
        blocks = _scan_markdown(text)
        assert blocks[0].kind == "list"
        assert blocks[1].kind == "paragraph"

    def test_paragraph_stops_at_header(self):
        text = "Some text\n# Header"
        blocks = _scan_markdown(text)
        assert len(blocks) == 2
        assert blocks[0] == Block(kind="paragraph", content="Some text")
        assert blocks[1] == Block(kind="h1", content="Header")

    def test_paragraph_stops_at_code_fence(self):
        text = "Some text\n```\ncode\n```"
        blocks = _scan_markdown(text)
        assert len(blocks) == 2
        assert blocks[0].kind == "paragraph"
        assert blocks[1].kind == "code"

    def test_paragraph_stops_at_list(self):
        text = "Some text\n- list item"
        blocks = _scan_markdown(text)
        assert len(blocks) == 2
        assert blocks[0].kind == "paragraph"
        assert blocks[1].kind == "list"

    def test_mixed_blocks_in_order(self):
        text = (
            "# Title\n\n"
            "Paragraph.\n\n"
            "```\ncode\n```\n\n"
            "| A | B |\n|---|---|\n\n"
            "- item\n"
        )
        blocks = _scan_markdown(text)
        kinds = [b.kind for b in blocks]
        assert kinds == ["h1", "paragraph", "code", "table", "list"]

    def test_skips_blank_lines(self):
        text = "\n\n\nSome text.\n\n\n"
        blocks = _scan_markdown(text)
        assert len(blocks) == 1
        assert blocks[0].kind == "paragraph"


class TestChunkMarkdown:
    def test_empty_text(self):
        chunks, meta = chunk_markdown("")
        assert chunks == []
        assert meta == {}

    def test_single_paragraph(self):
        chunks, meta = chunk_markdown("Just a paragraph.")
        assert len(chunks) == 1
        assert chunks[0] == "Just a paragraph."

    def test_preserves_code_block_content(self):
        text = (
            "# Intro\n\nSome text.\n\n"
            "```python\nprint('hello')\nprint('world')\n```\n\n"
            "More text."
        )
        chunks, _ = chunk_markdown(text, max_size=50)
        code_chunks = [
            c for c in chunks if "print('hello')" in c and "print('world')" in c
        ]
        assert len(code_chunks) >= 1

    def test_preserves_tilde_code_fence(self):
        text = "# Code\n\n~~~python\ncode line one\ncode line two\n~~~\n\nAfter."
        chunks, _ = chunk_markdown(text, max_size=30)
        code_chunks = [
            c for c in chunks if "code line one" in c and "code line two" in c
        ]
        assert len(code_chunks) >= 1

    def test_code_block_with_nested_fences_preserved(self):
        text = "# Docs\n\n````\n```python\nprint('inner')\n```\n````\n\nAfter."
        chunks, _ = chunk_markdown(text, max_size=200)
        code_chunks = [c for c in chunks if "```python" in c and "print('inner')" in c]
        assert len(code_chunks) >= 1

    def test_preserves_table_structure(self):
        text = (
            "# Data\n\n"
            "| Col1 | Col2 |\n|------|------|\n| A    | B    |\n\n"
            "After table."
        )
        chunks, _ = chunk_markdown(text, max_size=30)
        table_chunks = [c for c in chunks if "| Col1 | Col2 |" in c]
        assert len(table_chunks) >= 1
        for c in table_chunks:
            assert "| A    | B    |" in c

    def test_preserves_list_structure(self):
        text = "# List\n\n- Item one\n- Item two\n- Item three\n\nAfter list."
        chunks, _ = chunk_markdown(text, max_size=30)
        list_chunks = [c for c in chunks if "- Item one" in c]
        assert len(list_chunks) >= 1
        for c in list_chunks:
            assert "- Item two" in c
            assert "- Item three" in c

    def test_preserves_list_with_indented_items(self):
        text = "# List\n\n- Item one\n  - Nested item\n- Item two\n\nAfter."
        chunks, _ = chunk_markdown(text, max_size=40)
        list_chunks = [c for c in chunks if "- Item one" in c]
        assert len(list_chunks) >= 1
        for c in list_chunks:
            assert "Nested item" in c
            assert "- Item two" in c

    def test_loose_list_stays_together(self):
        text = (
            "# Notes\n\n- First point\n\n- Second point\n\n- Third point\n\nConclusion."
        )
        chunks, _ = chunk_markdown(text, max_size=200)
        list_chunks = [c for c in chunks if "- First point" in c]
        assert len(list_chunks) >= 1
        for c in list_chunks:
            assert "- Second point" in c
            assert "- Third point" in c

    def test_prepends_header_path(self):
        text = "# Main\n\nIntro.\n\n## Sub\n\nSub content."
        chunks, _ = chunk_markdown(text)
        sub_chunks = [c for c in chunks if "Sub content" in c]
        assert len(sub_chunks) == 1
        assert "# Main" in sub_chunks[0]
        assert "## Sub" in sub_chunks[0]

    def test_header_hierarchy_pops_on_same_or_higher_level(self):
        text = "# A\n\nContent A.\n\n## B\n\nContent B.\n\n# C\n\nContent C."
        chunks, _ = chunk_markdown(text, max_size=50)
        c_chunks = [c for c in chunks if "Content C" in c]
        assert len(c_chunks) == 1
        assert "# C" in c_chunks[0]
        assert "## B" not in c_chunks[0]

    def test_headers_without_content_produce_no_chunks(self):
        text = "# A\n\n## B\n\n### C"
        chunks, _ = chunk_markdown(text)
        assert chunks == []

    def test_splits_oversized_paragraphs_with_header_context(self):
        text = "# Section\n\n" + "word " * 300
        chunks, _ = chunk_markdown(text, max_size=200)
        assert len(chunks) > 1
        for c in chunks:
            assert "# Section" in c

    def test_oversized_code_block_starts_fresh_chunk(self):
        text = "# Section\n\n```\n" + "code line\n" * 100 + "```\n\nAfter."
        chunks, _ = chunk_markdown(text, max_size=200)
        code_chunks = [c for c in chunks if "code line" in c]
        assert len(code_chunks) >= 1

    def test_overlap_within_same_section(self):
        text = "# Section\n\n" + "word " * 150
        chunks, _ = chunk_markdown(text, max_size=100, overlap=20)
        assert len(chunks) >= 2
        first_tail = chunks[0].split()[-5:]
        second_head = chunks[1].split()[:5]
        assert any(word in second_head for word in first_tail)

    def test_no_overlap_across_section_boundaries(self):
        text = "# A\n\n" + "word " * 50 + "\n\n# B\n\nDifferent content here."
        chunks, _ = chunk_markdown(text, max_size=100, overlap=20)
        b_chunks = [c for c in chunks if "Different content" in c]
        assert len(b_chunks) == 1
        assert not b_chunks[0].startswith("word ")

    def test_extracts_front_matter(self):
        text = "---\ntitle: Doc\n---\n\n# Heading\n\nContent."
        chunks, meta = chunk_markdown(text)
        assert meta == {"title": "Doc"}
        assert len(chunks) == 1
        assert "# Heading" in chunks[0]

    def test_mixed_content_types(self):
        text = (
            "# Doc\n\n"
            "Paragraph one.\n\n"
            "```python\nx = 1\n```\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "- List item\n\n"
            "Paragraph two."
        )
        chunks, _ = chunk_markdown(text, max_size=200)
        assert any("x = 1" in c for c in chunks)
        assert any("| A | B |" in c for c in chunks)
        assert any("- List item" in c for c in chunks)
        assert any("Paragraph one" in c for c in chunks)
        assert any("Paragraph two" in c for c in chunks)

    def test_long_markdown_document(self):
        sections = []
        for i in range(10):
            sections.append(f"# Section {i}\n\n")
            sections.append(f"This is an introductory paragraph for section {i}. " * 20)
            sections.append("\n\n")
            sections.append("## Subsection A\n\n")
            sections.append(
                f"Some important content in subsection A of section {i}. " * 15
            )
            sections.append("\n\n")
            sections.append(f"```python\ndef func_{i}():\n    return {i}\n```\n\n")
            sections.append("| Key | Value |\n|-----|-------|\n")
            sections.append(f"| section | {i} |\n| type | demo |\n\n")
            sections.append(f"- Observation {i}a\n")
            sections.append(f"- Observation {i}b\n")
            sections.append(f"  - Detail for {i}\n")
            sections.append(f"- Observation {i}c\n\n")
            sections.append("## Subsection B\n\n")
            sections.append(
                f"Concluding paragraph for section {i} with a lot of text. " * 15
            )
            sections.append("\n\n")

        text = "".join(sections)
        chunks, meta = chunk_markdown(text, max_size=500, overlap=50)

        assert len(chunks) > 10

        for i in range(10):
            section_chunks = [c for c in chunks if f"Section {i}" in c]
            assert len(section_chunks) >= 1

            code_chunks = [c for c in chunks if f"def func_{i}():" in c]
            assert len(code_chunks) >= 1

            table_chunks = [c for c in chunks if f"| section | {i} |" in c]
            assert len(table_chunks) >= 1

            list_chunks = [c for c in chunks if f"Observation {i}a" in c]
            assert len(list_chunks) >= 1

        reconstructed = "\n\n".join(chunks)
        assert "# Section 0" in reconstructed
        assert "# Section 9" in reconstructed
        assert "def func_5():" in reconstructed
        assert "| section | 5 |" in reconstructed
        assert "Detail for 3" in reconstructed

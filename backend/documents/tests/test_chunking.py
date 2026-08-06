from documents.chunking import (
    Block,
    ParentChunkData,
    _scan_markdown,
    chunk_markdown,
    chunk_text,
    extract_front_matter,
    get_token_count,
)


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
        limit = 135
        for chunk in chunks:
            assert get_token_count(chunk) <= limit

    def test_consecutive_chunks_share_overlap_content(self):
        text = "A " * 300 + "MARKER " + "B " * 300
        chunks = chunk_text(text, chunk_size=150, overlap=30)
        assert len(chunks) >= 2
        for i in range(len(chunks) - 1):
            tail = chunks[i][-25:]
            head = chunks[i + 1][:25]
            assert any(word in head for word in tail.split()), (
                f"Chunks {i} and {i + 1} share no overlap"
            )

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

    def test_detects_code_block_with_fences(self):
        blocks = _scan_markdown("```python\nprint('hi')\n```")
        assert len(blocks) == 1
        assert blocks[0].kind == "code"
        assert blocks[0].content == "```python\nprint('hi')\n```"

    def test_detects_code_block_tildes(self):
        blocks = _scan_markdown("~~~\ncode here\n~~~")
        assert len(blocks) == 1
        assert blocks[0].kind == "code"
        assert "code here" in blocks[0].content

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

    def test_skips_blank_lines(self):
        text = "\n\n\nSome text.\n\n\n"
        blocks = _scan_markdown(text)
        assert len(blocks) == 1
        assert blocks[0].kind == "paragraph"


class TestChunkMarkdown:
    def test_empty_text(self):
        parents, meta = chunk_markdown("")
        assert parents == []
        assert meta == {}

    def test_single_paragraph(self):
        parents, meta = chunk_markdown("Just a paragraph.")
        assert len(parents) == 1
        assert isinstance(parents[0], ParentChunkData)
        assert "Just a paragraph." in parents[0].content
        assert parents[0].header_breadcrumb is None

    def test_header_hierarchy_and_breadcrumbs(self):
        text = (
            "# Main Title\n\nMain content.\n\n"
            "## Section 1\n\nSection 1 content.\n\n"
            "### Subsection 1A\n\nSubsection content."
        )
        parents, meta = chunk_markdown(text)
        assert len(parents) == 3
        assert parents[0].header_breadcrumb == "Main Title"
        assert parents[1].header_breadcrumb == "Main Title > Section 1"
        assert parents[2].header_breadcrumb == "Main Title > Section 1 > Subsection 1A"

    def test_header_level_popping(self):
        text = (
            "# Top\n\nContent top.\n\n"
            "## Sub 1\n\nContent sub 1.\n\n"
            "# Another Top\n\nContent another top."
        )
        parents, _ = chunk_markdown(text)
        assert len(parents) == 3
        assert parents[2].header_breadcrumb == "Another Top"

    def test_preserves_code_block_content(self):
        text = (
            "# Intro\n\nSome text.\n\n"
            "```python\nprint('hello')\nprint('world')\n```\n\n"
            "More text."
        )
        parents, _ = chunk_markdown(text)
        assert len(parents) == 1
        assert "```python\nprint('hello')\nprint('world')\n```" in parents[0].content

    def test_large_code_block_integral(self):
        code_lines = ["def huge_func():"] + [f"    x = {i}" for i in range(500)]
        text = "# Section\n\n```python\n" + "\n".join(code_lines) + "\n```"
        parents, meta = chunk_markdown(text)
        assert len(parents) == 1
        assert isinstance(parents[0], ParentChunkData)
        assert "def huge_func():" in parents[0].content
        assert len(parents[0].child_texts) > 1

    def test_child_texts_generation_and_overlap(self):
        paragraph = "Word " * 500
        text = f"# Long Section\n\n{paragraph}"
        parents, _ = chunk_markdown(text)
        assert len(parents) >= 1
        child_texts = parents[0].child_texts
        assert len(child_texts) > 1
        for child in child_texts:
            assert isinstance(child, str)
            assert len(child) > 0

    def test_headers_without_content_produce_no_chunks(self):
        text = "# A\n\n## B\n\n### C"
        parents, meta = chunk_markdown(text)
        assert parents == []

    def test_extracts_front_matter_in_chunk_markdown(self):
        text = "---\ntitle: Doc\n---\n\n# Heading\n\nContent."
        parents, meta = chunk_markdown(text)
        assert meta == {"title": "Doc"}
        assert len(parents) == 1
        assert "Content." in parents[0].content

    def test_mixed_content_types(self):
        text = (
            "# Doc\n\n"
            "Paragraph one.\n\n"
            "```python\nx = 1\n```\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "- List item\n\n"
            "Paragraph two."
        )
        parents, _ = chunk_markdown(text)
        assert len(parents) >= 1
        content = parents[0].content
        assert "x = 1" in content
        assert "| A | B |" in content
        assert "- List item" in content
        assert "Paragraph one" in content
        assert "Paragraph two" in content

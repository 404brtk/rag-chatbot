from src.parsing.md_utils import extract_md_title, strip_frontmatter


class TestExtractMdTitle:
    def test_from_heading(self):
        assert extract_md_title("# Hello World\nsome content") == "Hello World"

    def test_ignores_h2(self):
        assert extract_md_title("## Not a title\n# Real Title") == "Real Title"

    def test_empty_content(self):
        assert extract_md_title("") == ""

    def test_no_heading(self):
        assert extract_md_title("just some text\nno headings here") == ""

    def test_heading_with_extra_spaces(self):
        assert extract_md_title("#   Spaced Title  ") == "Spaced Title"

    def test_from_frontmatter(self):
        md = "---\ntitle: Getting Started\nsidebar_position: 1\n---\n\nSome content"
        assert extract_md_title(md) == "Getting Started"

    def test_from_frontmatter_quoted(self):
        md = '---\ntitle: "My Guide"\n---\n\n# Fallback Title'
        assert extract_md_title(md) == "My Guide"

    def test_frontmatter_takes_priority_over_heading(self):
        md = "---\ntitle: FM Title\n---\n\n# Heading Title"
        assert extract_md_title(md) == "FM Title"

    def test_frontmatter_without_title_falls_back_to_heading(self):
        md = "---\nslug: /intro\n---\n\n# Heading Title"
        assert extract_md_title(md) == "Heading Title"

    def test_from_toml_frontmatter(self):
        md = '+++\ntitle = "Hugo Guide"\nweight = 1\n+++\n\n# Content'
        assert extract_md_title(md) == "Hugo Guide"

    def test_toml_frontmatter_single_quotes(self):
        md = "+++\ntitle = 'My Page'\n+++\n\n# Content"
        assert extract_md_title(md) == "My Page"


class TestStripFrontmatter:
    def test_strips_frontmatter(self):
        md = "---\ntitle: Hello\nslug: /intro\n---\n\n# Hello\nContent here"
        result = strip_frontmatter(md)
        assert "title: Hello" not in result
        assert "# Hello\nContent here" in result

    def test_no_frontmatter(self):
        md = "# Hello\nContent here"
        assert strip_frontmatter(md) == "# Hello\nContent here"

    def test_empty_string(self):
        assert strip_frontmatter("") == ""

    def test_dashes_in_content_not_stripped(self):
        md = "# Title\n\nSome text\n---\nMore text"
        assert strip_frontmatter(md) == md

    def test_only_strips_first_frontmatter(self):
        md = "---\ntitle: First\n---\n\nContent\n\n---\ntitle: Second\n---\n"
        result = strip_frontmatter(md)
        assert "title: First" not in result
        assert "title: Second" in result

    def test_strips_toml_frontmatter(self):
        md = '+++\ntitle = "Hugo Guide"\nweight = 1\n+++\n\n# Content here'
        result = strip_frontmatter(md)
        assert "title" not in result
        assert "# Content here" in result

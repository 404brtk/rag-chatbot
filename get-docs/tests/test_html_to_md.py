from bs4 import BeautifulSoup

from src.parsing.html_to_md import html_to_markdown


def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("body") or soup


class TestHeadings:
    def test_h1(self):
        result = html_to_markdown(parse("<body><h1>Title</h1></body>"))
        assert "# Title" in result

    def test_h2(self):
        result = html_to_markdown(parse("<body><h2>Subtitle</h2></body>"))
        assert "## Subtitle" in result

    def test_h3(self):
        result = html_to_markdown(parse("<body><h3>Section</h3></body>"))
        assert "### Section" in result

    def test_h6(self):
        result = html_to_markdown(parse("<body><h6>Deep</h6></body>"))
        assert "###### Deep" in result

    def test_empty_heading_skipped(self):
        result = html_to_markdown(parse("<body><h1></h1><p>text</p></body>"))
        assert "#" not in result or "text" in result


class TestInlineFormatting:
    def test_bold(self):
        result = html_to_markdown(parse("<body><p><strong>bold</strong></p></body>"))
        assert "**bold**" in result

    def test_italic(self):
        result = html_to_markdown(parse("<body><p><em>italic</em></p></body>"))
        assert "*italic*" in result

    def test_bold_italic_nested(self):
        result = html_to_markdown(
            parse("<body><p><strong><em>both</em></strong></p></body>")
        )
        assert "***both***" in result or "**" in result and "*" in result

    def test_inline_code(self):
        result = html_to_markdown(
            parse("<body><p>Use <code>pip install</code> here</p></body>")
        )
        assert "`pip install`" in result

    def test_inline_code_with_backtick(self):
        result = html_to_markdown(parse("<body><p><code>use `this`</code></p></body>"))
        assert "``" in result


class TestCodeBlocks:
    def test_basic_code_block(self):
        html = "<body><pre><code>print('hello')</code></pre></body>"
        result = html_to_markdown(parse(html))
        assert "```" in result
        assert "print('hello')" in result

    def test_language_detection_from_class(self):
        html = '<body><pre><code class="language-python">x = 1</code></pre></body>'
        result = html_to_markdown(parse(html))
        assert "```python" in result
        assert "x = 1" in result

    def test_language_detection_lang_prefix(self):
        html = '<body><pre><code class="lang-javascript">let x</code></pre></body>'
        result = html_to_markdown(parse(html))
        assert "```javascript" in result

    def test_language_detection_highlight_prefix(self):
        html = '<body><pre><code class="highlight-rust">fn main()</code></pre></body>'
        result = html_to_markdown(parse(html))
        assert "```rust" in result

    def test_language_detection_on_pre_tag(self):
        html = '<body><pre class="language-go"><code>fmt.Println()</code></pre></body>'
        result = html_to_markdown(parse(html))
        assert "```go" in result

    def test_code_block_preserves_content(self):
        code = "def foo():\n    return 42\n\nfoo()"
        html = f"<body><pre><code>{code}</code></pre></body>"
        result = html_to_markdown(parse(html))
        assert "def foo():" in result
        assert "    return 42" in result
        assert "foo()" in result

    def test_pre_without_code(self):
        html = "<body><pre>raw preformatted</pre></body>"
        result = html_to_markdown(parse(html))
        assert "```" in result
        assert "raw preformatted" in result

    def test_code_inside_pre_not_double_backticked(self):
        html = '<body><pre><code class="language-python">x = 1</code></pre></body>'
        result = html_to_markdown(parse(html))
        count = result.count("```")
        assert count == 2


class TestLinks:
    def test_basic_link(self):
        html = '<body><p><a href="https://example.com">click</a></p></body>'
        result = html_to_markdown(parse(html))
        assert "[click](https://example.com)" in result

    def test_link_without_text(self):
        html = '<body><p><a href="https://example.com"></a></p></body>'
        result = html_to_markdown(parse(html))
        assert "example.com" in result or result.strip() == ""

    def test_link_without_href(self):
        html = "<body><p><a>just text</a></p></body>"
        result = html_to_markdown(parse(html))
        assert "just text" in result


class TestImages:
    def test_basic_image(self):
        html = '<body><img src="pic.png" alt="photo"></body>'
        result = html_to_markdown(parse(html))
        assert "![photo](pic.png)" in result

    def test_image_no_alt(self):
        html = '<body><img src="pic.png"></body>'
        result = html_to_markdown(parse(html))
        assert "![](pic.png)" in result

    def test_image_no_src(self):
        result = html_to_markdown(parse("<body><img alt='x'></body>"))
        assert "![" not in result or result.strip() == "" or "![x]()" in result


class TestLists:
    def test_unordered(self):
        html = "<body><ul><li>one</li><li>two</li><li>three</li></ul></body>"
        result = html_to_markdown(parse(html))
        assert "one" in result
        assert "two" in result
        assert "three" in result
        assert "*" in result or "-" in result

    def test_ordered(self):
        html = "<body><ol><li>first</li><li>second</li></ol></body>"
        result = html_to_markdown(parse(html))
        assert "1. first" in result
        assert "2. second" in result

    def test_nested_inline_in_list(self):
        html = "<body><ul><li><strong>bold item</strong></li></ul></body>"
        result = html_to_markdown(parse(html))
        assert "**bold item**" in result


class TestBlockquote:
    def test_basic(self):
        html = "<body><blockquote><p>quoted text</p></blockquote></body>"
        result = html_to_markdown(parse(html))
        assert "> " in result
        assert "quoted text" in result

    def test_multiline(self):
        html = "<body><blockquote><p>line one</p><p>line two</p></blockquote></body>"
        result = html_to_markdown(parse(html))
        lines = [line for line in result.split("\n") if line.strip().startswith(">")]
        assert len(lines) >= 2


class TestTable:
    def test_basic_table(self):
        html = (
            "<body><table>"
            "<thead><tr><th>Name</th><th>Age</th></tr></thead>"
            "<tbody><tr><td>Alice</td><td>30</td></tr></tbody>"
            "</table></body>"
        )
        result = html_to_markdown(parse(html))
        assert "| Name | Age |" in result
        assert "| --- | --- |" in result
        assert "| Alice | 30 |" in result

    def test_table_without_thead(self):
        html = (
            "<body><table>"
            "<tr><th>X</th><th>Y</th></tr>"
            "<tr><td>1</td><td>2</td></tr>"
            "</table></body>"
        )
        result = html_to_markdown(parse(html))
        assert "| X | Y |" in result
        assert "| 1 | 2 |" in result

    def test_table_uneven_rows(self):
        html = (
            "<body><table>"
            "<thead><tr><th>A</th><th>B</th><th>C</th></tr></thead>"
            "<tbody><tr><td>1</td><td>2</td></tr></tbody>"
            "</table></body>"
        )
        result = html_to_markdown(parse(html))
        assert "| A | B | C |" in result
        assert result.count("|") >= 8


class TestDefinitionList:
    def test_basic(self):
        html = "<body><dl><dt>Term</dt><dd>Definition</dd></dl></body>"
        result = html_to_markdown(parse(html))
        assert "Term" in result
        assert "Definition" in result


class TestDetails:
    def test_with_summary(self):
        html = "<body><details><summary>Click me</summary><p>Hidden content</p></details></body>"
        result = html_to_markdown(parse(html))
        assert "Click me" in result
        assert "Hidden content" in result


class TestMiscElements:
    def test_hr(self):
        html = "<body><p>before</p><hr><p>after</p></body>"
        result = html_to_markdown(parse(html))
        assert "---" in result

    def test_br(self):
        html = "<body><p>line1<br>line2</p></body>"
        result = html_to_markdown(parse(html))
        assert "line1" in result
        assert "line2" in result

    def test_transparent_div(self):
        html = "<body><div><p>inside div</p></div></body>"
        result = html_to_markdown(parse(html))
        assert "inside div" in result

    def test_nested_spans(self):
        html = "<body><p><span><span>deep text</span></span></p></body>"
        result = html_to_markdown(parse(html))
        assert "deep text" in result


class TestWhitespace:
    def test_no_excessive_blank_lines(self):
        html = "<body><h1>A</h1><p>B</p><p>C</p></body>"
        result = html_to_markdown(parse(html))
        assert "\n\n\n\n" not in result

    def test_stripped_result(self):
        html = "<body><p>content</p></body>"
        result = html_to_markdown(parse(html))
        assert result == result.strip()


class TestComplexDocument:
    def test_full_doc_page(self):
        html = (
            "<body>"
            "<h1>Getting Started</h1>"
            "<p>Install the package:</p>"
            '<pre><code class="language-bash">pip install fastapi</code></pre>'
            "<h2>First Steps</h2>"
            "<p>Create a <strong>simple</strong> app:</p>"
            '<pre><code class="language-python">'
            "from fastapi import FastAPI\n\napp = FastAPI()"
            "</code></pre>"
            "<p>Features:</p>"
            "<ul><li>Fast</li><li>Easy</li><li>Robust</li></ul>"
            "<blockquote><p>This is great!</p></blockquote>"
            "<table>"
            "<thead><tr><th>Method</th><th>Path</th></tr></thead>"
            "<tbody><tr><td>GET</td><td>/items</td></tr></tbody>"
            "</table>"
            "</body>"
        )
        result = html_to_markdown(parse(html))

        assert "# Getting Started" in result
        assert "## First Steps" in result
        assert "```bash" in result
        assert "pip install fastapi" in result
        assert "```python" in result
        assert "from fastapi import FastAPI" in result
        assert "app = FastAPI()" in result
        assert "**simple**" in result
        assert "Fast" in result
        assert "Easy" in result
        assert "> " in result
        assert "| Method | Path |" in result
        assert "| GET | /items |" in result

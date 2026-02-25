from src.parsing.html_extractor import extract_content, extract_title


class TestExtractContent:
    def test_finds_article_before_main(self):
        html = "<html><body><main><p>main</p><article><p>article</p></article></main></body></html>"
        result = extract_content(html)
        assert result is not None
        assert result.name == "article"

    def test_finds_main_tag(self):
        html = "<html><body><nav>menu</nav><main><p>content</p></main></body></html>"
        result = extract_content(html)
        assert result is not None
        assert "content" in result.get_text()
        assert "menu" not in result.get_text()

    def test_finds_role_main(self):
        html = '<html><body><div role="main"><p>sphinx content</p></div></body></html>'
        result = extract_content(html)
        assert result is not None
        assert "sphinx content" in result.get_text()

    def test_finds_by_class(self):
        html = '<html><body><div class="markdown-body"><p>docs</p></div></body></html>'
        result = extract_content(html)
        assert result is not None
        assert "docs" in result.get_text()

    def test_css_selector_override(self):
        html = '<html><body><main><p>main</p></main><div id="custom"><p>custom</p></div></body></html>'
        result = extract_content(html, css_selector="#custom")
        assert result is not None
        assert "custom" in result.get_text()
        assert "main" not in result.get_text()

    def test_fallback_to_largest_div(self):
        html = (
            "<html><body>"
            "<div>short</div>"
            "<div><p>this is a much longer block of text that should be "
            "detected as the main content area because it has the most text</p></div>"
            "</body></html>"
        )
        result = extract_content(html)
        assert result is not None
        assert "much longer block" in result.get_text()

    def test_returns_none_for_empty_html(self):
        assert extract_content("") is None
        assert extract_content("<html><body></body></html>") is None


class TestStripNoise:
    def test_removes_nav(self):
        html = "<main><nav>nav stuff</nav><p>content</p></main>"
        result = extract_content(html)
        assert "nav stuff" not in result.get_text()
        assert "content" in result.get_text()

    def test_removes_footer(self):
        html = "<main><p>content</p><footer>footer stuff</footer></main>"
        result = extract_content(html)
        assert "footer stuff" not in result.get_text()

    def test_removes_script_and_style(self):
        html = "<main><script>var x=1;</script><style>.x{}</style><p>content</p></main>"
        result = extract_content(html)
        assert "var x" not in result.get_text()
        assert "content" in result.get_text()

    def test_removes_buttons(self):
        """buttons are UI noise (copy, toggle, etc.)"""
        html = '<main><button>Copy</button><button class="toggle">Menu</button><p>content</p></main>'
        result = extract_content(html)
        assert "Copy" not in result.get_text()
        assert "Menu" not in result.get_text()
        assert "content" in result.get_text()

    def test_removes_sidebar_by_class(self):
        html = '<main><div class="sidebar">side</div><p>content</p></main>'
        result = extract_content(html)
        assert "side" not in result.get_text()

    def test_removes_toc_by_id(self):
        html = '<main><div id="table-of-contents">toc</div><p>content</p></main>'
        result = extract_content(html)
        assert "toc" not in result.get_text()

    def test_removes_toc_by_class_case_insensitive(self):
        html = '<main><div id="TableOfContents">toc stuff</div><p>content</p></main>'
        result = extract_content(html)
        assert "toc stuff" not in result.get_text()

    def test_removes_breadcrumbs(self):
        html = (
            '<article><nav id="breadcrumbs">Home / Docs</nav><p>content</p></article>'
        )
        result = extract_content(html)
        assert "Home / Docs" not in result.get_text()

    def test_removes_pagination(self):
        html = '<article><p>content</p><div class="pagination">Next »</div></article>'
        result = extract_content(html)
        assert "Next" not in result.get_text()

    def test_removes_search(self):
        html = '<main><div class="search-box">search here</div><p>content</p></main>'
        result = extract_content(html)
        assert "search here" not in result.get_text()

    def test_removes_line_numbers(self):
        html = """
        <article>
            <p>description</p>
            <table class="highlighttable">
                <tr>
                    <td class="linenos"><pre>1\n2\n3</pre></td>
                    <td class="code"><pre><code>print("hello")</code></pre></td>
                </tr>
            </table>
        </article>
        """
        result = extract_content(html)
        text = result.get_text()
        assert "description" in text
        assert 'print("hello")' in text
        assert result.find("td", class_="linenos") is None

    def test_removes_clipboard_buttons(self):
        html = """
        <main>
            <div class="highlight">
                <button class="clipboard-copy">Copy</button>
                <pre><code>pip install fastapi</code></pre>
            </div>
        </main>
        """
        result = extract_content(html)
        assert "pip install fastapi" in result.get_text()

    def test_removes_display_none(self):
        html = '<main><div style="display:none">hidden</div><p>visible</p></main>'
        result = extract_content(html)
        assert "hidden" not in result.get_text()
        assert "visible" in result.get_text()

    def test_removes_display_none_with_spaces(self):
        html = '<main><div style="display: none">hidden</div><p>visible</p></main>'
        result = extract_content(html)
        assert "hidden" not in result.get_text()

    def test_removes_visibility_hidden(self):
        html = (
            '<main><div style="visibility: hidden">invisible</div><p>visible</p></main>'
        )
        result = extract_content(html)
        assert "invisible" not in result.get_text()

    def test_preserves_code_blocks(self):
        html = """
        <article>
            <p>Install:</p>
            <pre><code class="language-bash">pip install fastapi</code></pre>
            <p>Then run it.</p>
        </article>
        """
        result = extract_content(html)
        pre_tags = result.find_all("pre")
        assert len(pre_tags) == 1
        assert "pip install fastapi" in pre_tags[0].get_text()

    def test_preserves_multiple_code_blocks(self):
        html = """
        <article>
            <pre><code>block one</code></pre>
            <p>text between</p>
            <pre><code>block two</code></pre>
        </article>
        """
        result = extract_content(html)
        pre_tags = result.find_all("pre")
        assert len(pre_tags) == 2

    def test_preserves_tables(self):
        html = """
        <article>
            <table><tr><th>Param</th><th>Type</th></tr>
            <tr><td>name</td><td>str</td></tr></table>
        </article>
        """
        result = extract_content(html)
        assert result.find("table") is not None

    def test_preserves_headings(self):
        html = "<article><h1>Title</h1><h2>Section</h2><p>text</p></article>"
        result = extract_content(html)
        assert result.find("h1") is not None
        assert result.find("h2") is not None

    def test_preserves_links(self):
        html = '<article><p>See <a href="https://example.com">docs</a></p></article>'
        result = extract_content(html)
        link = result.find("a")
        assert link is not None
        assert link["href"] == "https://example.com"


class TestExtractTitle:
    def test_from_h1(self):
        assert (
            extract_title("<html><body><h1>My Title</h1></body></html>") == "My Title"
        )

    def test_from_title_tag(self):
        assert (
            extract_title("<html><head><title>Page Title</title></head></html>")
            == "Page Title"
        )

    def test_from_og_title(self):
        html = '<html><head><meta property="og:title" content="OG Title"></head></html>'
        assert extract_title(html) == "OG Title"

    def test_h1_takes_priority(self):
        html = "<html><head><title>Title Tag</title></head><body><h1>H1 Title</h1></body></html>"
        assert extract_title(html) == "H1 Title"

    def test_strips_headerlink_pilcrow(self):
        html = '<h1>My Title<a class="headerlink" href="#my-title">¶</a></h1>'
        assert extract_title(html) == "My Title"

    def test_strips_headerlink_hash(self):
        html = '<h1>My Title<a class="headerlink" href="#my-title">#</a></h1>'
        assert extract_title(html) == "My Title"

    def test_h1_with_inline_code(self):
        html = "<h1>Exceptions - <code>HTTPException</code> and <code>WebSocketException</code></h1>"
        title = extract_title(html)
        assert "HTTPException" in title
        assert "WebSocketException" in title
        assert "HTTPExceptionand" not in title

    def test_empty_html(self):
        assert extract_title("") == ""
        assert extract_title("<html><body></body></html>") == ""


class TestEdgeCases:
    def test_nested_noise_inside_content(self):
        html = """
        <article>
            <p>content</p>
            <div class="wrapper">
                <div class="sidebar-nav">sidebar noise</div>
                <p>more content</p>
            </div>
        </article>
        """
        result = extract_content(html)
        assert "content" in result.get_text()
        assert "more content" in result.get_text()
        assert "sidebar noise" not in result.get_text()

    def test_multiple_noise_classes(self):
        html = '<main><div class="widget sidebar-left">noise</div><p>content</p></main>'
        result = extract_content(html)
        assert "noise" not in result.get_text()

    def test_noise_substring_match(self):
        html = '<main><div class="my-navigation-panel">nav</div><p>content</p></main>'
        result = extract_content(html)
        assert "nav" not in result.get_text()

    def test_code_block_with_syntax_highlighting_spans(self):
        html = """
        <article>
            <pre><code><span class="kn">from</span> <span class="nn">fastapi</span>
<span class="kn">import</span> <span class="n">FastAPI</span></code></pre>
        </article>
        """
        result = extract_content(html)
        code_text = result.find("pre").get_text()
        assert "from" in code_text
        assert "fastapi" in code_text
        assert "FastAPI" in code_text

    def test_code_block_strips_double_encoded_html(self):
        html = (
            "<article><pre><code>"
            '<span class="go">&lt;font color="#4E9A06"&gt;hello&lt;/font&gt;</span>'
            "</code></pre></article>"
        )
        result = extract_content(html)
        text = result.find("pre").get_text()
        assert "hello" in text
        assert "<font" not in text
        assert "&lt;" not in text

    def test_code_block_preserves_language_class(self):
        html = '<article><pre><code class="language-python"><span class="n">x</span> = 1</code></pre></article>'
        result = extract_content(html)
        code = result.find("code")
        assert code is not None
        assert "language-python" in code.get("class", [])

    def test_definition_list_flattened(self):
        html = """
        <article>
            <dl class="py method">
                <dt>Path.resolve(strict=False)</dt>
                <dd><p>Make the path absolute.</p>
                <pre><code>>>> p.resolve()</code></pre></dd>
            </dl>
        </article>
        """
        result = extract_content(html)
        assert result.find("dl") is None
        assert "Path.resolve(strict=False)" in result.get_text()
        assert "Make the path absolute." in result.get_text()
        assert result.find("pre") is not None

    def test_content_with_no_standard_container(self):
        html = """
        <html><body>
            <div>tiny</div>
            <div>
                <h2>Documentation</h2>
                <p>This is the actual documentation content that is quite long
                and should be detected as the main content block by the fallback.</p>
            </div>
        </body></html>
        """
        result = extract_content(html)
        assert result is not None
        assert "Documentation" in result.get_text()

    def test_css_selector_returns_none_if_not_found(self):
        html = "<main><p>content</p></main>"
        result = extract_content(html, css_selector="#nonexistent")
        assert result is None

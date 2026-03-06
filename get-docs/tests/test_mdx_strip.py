from src.parsing.mdx_strip import strip_mdx


class TestImportExportRemoval:
    def test_removes_import_lines(self):
        content = "import { Alert } from './components'\n\n# Hello\n"
        result = strip_mdx(content)
        assert "import" not in result
        assert "# Hello" in result

    def test_removes_export_lines(self):
        content = "export const meta = { title: 'Docs' }\n\n# Hello\n"
        result = strip_mdx(content)
        assert "export" not in result
        assert "# Hello" in result

    def test_removes_multiple_imports(self):
        content = (
            "import A from './a'\nimport { B, C } from './bc'\n\n# Title\nSome text\n"
        )
        result = strip_mdx(content)
        assert "import" not in result
        assert "# Title" in result
        assert "Some text" in result

    def test_keeps_import_in_code_block(self):
        content = "# Example\n\n```js\nimport React from 'react'\n```\n"
        result = strip_mdx(content)
        assert "import React" in result


class TestSelfClosingTags:
    def test_removes_self_closing_tag(self):
        result = strip_mdx("# Title\n\n<Spacer />\n\nSome text\n")
        assert "Spacer" not in result
        assert "# Title" in result
        assert "Some text" in result

    def test_removes_self_closing_tag_with_props(self):
        result = strip_mdx('<Banner message="hello" />\n\n# Docs\n')
        assert "Banner" not in result
        assert "# Docs" in result

    def test_keeps_html_self_closing(self):
        result = strip_mdx("Text with <br /> break\n")
        assert "<br />" in result


class TestWrapperTags:
    def test_strips_wrapper_keeps_content(self):
        content = "<Alert>\nThis is important\n</Alert>\n"
        result = strip_mdx(content)
        assert "Alert" not in result
        assert "This is important" in result

    def test_strips_wrapper_with_props(self):
        content = '<Callout type="warning">\nBe careful\n</Callout>\n'
        result = strip_mdx(content)
        assert "Callout" not in result
        assert "Be careful" in result

    def test_keeps_html_tags(self):
        content = "<div>\nSome content\n</div>\n"
        result = strip_mdx(content)
        assert "<div>" in result

    def test_nested_markdown_preserved(self):
        content = "<Note>\n\n**Bold text** and `code`\n\n</Note>\n"
        result = strip_mdx(content)
        assert "Note" not in result
        assert "**Bold text**" in result
        assert "`code`" in result


class TestJsxComments:
    def test_removes_inline_jsx_comment(self):
        content = "# Title\n\n{/* This is a comment */}\n\nSome text\n"
        result = strip_mdx(content)
        assert "This is a comment" not in result
        assert "# Title" in result
        assert "Some text" in result

    def test_removes_multiline_jsx_comment(self):
        content = "# Title\n\n{/*\nThis is a\nmultiline comment\n*/}\n\nSome text\n"
        result = strip_mdx(content)
        assert "multiline comment" not in result
        assert "# Title" in result
        assert "Some text" in result

    def test_removes_jsx_comment_inline_with_content(self):
        content = "Some text {/* hidden */} more text\n"
        result = strip_mdx(content)
        assert "hidden" not in result
        assert "Some text" in result
        assert "more text" in result

    def test_keeps_jsx_comment_in_code_block(self):
        content = "# Example\n\n```jsx\n{/* This stays */}\n```\n"
        result = strip_mdx(content)
        assert "{/* This stays */}" in result


class TestCodeBlocks:
    def test_jsx_inside_code_block_preserved(self):
        content = '# Example\n\n```jsx\n<MyComponent prop="val">\n  <Child />\n</MyComponent>\n```\n'
        result = strip_mdx(content)
        assert "<MyComponent" in result
        assert "<Child />" in result

    def test_import_inside_code_block_preserved(self):
        content = "# Setup\n\n```\nimport Something from 'pkg'\n```\n"
        result = strip_mdx(content)
        assert "import Something" in result


class TestFullDocument:
    def test_realistic_mdx(self):
        content = """\
import { Callout } from 'nextra-theme-docs'
import { Tab, Tabs } from 'nextra-theme-docs'
export const meta = { title: 'Getting Started' }

# Getting Started

Welcome to the docs.

<Callout type="info">
Make sure you have Node.js installed.
</Callout>

## Installation

<Tabs items={['npm', 'yarn']}>
<Tab>

```bash
npm install my-package
```

</Tab>
<Tab>

```bash
yarn add my-package
```

</Tab>
</Tabs>

<Spacer />

That's it!
"""
        result = strip_mdx(content)
        assert "import" not in result.split("```")[0]
        assert "export const meta" not in result
        assert "# Getting Started" in result
        assert "Welcome to the docs." in result
        assert "Make sure you have Node.js installed." in result
        assert "npm install my-package" in result
        assert "yarn add my-package" in result
        assert "That's it!" in result
        assert "Callout" not in result
        assert "Spacer" not in result


class TestEdgeCases:
    def test_empty_string(self):
        assert strip_mdx("") == ""

    def test_plain_markdown_unchanged(self):
        content = "# Title\n\nSome **bold** text.\n\n- item 1\n- item 2\n"
        result = strip_mdx(content)
        assert "# Title" in result
        assert "**bold**" in result
        assert "- item 1" in result

    def test_no_excessive_blank_lines(self):
        content = "import X from 'x'\n\n\n\n# Title\n"
        result = strip_mdx(content)
        assert "\n\n\n" not in result

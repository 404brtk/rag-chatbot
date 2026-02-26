from src.core.llms_txt_fetcher import parse_llms_txt


class TestTitle:
    def test_extracts_h1(self):
        result = parse_llms_txt("# My Project\n")
        assert result.title == "My Project"

    def test_first_h1_wins(self):
        result = parse_llms_txt("# First\n# Second\n")
        assert result.title == "First"

    def test_no_h1(self):
        result = parse_llms_txt("some content\n")
        assert result.title is None

    def test_h1_with_extra_whitespace(self):
        result = parse_llms_txt("#   Spaced Title  \n")
        assert result.title == "Spaced Title"


class TestSummary:
    def test_single_line_blockquote(self):
        content = "# Title\n\n> A short summary\n"
        result = parse_llms_txt(content)
        assert result.summary == "A short summary"

    def test_multiline_blockquote(self):
        content = "# Title\n> Line one\n> Line two\n> Line three\n"
        result = parse_llms_txt(content)
        assert result.summary == "Line one Line two Line three"

    def test_no_blockquote(self):
        result = parse_llms_txt("# Title\n\nJust text\n")
        assert result.summary is None

    def test_blockquote_not_after_h1_ignored(self):
        content = "Some text\n> Not a summary\n# Title\n"
        result = parse_llms_txt(content)
        assert result.summary is None


class TestLinks:
    def test_single_link(self):
        content = (
            "# Title\n\n## Docs\n\n- [Guide](https://example.com/guide): A guide\n"
        )
        result = parse_llms_txt(content)
        assert len(result.links) == 1
        link = result.links[0]
        assert link.title == "Guide"
        assert link.url == "https://example.com/guide"
        assert link.description == "A guide"
        assert link.section == "Docs"
        assert link.optional is False

    def test_multiple_links(self):
        content = (
            "# Proj\n\n"
            "## API\n"
            "- [Ref](https://example.com/ref): API reference\n"
            "- [Auth](https://example.com/auth): Authentication\n"
        )
        result = parse_llms_txt(content)
        assert len(result.links) == 2
        assert result.links[0].title == "Ref"
        assert result.links[1].title == "Auth"

    def test_link_without_description(self):
        content = "# T\n\n## Docs\n- [Page](https://example.com/page)\n"
        result = parse_llms_txt(content)
        assert len(result.links) == 1
        assert result.links[0].description is None

    def test_link_without_section(self):
        content = "# T\n\n- [Page](https://example.com/page): desc\n"
        result = parse_llms_txt(content)
        assert len(result.links) == 1
        assert result.links[0].section is None

    def test_multiple_sections(self):
        content = (
            "# T\n\n"
            "## Docs\n"
            "- [A](https://example.com/a)\n"
            "## Examples\n"
            "- [B](https://example.com/b)\n"
        )
        result = parse_llms_txt(content)
        assert result.links[0].section == "Docs"
        assert result.links[1].section == "Examples"


class TestOptionalSection:
    def test_optional_links_flagged(self):
        content = (
            "# T\n\n"
            "## Docs\n"
            "- [Required](https://example.com/req)\n"
            "## Optional\n"
            "- [Extra](https://example.com/extra)\n"
        )
        result = parse_llms_txt(content)
        assert result.links[0].optional is False
        assert result.links[1].optional is True

    def test_optional_case_insensitive(self):
        content = "# T\n\n## optional\n- [Link](https://example.com/link)\n"
        result = parse_llms_txt(content)
        assert result.links[0].optional is True

    def test_non_optional_after_optional(self):
        content = (
            "# T\n\n"
            "## Optional\n"
            "- [A](https://a.com)\n"
            "## More Docs\n"
            "- [B](https://b.com)\n"
        )
        result = parse_llms_txt(content)
        assert result.links[0].optional is True
        assert result.links[1].optional is False


class TestRelativeUrls:
    def test_relative_url_resolved(self):
        content = "# T\n\n## Docs\n- [Guide](guide.md): A guide\n"
        result = parse_llms_txt(content, source_url="https://example.com/llms.txt")
        assert result.links[0].url == "https://example.com/guide.md"

    def test_absolute_url_unchanged(self):
        content = "# T\n\n## Docs\n- [Guide](https://other.com/guide)\n"
        result = parse_llms_txt(content, source_url="https://example.com/llms.txt")
        assert result.links[0].url == "https://other.com/guide"

    def test_relative_path_with_directory(self):
        content = "# T\n\n- [Page](docs/page.md)\n"
        result = parse_llms_txt(content, source_url="https://example.com/docs/llms.txt")
        assert result.links[0].url == "https://example.com/docs/docs/page.md"

    def test_no_source_url_keeps_relative(self):
        content = "# T\n\n- [Page](page.md)\n"
        result = parse_llms_txt(content)
        assert result.links[0].url == "page.md"


class TestResultMetadata:
    def test_source_url_stored(self):
        result = parse_llms_txt("# T\n", source_url="https://example.com/llms.txt")
        assert result.source_url == "https://example.com/llms.txt"

    def test_raw_content_stored(self):
        content = "# Title\n> Summary\n"
        result = parse_llms_txt(content)
        assert result.raw_content == content

    def test_is_full_flag(self):
        result = parse_llms_txt("# T\n", is_full=True)
        assert result.is_full is True

    def test_is_full_default_false(self):
        result = parse_llms_txt("# T\n")
        assert result.is_full is False


class TestEdgeCases:
    def test_empty_string(self):
        result = parse_llms_txt("")
        assert result.title is None
        assert result.summary is None
        assert result.links == []

    def test_whitespace_only(self):
        result = parse_llms_txt("   \n\n  ")
        assert result.title is None
        assert result.links == []

    def test_h2_without_h1(self):
        content = "## Section\n- [Link](https://example.com)\n"
        result = parse_llms_txt(content)
        assert result.title is None
        assert len(result.links) == 1
        assert result.links[0].section == "Section"

    def test_non_link_list_items_ignored(self):
        content = "# T\n\n## Docs\n- Not a link\n- [Real](https://example.com)\n- Also not a link\n"
        result = parse_llms_txt(content)
        assert len(result.links) == 1
        assert result.links[0].title == "Real"

    def test_body_text_between_sections(self):
        content = (
            "# Title\n\n"
            "> Summary\n\n"
            "Some body text here.\n\n"
            "More body text.\n\n"
            "## Docs\n"
            "- [Link](https://example.com)\n"
        )
        result = parse_llms_txt(content)
        assert result.title == "Title"
        assert result.summary == "Summary"
        assert len(result.links) == 1

    def test_link_with_special_chars_in_title(self):
        content = "# T\n\n- [`code_func()`](https://example.com/ref)\n"
        result = parse_llms_txt(content)
        assert result.links[0].title == "`code_func()`"

    def test_link_with_colon_in_url(self):
        content = "# T\n\n- [Page](https://example.com:8080/page)\n"
        result = parse_llms_txt(content)
        assert result.links[0].url == "https://example.com:8080/page"


class TestRealisticLlmsTxt:
    def test_cloudflare_style(self):
        content = """\
# Cloudflare Developer Documentation

Explore guides and tutorials to start building on Cloudflare's platform.

> Each product below links to its own llms.txt, which contains a full index of that product's documentation pages and is the recommended way to explore a specific product's content.
>
> For the complete documentation archive in a single file, use the [Full Documentation Archive](https://developers.cloudflare.com/llms-full.txt). That file is intended for offline indexing, bulk vectorization, or large-context models. Each product's llms.txt also links to a product-scoped llms-full.txt.

## Application performance

- [Cache / CDN](https://developers.cloudflare.com/cache/llms.txt): Make websites faster by caching content across our global server network
- [DNS](https://developers.cloudflare.com/dns/llms.txt): Deliver excellent performance and reliability to your domain
- [Cache Rules](https://developers.cloudflare.com/cache-rules/llms.txt)
- [Load Balancing](https://developers.cloudflare.com/load-balancing/llms.txt): Maximize application performance and availability

## Application security

- [WAF](https://developers.cloudflare.com/waf/llms.txt): Filter incoming traffic and protect against web app vulnerabilities
- [DDoS Protection](https://developers.cloudflare.com/ddos-protection/llms.txt): Protect against DDoS attacks automatically with uncompromised performance
- [Turnstile](https://developers.cloudflare.com/turnstile/llms.txt): Turnstile is Cloudflare's smart CAPTCHA alternative

## Developer platform

- [Workers](https://developers.cloudflare.com/workers/llms.txt): Build, deploy, and scale serverless applications globally with low latency and minimal configuration
- [D1](https://developers.cloudflare.com/d1/llms.txt): Create managed, serverless databases with SQL semantics
- [R2](https://developers.cloudflare.com/r2/llms.txt): Store large amounts of unstructured data without egress fees

## Optional

- [Firewall Rules (deprecated)](https://developers.cloudflare.com/firewall/llms.txt): Create rules that examine incoming HTTP traffic against a set of powerful filters to block, challenge, log, or allow matching requests. Firewall Rules have been replaced with WAF custom rules.
"""
        result = parse_llms_txt(
            content,
            source_url="https://developers.cloudflare.com/llms.txt",
        )
        assert result.title == "Cloudflare Developer Documentation"
        assert result.summary is not None
        assert "recommended way to explore" in result.summary
        assert len(result.links) == 11

        perf = [lnk for lnk in result.links if lnk.section == "Application performance"]
        assert len(perf) == 4
        assert perf[0].title == "Cache / CDN"
        assert perf[2].title == "Cache Rules"
        assert perf[2].description is None

        security = [
            lnk for lnk in result.links if lnk.section == "Application security"
        ]
        assert len(security) == 3

        devplat = [lnk for lnk in result.links if lnk.section == "Developer platform"]
        assert len(devplat) == 3
        assert devplat[0].url == "https://developers.cloudflare.com/workers/llms.txt"

        optional = [lnk for lnk in result.links if lnk.optional]
        assert len(optional) == 1
        assert "deprecated" in optional[0].title

    def test_stripe_style(self):
        content = """\
# Stripe Documentation

## Docs
- [Testing](https://docs.stripe.com/testing.md): Simulate payments to test your integration.
- [API Reference](https://docs.stripe.com/api.md)
- [Supported currencies](https://docs.stripe.com/currencies.md): Learn which currencies Stripe supports.

## Payment Methods
Acquire more customers and improve conversion by offering the most popular payment methods around the world.

- [Payment Methods API](https://docs.stripe.com/payments/payment-methods.md): Learn more about the API that powers a range of global payment methods.
- [Linked external accounts](https://docs.stripe.com/get-started/account/linked-external-accounts.md): Manage your linked external accounts.
"""
        result = parse_llms_txt(content, source_url="https://docs.stripe.com/llms.txt")
        assert result.title == "Stripe Documentation"
        assert result.summary is None
        assert len(result.links) == 5

        docs = [lnk for lnk in result.links if lnk.section == "Docs"]
        assert len(docs) == 3
        assert docs[1].description is None

        payment = [lnk for lnk in result.links if lnk.section == "Payment Methods"]
        assert len(payment) == 2

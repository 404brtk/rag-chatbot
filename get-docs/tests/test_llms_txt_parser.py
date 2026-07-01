import pytest

from src.core.llms_txt_parser import fetch_llms_txt, is_llms_txt_full, parse_llms_txt
from src.core.robots_txt_parser import RobotsParser
from src.models.responses import EthicsContext
from tests.conftest import mock_http_client, mock_response


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


class TestFetchLlmsTxtRobotsCheck:
    @pytest.mark.asyncio
    async def test_skips_when_ai_input_disallowed(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /\nContent-Signal: ai-input=no")
        client, inner = mock_http_client(mocker)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is None
        inner.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_path_disallowed(self, mocker):
        robots = RobotsParser(
            "User-agent: *\nDisallow: /llms-full.txt\nDisallow: /llms.txt"
        )
        client, inner = mock_http_client(mocker)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is None
        inner.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetches_robots_when_none_provided(self, mocker):
        llms_content = "# Docs\n> Summary\n## API\n- [Ref](https://example.com/api)\n"

        def side_effect(url, **kw):
            if "robots.txt" in url:
                return mock_response(
                    text="User-agent: *\nAllow: /", content_type="text/plain"
                )
            return mock_response(text=llms_content, content_type="text/plain")

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt("https://example.com", client)

        assert result is not None
        assert result.title == "Docs"
        calls = [str(c) for c in inner.get.call_args_list]
        assert any("robots.txt" in c for c in calls)

    @pytest.mark.asyncio
    async def test_allows_when_robots_permits(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")
        content = "# Docs\n> Summary\n"

        def side_effect(url, **kw):
            if url == "https://example.com/llms-full.txt":
                return mock_response(text=content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is not None
        assert result.title == "Docs"
        assert result.source_url == "https://example.com/llms-full.txt"

    @pytest.mark.asyncio
    async def test_deep_url_finds_llms_txt_at_root(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")
        content = "# Root Docs\n> Found at root\n"

        def side_effect(url, **kw):
            if url == "https://example.com/llms-full.txt":
                return mock_response(text=content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt(
            "https://example.com/docs/en/home", client, robots=robots
        )

        assert result is not None
        assert result.title == "Root Docs"
        assert result.source_url == "https://example.com/llms-full.txt"

    @pytest.mark.asyncio
    async def test_deep_url_finds_llms_txt_at_subpath(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")
        content = "# Subpath Docs\n"

        def side_effect(url, **kw):
            if url == "https://example.com/docs/llms.txt":
                return mock_response(text=content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt(
            "https://example.com/docs/en/home", client, robots=robots
        )

        assert result is not None
        assert result.title == "Subpath Docs"
        assert result.source_url == "https://example.com/docs/llms.txt"

    @pytest.mark.asyncio
    async def test_closer_path_wins_over_root(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")

        def side_effect(url, **kw):
            if url == "https://example.com/docs/llms.txt":
                return mock_response(text="# Closer\n", content_type="text/plain")
            if url == "https://example.com/llms.txt":
                return mock_response(text="# Root\n", content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt(
            "https://example.com/docs/en/home", client, robots=robots
        )

        assert result is not None
        assert result.title == "Closer"

    @pytest.mark.asyncio
    async def test_partial_disallow_tries_allowed_path(self, mocker):
        robots = RobotsParser("User-agent: *\nDisallow: /llms-full.txt")
        content = "# Fallback\n"

        def side_effect(url, **kw):
            if url == "https://example.com/llms.txt":
                return mock_response(text=content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is not None
        assert result.title == "Fallback"
        assert result.is_full is False
        assert result.source_url == "https://example.com/llms.txt"


class TestFetchLlmsTxtEthicsTracking:
    @pytest.mark.asyncio
    async def test_increments_ethics_when_robots_disallows(self, mocker):
        robots = RobotsParser(
            "User-agent: *\nDisallow: /llms-full.txt\nDisallow: /llms.txt"
        )
        client, inner = mock_http_client(mocker)
        ethics = EthicsContext()

        result = await fetch_llms_txt(
            "https://example.com", client, robots=robots, ethics=ethics
        )

        assert result is None
        assert ethics.pages_filtered_by_robots_txt == 2

    @pytest.mark.asyncio
    async def test_increments_ethics_when_ai_input_disallowed(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /\nContent-Signal: ai-input=no")
        client, inner = mock_http_client(mocker)
        ethics = EthicsContext()

        result = await fetch_llms_txt(
            "https://example.com", client, robots=robots, ethics=ethics
        )

        assert result is None
        assert ethics.pages_filtered_by_robots_txt == 2

    @pytest.mark.asyncio
    async def test_partial_disallow_increments_ethics_for_blocked_only(self, mocker):
        robots = RobotsParser("User-agent: *\nDisallow: /llms-full.txt")
        content = "# Fallback\n"

        def side_effect(url, **kw):
            if url == "https://example.com/llms.txt":
                return mock_response(text=content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)
        ethics = EthicsContext()

        result = await fetch_llms_txt(
            "https://example.com", client, robots=robots, ethics=ethics
        )

        assert result is not None
        assert ethics.pages_filtered_by_robots_txt == 1

    @pytest.mark.asyncio
    async def test_no_ethics_still_works(self, mocker):
        robots = RobotsParser(
            "User-agent: *\nDisallow: /llms-full.txt\nDisallow: /llms.txt"
        )
        client, inner = mock_http_client(mocker)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is None
        inner.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_ethics_not_incremented_when_allowed(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")
        content = "# Docs\n> Summary\n"

        def side_effect(url, **kw):
            if url == "https://example.com/llms-full.txt":
                return mock_response(text=content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)
        ethics = EthicsContext()

        result = await fetch_llms_txt(
            "https://example.com", client, robots=robots, ethics=ethics
        )

        assert result is not None
        assert ethics.pages_filtered_by_robots_txt == 0


_SVELTEKIT_LLMS_TXT_SAMPLE = """\
<SYSTEM>This is the developer documentation for SvelteKit.</SYSTEM>


# Introduction

## Before we begin

> [!NOTE] If you're new to Svelte or SvelteKit we recommend checking out the [interactive tutorial](/tutorial/kit).
>
> If you get stuck, reach out for help in the [Discord chatroom](/chat).

## What is SvelteKit?

SvelteKit is a framework for rapidly developing robust, performant web applications using [Svelte](../svelte). If you're coming from React, SvelteKit is similar to Next. If you're coming from Vue, SvelteKit is similar to Nuxt.

To learn more about the kinds of applications you can build with SvelteKit, see the [documentation regarding project types](project-types).

## What is Svelte?

In short, Svelte is a way of writing user interface components — like a navigation bar, comment section, or contact form — that users see and interact with in their browsers. The Svelte compiler converts your components to JavaScript that can be run to render the HTML for the page and to CSS that styles the page. You don't need to know Svelte to understand the rest of this guide, but it will help. If you'd like to learn more, check out [the Svelte tutorial](/tutorial).

## SvelteKit vs Svelte

Svelte renders UI components. You can compose these components and render an entire page with just Svelte, but you need more than just Svelte to write an entire app.

SvelteKit helps you build web apps while following modern best practices and providing solutions to common development challenges. It offers everything from basic functionalities — like a [router](glossary#Routing) that updates your UI when a link is clicked — to more advanced capabilities. Its extensive list of features includes [build optimizations](https://vitejs.dev/guide/features.html#build-optimizations) to load only the minimal required code; [offline support](service-workers); [preloading](link-options#data-sveltekit-preload-data) pages before user navigation; [configurable rendering](page-options) to handle different parts of your app on the server via [SSR](glossary#SSR), in the browser through [client-side rendering](glossary#CSR), or at build-time with [prerendering](glossary#Prerendering); [image optimization](images); and much more. Building an app with all the modern best practices is fiendishly complicated, but SvelteKit does all the boring stuff for you so that you can get on with the creative part.

It reflects changes to your code in the browser instantly to provide a lightning-fast and feature-rich development experience by leveraging [Vite](https://vitejs.dev/) with a [Svelte plugin](https://github.com/sveltejs/vite-plugin-svelte) to do [Hot Module Replacement (HMR)](https://github.com/sveltejs/vite-plugin-svelte/blob/main/docs/config.md#hot).

# Creating a project

The easiest way to start building a SvelteKit app is to run `npx sv create`:

```sh
npx sv create my-app
cd my-app
npm run dev
```

The first command will scaffold a new project in the `my-app` directory asking if you'd like to set up some basic tooling such as TypeScript. See [the CLI docs](/docs/cli/overview) for information about these options and [the integrations page](./integrations) for pointers on setting up additional tooling.

There are two basic concepts:

- Each page of your app is a [Svelte](../svelte) component
- You create pages by adding files to the `src/routes` directory of your project. These will be server-rendered so that a user's first visit to your app is as fast as possible, then a client-side app takes over

Try editing the files to get a feel for how everything works.

## Editor setup

We recommend using [Visual Studio Code (aka VS Code)](https://code.visualstudio.com/download) with [the Svelte extension](https://marketplace.visualstudio.com/items?itemName=svelte.svelte-vscode), but [support also exists for numerous other editors](https://sveltesociety.dev/collection/editor-support-c85c080efc292a34).

# Project types

SvelteKit offers configurable rendering, which allows you to build and deploy your project in several different ways.

## Default rendering

By default, when a user visits a site, SvelteKit will render the first page with [server-side rendering (SSR)](glossary#SSR) and subsequent pages with [client-side rendering (CSR)](glossary#CSR).

## Static site generation

You can use SvelteKit as a [static site generator (SSG)](glossary#SSG) that fully [prerenders](glossary#Prerendering) your site with static rendering using [`adapter-static`](adapter-static).

## Single-page app

[Single-page apps (SPAs)](glossary#SPA) exclusively use [client-side rendering (CSR)](glossary#CSR). You can [build single-page apps (SPAs)](single-page-apps) with SvelteKit.

## See Also

- [Advanced Routing](https://svelte.dev/docs/kit/advanced-routing): Parameter matchers and optional params
- [Form Actions](https://svelte.dev/docs/kit/form-actions): Server-side form handling
"""


class TestIsLlmsTxtFull:
    def test_spec_compliant_index_stays_as_index(self):
        content = """\
# Project Docs

> Project documentation index

## API
- [Auth](https://example.com/auth): Authentication guide
- [Users](https://example.com/users): User management
- [Billing](https://example.com/billing): Billing API

## Guides
- [Quickstart](https://example.com/start): Get started fast
- [Deploy](https://example.com/deploy): Deployment guide

## Optional
- [Legacy](https://example.com/legacy): Old API docs
"""
        result = parse_llms_txt(content)
        assert is_llms_txt_full(result) is False

    def test_sveltekit_docs_detected_as_full(self):
        result = parse_llms_txt(_SVELTEKIT_LLMS_TXT_SAMPLE)
        assert is_llms_txt_full(result) is True
        assert len(result.links) == 2

    def test_short_file_always_stays_as_index(self):
        content = "# Small Doc\n" + "Some content line.\n" * 10
        result = parse_llms_txt(content)
        assert is_llms_txt_full(result) is False

    def test_borderline_index_with_verbose_descriptions(self):
        sections = ["## API\n"]
        for i in range(8):
            sections.append(
                f"- [Service {i}](https://example.com/svc-{i}): "
                f"Handles all {i}-related operations\n"
            )
        padding = "This section covers the core services.\n" * 42
        content = (
            "# Services Index\n\n> Overview of all services\n\n"
            + padding
            + "".join(sections)
        )
        result = parse_llms_txt(content)
        meaningful = [line for line in content.splitlines() if line.strip()]
        ratio = 8 / len(meaningful)
        assert ratio > 0.1
        assert is_llms_txt_full(result) is False


class TestFetchDetectsFullContent:
    @pytest.mark.asyncio
    async def test_llms_txt_with_full_content_returns_is_full_true(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")

        def side_effect(url, **kw):
            if url.endswith("llms-full.txt"):
                return mock_response(status_code=404)
            if url.endswith("llms.txt"):
                return mock_response(
                    text=_SVELTEKIT_LLMS_TXT_SAMPLE, content_type="text/plain"
                )
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is not None
        assert result.is_full is True
        assert result.source_url == "https://example.com/llms.txt"

    @pytest.mark.asyncio
    async def test_llms_full_txt_skips_heuristic(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /")
        short_content = "# Docs\n> Summary\n"

        def side_effect(url, **kw):
            if url.endswith("llms-full.txt"):
                return mock_response(text=short_content, content_type="text/plain")
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        result = await fetch_llms_txt("https://example.com", client, robots=robots)

        assert result is not None
        assert result.is_full is True

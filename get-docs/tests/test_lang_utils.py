from src.utils.lang_utils import filter_language_urls, is_lang_code


class TestIsLangCode:
    def test_two_letter(self):
        assert is_lang_code("fr") is True
        assert is_lang_code("de") is True
        assert is_lang_code("en") is True

    def test_lang_with_region(self):
        assert is_lang_code("zh-cn") is True
        assert is_lang_code("zh-tw") is True
        assert is_lang_code("en-us") is True
        assert is_lang_code("pt-br") is True

    def test_non_lang(self):
        assert is_lang_code("config") is False
        assert is_lang_code("getting-started") is False
        assert is_lang_code("api") is False

    def test_three_letter_not_matched(self):
        assert is_lang_code("abc") is False

    def test_uppercase_not_matched(self):
        assert is_lang_code("FR") is False

    def test_empty(self):
        assert is_lang_code("") is False


class TestFilterLanguageUrls:
    def test_flat_no_english_prefix(self):
        base = "https://opencode.ai/docs"
        urls = [
            "https://opencode.ai/docs/config",
            "https://opencode.ai/docs/permissions",
            "https://opencode.ai/docs/hooks",
            "https://opencode.ai/docs/de",
            "https://opencode.ai/docs/fr",
            "https://opencode.ai/docs/es",
            "https://opencode.ai/docs/ja",
            "https://opencode.ai/docs/ko",
            "https://opencode.ai/docs/zh-cn",
            "https://opencode.ai/docs/zh-tw",
            "https://opencode.ai/docs/it",
            "https://opencode.ai/docs/da",
        ]
        result = filter_language_urls(urls, base)
        assert "https://opencode.ai/docs/config" in result
        assert "https://opencode.ai/docs/permissions" in result
        assert "https://opencode.ai/docs/hooks" in result
        for lang in ("de", "fr", "es", "ja", "ko", "zh-cn", "zh-tw", "it", "da"):
            assert f"https://opencode.ai/docs/{lang}" not in result

    def test_flat_with_nested_lang_pages(self):
        base = "https://opencode.ai/docs"
        urls = [
            "https://opencode.ai/docs/config",
            "https://opencode.ai/docs/guide",
            "https://opencode.ai/docs/de",
            "https://opencode.ai/docs/de/config",
            "https://opencode.ai/docs/fr",
            "https://opencode.ai/docs/fr/guide",
        ]
        result = filter_language_urls(urls, base)
        assert result == [
            "https://opencode.ai/docs/config",
            "https://opencode.ai/docs/guide",
        ]

    def test_nested_english_folder(self):
        base = "https://example.com"
        urls = [
            "https://example.com/en/guide",
            "https://example.com/en/api",
            "https://example.com/fr/guide",
            "https://example.com/fr/api",
            "https://example.com/de/guide",
        ]
        result = filter_language_urls(urls, base)
        assert result == [
            "https://example.com/en/guide",
            "https://example.com/en/api",
        ]

    def test_nested_en_us_folder(self):
        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/en-us/intro",
            "https://example.com/docs/en-us/guide",
            "https://example.com/docs/ja/intro",
            "https://example.com/docs/ja/guide",
        ]
        result = filter_language_urls(urls, base)
        assert result == [
            "https://example.com/docs/en-us/intro",
            "https://example.com/docs/en-us/guide",
        ]

    def test_empty_list(self):
        assert filter_language_urls([], "https://example.com") == []

    def test_no_language_codes(self):
        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/config",
            "https://example.com/docs/guide",
            "https://example.com/docs/api",
        ]
        result = filter_language_urls(urls, base)
        assert result == urls

    def test_single_language_code_not_filtered(self):
        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/config",
            "https://example.com/docs/go",
        ]
        result = filter_language_urls(urls, base)
        assert result == urls

    def test_similar_prefix_not_stripped(self):
        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/config",
            "https://example.com/docs-extra/page",
            "https://example.com/docs/de",
            "https://example.com/docs/fr",
        ]
        result = filter_language_urls(urls, base)
        assert "https://example.com/docs-extra/page" in result
        assert "https://example.com/docs/config" in result
        assert "https://example.com/docs/de" not in result
        assert "https://example.com/docs/fr" not in result

    def test_last_segment_detected(self):
        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/intro",
            "https://example.com/docs/de",
            "https://example.com/docs/fr",
        ]
        result = filter_language_urls(urls, base)
        assert result == ["https://example.com/docs/intro"]

    def test_preserves_order(self):
        base = "https://example.com"
        urls = [
            "https://example.com/en/c",
            "https://example.com/fr/a",
            "https://example.com/en/a",
            "https://example.com/de/b",
            "https://example.com/en/b",
        ]
        result = filter_language_urls(urls, base)
        assert result == [
            "https://example.com/en/c",
            "https://example.com/en/a",
            "https://example.com/en/b",
        ]

    def test_deeply_nested_lang_folder(self):
        base = "https://example.com"
        urls = [
            "https://example.com/product/docs/en/guide",
            "https://example.com/product/docs/en/api",
            "https://example.com/product/docs/fr/guide",
            "https://example.com/product/docs/de/guide",
        ]
        result = filter_language_urls(urls, base)
        assert result == [
            "https://example.com/product/docs/en/guide",
            "https://example.com/product/docs/en/api",
        ]

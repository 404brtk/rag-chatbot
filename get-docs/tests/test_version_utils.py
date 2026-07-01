from src.utils.version_utils import dedupe_versioned_urls, parse_version


class TestParseVersion:
    def test_numeric(self):
        assert parse_version("v1.2.3") == (1, 2, 3)
        assert parse_version("3.4") == (3, 4)
        assert parse_version("v9") == (9,)

    def test_keywords(self):
        assert parse_version("current") == (9999,)
        assert parse_version("stable") == (9999,)
        assert parse_version("latest") == (9999,)

    def test_version_prefix(self):
        assert parse_version("version-2.0") == (2, 0)

    def test_x_suffix(self):
        assert parse_version("v6.x") == (6,)
        assert parse_version("1.0.x") == (1, 0)

    def test_non_version(self):
        assert parse_version("guide") is None
        assert parse_version("getting-started") is None
        assert parse_version("upcoming") is None


class TestDedupeVersionedUrls:
    def test_prefers_current_over_numeric(self):
        urls = [
            "https://example.com/docs/csharp/current/quick-start",
            "https://example.com/docs/csharp/v3.4/quick-start",
            "https://example.com/docs/csharp/v3.3/quick-start",
        ]
        result = dedupe_versioned_urls(urls)
        assert result == ["https://example.com/docs/csharp/current/quick-start"]

    def test_picks_highest_numeric(self):
        urls = [
            "https://example.com/docs/driver/v1.0/guide",
            "https://example.com/docs/driver/v2.0/guide",
            "https://example.com/docs/driver/v1.5/guide",
        ]
        result = dedupe_versioned_urls(urls)
        assert result == ["https://example.com/docs/driver/v2.0/guide"]

    def test_unversioned_urls_kept(self):
        urls = [
            "https://example.com/docs/overview",
            "https://example.com/docs/guide",
        ]
        result = dedupe_versioned_urls(urls)
        assert result == urls

    def test_mixed_versioned_and_unversioned(self):
        urls = [
            "https://example.com/docs/overview",
            "https://example.com/docs/csharp/current/guide",
            "https://example.com/docs/csharp/v3.3/guide",
        ]
        result = dedupe_versioned_urls(urls)
        assert len(result) == 2
        assert "https://example.com/docs/overview" in result
        assert "https://example.com/docs/csharp/current/guide" in result

    def test_multiple_products_deduped_independently(self):
        urls = [
            "https://example.com/docs/java/current/guide",
            "https://example.com/docs/java/v4.0/guide",
            "https://example.com/docs/python/v2.0/guide",
            "https://example.com/docs/python/v1.0/guide",
        ]
        result = dedupe_versioned_urls(urls)
        assert len(result) == 2
        assert "https://example.com/docs/java/current/guide" in result
        assert "https://example.com/docs/python/v2.0/guide" in result

    def test_same_product_different_pages(self):
        urls = [
            "https://example.com/docs/driver/current/guide",
            "https://example.com/docs/driver/current/api",
            "https://example.com/docs/driver/v1.0/guide",
            "https://example.com/docs/driver/v1.0/api",
        ]
        result = dedupe_versioned_urls(urls)
        assert len(result) == 2
        assert "https://example.com/docs/driver/current/guide" in result
        assert "https://example.com/docs/driver/current/api" in result

    def test_single_version_kept(self):
        urls = [
            "https://example.com/docs/driver/v2.0/guide",
            "https://example.com/docs/driver/v2.0/api",
        ]
        result = dedupe_versioned_urls(urls)
        assert result == urls

    def test_empty_list(self):
        assert dedupe_versioned_urls([]) == []

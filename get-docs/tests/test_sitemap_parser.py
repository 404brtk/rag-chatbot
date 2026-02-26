import pytest

from src.core.sitemap_parser import SitemapParser


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _urlset_xml(*urls: str, ns: bool = True) -> str:
    """Helper to build a <urlset> XML string."""
    ns_attr = f' xmlns="{SITEMAP_NS}"' if ns else ""
    entries = ""
    for u in urls:
        entries += f"  <url><loc>{u}</loc></url>\n"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset{ns_attr}>\n{entries}</urlset>'
    )


def _urlset_xml_with_lastmod(urls: list[tuple[str, str]], ns: bool = True) -> str:
    """Helper for urlset with lastmod values."""
    ns_attr = f' xmlns="{SITEMAP_NS}"' if ns else ""
    entries = ""
    for loc, lastmod in urls:
        entries += f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>\n"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset{ns_attr}>\n{entries}</urlset>'
    )


def _index_xml(*sitemaps: str, ns: bool = True) -> str:
    """Helper to build a <sitemapindex> XML string."""
    ns_attr = f' xmlns="{SITEMAP_NS}"' if ns else ""
    entries = ""
    for s in sitemaps:
        entries += f"  <sitemap><loc>{s}</loc></sitemap>\n"
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex{ns_attr}>\n{entries}</sitemapindex>'


class TestUrlset:
    def test_single_url(self):
        xml = _urlset_xml("https://example.com/page1")
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/page1"
        assert urls[0].lastmod is None

    def test_multiple_urls(self):
        xml = _urlset_xml(
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        )
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 3
        assert [u.loc for u in urls] == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_with_lastmod(self):
        xml = _urlset_xml_with_lastmod(
            [
                ("https://example.com/page1", "2024-01-15"),
                ("https://example.com/page2", "2024-06-20T10:30:00+00:00"),
            ]
        )
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 2
        assert urls[0].lastmod == "2024-01-15"
        assert urls[1].lastmod == "2024-06-20T10:30:00+00:00"

    def test_not_an_index(self):
        parser = SitemapParser(_urlset_xml("https://example.com/"))
        assert parser.is_index() is False
        assert parser.get_sub_sitemaps() == []

    def test_ignores_changefreq_and_priority(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url>
    <loc>https://example.com/page</loc>
    <lastmod>2024-01-01</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/page"
        assert urls[0].lastmod == "2024-01-01"

    def test_empty_loc_skipped(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url><loc></loc></url>
  <url><loc>https://example.com/valid</loc></url>
</urlset>"""
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/valid"

    def test_missing_loc_skipped(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url><lastmod>2024-01-01</lastmod></url>
  <url><loc>https://example.com/ok</loc></url>
</urlset>"""
        parser = SitemapParser(xml)
        assert len(parser.get_urls()) == 1
        assert parser.get_urls()[0].loc == "https://example.com/ok"


class TestSitemapIndex:
    def test_single_sub_sitemap(self):
        xml = _index_xml("https://example.com/sitemap-docs.xml")
        parser = SitemapParser(xml)
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 1
        assert subs[0].loc == "https://example.com/sitemap-docs.xml"

    def test_multiple_sub_sitemaps(self):
        xml = _index_xml(
            "https://example.com/sitemap1.xml",
            "https://example.com/sitemap2.xml",
            "https://example.com/sitemap3.xml",
        )
        parser = SitemapParser(xml)
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 3
        assert [s.loc for s in subs] == [
            "https://example.com/sitemap1.xml",
            "https://example.com/sitemap2.xml",
            "https://example.com/sitemap3.xml",
        ]

    def test_is_index(self):
        parser = SitemapParser(_index_xml("https://example.com/sitemap.xml"))
        assert parser.is_index() is True
        assert parser.get_urls() == []

    def test_with_lastmod(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="{SITEMAP_NS}">
  <sitemap>
    <loc>https://example.com/sitemap-blog.xml</loc>
    <lastmod>2024-03-10</lastmod>
  </sitemap>
</sitemapindex>"""
        parser = SitemapParser(xml)
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 1
        assert subs[0].loc == "https://example.com/sitemap-blog.xml"
        assert subs[0].lastmod == "2024-03-10"


class TestPlainText:
    def test_basic(self):
        content = "https://example.com/a\nhttps://example.com/b\nhttps://example.com/c"
        parser = SitemapParser(content)
        urls = parser.get_urls()
        assert len(urls) == 3
        assert [u.loc for u in urls] == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]
        assert all(u.lastmod is None for u in urls)

    def test_blank_lines_skipped(self):
        content = "https://example.com/a\n\n\nhttps://example.com/b\n"
        parser = SitemapParser(content)
        assert len(parser.get_urls()) == 2

    def test_comments_skipped(self):
        content = "# this is a comment\nhttps://example.com/page\n# another comment"
        parser = SitemapParser(content)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/page"

    def test_whitespace_trimmed(self):
        content = "  https://example.com/a  \n  https://example.com/b  "
        parser = SitemapParser(content)
        urls = parser.get_urls()
        assert urls[0].loc == "https://example.com/a"
        assert urls[1].loc == "https://example.com/b"

    def test_not_an_index(self):
        parser = SitemapParser("https://example.com/page")
        assert parser.is_index() is False


class TestEdgeCases:
    def test_empty_string(self):
        parser = SitemapParser("")
        assert parser.get_urls() == []
        assert parser.get_sub_sitemaps() == []
        assert parser.is_index() is False

    def test_whitespace_only(self):
        parser = SitemapParser("   \n\n  \n  ")
        assert parser.get_urls() == []
        assert parser.get_sub_sitemaps() == []

    def test_malformed_xml_raises(self):
        with pytest.raises(Exception):
            SitemapParser("<urlset><url><loc>broken")

    def test_without_namespace(self):
        xml = _urlset_xml("https://example.com/page", ns=False)
        parser = SitemapParser(xml)
        assert len(parser.get_urls()) == 1
        assert parser.get_urls()[0].loc == "https://example.com/page"

    def test_index_without_namespace(self):
        xml = _index_xml("https://example.com/sitemap.xml", ns=False)
        parser = SitemapParser(xml)
        assert parser.is_index() is True
        assert parser.get_sub_sitemaps()[0].loc == "https://example.com/sitemap.xml"

    def test_loc_with_whitespace_trimmed(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url>
    <loc>
      https://example.com/page
    </loc>
  </url>
</urlset>"""
        parser = SitemapParser(xml)
        assert parser.get_urls()[0].loc == "https://example.com/page"

    def test_returns_defensive_copies(self):
        parser = SitemapParser(_urlset_xml("https://example.com/"))
        urls1 = parser.get_urls()
        urls2 = parser.get_urls()
        assert urls1 == urls2
        assert urls1 is not urls2

    def test_unknown_root_tag_produces_empty(self):
        xml = '<?xml version="1.0"?><something><url><loc>https://example.com/</loc></url></something>'
        parser = SitemapParser(xml)
        assert parser.get_urls() == []
        assert parser.get_sub_sitemaps() == []
        assert parser.is_index() is False

    def test_large_urlset(self):
        urls = [f"https://example.com/page{i}" for i in range(500)]
        xml = _urlset_xml(*urls)
        parser = SitemapParser(xml)
        assert len(parser.get_urls()) == 500
        assert parser.get_urls()[0].loc == "https://example.com/page0"
        assert parser.get_urls()[499].loc == "https://example.com/page499"


class TestCombined:
    def test_realistic_docs_sitemap(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url>
    <loc>https://docs.example.com/</loc>
    <lastmod>2024-06-01</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://docs.example.com/getting-started</loc>
    <lastmod>2024-05-20</lastmod>
  </url>
  <url>
    <loc>https://docs.example.com/api-reference</loc>
  </url>
</urlset>"""
        parser = SitemapParser(xml)
        assert parser.is_index() is False
        urls = parser.get_urls()
        assert len(urls) == 3
        assert urls[0].loc == "https://docs.example.com/"
        assert urls[0].lastmod == "2024-06-01"
        assert urls[1].lastmod == "2024-05-20"
        assert urls[2].lastmod is None

    def test_realistic_sitemap_index(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="{SITEMAP_NS}">
  <sitemap>
    <loc>https://example.com/sitemap-docs.xml</loc>
    <lastmod>2024-06-01</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://example.com/sitemap-blog.xml</loc>
    <lastmod>2024-05-15</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://example.com/sitemap-api.xml</loc>
  </sitemap>
</sitemapindex>"""
        parser = SitemapParser(xml)
        assert parser.is_index() is True
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 3
        assert subs[0].loc == "https://example.com/sitemap-docs.xml"
        assert subs[0].lastmod == "2024-06-01"
        assert subs[2].lastmod is None
        assert parser.get_urls() == []

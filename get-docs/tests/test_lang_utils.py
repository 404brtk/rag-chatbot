from src.utils.lang_utils import is_lang_code


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

from api.token_counter import TokenCounter

from .conftest import _msg


class TestTokenCounter:
    def setup_method(self):
        self.counter = TokenCounter()

    def test_estimate_text_tokens_counts_correctly(self):
        count = self.counter.estimate_text_tokens("Hello, world!", "gpt-5.5")
        assert count > 0
        assert isinstance(count, int)

    def test_estimate_text_tokens_uses_fallback_for_unknown_model(self):
        count = self.counter.estimate_text_tokens("Hello", "nonexistent-model-xyz")
        assert count > 0

    def test_estimate_message_tokens_includes_overhead(self):
        msg = _msg("user", "Hello")
        text_tokens = self.counter.estimate_text_tokens("Hello", "gpt-5.5")
        message_tokens = self.counter.estimate_message_tokens(msg, "gpt-5.5")
        assert message_tokens == text_tokens + 3

    def test_estimate_system_tokens_with_content(self):
        count = self.counter.estimate_system_tokens(
            "You are a helpful assistant.", "gpt-5.5"
        )
        assert count > 3

    def test_estimate_system_tokens_empty_string_returns_zero(self):
        assert self.counter.estimate_system_tokens("", "gpt-5.5") == 0

    def test_estimate_system_tokens_whitespace_only_returns_zero(self):
        assert self.counter.estimate_system_tokens("   \n\t  ", "gpt-5.5") == 0

    def test_truncate_text_under_limit_returns_unchanged(self):
        text = "Hello"
        result = self.counter.truncate_text_to_max_tokens(text, "gpt-5.5", 100)
        assert result == text

    def test_truncate_text_over_limit_truncates(self):
        text = "This is a longer piece of text that should be truncated"
        result = self.counter.truncate_text_to_max_tokens(text, "gpt-5.5", 2)
        full_count = self.counter.estimate_text_tokens(text, "gpt-5.5")
        truncated_count = self.counter.estimate_text_tokens(result, "gpt-5.5")
        assert truncated_count <= 2
        assert truncated_count < full_count

    def test_truncate_text_zero_limit_returns_empty(self):
        result = self.counter.truncate_text_to_max_tokens("Hello", "gpt-5.5", 0)
        assert result == ""

    def test_truncate_text_negative_limit_returns_empty(self):
        result = self.counter.truncate_text_to_max_tokens("Hello", "gpt-5.5", -5)
        assert result == ""

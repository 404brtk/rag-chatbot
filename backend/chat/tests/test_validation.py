from chat.llm_config import validate_llm_config


class TestValidateLLMConfig:
    def test_valid_required_only(self):
        assert validate_llm_config({"provider": "openai", "model": "gpt"}) is None

    def test_rejects_empty_config(self):
        result = validate_llm_config({})
        assert result is not None
        assert result["error"] == "provider is required."

    def test_valid_custom_values(self):
        assert (
            validate_llm_config(
                {
                    "provider": "openai",
                    "model": "gpt",
                    "max_input_tokens": 500,
                    "compaction_threshold": 0.5,
                }
            )
            is None
        )

    def test_rejects_missing_provider(self):
        result = validate_llm_config({"model": "gpt"})
        assert result is not None
        assert result["error"] == "provider is required."

    def test_rejects_unsupported_provider(self):
        result = validate_llm_config({"provider": "anthropic", "model": "gpt"})
        assert result is not None
        assert (
            result["error"]
            == "Unsupported provider: anthropic. Supported: openai, llamacpp, openrouter, gemini."
        )

    def test_rejects_missing_model(self):
        result = validate_llm_config({"provider": "openai"})
        assert result is not None
        assert result["error"] == "model is required."

    def test_rejects_empty_model(self):
        result = validate_llm_config({"provider": "openai", "model": ""})
        assert result is not None
        assert result["error"] == "model cannot be empty."

    def test_rejects_non_string_model(self):
        result = validate_llm_config({"provider": "openai", "model": 123})
        assert result is not None
        assert result["error"] == "model must be a string."

    def test_valid_compaction_model_unset(self):
        assert (
            validate_llm_config(
                {"provider": "openai", "model": "gpt", "compaction_model": None}
            )
            is None
        )

    def test_valid_compaction_model_string(self):
        assert (
            validate_llm_config(
                {"provider": "openai", "model": "gpt", "compaction_model": "gpt"}
            )
            is None
        )

    def test_allows_empty_compaction_model(self):
        assert (
            validate_llm_config(
                {"provider": "openai", "model": "gpt", "compaction_model": ""}
            )
            is None
        )

    def test_rejects_non_string_compaction_model(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "compaction_model": 42}
        )
        assert result is not None
        assert result["error"] == "compaction_model must be a string."

    def test_valid_compaction_provider_unset(self):
        assert (
            validate_llm_config(
                {"provider": "openai", "model": "gpt", "compaction_provider": None}
            )
            is None
        )

    def test_valid_compaction_provider_string(self):
        assert (
            validate_llm_config(
                {
                    "provider": "openai",
                    "model": "gpt",
                    "compaction_provider": "llamacpp",
                }
            )
            is None
        )

    def test_allows_empty_compaction_provider(self):
        assert (
            validate_llm_config(
                {"provider": "openai", "model": "gpt", "compaction_provider": ""}
            )
            is None
        )

    def test_rejects_non_string_compaction_provider(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "compaction_provider": 42}
        )
        assert result is not None
        assert result["error"] == "compaction_provider must be a string."

    def test_rejects_unsupported_compaction_provider(self):
        result = validate_llm_config(
            {
                "provider": "openai",
                "model": "gpt",
                "compaction_provider": "anthropic",
            }
        )
        assert result is not None
        assert (
            result["error"]
            == "Unsupported compaction provider: anthropic. Supported: openai, llamacpp, openrouter, gemini."
        )

    def test_rejects_max_input_tokens_too_low(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "max_input_tokens": 50}
        )
        assert result is not None
        assert "max_input_tokens" in result["error"]

    def test_rejects_max_input_tokens_too_high(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "max_input_tokens": 500_000}
        )
        assert result is not None
        assert "max_input_tokens" in result["error"]

    def test_rejects_max_input_tokens_non_integer(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "max_input_tokens": 5000.5}
        )
        assert result is not None

    def test_rejects_max_input_tokens_boolean(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "max_input_tokens": True}
        )
        assert result is not None

    def test_rejects_compaction_threshold_too_low(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "compaction_threshold": -0.1}
        )
        assert result is not None
        assert "compaction_threshold" in result["error"]

    def test_rejects_compaction_threshold_too_high(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "compaction_threshold": 1.5}
        )
        assert result is not None
        assert "compaction_threshold" in result["error"]

    def test_rejects_compaction_threshold_non_numeric(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "compaction_threshold": "high"}
        )
        assert result is not None

    def test_rejects_compaction_threshold_boolean(self):
        result = validate_llm_config(
            {"provider": "openai", "model": "gpt", "compaction_threshold": True}
        )
        assert result is not None

    def test_returns_first_error_only(self):
        result = validate_llm_config(
            {
                "provider": "invalid",
                "model": "",
                "max_input_tokens": -1,
                "compaction_threshold": 2.0,
            }
        )
        assert result is not None
        assert "provider" in result["error"]

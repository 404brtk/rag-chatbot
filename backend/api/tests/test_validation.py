from api.llm_config import validate_llm_config


class TestValidateLLMConfig:
    def test_valid_defaults(self):
        assert validate_llm_config({}) is None

    def test_valid_custom_values(self):
        assert (
            validate_llm_config({"max_input_tokens": 500, "compaction_threshold": 0.5})
            is None
        )

    def test_valid_provider(self):
        assert validate_llm_config({"provider": "openai"}) is None

    def test_rejects_unsupported_provider(self):
        result = validate_llm_config({"provider": "anthropic"})
        assert result is not None
        assert "provider" in result["error"]

    def test_valid_model_string(self):
        assert validate_llm_config({"model": "gpt-5.4-mini"}) is None

    def test_rejects_empty_model(self):
        result = validate_llm_config({"model": ""})
        assert result is not None
        assert "model" in result["error"]

    def test_rejects_non_string_model(self):
        result = validate_llm_config({"model": 123})
        assert result is not None
        assert "model" in result["error"]

    def test_valid_compaction_model_unset(self):
        assert validate_llm_config({"compaction_model": None}) is None

    def test_valid_compaction_model_string(self):
        assert validate_llm_config({"compaction_model": "gpt-5.4-mini"}) is None

    def test_rejects_empty_compaction_model(self):
        result = validate_llm_config({"compaction_model": ""})
        assert result is not None
        assert "compaction_model" in result["error"]

    def test_rejects_non_string_compaction_model(self):
        result = validate_llm_config({"compaction_model": 42})
        assert result is not None
        assert "compaction_model" in result["error"]

    def test_rejects_max_input_tokens_too_low(self):
        result = validate_llm_config({"max_input_tokens": 50})
        assert result is not None
        assert "max_input_tokens" in result["error"]

    def test_rejects_max_input_tokens_too_high(self):
        result = validate_llm_config({"max_input_tokens": 500_000})
        assert result is not None
        assert "max_input_tokens" in result["error"]

    def test_rejects_max_input_tokens_non_integer(self):
        result = validate_llm_config({"max_input_tokens": 5000.5})
        assert result is not None

    def test_rejects_max_input_tokens_boolean(self):
        result = validate_llm_config({"max_input_tokens": True})
        assert result is not None

    def test_rejects_compaction_threshold_too_low(self):
        result = validate_llm_config({"compaction_threshold": -0.1})
        assert result is not None
        assert "compaction_threshold" in result["error"]

    def test_rejects_compaction_threshold_too_high(self):
        result = validate_llm_config({"compaction_threshold": 1.5})
        assert result is not None
        assert "compaction_threshold" in result["error"]

    def test_rejects_compaction_threshold_non_numeric(self):
        result = validate_llm_config({"compaction_threshold": "high"})
        assert result is not None

    def test_rejects_compaction_threshold_boolean(self):
        result = validate_llm_config({"compaction_threshold": True})
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

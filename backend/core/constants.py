from django.db import models


class LLMProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    LLAMACPP = "llamacpp", "llama.cpp"
    ANTHROPIC = "anthropic", "Anthropic"
    GOOGLE = "google", "Google"

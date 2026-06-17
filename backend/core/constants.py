from django.db import models


class LLMProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    LLAMACPP = "llamacpp", "llama.cpp"
    OPENROUTER = "openrouter", "OpenRouter"
    GEMINI = "gemini", "Gemini"

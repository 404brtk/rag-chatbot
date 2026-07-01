from django.db import models


class Provider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    LLAMACPP = "llamacpp", "llama.cpp"
    OPENROUTER = "openrouter", "OpenRouter"
    GEMINI = "gemini", "Gemini"
    GITHUB = "github", "GitHub"

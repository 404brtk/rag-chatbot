import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from django.conf import settings
from .fields import EncryptedTextField


class LLMProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    LLAMACPP = "llamacpp", "llama.cpp"
    ANTHROPIC = "anthropic", "Anthropic"
    GOOGLE = "google", "Google"


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": email})


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()


class UserApiKey(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
    provider = models.CharField(max_length=32, choices=LLMProvider.choices)
    encrypted_key = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "provider")]

    def __str__(self):
        return f"{self.user.email} - {self.get_provider_display()}"

    @property
    def masked_key(self):
        key = self.encrypted_key
        if not key or len(key) < 8:
            return "****"
        return f"{key[:3]}...{key[-4:]}"


class Conversation(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status", "-last_message_at"]),
        ]

    def __str__(self):
        return self.title or f"Chat {self.id}"


class Message(UUIDModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        AI = "ai", "AI"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices, db_index=True)
    content = models.TextField()
    raw_question = models.TextField(null=True, blank=True)
    context = models.JSONField(null=True, blank=True)
    provider = models.CharField(
        max_length=16,
        choices=LLMProvider.choices,
        null=True,
        blank=True,
    )
    model = models.CharField(max_length=128, null=True, blank=True)
    usage = models.JSONField(null=True, blank=True)
    compacted = models.BooleanField(default=False, db_index=True)
    is_compaction_summary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class DocumentLanguage(models.TextChoices):
    ENGLISH = "english", "English"
    POLISH = "polish", "Polish"


PG_REGCONFIG: dict[str, str] = {
    DocumentLanguage.ENGLISH: "english",
    DocumentLanguage.POLISH: "simple",  # TODO: add polish dictionary
}


class Document(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="documents")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    raw_text = models.TextField()
    language = models.CharField(
        max_length=16,
        choices=DocumentLanguage.choices,
        default=DocumentLanguage.ENGLISH,
    )
    meta = models.JSONField(default=dict, blank=True)
    source_url = models.URLField(max_length=2000, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.filename


class DocumentChunk(UUIDModel):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="chunks"
    )
    content = models.TextField()
    chunk_index = models.PositiveIntegerField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS)
    search_vector = SearchVectorField(null=True)
    word_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["chunk_index"]
        indexes = [
            models.Index(fields=["document", "chunk_index"]),
            HnswIndex(
                name="chunk_embedding_idx",
                fields=["embedding"],
                m=16,  # TODO: adjust
                ef_construction=64,  # TODO: adjust
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(fields=["search_vector"], name="chunk_search_vector_idx"),
        ]

    def __str__(self):
        return f"{self.document.filename} chunk {self.chunk_index}"


class GetDocsJob(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="get_docs_jobs"
    )
    job_id = models.CharField(max_length=255, unique=True)
    url = models.URLField(max_length=1000, null=True, blank=True)
    github_repo = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    language = models.CharField(
        max_length=16,
        choices=DocumentLanguage.choices,
        default=DocumentLanguage.ENGLISH,
    )
    pages_fetched = models.PositiveIntegerField(default=0)
    pages_total = models.PositiveIntegerField(null=True, blank=True)
    max_pages = models.PositiveIntegerField(default=150)
    max_depth = models.PositiveIntegerField(default=3)
    delay_seconds = models.FloatField(default=1.5)
    timeout = models.FloatField(default=15.0)
    skip_llms_full = models.BooleanField(default=False)
    fair_use = models.BooleanField(default=True)
    source_method = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"GetDocsJob {self.job_id} ({self.status})"

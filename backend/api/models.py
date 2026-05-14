import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

from django.conf import settings
from .fields import EncryptedTextField


class LLMProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
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
    meta = models.JSONField(default=dict, blank=True)

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
    provider = models.CharField(
        max_length=16,
        choices=LLMProvider.choices,
        null=True,
        blank=True,
    )
    model = models.CharField(max_length=128, null=True, blank=True)
    usage = models.JSONField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class Document(UUIDModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="documents")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    raw_text = models.TextField()
    meta = models.JSONField(default=dict, blank=True)
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
        ]

    def __str__(self):
        return f"{self.document.filename} chunk {self.chunk_index}"

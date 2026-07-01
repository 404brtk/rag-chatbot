from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.core.files.storage import default_storage
from django.utils import timezone
from core.models import UUIDModel
from core.constants import Provider


class Conversation(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    class Mode(models.TextChoices):
        DIRECT = "direct", "Direct"
        SIDE_BY_SIDE = "side-by-side", "Side-by-Side"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    title = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.DIRECT,
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

    class Variant(models.TextChoices):
        RAG_ON = "rag_on", "RAG On"
        RAG_OFF = "rag_off", "RAG Off"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices, db_index=True)
    variant = models.CharField(
        max_length=16,
        choices=Variant.choices,
        null=True,
        blank=True,
    )
    content = models.TextField()
    raw_question = models.TextField(null=True, blank=True)
    context = models.JSONField(null=True, blank=True)
    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        null=True,
        blank=True,
    )
    model = models.CharField(max_length=128, null=True, blank=True)
    usage = models.JSONField(null=True, blank=True)
    compacted = models.BooleanField(default=False)
    truncated = models.BooleanField(default=False)
    is_compaction_summary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class MessageAttachment(UUIDModel):
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="attachments"
    )
    file_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    size = models.BigIntegerField()
    mime_type = models.CharField(max_length=127)
    saved_path = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.name} ({self.file_id})"


@receiver(post_delete, sender=MessageAttachment)
def delete_message_attachment_file(sender, instance, **kwargs):
    if instance.saved_path:
        transaction.on_commit(lambda: default_storage.delete(instance.saved_path))

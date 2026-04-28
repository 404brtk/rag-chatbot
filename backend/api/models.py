import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)


class Conversation(UUIDModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Chat {self.id}"


class Message(UUIDModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        AI = "ai", "AI"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"

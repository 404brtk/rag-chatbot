from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Message, Conversation


@dataclass(frozen=True, slots=True)
class StoredMessage:
    role: str
    content: str
    created_at: datetime | None = None
    meta: dict[str, Any] | None = None


class DjangoMessageRepository:
    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[StoredMessage]:
        qs = (
            Message.objects.filter(conversation_id=session_id)
            .only("role", "content", "created_at", "meta", "id")
            .order_by("-created_at")
        )

        if limit is not None:
            qs = qs[:limit]

        rows = list(qs)
        rows.reverse()

        return [
            StoredMessage(
                role="assistant" if row.role == Message.Role.AI else row.role,
                content=row.content,
                created_at=row.created_at,
                meta=row.meta or {},
            )
            for row in rows
        ]

    def append_message(
        self,
        *,
        session: Conversation,
        role: str,
        content: str,
        provider: str | None,
        model: str | None,
        usage: dict[str, Any] | None,
        meta: dict[str, Any] | None,
    ) -> Message:
        db_role = Message.Role.AI if role == "assistant" else Message.Role.USER

        message = Message.objects.create(
            conversation=session,
            role=db_role,
            content=content,
            provider=provider,
            model=model,
            usage=usage,
            meta=meta or {},
        )

        return message

    def append_message_pair(
        self,
        *,
        session_id: str,
        user_content: str,
        assistant_content: str,
        provider: str,
        model: str,
        usage: dict[str, Any] | None,
        user_meta: dict[str, Any] | None,
        assistant_meta: dict[str, Any] | None,
    ) -> tuple[Message, Message]:
        now = timezone.now()
        with transaction.atomic():
            session = Conversation.objects.select_for_update().get(id=session_id)

            user_msg = self.append_message(
                session=session,
                role="user",
                content=user_content,
                provider=None,
                model=None,
                usage=None,
                meta=user_meta,
            )
            assistant_msg = self.append_message(
                session=session,
                role="assistant",
                content=assistant_content,
                provider=provider,
                model=model,
                usage=usage,
                meta=assistant_meta,
            )
            session.last_message_at = now
            session.save(update_fields=["last_message_at"])

            return user_msg, assistant_msg

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Message, Conversation


@dataclass(frozen=True, slots=True)
class StoredMessage:
    role: str
    content: str
    created_at: datetime | None = None
    meta: dict[str, Any] | None = None


class DjangoMessageRepository:
    def _build_base_queryset(self, session_id: str):
        return (
            Message.objects.filter(conversation_id=session_id)
            .only("role", "content", "created_at", "meta", "id")
            .order_by("-created_at")
        )

    def _rows_to_stored_messages(self, rows) -> list[StoredMessage]:
        return [
            StoredMessage(
                role="assistant" if row.role == Message.Role.AI else row.role,
                content=row.content,
                created_at=row.created_at,
                meta=row.meta or {},
            )
            for row in rows
        ]

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        exclude_compacted: bool = False,
    ) -> list[StoredMessage]:
        qs = self._build_base_queryset(session_id)

        if exclude_compacted:
            qs = qs.filter(Q(meta__compacted__isnull=True) | Q(meta__compacted=False))

        if limit is not None:
            qs = qs[:limit]

        rows = list(qs)
        rows.reverse()

        return self._rows_to_stored_messages(rows)

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

        return Message.objects.create(
            conversation=session,
            role=db_role,
            content=content,
            provider=provider,
            model=model,
            usage=usage,
            meta=meta or {},
        )

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

    def compact_messages(self, session: Conversation) -> int:
        messages_to_update = []
        for msg in (
            Message.objects.filter(conversation=session)
            .filter(Q(meta__compacted__isnull=True) | Q(meta__compacted=False))
            .iterator()
        ):
            msg.meta = {**(msg.meta or {}), "compacted": True}
            messages_to_update.append(msg)
        if messages_to_update:
            Message.objects.bulk_update(messages_to_update, ["meta"])
        return len(messages_to_update)

    def apply_compaction(
        self,
        *,
        session: Conversation,
        summary: str,
        usage: dict[str, Any] | None = None,
    ) -> Message:
        with transaction.atomic():
            self.compact_messages(session)
            return self.append_message(
                session=session,
                role="assistant",
                content=summary,
                provider=None,
                model=None,
                usage=usage,
                meta={"is_compaction_summary": True},
            )


class AsyncDjangoMessageRepository:
    def __init__(self) -> None:
        self._sync_repo = DjangoMessageRepository()

    async def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        exclude_compacted: bool = False,
    ) -> list[StoredMessage]:
        qs = self._sync_repo._build_base_queryset(session_id)

        if exclude_compacted:
            qs = qs.filter(Q(meta__compacted__isnull=True) | Q(meta__compacted=False))

        if limit is not None:
            qs = qs[:limit]

        rows = [row async for row in qs]
        rows.reverse()

        return self._sync_repo._rows_to_stored_messages(rows)

    async def append_message(
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

        return await Message.objects.acreate(
            conversation=session,
            role=db_role,
            content=content,
            provider=provider,
            model=model,
            usage=usage,
            meta=meta or {},
        )

    async def append_message_pair(
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
        return await sync_to_async(
            self._sync_repo.append_message_pair,
            thread_sensitive=True,
        )(
            session_id=session_id,
            user_content=user_content,
            assistant_content=assistant_content,
            provider=provider,
            model=model,
            usage=usage,
            user_meta=user_meta,
            assistant_meta=assistant_meta,
        )

    async def compact_messages(self, session: Conversation) -> int:
        return await sync_to_async(
            self._sync_repo.compact_messages,
            thread_sensitive=True,
        )(session)

    async def apply_compaction(
        self,
        *,
        session: Conversation,
        summary: str,
        usage: dict[str, Any] | None = None,
    ) -> Message:
        return await sync_to_async(
            self._sync_repo.apply_compaction,
            thread_sensitive=True,
        )(session=session, summary=summary, usage=usage)

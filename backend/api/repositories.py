from dataclasses import dataclass
from datetime import datetime

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from .models import Message, Conversation


@dataclass(frozen=True, slots=True)
class StoredMessage:
    role: str
    content: str
    created_at: datetime | None = None
    is_compaction_summary: bool = False


class DjangoMessageRepository:
    def _build_base_queryset(self, session_id: str):
        return (
            Message.objects.filter(conversation_id=session_id)
            .only(
                "role",
                "content",
                "created_at",
                "is_compaction_summary",
                "id",
            )
            .order_by("-created_at")
        )

    def _rows_to_stored_messages(self, rows) -> list[StoredMessage]:
        return [
            StoredMessage(
                role="assistant" if row.role == Message.Role.AI else row.role,
                content=row.content,
                created_at=row.created_at,
                is_compaction_summary=row.is_compaction_summary,
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
            qs = qs.filter(compacted=False, truncated=False)

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
        raw_question: str | None = None,
        context: list | None = None,
        provider: str | None = None,
        model: str | None = None,
        usage: dict | None = None,
        is_compaction_summary: bool = False,
    ) -> Message:
        db_role = Message.Role.AI if role == "assistant" else Message.Role.USER

        return Message.objects.create(
            conversation=session,
            role=db_role,
            content=content,
            raw_question=raw_question,
            context=context or None,
            provider=provider,
            model=model,
            usage=usage,
            is_compaction_summary=is_compaction_summary,
        )

    def append_message_pair(
        self,
        *,
        session_id: str,
        user_content: str,
        assistant_content: str,
        user_raw_question: str | None = None,
        user_context: list | None = None,
        provider: str,
        model: str,
        usage: dict | None,
    ) -> tuple[Message, Message]:
        now = timezone.now()
        with transaction.atomic():
            session = Conversation.objects.select_for_update().get(id=session_id)

            user_msg = self.append_message(
                session=session,
                role="user",
                content=user_content,
                raw_question=user_raw_question,
                context=user_context,
                provider=provider,
                model=model,
            )
            assistant_msg = self.append_message(
                session=session,
                role="assistant",
                content=assistant_content,
                provider=provider,
                model=model,
                usage=usage,
            )
            session.last_message_at = now
            session.save(update_fields=["last_message_at"])

            return user_msg, assistant_msg

    def compact_messages(self, session: Conversation) -> int:
        return Message.objects.filter(conversation=session, compacted=False).update(
            compacted=True
        )

    def truncate_oldest_messages(self, session_id: str, count: int) -> int:
        message_ids = list(
            Message.objects.filter(
                conversation_id=session_id,
                compacted=False,
                truncated=False,
            )
            .order_by("created_at")[:count]
            .values_list("id", flat=True)
        )
        return Message.objects.filter(id__in=message_ids).update(truncated=True)

    def apply_compaction(
        self,
        *,
        session: Conversation,
        summary: str,
        provider: str,
        model: str,
        usage: dict | None = None,
    ) -> Message:
        with transaction.atomic():
            self.compact_messages(session)
            return self.append_message(
                session=session,
                role="assistant",
                content=summary,
                provider=provider,
                model=model,
                usage=usage,
                is_compaction_summary=True,
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
            qs = qs.filter(compacted=False, truncated=False)

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
        raw_question: str | None = None,
        context: list | None = None,
        provider: str | None = None,
        model: str | None = None,
        usage: dict | None = None,
        is_compaction_summary: bool = False,
    ) -> Message:
        db_role = Message.Role.AI if role == "assistant" else Message.Role.USER

        return await Message.objects.acreate(
            conversation=session,
            role=db_role,
            content=content,
            raw_question=raw_question,
            context=context or None,
            provider=provider,
            model=model,
            usage=usage,
            is_compaction_summary=is_compaction_summary,
        )

    async def append_message_pair(
        self,
        *,
        session_id: str,
        user_content: str,
        assistant_content: str,
        user_raw_question: str | None = None,
        user_context: list | None = None,
        provider: str,
        model: str,
        usage: dict | None,
    ) -> tuple[Message, Message]:
        return await sync_to_async(
            self._sync_repo.append_message_pair,
            thread_sensitive=True,
        )(
            session_id=session_id,
            user_content=user_content,
            assistant_content=assistant_content,
            user_raw_question=user_raw_question,
            user_context=user_context,
            provider=provider,
            model=model,
            usage=usage,
        )

    async def compact_messages(self, session: Conversation) -> int:
        return await sync_to_async(
            self._sync_repo.compact_messages,
            thread_sensitive=True,
        )(session)

    async def truncate_oldest_messages(self, session_id: str, count: int) -> int:
        return await sync_to_async(
            self._sync_repo.truncate_oldest_messages,
            thread_sensitive=True,
        )(session_id=session_id, count=count)

    async def apply_compaction(
        self,
        *,
        session: Conversation,
        summary: str,
        provider: str,
        model: str,
        usage: dict | None = None,
    ) -> Message:
        return await sync_to_async(
            self._sync_repo.apply_compaction,
            thread_sensitive=True,
        )(session=session, summary=summary, provider=provider, model=model, usage=usage)

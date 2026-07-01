import uuid

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone

from chat.models import Conversation, Message, MessageAttachment
from chat.repositories import AsyncDjangoMessageRepository

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(email="test@example.com", password="Str0ngP@ss!")


@pytest.fixture
def conversation(user):
    return Conversation.objects.create(user=user, title="Test conversation")


@pytest.fixture
def repo():
    return AsyncDjangoMessageRepository()


@pytest.mark.django_db(transaction=True)
class TestAsyncListMessages:
    async def test_returns_messages_in_chronological_order(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="first"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="second"
        )
        await Message.objects.acreate(
            conversation=conversation, role="user", content="third"
        )

        messages = await repo.list_messages(session_id=str(conversation.id))

        assert [m.content for m in messages] == ["first", "second", "third"]

    async def test_maps_ai_role_to_assistant(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="AI response"
        )

        messages = await repo.list_messages(session_id=str(conversation.id))

        assert messages[0].role == "assistant"

    async def test_preserves_user_role(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="User msg"
        )

        messages = await repo.list_messages(session_id=str(conversation.id))

        assert messages[0].role == "user"

    async def test_respects_limit_and_returns_most_recent(self, repo, conversation):
        for i in range(5):
            await Message.objects.acreate(
                conversation=conversation, role="user", content=f"msg_{i}"
            )

        messages = await repo.list_messages(session_id=str(conversation.id), limit=3)

        assert len(messages) == 3
        assert [m.content for m in messages] == ["msg_2", "msg_3", "msg_4"]

    async def test_returns_empty_list_for_empty_conversation(self, repo, conversation):
        messages = await repo.list_messages(session_id=str(conversation.id))

        assert messages == []

    async def test_returns_empty_list_for_nonexistent_conversation(self, repo):
        messages = await repo.list_messages(session_id=str(uuid.uuid4()))

        assert messages == []

    async def test_includes_created_at(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="test"
        )

        messages = await repo.list_messages(session_id=str(conversation.id))

        assert messages[0].created_at is not None

    async def test_exclude_compacted_filters_out_compacted_messages(
        self, repo, conversation
    ):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="keep"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="exclude", compacted=True
        )

        messages = await repo.list_messages(
            session_id=str(conversation.id), exclude_compacted=True
        )

        assert len(messages) == 1
        assert messages[0].content == "keep"

    async def test_exclude_compacted_filters_out_truncated_messages(
        self, repo, conversation
    ):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="keep"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="exclude", truncated=True
        )

        messages = await repo.list_messages(
            session_id=str(conversation.id), exclude_compacted=True
        )

        assert len(messages) == 1
        assert messages[0].content == "keep"

    async def test_includes_attachments(self, repo, conversation):
        user_msg = await Message.objects.acreate(
            conversation=conversation, role="user", content="message with files"
        )
        await MessageAttachment.objects.acreate(
            message=user_msg,
            file_id="att-1",
            name="file1.png",
            size=1024,
            mime_type="image/png",
            saved_path="attachments/att-1",
        )

        messages = await repo.list_messages(session_id=str(conversation.id))
        assert len(messages) == 1
        assert messages[0].content == "message with files"
        assert len(messages[0].attachments) == 1
        assert messages[0].attachments[0] == {
            "id": "att-1",
            "name": "file1.png",
            "size": 1024,
            "mimeType": "image/png",
            "saved_path": "attachments/att-1",
        }

    async def test_list_messages_filters_by_variant_and_neutral(
        self, repo, conversation
    ):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="hello shared"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="answer on", variant="rag_on"
        )
        await Message.objects.acreate(
            conversation=conversation,
            role="ai",
            content="answer off",
            variant="rag_off",
        )

        msgs_on = await repo.list_messages(
            session_id=str(conversation.id), variant="rag_on"
        )
        assert [m.content for m in msgs_on] == ["hello shared", "answer on"]

        msgs_off = await repo.list_messages(
            session_id=str(conversation.id), variant="rag_off"
        )
        assert [m.content for m in msgs_off] == ["hello shared", "answer off"]

    async def test_list_messages_serves_raw_question_for_rag_off(
        self, repo, conversation
    ):
        await Message.objects.acreate(
            conversation=conversation,
            role="user",
            content="stuffed context hello",
            raw_question="clean question",
        )

        msgs_on = await repo.list_messages(
            session_id=str(conversation.id), variant="rag_on"
        )
        assert msgs_on[0].content == "stuffed context hello"

        msgs_off = await repo.list_messages(
            session_id=str(conversation.id), variant="rag_off"
        )
        assert msgs_off[0].content == "clean question"


@pytest.mark.django_db(transaction=True)
class TestAsyncAppendMessage:
    async def test_creates_message_with_given_fields(self, repo, conversation):
        msg = await repo.append_message(
            session=conversation,
            role="assistant",
            content="Hello",
            provider="openai",
            model="gpt-5.5",
            usage={"prompt_tokens": 5, "completion_tokens": 10},
            is_compaction_summary=True,
        )

        assert msg.role == Message.Role.AI
        assert msg.content == "Hello"
        assert msg.provider == "openai"
        assert msg.model == "gpt-5.5"
        assert msg.usage == {"prompt_tokens": 5, "completion_tokens": 10}
        assert msg.is_compaction_summary is True

    async def test_append_message_creates_attachments(self, repo, conversation):
        attachments = [
            {"id": "att-1", "name": "file1.png", "size": 1024, "mimeType": "image/png"},
        ]
        msg = await repo.append_message(
            session=conversation,
            role="user",
            content="Hello",
            attachments=attachments,
        )

        attachment_count = await sync_to_async(
            MessageAttachment.objects.filter(message=msg).count
        )()
        assert attachment_count == 1

        db_att = await MessageAttachment.objects.aget(message=msg)
        assert db_att.file_id == "att-1"
        assert db_att.name == "file1.png"


@pytest.mark.django_db(transaction=True)
class TestAsyncAppendMessagePair:
    async def test_creates_user_and_assistant_messages(self, repo, conversation):
        before = timezone.now()
        user_msg, assistant_msg = await repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Hello",
            assistant_content="Hi there!",
            provider="openai",
            model="gpt-5.5",
            usage={"prompt_tokens": 5, "completion_tokens": 10},
            user_raw_question="Hello",
            user_context=[{"chunk": 1}],
        )
        after = timezone.now()

        assert user_msg.role == "user"
        assert user_msg.content == "Hello"
        assert user_msg.provider == "openai"
        assert user_msg.model == "gpt-5.5"
        assert user_msg.raw_question == "Hello"
        assert user_msg.context == [{"chunk": 1}]
        assert before <= user_msg.created_at <= after

        assert assistant_msg.role == "ai"
        assert assistant_msg.content == "Hi there!"
        assert assistant_msg.provider == "openai"
        assert assistant_msg.model == "gpt-5.5"
        assert assistant_msg.usage == {"prompt_tokens": 5, "completion_tokens": 10}

    async def test_updates_conversation_last_message_at(self, repo, conversation):
        await sync_to_async(conversation.refresh_from_db)()
        old_last_message_at = conversation.last_message_at

        await repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Hello",
            assistant_content="Hi!",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )

        await sync_to_async(conversation.refresh_from_db)()
        assert conversation.last_message_at > old_last_message_at

    async def test_multiple_pairs_in_same_conversation(self, repo, conversation):
        await repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="First question",
            assistant_content="First answer",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )
        await repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Second question",
            assistant_content="Second answer",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )

        count = await sync_to_async(
            Message.objects.filter(conversation=conversation).count
        )()
        assert count == 4

    async def test_creates_user_message_with_attachments(self, repo, conversation):
        attachments = [
            {"id": "att-1", "name": "file1.png", "size": 1024, "mimeType": "image/png"},
            {
                "id": "att-2",
                "name": "file2.pdf",
                "size": 2048,
                "mimeType": "application/pdf",
            },
        ]
        user_msg, assistant_msg = await repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Hello",
            assistant_content="Hi there!",
            provider="openai",
            model="gpt-5.5",
            usage=None,
            user_attachments=attachments,
        )

        attachment_count = await sync_to_async(
            MessageAttachment.objects.filter(message=user_msg).count
        )()
        assert attachment_count == 2

        db_attachments = [
            att
            async for att in MessageAttachment.objects.filter(
                message=user_msg
            ).order_by("created_at")
        ]
        assert db_attachments[0].file_id == "att-1"
        assert db_attachments[0].name == "file1.png"
        assert db_attachments[0].size == 1024
        assert db_attachments[0].mime_type == "image/png"
        assert db_attachments[0].saved_path == "attachments/att-1"

        assert db_attachments[1].file_id == "att-2"
        assert db_attachments[1].name == "file2.pdf"
        assert db_attachments[1].size == 2048
        assert db_attachments[1].mime_type == "application/pdf"
        assert db_attachments[1].saved_path == "attachments/att-2"


@pytest.mark.django_db(transaction=True)
class TestAsyncCompactMessages:
    async def test_marks_messages_as_compacted(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="first"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="second"
        )

        count = await repo.compact_messages(conversation)

        assert count == 2
        async for msg in Message.objects.filter(conversation=conversation):
            assert msg.compacted is True

    async def test_does_not_recompact_already_compacted(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="first", compacted=True
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="second"
        )

        count = await repo.compact_messages(conversation)

        assert count == 1

    async def test_returns_zero_for_empty_conversation(self, repo, conversation):
        count = await repo.compact_messages(conversation)

        assert count == 0


@pytest.mark.django_db(transaction=True)
class TestAsyncApplyCompaction:
    async def test_marks_compacted_and_appends_summary(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="question"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="answer"
        )

        summary_msg = await repo.apply_compaction(
            session=conversation,
            summary="Summary of conversation",
            provider="openai",
            model="gpt-model",
        )

        assert summary_msg.role == "ai"
        assert summary_msg.content == "Summary of conversation"
        assert summary_msg.is_compaction_summary is True
        assert summary_msg.provider == "openai"
        assert summary_msg.model == "gpt-model"

        compacted_count = 0
        async for m in Message.objects.filter(
            conversation=conversation, compacted=True
        ):
            compacted_count += 1
        assert compacted_count == 2


@pytest.mark.django_db(transaction=True)
class TestAsyncTruncateOldestMessages:
    async def test_truncates_specified_number_of_oldest_messages(
        self, repo, conversation
    ):
        m1 = await Message.objects.acreate(
            conversation=conversation, role="user", content="first"
        )
        m2 = await Message.objects.acreate(
            conversation=conversation, role="ai", content="second"
        )
        m3 = await Message.objects.acreate(
            conversation=conversation, role="user", content="third"
        )

        updated_count = await repo.truncate_oldest_messages(str(conversation.id), 2)
        assert updated_count == 2

        await sync_to_async(m1.refresh_from_db)()
        await sync_to_async(m2.refresh_from_db)()
        await sync_to_async(m3.refresh_from_db)()

        assert m1.truncated is True
        assert m2.truncated is True
        assert m3.truncated is False

    async def test_excludes_already_truncated_or_compacted(self, repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="first", compacted=True
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="second", truncated=True
        )
        m3 = await Message.objects.acreate(
            conversation=conversation, role="user", content="third"
        )
        m4 = await Message.objects.acreate(
            conversation=conversation, role="ai", content="fourth"
        )

        updated_count = await repo.truncate_oldest_messages(str(conversation.id), 1)
        assert updated_count == 1

        await sync_to_async(m3.refresh_from_db)()
        await sync_to_async(m4.refresh_from_db)()

        assert m3.truncated is True
        assert m4.truncated is False

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone

from chat.models import Conversation, Message
from chat.repositories import AsyncDjangoMessageRepository, DjangoMessageRepository

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(email="test@example.com", password="Str0ngP@ss!")


@pytest.fixture
def conversation(user):
    return Conversation.objects.create(user=user, title="Test conversation")


@pytest.fixture
def repo():
    return DjangoMessageRepository()


@pytest.mark.django_db
class TestListMessages:
    def test_returns_messages_in_chronological_order(self, repo, conversation):
        Message.objects.create(conversation=conversation, role="user", content="first")
        Message.objects.create(conversation=conversation, role="ai", content="second")
        Message.objects.create(conversation=conversation, role="user", content="third")

        messages = repo.list_messages(session_id=str(conversation.id))

        assert [m.content for m in messages] == ["first", "second", "third"]

    def test_maps_ai_role_to_assistant(self, repo, conversation):
        Message.objects.create(
            conversation=conversation, role="ai", content="AI response"
        )

        messages = repo.list_messages(session_id=str(conversation.id))

        assert messages[0].role == "assistant"
        assert messages[0].content == "AI response"

    def test_preserves_user_role(self, repo, conversation):
        Message.objects.create(
            conversation=conversation, role="user", content="User msg"
        )

        messages = repo.list_messages(session_id=str(conversation.id))

        assert messages[0].role == "user"

    def test_respects_limit_parameter(self, repo, conversation):
        for i in range(5):
            Message.objects.create(
                conversation=conversation, role="user", content=f"msg_{i}"
            )

        messages = repo.list_messages(session_id=str(conversation.id), limit=3)

        assert len(messages) == 3

    def test_limit_returns_most_recent_messages(self, repo, conversation):
        for i in range(5):
            Message.objects.create(
                conversation=conversation, role="user", content=f"msg_{i}"
            )

        messages = repo.list_messages(session_id=str(conversation.id), limit=3)

        contents = [m.content for m in messages]
        assert "msg_2" in contents
        assert "msg_3" in contents
        assert "msg_4" in contents
        assert "msg_0" not in contents

    def test_returns_empty_list_for_empty_conversation(self, repo, conversation):
        messages = repo.list_messages(session_id=str(conversation.id))

        assert messages == []

    def test_returns_empty_list_for_nonexistent_conversation(self, repo):
        messages = repo.list_messages(session_id=str(uuid.uuid4()))

        assert messages == []

    def test_includes_created_at(self, repo, conversation):
        Message.objects.create(
            conversation=conversation,
            role="user",
            content="test",
        )

        messages = repo.list_messages(session_id=str(conversation.id))

        assert messages[0].created_at is not None
        assert messages[0].content == "test"


@pytest.mark.django_db
class TestAppendMessagePair:
    def test_creates_user_and_assistant_messages(self, repo, conversation):
        before = timezone.now()
        user_msg, assistant_msg = repo.append_message_pair(
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

        assert assistant_msg.role == "ai"
        assert assistant_msg.content == "Hi there!"
        assert assistant_msg.provider == "openai"
        assert assistant_msg.model == "gpt-5.5"
        assert assistant_msg.usage == {"prompt_tokens": 5, "completion_tokens": 10}

        assert before <= user_msg.created_at <= after

    def test_updates_conversation_last_message_at(self, repo, conversation):
        conversation.refresh_from_db()
        old_last_message_at = conversation.last_message_at

        repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Hello",
            assistant_content="Hi!",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )

        conversation.refresh_from_db()
        assert conversation.last_message_at > old_last_message_at

    def test_multiple_pairs_in_same_conversation(self, repo, conversation):
        repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="First question",
            assistant_content="First answer",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )
        repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Second question",
            assistant_content="Second answer",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )

        assert Message.objects.filter(conversation=conversation).count() == 4


@pytest.fixture
def async_repo():
    return AsyncDjangoMessageRepository()


@pytest.mark.django_db(transaction=True)
class TestAsyncListMessages:
    async def test_returns_messages_in_chronological_order(
        self, async_repo, conversation
    ):
        await Message.objects.acreate(
            conversation=conversation, role="user", content="first"
        )
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="second"
        )
        await Message.objects.acreate(
            conversation=conversation, role="user", content="third"
        )

        messages = await async_repo.list_messages(session_id=str(conversation.id))

        assert [m.content for m in messages] == ["first", "second", "third"]

    async def test_maps_ai_role_to_assistant(self, async_repo, conversation):
        await Message.objects.acreate(
            conversation=conversation, role="ai", content="AI response"
        )

        messages = await async_repo.list_messages(session_id=str(conversation.id))

        assert messages[0].role == "assistant"

    async def test_respects_limit_parameter(self, async_repo, conversation):
        for i in range(5):
            await Message.objects.acreate(
                conversation=conversation, role="user", content=f"msg_{i}"
            )

        messages = await async_repo.list_messages(
            session_id=str(conversation.id), limit=3
        )

        assert len(messages) == 3

    async def test_returns_empty_list_for_empty_conversation(
        self, async_repo, conversation
    ):
        messages = await async_repo.list_messages(session_id=str(conversation.id))

        assert messages == []


@pytest.mark.django_db(transaction=True)
class TestAsyncAppendMessagePair:
    async def test_creates_user_and_assistant_messages(self, async_repo, conversation):
        user_msg, assistant_msg = await async_repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Hello",
            assistant_content="Hi there!",
            provider="openai",
            model="gpt-5.5",
            usage={"prompt_tokens": 5, "completion_tokens": 10},
            user_raw_question="Hello",
        )

        assert user_msg.role == "user"
        assert user_msg.content == "Hello"
        assert assistant_msg.role == "ai"
        assert assistant_msg.content == "Hi there!"
        assert assistant_msg.provider == "openai"

    async def test_updates_conversation_last_message_at(self, async_repo, conversation):
        await sync_to_async(conversation.refresh_from_db)()
        old_last_message_at = conversation.last_message_at

        await async_repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Hello",
            assistant_content="Hi!",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )

        await sync_to_async(conversation.refresh_from_db)()
        assert conversation.last_message_at > old_last_message_at

    async def test_creates_two_messages_in_db(self, async_repo, conversation):
        await async_repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Q",
            assistant_content="A",
            provider="openai",
            model="gpt-5.5",
            usage=None,
        )

        count = await sync_to_async(
            Message.objects.filter(conversation=conversation).count
        )()
        assert count == 2


@pytest.mark.django_db
class TestCompactMessages:
    def test_marks_messages_as_compacted(self, repo, conversation):
        Message.objects.create(conversation=conversation, role="user", content="first")
        Message.objects.create(conversation=conversation, role="ai", content="second")

        count = repo.compact_messages(conversation)

        assert count == 2
        for msg in Message.objects.filter(conversation=conversation):
            assert msg.compacted is True

    def test_does_not_recompact_already_compacted(self, repo, conversation):
        Message.objects.create(
            conversation=conversation,
            role="user",
            content="first",
            compacted=True,
        )
        Message.objects.create(conversation=conversation, role="ai", content="second")

        count = repo.compact_messages(conversation)

        assert count == 1

    def test_returns_zero_for_empty_conversation(self, repo, conversation):
        count = repo.compact_messages(conversation)
        assert count == 0


@pytest.mark.django_db
class TestApplyCompaction:
    def test_marks_compacted_and_appends_summary(self, repo, conversation):
        Message.objects.create(
            conversation=conversation, role="user", content="question"
        )
        Message.objects.create(conversation=conversation, role="ai", content="answer")

        summary_msg = repo.apply_compaction(
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

        compacted_count = sum(
            1 for m in Message.objects.filter(conversation=conversation, compacted=True)
        )
        assert compacted_count == 2


@pytest.mark.django_db
class TestTruncateOldestMessages:
    def test_truncates_specified_number_of_oldest_messages(self, repo, conversation):
        m1 = Message.objects.create(
            conversation=conversation, role="user", content="first"
        )
        m2 = Message.objects.create(
            conversation=conversation, role="ai", content="second"
        )
        m3 = Message.objects.create(
            conversation=conversation, role="user", content="third"
        )

        updated_count = repo.truncate_oldest_messages(str(conversation.id), 2)
        assert updated_count == 2

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()

        assert m1.truncated is True
        assert m2.truncated is True
        assert m3.truncated is False

    def test_excludes_already_truncated_or_compacted_messages(self, repo, conversation):
        Message.objects.create(
            conversation=conversation, role="user", content="first", compacted=True
        )
        Message.objects.create(
            conversation=conversation, role="ai", content="second", truncated=True
        )
        m3 = Message.objects.create(
            conversation=conversation, role="user", content="third"
        )
        m4 = Message.objects.create(
            conversation=conversation, role="ai", content="fourth"
        )

        updated_count = repo.truncate_oldest_messages(str(conversation.id), 1)
        assert updated_count == 1

        m3.refresh_from_db()
        m4.refresh_from_db()

        assert m3.truncated is True
        assert m4.truncated is False

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from api.models import Conversation, Message
from api.repositories import DjangoMessageRepository

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

    def test_includes_created_at_and_meta(self, repo, conversation):
        Message.objects.create(
            conversation=conversation,
            role="user",
            content="test",
            meta={"key": "value"},
        )

        messages = repo.list_messages(session_id=str(conversation.id))

        assert messages[0].created_at is not None
        assert messages[0].meta == {"key": "value"}


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
            user_meta={"provider_selected": "openai"},
            assistant_meta={"input_tokens": 5, "output_tokens": 10},
        )
        after = timezone.now()

        assert user_msg.role == "user"
        assert user_msg.content == "Hello"
        assert user_msg.provider is None
        assert user_msg.model is None
        assert user_msg.meta == {"provider_selected": "openai"}

        assert assistant_msg.role == "ai"
        assert assistant_msg.content == "Hi there!"
        assert assistant_msg.provider == "openai"
        assert assistant_msg.model == "gpt-5.5"
        assert assistant_msg.usage == {"prompt_tokens": 5, "completion_tokens": 10}
        assert assistant_msg.meta == {"input_tokens": 5, "output_tokens": 10}

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
            user_meta=None,
            assistant_meta=None,
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
            user_meta=None,
            assistant_meta=None,
        )
        repo.append_message_pair(
            session_id=str(conversation.id),
            user_content="Second question",
            assistant_content="Second answer",
            provider="openai",
            model="gpt-5.5",
            usage=None,
            user_meta=None,
            assistant_meta=None,
        )

        assert Message.objects.filter(conversation=conversation).count() == 4

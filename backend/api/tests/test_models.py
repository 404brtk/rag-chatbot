import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from api.models import Conversation, Message

User = get_user_model()


@pytest.mark.django_db
class TestUserManager:
    def test_create_user_with_email(self):
        user = User.objects.create_user(
            email="test@example.com", password="Str0ngP@ss!"
        )
        assert user.email == "test@example.com"
        assert user.check_password("Str0ngP@ss!")
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_create_user_normalizes_email_to_lowercase(self):
        user = User.objects.create_user(
            email="Test@EXAMPLE.COM", password="Str0ngP@ss!"
        )
        assert user.email == "test@example.com"

    def test_create_user_auto_generates_username_from_email(self):
        user = User.objects.create_user(
            email="john@example.com", password="Str0ngP@ss!"
        )
        assert user.username == "john@example.com"

    def test_create_user_without_email_raises(self):
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_user(email="", password="Str0ngP@ss!")

    def test_create_user_hashes_password(self):
        user = User.objects.create_user(
            email="test@example.com", password="Str0ngP@ss!"
        )
        assert user.password != "Str0ngP@ss!"
        assert user.has_usable_password()

    def test_create_superuser(self):
        user = User.objects.create_superuser(
            email="admin@example.com", password="Str0ngP@ss!"
        )
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_create_superuser_rejects_is_staff_false(self):
        with pytest.raises(ValueError, match="is_staff=True"):
            User.objects.create_superuser(
                email="admin@example.com", password="Str0ngP@ss!", is_staff=False
            )

    def test_create_superuser_rejects_is_superuser_false(self):
        with pytest.raises(ValueError, match="is_superuser=True"):
            User.objects.create_superuser(
                email="admin@example.com", password="Str0ngP@ss!", is_superuser=False
            )

    def test_get_by_natural_key_is_case_insensitive(self):
        User.objects.create_user(email="test@example.com", password="Str0ngP@ss!")
        found = User.objects.get_by_natural_key("TEST@EXAMPLE.COM")
        assert found.email == "test@example.com"

    def test_duplicate_email_raises_integrity_error(self):
        User.objects.create_user(email="dupe@example.com", password="Str0ngP@ss!")
        with pytest.raises(IntegrityError):
            User.objects.create_user(email="dupe@example.com", password="Str0ngP@ss!")

    def test_user_id_is_uuid(self):
        user = User.objects.create_user(
            email="uuid@example.com", password="Str0ngP@ss!"
        )
        assert isinstance(user.id, uuid.UUID)


@pytest.mark.django_db
class TestConversationModel:
    def test_str_uses_title_when_set(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        conv = Conversation.objects.create(user=user, title="My Chat")
        assert str(conv) == "My Chat"

    def test_str_falls_back_to_id(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        conv = Conversation.objects.create(user=user)
        assert str(conv) == f"Chat {conv.id}"

    def test_cascade_deletes_conversations_when_user_deleted(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        Conversation.objects.create(user=user, title="Temp")
        user.delete()
        assert Conversation.objects.count() == 0

    def test_conversation_defaults_to_active_status(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        conv = Conversation.objects.create(user=user)
        assert conv.status == Conversation.Status.ACTIVE


@pytest.mark.django_db
class TestMessageModel:
    def test_cascade_deletes_messages_when_conversation_deleted(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        conv = Conversation.objects.create(user=user)
        Message.objects.create(
            conversation=conv, role=Message.Role.USER, content="hello"
        )
        conv.delete()
        assert Message.objects.count() == 0

    def test_role_choices_enforced(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        conv = Conversation.objects.create(user=user)
        msg = Message(conversation=conv, role="invalid", content="test")
        with pytest.raises(ValidationError):
            msg.full_clean()

    def test_message_str_truncates_long_content(self):
        user = User.objects.create_user(email="u@example.com", password="Str0ngP@ss!")
        conv = Conversation.objects.create(user=user)
        msg = Message.objects.create(
            conversation=conv, role=Message.Role.USER, content="x" * 100
        )
        assert str(msg) == f"user: {'x' * 50}"

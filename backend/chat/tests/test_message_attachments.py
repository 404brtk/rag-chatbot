from unittest.mock import patch

import pytest
from django.core.files.storage import default_storage

from chat.models import Conversation, Message, MessageAttachment


@pytest.fixture
def conversation(user_a):
    return Conversation.objects.create(user=user_a, title="Test Chat")


@pytest.fixture
def message(conversation):
    return Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content="Hello"
    )


@pytest.mark.django_db(transaction=True)
class TestMessageAttachmentModel:
    def test_create_attachment(self, message):
        attachment = MessageAttachment.objects.create(
            message=message,
            file_id="abc-123",
            name="photo.jpg",
            size=1024,
            mime_type="image/jpeg",
            saved_path="attachments/abc-123.jpg",
        )
        assert attachment.message == message
        assert attachment.file_id == "abc-123"
        assert attachment.name == "photo.jpg"
        assert attachment.size == 1024
        assert attachment.mime_type == "image/jpeg"
        assert attachment.saved_path == "attachments/abc-123.jpg"

    def test_delete_attachment_triggers_storage_cleanup(self, message):
        attachment = MessageAttachment.objects.create(
            message=message,
            file_id="abc-123",
            name="photo.jpg",
            size=1024,
            mime_type="image/jpeg",
            saved_path="attachments/abc-123.jpg",
        )

        with patch.object(default_storage, "delete") as mock_delete:
            attachment.delete()
            mock_delete.assert_called_once_with("attachments/abc-123.jpg")

    def test_message_cascade_delete(self, message):
        attachment = MessageAttachment.objects.create(
            message=message,
            file_id="abc-123",
            name="photo.jpg",
            size=1024,
            mime_type="image/jpeg",
            saved_path="attachments/abc-123.jpg",
        )

        assert MessageAttachment.objects.filter(id=attachment.id).exists()

        with patch.object(default_storage, "delete") as mock_delete:
            message.delete()
            assert not MessageAttachment.objects.filter(id=attachment.id).exists()
            mock_delete.assert_called_once_with("attachments/abc-123.jpg")

    def test_conversation_cascade_delete(self, conversation, message):
        attachment = MessageAttachment.objects.create(
            message=message,
            file_id="abc-123",
            name="photo.jpg",
            size=1024,
            mime_type="image/jpeg",
            saved_path="attachments/abc-123.jpg",
        )

        assert MessageAttachment.objects.filter(id=attachment.id).exists()

        with patch.object(default_storage, "delete") as mock_delete:
            conversation.delete()
            assert not MessageAttachment.objects.filter(id=attachment.id).exists()
            mock_delete.assert_called_once_with("attachments/abc-123.jpg")

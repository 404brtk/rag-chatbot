from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    HealthView,
    ModelListView,
    ConversationViewSet,
    MessageViewSet,
    MessageStreamView,
    AttachmentUploadView,
)

router = DefaultRouter()
router.register(r"conversations", ConversationViewSet, basename="conversation")

message_list = MessageViewSet.as_view({"get": "list", "post": "create"})

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("models/", ModelListView.as_view(), name="models"),
    path("attachments/", AttachmentUploadView.as_view(), name="attachment-upload"),
    path("", include(router.urls)),
    path(
        "conversations/<uuid:conversation_pk>/messages/",
        message_list,
        name="conversation-messages",
    ),
    path(
        "conversations/<uuid:conversation_pk>/messages/stream/",
        MessageStreamView.as_view(),
        name="conversation-messages-stream",
    ),
]

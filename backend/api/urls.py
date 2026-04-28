from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet, MessageViewSet, RegisterView

router = DefaultRouter()
router.register(r"conversations", ConversationViewSet, basename="conversation")

message_list = MessageViewSet.as_view({"get": "list", "post": "create"})

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("", include(router.urls)),
    path(
        "conversations/<uuid:conversation_pk>/messages/",
        message_list,
        name="conversation-messages",
    ),
]

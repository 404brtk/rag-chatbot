from rest_framework import generics, permissions, viewsets
from .serializers import RegisterSerializer, UserApiKeySerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class UserApiKeyViewSet(viewsets.ModelViewSet):
    serializer_class = UserApiKeySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return self.request.user.api_keys.all()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

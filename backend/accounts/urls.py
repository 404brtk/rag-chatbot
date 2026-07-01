from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import RegisterView, UserApiKeyViewSet

router = DefaultRouter()
router.register(r"keys", UserApiKeyViewSet, basename="apikey")

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("", include(router.urls)),
]

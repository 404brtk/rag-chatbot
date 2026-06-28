from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import DocumentViewSet, GetDocsJobViewSet, DocumentRetrieveView

router = DefaultRouter()
router.register(r"documents", DocumentViewSet, basename="document")
router.register(r"getdocs-jobs", GetDocsJobViewSet, basename="getdocs-job")

urlpatterns = [
    path(
        "documents/retrieve/", DocumentRetrieveView.as_view(), name="document-retrieve"
    ),
    path("", include(router.urls)),
]

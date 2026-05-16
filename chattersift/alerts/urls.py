from django.urls import path

from . import views

app_name = "alerts"

urlpatterns = [
    path("notifications/", views.notification_settings, name="notification_settings"),
]

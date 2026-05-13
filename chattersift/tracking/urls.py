from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("dash/", views.dashboard, name="dashboard"),
    path("dash/monitors/", views.monitor_create, name="monitor_create"),
    path("dash/monitors/<int:pk>/deactivate/", views.monitor_deactivate, name="monitor_deactivate"),
]

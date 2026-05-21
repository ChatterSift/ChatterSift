from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("dash/", views.dashboard, name="dashboard"),
    path("dash/monitors/", views.monitor_create, name="monitor_create"),
    path("dash/monitors/<int:pk>/deactivate/", views.monitor_deactivate, name="monitor_deactivate"),
    path("dash/matches/", views.matches, name="matches"),
    path("dash/settings/", views.dashboard_settings, name="dashboard_settings"),
    path("dash/settings/profile/", views.dashboard_settings_profile, name="dashboard_settings_profile"),
    path(
        "dash/settings/notifications/",
        views.dashboard_settings_notifications,
        name="dashboard_settings_notifications",
    ),
]

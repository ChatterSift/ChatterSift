from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("dash/", views.dashboard, name="dashboard"),
    path("dash/monitors/", views.monitor_create, name="monitor_create"),
    path("dash/monitors/<int:pk>/deactivate/", views.monitor_deactivate, name="monitor_deactivate"),
    path("dash/monitors/<int:pk>/delete/", views.monitor_delete, name="monitor_delete"),
    path("dash/monitors/<str:subreddit>/add-keyword/", views.monitor_add_keyword, name="monitor_add_keyword"),
    path("dash/monitors/<str:subreddit>/toggle/", views.monitor_toggle_group, name="monitor_toggle_group"),
    path("dash/monitors/<str:subreddit>/delete/", views.monitor_delete_group, name="monitor_delete_group"),
    path("dash/monitors/<str:subreddit>/cadence/", views.monitor_update_cadence, name="monitor_update_cadence"),
    path("dash/matches/", views.matches, name="matches"),
    path("dash/settings/", views.dashboard_settings, name="dashboard_settings"),
    path("dash/settings/match-retention/", views.match_retention_update, name="match_retention_update"),
]

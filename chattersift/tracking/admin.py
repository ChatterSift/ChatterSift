from django.contrib import admin

from .models import Match
from .models import Monitor


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    """Admin interface for user keyword monitors."""

    list_display = ["subreddit", "keyword", "user", "is_active", "created_at", "updated_at"]
    list_filter = ["is_active", "subreddit", "created_at"]
    search_fields = ["subreddit", "keyword", "user__email", "user__name"]
    autocomplete_fields = ["user"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["subreddit", "keyword"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    """Admin interface for Reddit items matched against monitors."""

    list_display = ["reddit_item_id", "monitor", "occurred_at", "created_at"]
    list_filter = ["occurred_at", "created_at", "monitor__subreddit"]
    search_fields = [
        "reddit_item_id",
        "title",
        "body",
        "monitor__subreddit",
        "monitor__keyword",
        "monitor__user__email",
    ]
    autocomplete_fields = ["monitor"]
    readonly_fields = ["created_at"]
    date_hierarchy = "occurred_at"
    ordering = ["-occurred_at"]

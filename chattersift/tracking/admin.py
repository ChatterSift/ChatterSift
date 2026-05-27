from django.contrib import admin

from .models import Match
from .models import MatchRetentionPreference
from .models import Monitor


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    """Admin interface for user Reddit monitors."""

    list_display = ["subreddit", "match_mode", "keyword", "semantic_description", "user", "is_active", "created_at"]
    list_filter = ["match_mode", "is_active", "subreddit", "created_at"]
    search_fields = ["subreddit", "keyword", "semantic_description", "user__email", "user__name"]
    autocomplete_fields = ["user"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["subreddit", "keyword"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    """Admin interface for Reddit items matched against monitors."""

    list_display = ["reddit_item_id", "monitor", "match_mode", "confidence", "occurred_at", "created_at"]
    list_filter = ["match_mode", "occurred_at", "created_at", "monitor__subreddit"]
    search_fields = [
        "reddit_item_id",
        "title",
        "body",
        "match_reason",
        "monitor__subreddit",
        "monitor__keyword",
        "monitor__semantic_description",
        "monitor__user__email",
    ]
    autocomplete_fields = ["monitor"]
    readonly_fields = ["created_at"]
    date_hierarchy = "occurred_at"
    ordering = ["-occurred_at"]


@admin.register(MatchRetentionPreference)
class MatchRetentionPreferenceAdmin(admin.ModelAdmin):
    """Admin interface for matched-item retention preferences."""

    list_display = ["user", "retention_days", "created_at", "updated_at"]
    search_fields = ["user__email", "user__name"]
    autocomplete_fields = ["user"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["user_id"]

from django.contrib import admin

from .models import RedditItem
from .models import SubredditFetchState


@admin.register(SubredditFetchState)
class SubredditFetchStateAdmin(admin.ModelAdmin):
    """Admin interface for Reddit feed scheduling state."""

    list_display = [
        "subreddit",
        "kind",
        "format",
        "query_fingerprint",
        "next_fetch_at",
        "consecutive_failures",
        "updated_at",
    ]
    list_filter = ["kind", "format", "consecutive_failures", "next_fetch_at"]
    search_fields = ["subreddit", "query_fingerprint", "last_seen_fullname", "last_error"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "next_fetch_at"
    ordering = ["subreddit", "kind", "format", "query_fingerprint"]


@admin.register(RedditItem)
class RedditItemAdmin(admin.ModelAdmin):
    """Admin interface for normalized Reddit posts and comments."""

    list_display = ["reddit_id", "item_type", "subreddit", "author", "occurred_at", "fetched_at"]
    list_filter = ["item_type", "subreddit", "occurred_at", "fetched_at"]
    search_fields = ["reddit_id", "subreddit", "author", "title", "body", "permalink"]
    readonly_fields = ["fetched_at"]
    date_hierarchy = "occurred_at"
    ordering = ["-occurred_at"]

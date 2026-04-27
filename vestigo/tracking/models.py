from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Monitor(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subreddit = models.CharField(max_length=100)
    keyword = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subreddit", "keyword"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "subreddit", "keyword"],
                name="unique_monitor_per_user_subreddit_keyword",
            ),
        ]

    def __str__(self) -> str:
        return _("%(keyword)s in r/%(subreddit)s") % {
            "keyword": self.keyword,
            "subreddit": self.subreddit,
        }


class Match(models.Model):
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE)
    reddit_item_id = models.CharField(max_length=255)
    title = models.TextField(blank=True)
    body = models.TextField(blank=True)
    permalink = models.URLField()
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["monitor", "reddit_item_id"],
                name="unique_match_per_monitor_reddit_item",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.monitor_id}:{self.reddit_item_id}"

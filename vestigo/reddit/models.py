from django.db import models


class SubredditFetchState(models.Model):
    subreddit = models.CharField(max_length=100, unique=True)
    last_seen_fullname = models.CharField(max_length=255, blank=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subreddit"]

    def __str__(self) -> str:
        return f"r/{self.subreddit}"


class RedditItem(models.Model):
    class RedditItemType(models.TextChoices):
        POST = "post", "Post"
        COMMENT = "comment", "Comment"

    reddit_id = models.CharField(max_length=255, unique=True)
    item_type = models.CharField(max_length=20, choices=RedditItemType)
    subreddit = models.CharField(max_length=100)
    author = models.CharField(max_length=255, blank=True)
    title = models.TextField(blank=True)
    body = models.TextField(blank=True)
    permalink = models.URLField()
    occurred_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["subreddit", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return self.reddit_id

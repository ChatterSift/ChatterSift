from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("reddit", "0003_expand_subreddit_fetch_state"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="subredditfetchstate",
            name="unique_reddit_fetch_state_feed",
        ),
        migrations.RemoveIndex(
            model_name="subredditfetchstate",
            name="reddit_subr_kind_eb52e6_idx",
        ),
        migrations.AddField(
            model_name="subredditfetchstate",
            name="lane",
            field=models.CharField(default="default", max_length=32),
        ),
        migrations.AlterModelOptions(
            name="subredditfetchstate",
            options={"ordering": ["lane", "subreddit", "kind", "format", "query_fingerprint"]},
        ),
        migrations.AddIndex(
            model_name="subredditfetchstate",
            index=models.Index(
                fields=["lane", "kind", "format", "subreddit"],
                name="reddit_subr_kind_eb52e6_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="subredditfetchstate",
            constraint=models.UniqueConstraint(
                fields=("lane", "kind", "format", "subreddit", "query_fingerprint"),
                name="unique_reddit_fetch_state_feed",
            ),
        ),
    ]

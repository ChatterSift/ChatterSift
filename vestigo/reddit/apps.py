from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RedditConfig(AppConfig):
    name = "vestigo.reddit"
    verbose_name = _("Reddit")

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TrackingConfig(AppConfig):
    name = "vestigo.tracking"
    verbose_name = _("Tracking")

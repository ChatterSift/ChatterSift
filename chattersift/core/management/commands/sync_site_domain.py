from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Interface: sync the default django_site record from CHATTERSIFT_SITE_DOMAIN."""

    help = "Sync django.contrib.sites with CHATTERSIFT_SITE_DOMAIN."

    def handle(self, *args: object, **options: object) -> None:
        site_domain = settings.CHATTERSIFT_SITE_DOMAIN
        Site.objects.update_or_create(
            id=settings.SITE_ID,
            defaults={"domain": site_domain, "name": site_domain},
        )
        self.stdout.write(self.style.SUCCESS(f"Synced site domain to {site_domain}"))

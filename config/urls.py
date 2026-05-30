from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import TemplateView

from chattersift.core.views import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path(
        "",
        TemplateView.as_view(template_name=settings.CHATTERSIFT_HOME_TEMPLATE),
        name="home",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("chattersift.tracking.urls", namespace="tracking")),
    path("", include("chattersift.alerts.urls", namespace="alerts")),
    # Media files
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]
if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()


for urlconf in settings.CHATTERSIFT_URLCONFS:
    urlpatterns.append(path("", include(urlconf)))

if settings.CHATTERSIFT_ENABLE_API:
    from .api import api

    urlpatterns += [
        path("api/", api.urls),
    ]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
        ]
    if "django_browser_reload" in settings.INSTALLED_APPS:
        urlpatterns = [
            path("__reload__/", include("django_browser_reload.urls")),
            *urlpatterns,
        ]

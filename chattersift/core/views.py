from http import HTTPStatus

from django.http import HttpRequest
from django.http import HttpResponse


def healthz(request: HttpRequest) -> HttpResponse:
    """Interface: lightweight process health check for Docker and reverse proxies."""
    return HttpResponse("ok", status=HTTPStatus.OK, content_type="text/plain")

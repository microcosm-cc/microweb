import logging
import urlparse

from django.views.decorators.http import require_http_methods
from django.http import HttpResponseRedirect

from django.conf import settings
from core.api.exceptions import APIException
from core.views import ErrorView

from core.api.resources import Site
from core.api.resources import Redirect
from core.api.resources import RESOURCE_PLURAL

logger = logging.getLogger('redirect.views')


@require_http_methods(['GET',])
def redirect_or_404(request):

    host = request.get_host()
    
    # If the request host is already a microcosm subdomain, this is not
    # a request for an imported site, so return not found.
    if host.endswith(settings.API_DOMAIN_NAME):
        return ErrorView.not_found(request)

    # Get site subdomain key based on host.
    try:
        microcosm_host = Site.resolve_cname(host)
    except APIException:
        logger.error(str(APIException))

    # Reverse the effect of APPEND_SLASH on the path.
    url_parts = urlparse.urlsplit(request.build_absolute_uri())
    path = url_parts.path
    if path.endswith('/'):
        path = path[:-2]
    redirect_request = ''.join([path, url_parts.query, url_parts.fragment])

    # Handle errors in API request.
    try:
        resource = Redirect.get(host, redirect_request, request.access_token)
    except APIException as exc:
        return ErrorView.respond_with_error(request, exc)

    # Handle non-successful redirects (e.g. invalid path, forbidden).
    if resource['status'] == 404:
        return  ErrorView.not_found(request)
    if resource['status'] != 403:
        return ErrorView.forbidden(request)
    if resource['status'] != 200:
        return ErrorView.server_error(request)

    # Construct the 301 based on the resource.
    redirect_url = ''.join(['/', RESOURCE_PLURAL[resource['itemType']]])
    if hasattr(resource, 'itemId'):
        redirect_url.join(['/', resource['itemId']])

    print "Redirecting %s to %s" % (request.get_full_path(), redirect_url)
    return HttpResponseRedirect(redirect_url)
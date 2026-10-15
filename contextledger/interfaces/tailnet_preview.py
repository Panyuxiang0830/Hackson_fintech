"""Trusted loopback gateway for an explicitly shared synthetic demo."""
from urllib.parse import urlparse

from werkzeug.wrappers import Response


class TailnetPreview:
    def __init__(self, application, *, public_url, local_url, allowed_logins):
        public, local = urlparse(public_url), urlparse(local_url)
        if (public.scheme != 'https' or not public.hostname or not public.hostname.endswith('.ts.net')
                or public.username or public.password or public.query or public.fragment or public.path not in {'', '/'}):
            raise ValueError('Preview requires an exact Tailscale HTTPS origin')
        if (local.scheme != 'http' or local.hostname not in {'127.0.0.1', '::1'} or local.username
                or local.password or local.query or local.fragment or local.path):
            raise ValueError('Preview application must have a loopback origin')
        self.logins = {value.casefold() for value in allowed_logins if value and value.strip() == value}
        if not self.logins:
            raise ValueError('At least one explicit Tailscale login is required')
        self.application = application
        self.public_origin = public_url.rstrip('/')
        self.public_host = public.netloc
        self.local_origin = local_url
        self.local_host = local.netloc

    def __call__(self, environ, start_response):
        # Serve overwrites identity headers. The gateway itself binds only loopback.
        login = environ.get('HTTP_TAILSCALE_USER_LOGIN', '').casefold()
        origin = environ.get('HTTP_ORIGIN')
        safe = environ.get('REQUEST_METHOD') in {'GET', 'HEAD', 'OPTIONS'}
        if (environ.get('REMOTE_ADDR') not in {'127.0.0.1', '::1'}
                or environ.get('HTTP_HOST') != self.public_host or login not in self.logins
                or origin is not None and origin != self.public_origin
                or not safe and origin != self.public_origin):
            return Response('{"error":"private_preview_access_denied"}', status=403,
                            content_type='application/json', headers={'Cache-Control': 'no-store'})(environ, start_response)
        trusted = environ.copy()
        trusted['HTTP_HOST'], trusted['wsgi.url_scheme'] = self.local_host, 'http'
        if origin is not None:
            trusted['HTTP_ORIGIN'] = self.local_origin
        # Tailscale identity permits demo entry; it never selects an application actor.
        for key in list(trusted):
            if key.startswith(('HTTP_TAILSCALE_', 'HTTP_X_FORWARDED_')):
                trusted.pop(key)
        return self.application(trusted, start_response)

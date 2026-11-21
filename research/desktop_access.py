"""Verify desktop entitlements with the license authority before exposing full research."""
import os
import re
from urllib.parse import urlsplit
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, Request


def local_development_request(request: Request):
    # Both the actual socket peer and destination must be loopback. Never trust
    # forwarded headers, a browser cookie or a client-supplied desktop flag.
    return (os.environ.get('OUTLOUD_LOCAL_TESTING') == '1'
            and os.environ.get('OUTLOUD_LOCAL_DESKTOP') == '1'
            and request.client is not None
            and request.client.host in ('127.0.0.1', '::1')
            and request.url.hostname in ('127.0.0.1', 'localhost')
            and not request.headers.get('origin')
            and request.headers.get('authorization') == 'Bearer outloud-local-development')


def desktop_identity(request: Request):
    if local_development_request(request):
        identity = 'desktop:local-development'
        request.state.desktop_owner = identity
        return identity
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Activate Outloud on this Mac to continue.')
    token = authorization[7:]
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise HTTPException(401, 'This license session could not be verified.')
    endpoint = os.environ.get('OUTLOUD_LICENSE_AUTHORITY', '')
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise HTTPException(503, 'Desktop research is not connected yet.')
    # This URL comes from server configuration, never a caller-controlled header.
    try:
        response = httpx.post(endpoint.rstrip('/')+'/v1/licenses/check',json={'device_token':token},timeout=12,follow_redirects=False)
    except httpx.HTTPError:
        raise HTTPException(503, 'We couldn’t verify your license. Please try again.') from None
    if response.status_code in (401,403,404):
        raise HTTPException(403, 'Activate a valid license to use desktop research.')
    if response.status_code != 200:
        raise HTTPException(503, 'License verification is temporarily unavailable.')
    try:
        entitlement = response.json()
    except ValueError:
        raise HTTPException(503, 'License verification is temporarily unavailable.') from None
    if not isinstance(entitlement,dict):
        raise HTTPException(503, 'License verification is temporarily unavailable.')
    if entitlement.get('environment') != 'live' or entitlement.get('status') != 'active' or entitlement.get('unlocked') is not True:
        raise HTTPException(403, 'Your license does not currently include full workspace access.')
    subject=entitlement.get('license_subject','')
    try:
        expires=datetime.fromisoformat(entitlement.get('access_ends_at','').replace('Z','+00:00'))
        valid=expires.tzinfo is not None and expires>datetime.now(timezone.utc)
    except (TypeError,ValueError,AttributeError):
        valid=False
    if not valid or not isinstance(subject,str) or not re.fullmatch(r'[a-f0-9]{64}',subject):
        raise HTTPException(403, 'Your license entitlement could not be confirmed.')
    # Stable across device-token rotation. Tokens and license keys are never persisted.
    identity = 'desktop:'+subject
    request.state.desktop_owner = identity
    return identity

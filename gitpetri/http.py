"""Tiny JSON-over-HTTP client with ETag revalidation."""

import json
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status} {message}" if status else message)
        self.status = status


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    # urllib replays request headers on redirect, which would hand the token
    # to whatever host the server points at.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Http:
    def __init__(self, headers, timeout=20):
        self.headers = {"User-Agent": "git-petri", "Accept": "application/json", **headers}
        self.timeout = timeout
        self.etags = {}
        self.opener = urllib.request.build_opener(_SameOriginRedirects)

    def get(self, url, params=None):
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        cached = self.etags.get(url)
        if cached:
            req.add_header("If-None-Match", cached[0])
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                body = json.load(r)
                etag = r.headers.get("ETag")
                if etag:
                    self.etags[url] = (etag, body)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 304 and cached:
                return cached[1]
            raise ApiError(e.code, _reason(e)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(0, str(getattr(e, "reason", e))) from None

    def post(self, url, payload):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={**self.headers, "Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, _reason(e)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(0, str(getattr(e, "reason", e))) from None


def parallel(fn, items, workers=6):
    """Run fn over items concurrently; the first failure propagates."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(min(workers, len(items))) as pool:
        return list(pool.map(fn, items))


def _reason(e):
    try:
        body = json.loads(e.read() or b"{}")
        msg = body.get("message") or body.get("error_description") or body.get("error")
        if msg:
            return str(msg)[:120]
    except (ValueError, AttributeError, OSError):
        pass
    return e.reason or "error"

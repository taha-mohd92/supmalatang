#!/usr/bin/env python3
"""stdio ⇄ HTTP bridge for the Stitch MCP server, with Google OAuth.

Why this exists
---------------
`stitch.googleapis.com/mcp` is an OAuth 2.0 protected resource:

    $ curl .../.well-known/oauth-protected-resource/mcp
    {"authorization_servers":["https://accounts.google.com/"],
     "bearer_methods_supported":["header"],
     "scopes_supported":["https://www.googleapis.com/auth/aida",
                         "https://www.googleapis.com/auth/cloud-platform"]}

Two consequences:

* An API key cannot authenticate it. Google answers a keyed `tools/call` with
  "API keys are not supported by this API. Expected OAuth2 access token or other
  authentication credentials that assert a principal." A static `X-Goog-Api-Key`
  header in .mcp.json therefore cannot be made to work, however fresh the key.
* Claude Code's built-in OAuth cannot complete either — accounts.google.com does
  not implement RFC 7591 dynamic client registration, which is the
  "Incompatible auth server: does not support dynamic client registration" error.

`initialize` and `tools/list` need no credentials, which is why a health check
reports the server as connected right up until the first real tool call fails.

This bridge mints a short-lived OAuth access token per session and attaches it as
`Authorization: Bearer`, refreshing before expiry. Token sources, in order:

  1. $STITCH_ACCESS_TOKEN                      — explicit override
  2. `gcloud auth print-access-token`          — user or service-account ADC
  3. google.auth default credentials           — if the library is installed

With no token available the bridge still forwards the request, so the
unauthenticated methods work and Google's own error surfaces verbatim.

Setup (once, on a machine with gcloud):

    gcloud auth application-default login \
      --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/aida

Then point .mcp.json at this file with "type": "stdio".
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("STITCH_MCP_URL", "https://stitch.googleapis.com/mcp")
SCOPES = ["https://www.googleapis.com/auth/cloud-platform",
          "https://www.googleapis.com/auth/aida"]
REFRESH_MARGIN = 300          # re-mint 5 minutes before the token lapses

_token = {"value": None, "expires": 0.0}
_session_id = None


def log(msg):
    """stdout is the protocol channel; diagnostics go to stderr."""
    print(f"[stitch-proxy] {msg}", file=sys.stderr, flush=True)


def _from_gcloud():
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-access-token", "--scopes=" + ",".join(SCOPES)],
            capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    # Older gcloud builds reject --scopes on user credentials; retry plainly.
    try:
        out = subprocess.run(["gcloud", "auth", "print-access-token"],
                             capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    log("gcloud could not mint a token: " + out.stderr.strip()[:200])
    return None


def _from_library():
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError:
        return None
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception as e:                      # noqa: BLE001 — report, never crash
        log(f"google.auth failed: {e}")
        return None


def access_token():
    override = os.environ.get("STITCH_ACCESS_TOKEN")
    if override:
        return override
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    tok = _from_gcloud() or _from_library()
    if tok:
        _token.update(value=tok, expires=time.time() + 3600 - REFRESH_MARGIN)
        log("minted a fresh access token")
    return tok


def parse_response(raw, content_type):
    """The endpoint may answer as JSON or as a single SSE frame."""
    text = raw.decode("utf-8", "replace").strip()
    if "text/event-stream" in (content_type or ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError("event-stream carried no data frame")
    return json.loads(text)


def forward(message):
    global _session_id
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    tok = access_token()
    if tok:
        headers["Authorization"] = "Bearer " + tok
    if _session_id:
        headers["Mcp-Session-Id"] = _session_id

    req = urllib.request.Request(ENDPOINT, data=json.dumps(message).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            _session_id = resp.headers.get("Mcp-Session-Id") or _session_id
            body = resp.read()
            ctype = resp.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        body, ctype = e.read(), e.headers.get("Content-Type")
        if e.code == 401:
            log("401 from Stitch — run: gcloud auth application-default login "
                "--scopes=" + ",".join(SCOPES))
    except urllib.error.URLError as e:
        return {"jsonrpc": "2.0", "id": message.get("id"),
                "error": {"code": -32001, "message": f"cannot reach Stitch: {e.reason}"}}

    try:
        return parse_response(body, ctype)
    except (ValueError, json.JSONDecodeError) as e:
        return {"jsonrpc": "2.0", "id": message.get("id"),
                "error": {"code": -32700,
                          "message": f"unparseable response: {e}",
                          "data": body[:400].decode("utf-8", "replace")}}


def main():
    log(f"bridging stdio → {ENDPOINT}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as e:
            log(f"dropped malformed input: {e}")
            continue
        response = forward(message)
        # Notifications carry no id and must not be answered.
        if message.get("id") is None:
            continue
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

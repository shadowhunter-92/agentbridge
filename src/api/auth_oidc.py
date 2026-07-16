"""
OIDC / JWT operator authentication — the modern "SSO" path for the control plane.

Instead of a single shared admin key, operators authenticate with a JWT issued by your
identity provider (Okta, Azure AD, Auth0, Keycloak, ...). The token's signature is verified
against the IdP's public key, and a role claim maps to an RBAC role (see src/governance/rbac.py).

Production-ready options:
  - `public_key_pem`: configure the IdP signing public key directly (simple/self-hosted).
  - `jwks_url`: fetch the JWKS from the IdP at first use (and refresh on `kid` miss).
    If neither is set but `issuer` is, the verifier auto-discovers the JWKS URL from
    `<issuer>/.well-known/openid-configuration` on first use.

Requires `pyjwt` (already a dev dep; add to runtime deps if you enable OIDC). For JWKS
auto-fetch, `pyjwt[crypto]` and a JSON HTTP fetcher are also pulled in lazily.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple


@dataclass
class OidcConfig:
    issuer: str
    audience: str
    public_key_pem: Optional[str] = None              # IdP signing public key (or JWKS in prod)
    jwks_url: Optional[str] = None                    # explicit JWKS URL (else discover)
    algorithms: Sequence[str] = field(default_factory=lambda: ("RS256", "ES256", "EdDSA"))
    role_claim: str = "role"
    default_role: str = "viewer"
    # Cache TTL for the JWKS (seconds). Default 15 min — keys rotate rarely.
    jwks_ttl_seconds: int = 900
    # HTTP timeout for JWKS/discovery fetches.
    fetch_timeout_seconds: float = 5.0


class OidcError(Exception):
    """Raised when a token is missing, malformed, expired, or fails verification."""


class OidcVerifier:
    def __init__(self, config: OidcConfig):
        self.config = config
        # JWKS cache: {kid: {key_pem, fetched_at}}; guarded by a lock.
        self._jwks_lock = threading.RLock()
        self._jwks_cache: Dict[str, Dict[str, Any]] = {}
        self._jwks_full_fetch_at: float = 0.0
        self._discovered_jwks_url: Optional[str] = None

    # --- key resolution ----------------------------------------------------------

    def _fetch_url(self, url: str) -> bytes:
        """Tiny HTTP GET. We avoid a hard dep on httpx/requests here so OIDC works
        in minimal installs (pyjwt only)."""
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.config.fetch_timeout_seconds) as resp:  # noqa: S310 (trusted IdP URL)
            return resp.read()

    def _discover_jwks_url(self) -> Optional[str]:
        """Fetch `<issuer>/.well-known/openid-configuration` and extract `jwks_uri`."""
        if self._discovered_jwks_url:
            return self._discovered_jwks_url
        url = self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"
        try:
            data = json.loads(self._fetch_url(url).decode("utf-8"))
            self._discovered_jwks_url = data.get("jwks_uri")
            return self._discovered_jwks_url
        except Exception:
            return None

    def _fetch_jwks(self) -> Dict[str, Any]:
        url = self.config.jwks_url or self._discover_jwks_url()
        if not url:
            raise OidcError("no JWKS URL configured and OIDC discovery failed")
        try:
            return json.loads(self._fetch_url(url).decode("utf-8"))
        except Exception as e:
            raise OidcError(f"failed to fetch JWKS from {url}: {e}") from e

    def _key_for_kid(self, kid: Optional[str]) -> Any:
        """Return a public key OBJECT for `kid`, fetching/caching the JWKS on miss or expiry.
        PyJWT's decode() accepts the cryptography key object directly, so we cache the object
        and skip the brittle JWK->PEM round-trip. Raises OidcError if it can't be resolved."""
        cache_key = kid or "_default"
        with self._jwks_lock:
            now = time.monotonic()
            entry = self._jwks_cache.get(cache_key)
            if entry and now - entry["fetched_at"] < self.config.jwks_ttl_seconds:
                return entry["key"]

            try:
                from jwt import PyJWK  # type: ignore[attr-defined]
            except ImportError as e:
                raise OidcError(
                    "JWKS support requires 'pyjwt[crypto]' (pip install 'pyjwt[crypto]')"
                ) from e

            jwks = self._fetch_jwks()  # raises OidcError on fetch/parse failure
            self._jwks_full_fetch_at = now
            for jwk in jwks.get("keys", []):
                k = jwk.get("kid") or "_default"
                try:
                    self._jwks_cache[k] = {"key": PyJWK(jwk).key, "fetched_at": now}
                except Exception:
                    continue  # skip a malformed JWK; others may still resolve

            entry = self._jwks_cache.get(cache_key)
            if entry:
                return entry["key"]
            raise OidcError(f"no signing key found for kid={kid!r} in JWKS")

    def _resolve_signing_key(self, unverified_header: Dict[str, Any]) -> Any:
        if self.config.public_key_pem:
            return self.config.public_key_pem
        return self._key_for_kid(unverified_header.get("kid"))

    # --- public API --------------------------------------------------------------

    def verify(self, token: str) -> Dict[str, Any]:
        """Verify a JWT and return its claims, or raise OidcError."""
        try:
            import jwt  # PyJWT
        except ImportError as e:  # pragma: no cover
            raise OidcError("OIDC requires the 'pyjwt' package (pip install pyjwt)") from e
        if not self.config.public_key_pem and not self.config.jwks_url and not self.config.issuer:
            raise OidcError("no signing key configured (set public_key_pem, jwks_url, or issuer)")

        # Peek at the header to find the kid, then resolve the signing key.
        try:
            header = jwt.get_unverified_header(token)
        except Exception as e:
            raise OidcError(f"malformed token header: {e}") from e

        try:
            signing_key = self._resolve_signing_key(header)
        except OidcError:
            # If JWKS lookup failed because the kid wasn't cached, force a refresh and retry.
            # (Handles key rotation: the IdP added a new kid since our last fetch.)
            with self._jwks_lock:
                self._jwks_cache.clear()
                self._discovered_jwks_url = None
            signing_key = self._resolve_signing_key(header)

        try:
            return jwt.decode(
                token,
                signing_key,
                algorithms=list(self.config.algorithms),
                audience=self.config.audience,
                issuer=self.config.issuer,
            )
        except Exception as e:  # jwt.* exceptions
            raise OidcError(f"token verification failed: {e}") from e

    def role_of(self, claims: Dict[str, Any]) -> str:
        return claims.get(self.config.role_claim, self.config.default_role)

    def authenticate(self, authorization_header: Optional[str]) -> Tuple[Dict[str, Any], str]:
        """Verify an `Authorization: Bearer <jwt>` header; return (claims, role)."""
        if not authorization_header:
            raise OidcError("missing Authorization header")
        token = authorization_header
        if authorization_header.lower().startswith("bearer "):
            token = authorization_header.split(" ", 1)[1].strip()
        claims = self.verify(token)
        return claims, self.role_of(claims)

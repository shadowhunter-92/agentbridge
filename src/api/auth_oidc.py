"""
OIDC / JWT operator authentication — the modern "SSO" path for the control plane.

Instead of a single shared admin key, operators authenticate with a JWT issued by your
identity provider (Okta, Azure AD, Auth0, Keycloak, ...). The token's signature is verified
against the IdP's public key, and a role claim maps to an RBAC role (see src/governance/rbac.py).

Production: fetch the IdP's JWKS from `<issuer>/.well-known/openid-configuration` and select the
key by `kid`. For a simple/self-hosted setup, configure the IdP signing public key directly
(`public_key_pem`). Requires `pyjwt` (already a dev dep; add to runtime deps if you enable OIDC).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple


@dataclass
class OidcConfig:
    issuer: str
    audience: str
    public_key_pem: Optional[str] = None              # IdP signing public key (or JWKS in prod)
    algorithms: Sequence[str] = field(default_factory=lambda: ("RS256", "ES256", "EdDSA"))
    role_claim: str = "role"
    default_role: str = "viewer"


class OidcError(Exception):
    """Raised when a token is missing, malformed, expired, or fails verification."""


class OidcVerifier:
    def __init__(self, config: OidcConfig):
        self.config = config

    def verify(self, token: str) -> Dict[str, Any]:
        """Verify a JWT and return its claims, or raise OidcError."""
        try:
            import jwt  # PyJWT
        except ImportError as e:  # pragma: no cover
            raise OidcError("OIDC requires the 'pyjwt' package (pip install pyjwt)") from e
        if not self.config.public_key_pem:
            raise OidcError("no signing key configured (set OidcConfig.public_key_pem or JWKS)")
        try:
            return jwt.decode(
                token,
                self.config.public_key_pem,
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

"""OIDC ID-token verification for per-user API access.

The API receives the ID token from the trusted Streamlit server, not from the browser.
The token is validated against the configured issuer, audience and signing keys before
the subject is used to bind a session. This module deliberately stores no token.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient


class OIDCVerificationError(Exception):
    """Raised when an identity token is missing, expired or not trustworthy."""


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    key: str
    email: str | None = None


class OIDCVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str | None = None,
        algorithms: tuple[str, ...] = ("RS256",),
        hmac_secret: str | None = None,
        leeway_seconds: int = 30,
    ) -> None:
        if not issuer.strip() or not audience.strip():
            raise ValueError("OIDC issuer and audience are required")
        if hmac_secret:
            algorithms = ("HS256",)
        elif not jwks_url:
            raise ValueError("OIDC jwks_url is required for asymmetric tokens")
        self.issuer = issuer.strip()
        self.audience = audience.strip()
        self.algorithms = tuple(algorithms)
        self.leeway_seconds = max(0, int(leeway_seconds))
        self._hmac_secret = hmac_secret
        self._jwks = (
            PyJWKClient(jwks_url, cache_keys=True) if jwks_url and not hmac_secret else None
        )

    def verify(self, token: str) -> Identity:
        if not token or not token.strip():
            raise OIDCVerificationError("Identity token is empty")
        try:
            header = jwt.get_unverified_header(token)
            algorithm = str(header.get("alg", ""))
            if algorithm not in self.algorithms:
                raise OIDCVerificationError("Identity token algorithm is not allowed")
            if self._hmac_secret:
                key = self._hmac_secret
            elif self._jwks is not None:
                key = self._jwks.get_signing_key_from_jwt(token).key
            else:  # pragma: no cover - constructor prevents this state
                raise OIDCVerificationError("No identity signing key is configured")
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "aud", "iss", "sub"]},
            )
        except OIDCVerificationError:
            raise
        except Exception as exc:  # noqa: BLE001 - never expose token parsing details
            raise OIDCVerificationError("Identity token is invalid or expired") from exc

        issuer = str(claims.get("iss", ""))
        subject = str(claims.get("sub", ""))
        if not issuer or not subject:
            raise OIDCVerificationError("Identity token has no issuer or subject")
        return Identity(
            issuer=issuer,
            subject=subject,
            # Subject is only unique within an issuer; bind both to avoid collisions.
            key=f"{issuer}#{subject}"[:512],
            email=str(claims["email"]) if claims.get("email") else None,
        )

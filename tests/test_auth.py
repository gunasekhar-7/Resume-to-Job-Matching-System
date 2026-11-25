from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from talentlens.auth import OIDCVerificationError, OIDCVerifier

ISSUER = "https://identity.example.test"
AUDIENCE = "talentlens"
SECRET = "unit-test-identity-secret-32-bytes-minimum"


def _token(
    *,
    subject: str = "user-1",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: int = 300,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            "email": "user@example.test",
        },
        SECRET,
        algorithm="HS256",
    )


def _verifier() -> OIDCVerifier:
    return OIDCVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        hmac_secret=SECRET,
    )


def test_valid_oidc_token_returns_issuer_subject_and_email():
    identity = _verifier().verify(_token())
    assert identity.subject == "user-1"
    assert identity.issuer == ISSUER
    assert identity.key == f"{ISSUER}#user-1"
    assert identity.email == "user@example.test"


@pytest.mark.parametrize(
    "token",
    [
        _token(audience="another-app"),
        _token(issuer="https://other.example.test"),
        _token(expires_in=-120),
        "not-a-jwt",
    ],
)
def test_invalid_identity_tokens_are_rejected(token):
    with pytest.raises(OIDCVerificationError):
        _verifier().verify(token)


class _JWKSHandler(BaseHTTPRequestHandler):
    jwks: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/jwks":
            self.send_error(404)
            return
        payload = json.dumps(self.jwks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args) -> None:
        return


def test_rs256_token_is_verified_through_a_jwks_endpoint():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    handler = type("JWKSHandler", (_JWKSHandler,), {"jwks": {"keys": [public_jwk]}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        verifier = OIDCVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_url=f"http://127.0.0.1:{server.server_port}/jwks",
        )
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": "user-rsa",
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
        identity = verifier.verify(token)
        assert identity.key == f"{ISSUER}#user-rsa"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

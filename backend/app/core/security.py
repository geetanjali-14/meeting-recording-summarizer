import logging
import time
from typing import Any
from uuid import UUID

import httpx
from jose import JWTError, jwt  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class UserContext(BaseModel):
    """Authenticated user context extracted from verified JWT claims."""

    user_id: UUID
    email: str | None = None
    claims: dict[str, Any] = Field(default_factory=dict)


class SecurityError(Exception):
    """Base exception for security and authentication failures."""

    def __init__(self, message: str, code: str = "UNAUTHORIZED") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class JWKSKeyManager:
    """Manages JWKS retrieval, bounded TTL caching, and key rotation.

    Avoids unnecessary outbound network requests on every authentication check
    while supporting rotation and graceful cache refresh on unknown key IDs.
    """

    def __init__(self, jwks_url: str, cache_ttl_seconds: int = 300) -> None:
        self.jwks_url = jwks_url
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_keys: dict[str, dict[str, Any]] = {}
        self._last_fetched: float = 0.0

    async def get_key_for_kid(
        self, kid: str | None, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any] | None:
        """Retrieves matching JWK by key ID (kid), refreshing cache if expired or missing."""
        now = time.monotonic()
        is_expired = (now - self._last_fetched) >= self.cache_ttl_seconds

        # Refresh if cache expired or if key not found in currently cached keys
        if is_expired or (kid is not None and kid not in self._cached_keys):
            await self._refresh_keys(client=client)

        if kid is not None:
            return self._cached_keys.get(kid)

        # If kid is not specified in the token header, return key if exactly one key exists
        if len(self._cached_keys) == 1:
            return next(iter(self._cached_keys.values()))

        return None

    async def _refresh_keys(self, client: httpx.AsyncClient | None = None) -> None:
        """Fetches latest JWKS keyset from remote endpoint and updates bounded cache."""
        try:
            if client is not None:
                resp = await client.get(self.jwks_url, timeout=5.0)
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient() as default_client:
                    resp = await default_client.get(self.jwks_url, timeout=5.0)
                    resp.raise_for_status()
                    data = resp.json()

            keys = data.get("keys", [])
            new_cache: dict[str, dict[str, Any]] = {}
            for k in keys:
                k_id = k.get("kid")
                if k_id:
                    new_cache[k_id] = k
                else:
                    # Key without kid: index by string hash / id
                    new_cache[str(id(k))] = k

            self._cached_keys = new_cache
            self._last_fetched = time.monotonic()
            logger.debug(
                "Successfully refreshed JWKS cache",
                extra={"key_count": len(self._cached_keys)},
            )
        except Exception as exc:
            logger.warning(
                "Failed to refresh JWKS keys from endpoint",
                extra={"jwks_url": self.jwks_url, "error": str(exc)},
            )
            # Fail closed: do not assume unverified keys if refresh failed


_jwks_managers: dict[str, JWKSKeyManager] = {}


def get_jwks_manager(jwks_url: str, cache_ttl_seconds: int = 300) -> JWKSKeyManager:
    """Returns or creates a cached JWKSKeyManager instance for a given JWKS URL."""
    if jwks_url not in _jwks_managers:
        _jwks_managers[jwks_url] = JWKSKeyManager(
            jwks_url=jwks_url, cache_ttl_seconds=cache_ttl_seconds
        )
    return _jwks_managers[jwks_url]


async def verify_jwt_token(
    token: str,
    settings: Settings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> UserContext:
    """Verifies a Supabase Auth / OIDC JWT access token and returns UserContext.

    Validates:
      - Token format and signature using asymmetric key (JWKS/PEM) or HMAC secret
      - Allowed algorithms (disallowing 'none' or unconfigured algorithms)
      - Standard required claims: 'exp', 'iss', 'aud', 'sub'
      - Formats subject claim as a valid UUID

    Fails closed on any invalid, expired, malformed, or untrusted token.
    Never logs access tokens, secret keys, or sensitive token payloads.
    """
    if settings is None:
        settings = get_settings()

    if not token or not isinstance(token, str):
        raise SecurityError("Token is missing or empty")

    # 1. Parse header to check algorithm and kid
    try:
        header = jwt.get_unverified_headers(token)
    except JWTError as exc:
        raise SecurityError("Malformed token header") from exc

    alg = header.get("alg")
    if not alg or alg not in settings.JWT_ALGORITHMS:
        raise SecurityError(f"Unsupported or unauthorized algorithm: {alg}")

    kid = header.get("kid")

    # 2. Resolve verification key based on configuration
    key_config = settings.JWT_SIGNING_KEY_OR_JWKS

    verification_key: Any
    if key_config.startswith("http://") or key_config.startswith("https://"):
        manager = get_jwks_manager(
            jwks_url=key_config,
            cache_ttl_seconds=settings.JWKS_CACHE_TTL_SECONDS,
        )
        resolved_jwk = await manager.get_key_for_kid(kid=kid, client=http_client)
        if not resolved_jwk:
            raise SecurityError("Signing key could not be resolved from JWKS")
        verification_key = resolved_jwk
    else:
        # Static symmetric secret or static public PEM
        verification_key = key_config

    # 3. Decode and verify token signature and claims
    try:
        payload = jwt.decode(
            token,
            key=verification_key,
            algorithms=settings.JWT_ALGORITHMS,
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iat": True,
                "verify_exp": True,
                "verify_iss": True,
                "require_exp": True,
                "require_iat": False,
                "require_iss": True,
                "require_aud": True,
                "require_sub": True,
            },
        )
    except JWTError as exc:
        raise SecurityError(f"Token verification failed: {exc}") from exc

    # 4. Extract and validate user identity
    sub = payload.get("sub")
    if not sub:
        raise SecurityError("Token subject (sub) claim is missing or empty")

    try:
        user_uuid = UUID(str(sub))
    except (ValueError, TypeError) as exc:
        raise SecurityError("Token subject is not a valid UUID") from exc

    email = payload.get("email")

    return UserContext(
        user_id=user_uuid,
        email=str(email) if email else None,
        claims=payload,
    )

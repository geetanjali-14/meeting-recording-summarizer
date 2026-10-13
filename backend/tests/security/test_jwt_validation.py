import datetime
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from app.core.config import Settings
from app.core.security import SecurityError, verify_jwt_token


@pytest.fixture
def rsa_keypair() -> tuple[str, str, dict[str, str]]:
    """Generates an RSA keypair and matching JWK."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    jwk_dict = jwk.RSAKey(algorithm="RS256", key=public_pem).to_dict()
    jwk_dict["kid"] = "test-key-id-1"
    return private_pem, public_pem, jwk_dict


@pytest.mark.asyncio
async def test_verify_valid_hs256_token() -> None:
    secret = "test-symmetric-secret-key-at-least-32-chars-long"
    user_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "email": "user@example.com",
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")

    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS=secret,
    )

    user_context = await verify_jwt_token(token, settings=settings)
    assert user_context.user_id == user_id
    assert user_context.email == "user@example.com"
    assert user_context.claims["aud"] == "authenticated"


@pytest.mark.asyncio
async def test_verify_valid_rs256_token_with_jwks(
    rsa_keypair: tuple[str, str, dict[str, str]],
) -> None:
    private_pem, _, jwk_dict = rsa_keypair
    user_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "email": "rsa_user@example.com",
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-key-id-1"})

    jwks_url = "https://auth.example.com/.well-known/jwks.json"
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["RS256"],
        JWT_SIGNING_KEY_OR_JWKS=jwks_url,
    )

    # Mock HTTP client returning JWKS
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [jwk_dict]}))
    async with httpx.AsyncClient(transport=transport) as client:
        user_context = await verify_jwt_token(token, settings=settings, http_client=client)
        assert user_context.user_id == user_id
        assert user_context.email == "rsa_user@example.com"


@pytest.mark.asyncio
async def test_missing_or_empty_token() -> None:
    settings = Settings()
    with pytest.raises(SecurityError, match="Token is missing or empty"):
        await verify_jwt_token("", settings=settings)


@pytest.mark.asyncio
async def test_malformed_token() -> None:
    settings = Settings()
    with pytest.raises(SecurityError, match="Malformed token header"):
        await verify_jwt_token("not-a-token", settings=settings)


@pytest.mark.asyncio
async def test_expired_token() -> None:
    secret = "test-secret"
    user_id = uuid.uuid4()
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int(past.timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS=secret,
    )

    with pytest.raises(SecurityError, match="Token verification failed"):
        await verify_jwt_token(token, settings=settings)


@pytest.mark.asyncio
async def test_invalid_signature() -> None:
    user_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, "secret-one", algorithm="HS256")
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS="secret-two",
    )

    with pytest.raises(SecurityError, match="Token verification failed"):
        await verify_jwt_token(token, settings=settings)


@pytest.mark.asyncio
async def test_invalid_audience() -> None:
    secret = "test-secret"
    user_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "aud": "wrong-audience",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS=secret,
    )

    with pytest.raises(SecurityError, match="Token verification failed"):
        await verify_jwt_token(token, settings=settings)


@pytest.mark.asyncio
async def test_invalid_issuer() -> None:
    secret = "test-secret"
    user_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iss": "https://wrong-issuer.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS=secret,
    )

    with pytest.raises(SecurityError, match="Token verification failed"):
        await verify_jwt_token(token, settings=settings)


@pytest.mark.asyncio
async def test_missing_sub_or_non_uuid() -> None:
    secret = "test-secret"
    now = datetime.datetime.now(datetime.UTC)
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["HS256"],
        JWT_SIGNING_KEY_OR_JWKS=secret,
    )

    # Missing sub
    payload_no_sub = {
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token_no_sub = jwt.encode(payload_no_sub, secret, algorithm="HS256")
    with pytest.raises(SecurityError):
        await verify_jwt_token(token_no_sub, settings=settings)

    # Non-UUID sub
    payload_invalid_uuid = {
        "sub": "not-a-valid-uuid",
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token_invalid_uuid = jwt.encode(payload_invalid_uuid, secret, algorithm="HS256")
    with pytest.raises(SecurityError, match="Token subject is not a valid UUID"):
        await verify_jwt_token(token_invalid_uuid, settings=settings)


@pytest.mark.asyncio
async def test_rejects_none_algorithm() -> None:
    import base64

    settings = Settings(
        JWT_ALGORITHMS=["HS256", "RS256"],
    )
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(b'{"sub":"123"}').decode().rstrip("=")
    token = f"{header}.{payload}."

    with pytest.raises(SecurityError, match="Unsupported or unauthorized algorithm"):
        await verify_jwt_token(token, settings=settings)


@pytest.mark.asyncio
async def test_jwks_network_failure_fails_closed(
    rsa_keypair: tuple[str, str, dict[str, str]],
) -> None:
    private_pem, _, _ = rsa_keypair
    user_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iss": "https://auth.example.com",
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "missing-kid"})

    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["RS256"],
        JWT_SIGNING_KEY_OR_JWKS="https://auth.example.com/unreachable/jwks.json",
    )

    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="Internal Server Error")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SecurityError, match="Signing key could not be resolved from JWKS"):
            await verify_jwt_token(token, settings=settings, http_client=client)


@pytest.mark.asyncio
async def test_jwks_key_rotation_fetches_new_key(
    rsa_keypair: tuple[str, str, dict[str, str]],
) -> None:
    private_pem, _, jwk_dict_1 = rsa_keypair

    # Generate a second keypair for rotated key
    private_key_2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem_2 = private_key_2.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem_2 = (
        private_key_2.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    jwk_dict_2 = jwk.RSAKey(algorithm="RS256", key=public_pem_2).to_dict()
    jwk_dict_2["kid"] = "rotated-key-id-2"

    jwks_url = "https://auth.example.com/rotation/jwks.json"
    settings = Settings(
        JWT_ISSUER="https://auth.example.com",
        JWT_AUDIENCE="authenticated",
        JWT_ALGORITHMS=["RS256"],
        JWT_SIGNING_KEY_OR_JWKS=jwks_url,
        JWKS_CACHE_TTL_SECONDS=300,
    )

    # Initial state: only key 1 is published
    server_keys = [jwk_dict_1]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": server_keys})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # First request with key 1 succeeds and warms the cache
        user_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.UTC)
        token_1 = jwt.encode(
            {
                "sub": str(user_id),
                "aud": "authenticated",
                "iss": "https://auth.example.com",
                "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "test-key-id-1"},
        )
        ctx_1 = await verify_jwt_token(token_1, settings=settings, http_client=client)
        assert ctx_1.user_id == user_id

        # Server rotates keys: now key 2 is published
        server_keys = [jwk_dict_1, jwk_dict_2]

        # Token signed with new key 2 arrives
        user_id_2 = uuid.uuid4()
        token_2 = jwt.encode(
            {
                "sub": str(user_id_2),
                "aud": "authenticated",
                "iss": "https://auth.example.com",
                "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
            },
            private_pem_2,
            algorithm="RS256",
            headers={"kid": "rotated-key-id-2"},
        )

        # Manager should detect unknown kid and fetch rotated keyset
        ctx_2 = await verify_jwt_token(token_2, settings=settings, http_client=client)
        assert ctx_2.user_id == user_id_2

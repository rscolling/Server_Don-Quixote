"""Multi-backend authentication for BOB Voice.

The same `identify_user(headers)` interface is preserved so app.py doesn't
need to change. Under the hood, this module dispatches to one of four
backends based on the BOB_AUTH_BACKEND env var:

  - cloudflare    Cloudflare Zero Trust JWT validation (default — current behavior)
  - oidc          Generic OIDC bearer token via JWKS endpoint (Auth0, Okta, Keycloak, etc.)
  - shared_secret Simple bearer token from BOB_AUTH_SHARED_SECRET env var
  - none          Everyone is GUEST. Useful for dev / public deployments

Each backend resolves a request's identity to a UserIdentity (role, email,
name, user_id). The role logic and memory collection naming is shared
across backends — the difference is just how the token gets validated.

Adding a new backend:
1. Add a branch in `identify_user()` below
2. Implement an `_identify_via_<name>(headers)` function
3. Document it in LLM_PROVIDERS.md (or a new AUTH_PROVIDERS.md)
4. Test that the same UserIdentity comes out the other side
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum

import httpx
import jwt

logger = logging.getLogger("bob-voice.auth")


# ── Backend selection ──────────────────────────────────────────────────────

# Pick a backend with BOB_AUTH_BACKEND. Default is cloudflare for backward compat.
AUTH_BACKEND = os.getenv("BOB_AUTH_BACKEND", "cloudflare").lower().strip()

# ── Cloudflare Access config (used by cloudflare backend) ──────────────────
CF_TEAM_NAME = os.getenv("CF_TEAM_NAME", "")
CF_POLICY_AUD = os.getenv("CF_POLICY_AUD", "")
CF_CERTS_URL = (
    f"https://{CF_TEAM_NAME}.cloudflareaccess.com/cdn-cgi/access/certs"
    if CF_TEAM_NAME else ""
)

# ── Generic OIDC config (used by oidc backend) ─────────────────────────────
# Set BOB_AUTH_OIDC_JWKS_URL to your provider's JWKS endpoint, e.g.:
#   https://YOUR_TENANT.auth0.com/.well-known/jwks.json   (Auth0)
#   https://accounts.google.com/.well-known/jwks.json     (Google sign-in)
#   https://YOUR_KEYCLOAK/realms/<realm>/protocol/openid-connect/certs
OIDC_JWKS_URL = os.getenv("BOB_AUTH_OIDC_JWKS_URL", "")
OIDC_ISSUER = os.getenv("BOB_AUTH_OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("BOB_AUTH_OIDC_AUDIENCE", "")
OIDC_HEADER = os.getenv("BOB_AUTH_OIDC_HEADER", "authorization")  # Bearer <token>

# ── Shared secret config (used by shared_secret backend) ───────────────────
SHARED_SECRET = os.getenv("BOB_AUTH_SHARED_SECRET", "")
SHARED_SECRET_HEADER = os.getenv("BOB_AUTH_SHARED_SECRET_HEADER", "x-bob-auth")

# ── Common: who counts as Rob (full access) ────────────────────────────────
ROB_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ROB_EMAILS", "robert.colling@gmail.com").split(",")
    if email.strip()
}


# ── Identity types ─────────────────────────────────────────────────────────

class UserRole(Enum):
    ROB = "rob"           # Full access, "Yes Boss" mode
    MEMBER = "member"     # Authenticated user, own memory silo
    GUEST = "guest"       # No auth, no memory, limited


@dataclass
class UserIdentity:
    role: UserRole
    email: str | None = None
    name: str | None = None
    user_id: str | None = None
    backend: str = "none"  # which auth backend produced this identity

    @property
    def memory_collection(self) -> str | None:
        """ChromaDB collection name for this user's voice memory."""
        if self.role == UserRole.ROB:
            return "voice_conversations"
        if self.role == UserRole.MEMBER and self.email:
            safe = self.email.replace("@", "_at_").replace(".", "_")
            return f"voice_{safe}"
        return None  # Guests get no memory

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.email:
            return self.email.split("@")[0]
        return "Guest"

    @property
    def is_rob(self) -> bool:
        return self.role == UserRole.ROB


GUEST = UserIdentity(role=UserRole.GUEST, backend=AUTH_BACKEND)


def _role_for_email(email: str) -> UserRole:
    """Apply the ROB_EMAILS allowlist to determine the role."""
    return UserRole.ROB if email.lower() in ROB_EMAILS else UserRole.MEMBER


# ── Public dispatch ────────────────────────────────────────────────────────

async def identify_user(headers: dict) -> UserIdentity:
    """Resolve a request's headers to a UserIdentity.

    Backend is chosen by BOB_AUTH_BACKEND env var. Failures fall back to
    GUEST — never to a higher-privilege role.
    """
    if AUTH_BACKEND == "none":
        return GUEST
    if AUTH_BACKEND == "cloudflare":
        return await _identify_via_cloudflare(headers)
    if AUTH_BACKEND == "oidc":
        return await _identify_via_oidc(headers)
    if AUTH_BACKEND == "shared_secret":
        return _identify_via_shared_secret(headers)

    logger.error(
        f"Unknown BOB_AUTH_BACKEND='{AUTH_BACKEND}'. "
        f"Supported: cloudflare, oidc, shared_secret, none. Falling back to GUEST."
    )
    return GUEST


# ── Backend 1: Cloudflare Zero Trust ───────────────────────────────────────

_cf_public_keys: list[dict] | None = None


async def _fetch_cf_public_keys() -> list[dict]:
    """Fetch Cloudflare Access public keys (JWKS). Cached after first call."""
    global _cf_public_keys
    if _cf_public_keys is not None:
        return _cf_public_keys
    if not CF_CERTS_URL:
        logger.warning("CF_TEAM_NAME not set — JWT validation disabled")
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(CF_CERTS_URL)
            resp.raise_for_status()
            data = resp.json()
            _cf_public_keys = data.get("keys", [])
            logger.info(f"Loaded {len(_cf_public_keys)} CF Access public keys")
            return _cf_public_keys
    except Exception as e:
        logger.error(f"Failed to fetch CF Access certs: {e}")
        return []


def clear_key_cache():
    """Clear cached CF keys — call if validation fails due to key rotation."""
    global _cf_public_keys
    _cf_public_keys = None


async def _identify_via_cloudflare(headers: dict) -> UserIdentity:
    """Validate a Cloudflare Access JWT and extract identity."""
    token = headers.get("cf-access-jwt-assertion") or headers.get("Cf-Access-Jwt-Assertion")
    if not token:
        return GUEST

    if not CF_TEAM_NAME:
        logger.error(
            "CF_TEAM_NAME not set — cannot validate Cloudflare JWT. "
            "All users treated as GUEST until configured."
        )
        return GUEST

    try:
        public_keys = await _fetch_cf_public_keys()
        if not public_keys:
            return GUEST

        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        matching_key = next((k for k in public_keys if k.get("kid") == kid), None)
        if not matching_key:
            clear_key_cache()
            public_keys = await _fetch_cf_public_keys()
            matching_key = next((k for k in public_keys if k.get("kid") == kid), None)
        if not matching_key:
            logger.warning(f"No matching CF key for kid={kid}")
            return GUEST

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)
        payload = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=CF_POLICY_AUD,
            issuer=f"https://{CF_TEAM_NAME}.cloudflareaccess.com",
        )

        email = (payload.get("email") or "").lower()
        identity = UserIdentity(
            role=_role_for_email(email),
            email=email,
            name=payload.get("name"),
            user_id=payload.get("sub"),
            backend="cloudflare",
        )
        logger.info(f"[cloudflare] {email} → {identity.role.value}")
        return identity

    except jwt.ExpiredSignatureError:
        logger.warning("CF JWT expired")
    except jwt.InvalidAudienceError:
        logger.warning("CF JWT audience mismatch")
    except Exception as e:
        logger.warning(f"CF JWT validation failed: {e}")
    return GUEST


# ── Backend 2: Generic OIDC ────────────────────────────────────────────────

_oidc_public_keys: list[dict] | None = None


async def _fetch_oidc_jwks() -> list[dict]:
    """Fetch the OIDC provider's JWKS. Cached after first call."""
    global _oidc_public_keys
    if _oidc_public_keys is not None:
        return _oidc_public_keys
    if not OIDC_JWKS_URL:
        logger.warning("BOB_AUTH_OIDC_JWKS_URL not set — OIDC backend disabled")
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OIDC_JWKS_URL)
            resp.raise_for_status()
            data = resp.json()
            _oidc_public_keys = data.get("keys", [])
            logger.info(f"Loaded {len(_oidc_public_keys)} OIDC public keys")
            return _oidc_public_keys
    except Exception as e:
        logger.error(f"Failed to fetch OIDC JWKS: {e}")
        return []


def _extract_bearer_token(headers: dict, header_name: str) -> str | None:
    """Pull a bearer token from a header. Accepts 'Bearer <token>' or raw token."""
    value = headers.get(header_name) or headers.get(header_name.lower()) or headers.get(header_name.title())
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value.strip()


async def _identify_via_oidc(headers: dict) -> UserIdentity:
    """Validate a generic OIDC bearer token against any provider's JWKS."""
    token = _extract_bearer_token(headers, OIDC_HEADER)
    if not token:
        return GUEST

    if not OIDC_JWKS_URL:
        logger.error("BOB_AUTH_OIDC_JWKS_URL not set — cannot validate OIDC token")
        return GUEST

    try:
        public_keys = await _fetch_oidc_jwks()
        if not public_keys:
            return GUEST

        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        matching_key = next((k for k in public_keys if k.get("kid") == kid), None)
        if not matching_key:
            # Try refreshing the cache once for key rotation
            global _oidc_public_keys
            _oidc_public_keys = None
            public_keys = await _fetch_oidc_jwks()
            matching_key = next((k for k in public_keys if k.get("kid") == kid), None)
        if not matching_key:
            logger.warning(f"No matching OIDC key for kid={kid}")
            return GUEST

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)
        decode_kwargs = {
            "key": public_key,
            "algorithms": ["RS256"],
        }
        if OIDC_AUDIENCE:
            decode_kwargs["audience"] = OIDC_AUDIENCE
        if OIDC_ISSUER:
            decode_kwargs["issuer"] = OIDC_ISSUER
        payload = jwt.decode(token, **decode_kwargs)

        email = (payload.get("email") or "").lower()
        identity = UserIdentity(
            role=_role_for_email(email),
            email=email,
            name=payload.get("name") or payload.get("preferred_username"),
            user_id=payload.get("sub"),
            backend="oidc",
        )
        logger.info(f"[oidc] {email} → {identity.role.value}")
        return identity

    except jwt.ExpiredSignatureError:
        logger.warning("OIDC token expired")
    except jwt.InvalidAudienceError:
        logger.warning("OIDC token audience mismatch")
    except Exception as e:
        logger.warning(f"OIDC token validation failed: {e}")
    return GUEST


# ── Backend 3: Shared secret ───────────────────────────────────────────────

def _identify_via_shared_secret(headers: dict) -> UserIdentity:
    """Validate a static bearer token. Useful for self-hosted setups with no IdP.

    The shared secret model has no per-user identity by default — anyone
    presenting the secret is treated as ROB. To support multiple users,
    set BOB_AUTH_SHARED_SECRET to a JSON map: {"secret1": "alice@example.com",
    "secret2": "bob@example.com"}. Each secret then maps to its email.
    """
    if not SHARED_SECRET:
        logger.error("BOB_AUTH_SHARED_SECRET not set — shared_secret backend disabled")
        return GUEST

    token = _extract_bearer_token(headers, SHARED_SECRET_HEADER)
    if not token:
        return GUEST

    # Single-secret mode (default): the secret is a literal string
    if SHARED_SECRET == token:
        # No per-user info — treat the bearer as Rob since they presented the master key
        identity = UserIdentity(
            role=UserRole.ROB,
            email=next(iter(ROB_EMAILS), "rob"),
            name="Rob (shared secret)",
            user_id="shared-secret-bearer",
            backend="shared_secret",
        )
        logger.info("[shared_secret] master token accepted")
        return identity

    # Multi-secret mode: check if SHARED_SECRET is a JSON map
    try:
        import json
        token_map = json.loads(SHARED_SECRET)
        if isinstance(token_map, dict) and token in token_map:
            email = (token_map[token] or "").lower()
            identity = UserIdentity(
                role=_role_for_email(email),
                email=email,
                name=email.split("@")[0] if email else "Anonymous",
                user_id=f"shared-secret-{token[:8]}",
                backend="shared_secret",
            )
            logger.info(f"[shared_secret] {email} → {identity.role.value}")
            return identity
    except (ValueError, TypeError):
        pass

    logger.warning("[shared_secret] invalid bearer token")
    return GUEST


# ── Diagnostics ────────────────────────────────────────────────────────────

def status() -> dict:
    """Return current auth config for /auth/status endpoint diagnostics."""
    return {
        "backend": AUTH_BACKEND,
        "rob_emails": list(ROB_EMAILS),
        "cloudflare_configured": bool(CF_TEAM_NAME and CF_POLICY_AUD),
        "oidc_configured": bool(OIDC_JWKS_URL),
        "shared_secret_configured": bool(SHARED_SECRET),
    }

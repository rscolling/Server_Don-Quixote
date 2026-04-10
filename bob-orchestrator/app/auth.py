"""Multi-backend authentication for BOB orchestrator (SaaS-ready).

Unified auth module that works for both internal (Rob) and external
(paying customers) use. The same `identify_user(request)` interface is
used everywhere — chat, dashboard, voice, MCP.

Backends (selected via BOB_AUTH_BACKEND env var):

  - cloudflare    Cloudflare Zero Trust JWT (default). Supports Google, GitHub,
                  Apple, Microsoft, email OTP — all configured in the CF dashboard,
                  zero code changes needed to add new identity providers.
  - oidc          Generic OIDC bearer token via JWKS (Auth0, Okta, Keycloak, etc.)
  - shared_secret Static bearer token (self-hosted setups with no IdP)
  - none          Everyone is GUEST. Dev / public demos only.

User roles:
  - admin    Rob. Full access, "Yes Boss" mode.
  - customer Paying subscriber. Own memory silo, usage-metered.
  - trial    Free trial user. Limited usage, no persistent memory.
  - guest    No auth. Read-only or demo access.

Adding an identity provider:
  You DON'T need to change this code. Configure the provider in your auth
  backend (Cloudflare Access dashboard, Auth0 tenant, etc.) and the JWT
  will arrive with the same claims. This module only cares about the JWT —
  not which button the user clicked to log in.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum

import httpx
import jwt

logger = logging.getLogger("bob.auth")


# ── Backend selection ──────────────────────────────────────────────────────

AUTH_BACKEND = os.getenv("BOB_AUTH_BACKEND", "cloudflare").lower().strip()

# ── Cloudflare Access config ──────────────────────────────────────────────
CF_TEAM_NAME = os.getenv("CF_TEAM_NAME", "")
CF_POLICY_AUD = os.getenv("CF_POLICY_AUD", "")
CF_CERTS_URL = (
    f"https://{CF_TEAM_NAME}.cloudflareaccess.com/cdn-cgi/access/certs"
    if CF_TEAM_NAME else ""
)

# ── Generic OIDC config ──────────────────────────────────────────────────
OIDC_JWKS_URL = os.getenv("BOB_AUTH_OIDC_JWKS_URL", "")
OIDC_ISSUER = os.getenv("BOB_AUTH_OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("BOB_AUTH_OIDC_AUDIENCE", "")
OIDC_HEADER = os.getenv("BOB_AUTH_OIDC_HEADER", "authorization")

# ── Shared secret config ─────────────────────────────────────────────────
SHARED_SECRET = os.getenv("BOB_AUTH_SHARED_SECRET", "")
SHARED_SECRET_HEADER = os.getenv("BOB_AUTH_SHARED_SECRET_HEADER", "x-bob-auth")

# ── Admin emails (full access) ───────────────────────────────────────────
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv(
        "BOB_ADMIN_EMAILS",
        "robert.colling@gmail.com,rob@appalachiantoysgames.com"
    ).split(",")
    if email.strip()
}


# ── Identity types ────────────────────────────────────────────────────────

class UserRole(Enum):
    ADMIN = "admin"         # Rob. Full access, all tools, "Yes Boss" mode.
    CUSTOMER = "customer"   # Paying subscriber. Own memory silo, metered usage.
    TRIAL = "trial"         # Free trial. Limited messages, no persistent memory.
    GUEST = "guest"         # No auth. Demo/read-only.


@dataclass
class UserIdentity:
    role: UserRole
    email: str | None = None
    name: str | None = None
    user_id: str | None = None
    backend: str = "none"
    provider: str | None = None   # "google", "github", "apple", "microsoft", "email"
    tier: str | None = None       # subscription tier for customers (future: "basic", "pro", "enterprise")

    @property
    def memory_collection(self) -> str | None:
        """ChromaDB collection name for this user's memory silo."""
        if self.role == UserRole.ADMIN:
            return "voice_conversations"
        if self.role in (UserRole.CUSTOMER, UserRole.TRIAL) and self.email:
            safe = self.email.replace("@", "_at_").replace(".", "_")
            return f"user_{safe}"
        return None  # Guests get no memory

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.email:
            return self.email.split("@")[0]
        return "Guest"

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_paying(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.CUSTOMER)

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "email": self.email,
            "name": self.display_name,
            "user_id": self.user_id,
            "backend": self.backend,
            "provider": self.provider,
            "tier": self.tier,
            "memory_collection": self.memory_collection,
        }


GUEST = UserIdentity(role=UserRole.GUEST, backend=AUTH_BACKEND)


def _role_for_email(email: str) -> UserRole:
    """Determine role from email. Admin allowlist checked first, then customer
    lookup. Default is TRIAL for authenticated users we don't recognize yet.

    TODO: When Stripe integration is live, check subscription status here
    to distinguish CUSTOMER from TRIAL.
    """
    if email.lower() in ADMIN_EMAILS:
        return UserRole.ADMIN
    # Future: query subscription DB / Stripe to check if email is a paying customer
    # For now, all authenticated non-admin users are CUSTOMER (early access).
    return UserRole.CUSTOMER


def _detect_provider(payload: dict) -> str | None:
    """Best-effort detection of which identity provider issued the JWT."""
    issuer = payload.get("iss", "")
    if "accounts.google.com" in issuer or "googleapis" in issuer:
        return "google"
    if "github" in issuer:
        return "github"
    if "apple" in issuer or "appleid" in issuer:
        return "apple"
    if "microsoftonline" in issuer or "login.microsoft" in issuer:
        return "microsoft"
    # Cloudflare Access wraps the original IdP — check identity provider info
    idp = payload.get("identity_provider", {})
    if isinstance(idp, dict):
        idp_type = idp.get("type", "").lower()
        if idp_type:
            return idp_type
    # Check amr (authentication methods) for email OTP
    amr = payload.get("amr", [])
    if "otp" in amr or "email" in amr:
        return "email"
    return None


# ── Public dispatch ───────────────────────────────────────────────────────

async def identify_user(request) -> UserIdentity:
    """Resolve a FastAPI Request to a UserIdentity.

    Backend is chosen by BOB_AUTH_BACKEND env var. Failures fall back to
    GUEST — never to a higher-privilege role.
    """
    headers = dict(request.headers) if hasattr(request, "headers") else request

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


# ── Backend 1: Cloudflare Zero Trust ─────────────────────────────────────

_cf_public_keys: list[dict] | None = None


async def _fetch_cf_public_keys() -> list[dict]:
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


def _clear_cf_key_cache():
    global _cf_public_keys
    _cf_public_keys = None


async def _identify_via_cloudflare(headers: dict) -> UserIdentity:
    """Validate Cloudflare Access JWT and extract identity.

    Supports all CF Access identity providers: Google, GitHub, Apple,
    Microsoft, email OTP, SAML, etc. The provider is detected from the
    JWT claims for logging/analytics.
    """
    token = headers.get("cf-access-jwt-assertion") or headers.get("Cf-Access-Jwt-Assertion")

    # Fallback: CF may pass email directly without JWT in some configurations
    if not token:
        email = (
            headers.get("cf-access-authenticated-user-email")
            or headers.get("Cf-Access-Authenticated-User-Email")
        )
        if email:
            role = _role_for_email(email)
            identity = UserIdentity(
                role=role,
                email=email.lower(),
                name=email.split("@")[0],
                backend="cloudflare",
            )
            logger.info(f"[cloudflare/header] {email} → {identity.role.value}")
            return identity
        return GUEST

    if not CF_TEAM_NAME:
        logger.error("CF_TEAM_NAME not set — cannot validate JWT")
        return GUEST

    try:
        public_keys = await _fetch_cf_public_keys()
        if not public_keys:
            return GUEST

        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        matching_key = next((k for k in public_keys if k.get("kid") == kid), None)
        if not matching_key:
            _clear_cf_key_cache()
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
        provider = _detect_provider(payload)
        identity = UserIdentity(
            role=_role_for_email(email),
            email=email,
            name=payload.get("name") or email.split("@")[0],
            user_id=payload.get("sub"),
            backend="cloudflare",
            provider=provider,
        )
        logger.info(f"[cloudflare/{provider or 'unknown'}] {email} → {identity.role.value}")
        return identity

    except jwt.ExpiredSignatureError:
        logger.warning("CF JWT expired")
    except jwt.InvalidAudienceError:
        logger.warning("CF JWT audience mismatch")
    except Exception as e:
        logger.warning(f"CF JWT validation failed: {e}")
    return GUEST


# ── Backend 2: Generic OIDC ──────────────────────────────────────────────

_oidc_public_keys: list[dict] | None = None


async def _fetch_oidc_jwks() -> list[dict]:
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
    value = headers.get(header_name) or headers.get(header_name.lower()) or headers.get(header_name.title())
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value.strip()


async def _identify_via_oidc(headers: dict) -> UserIdentity:
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
            global _oidc_public_keys
            _oidc_public_keys = None
            public_keys = await _fetch_oidc_jwks()
            matching_key = next((k for k in public_keys if k.get("kid") == kid), None)
        if not matching_key:
            logger.warning(f"No matching OIDC key for kid={kid}")
            return GUEST

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)
        decode_kwargs = {"key": public_key, "algorithms": ["RS256"]}
        if OIDC_AUDIENCE:
            decode_kwargs["audience"] = OIDC_AUDIENCE
        if OIDC_ISSUER:
            decode_kwargs["issuer"] = OIDC_ISSUER
        payload = jwt.decode(token, **decode_kwargs)

        email = (payload.get("email") or "").lower()
        provider = _detect_provider(payload)
        identity = UserIdentity(
            role=_role_for_email(email),
            email=email,
            name=payload.get("name") or payload.get("preferred_username"),
            user_id=payload.get("sub"),
            backend="oidc",
            provider=provider,
        )
        logger.info(f"[oidc/{provider or 'unknown'}] {email} → {identity.role.value}")
        return identity

    except jwt.ExpiredSignatureError:
        logger.warning("OIDC token expired")
    except jwt.InvalidAudienceError:
        logger.warning("OIDC token audience mismatch")
    except Exception as e:
        logger.warning(f"OIDC token validation failed: {e}")
    return GUEST


# ── Backend 3: Shared secret ─────────────────────────────────────────────

def _identify_via_shared_secret(headers: dict) -> UserIdentity:
    if not SHARED_SECRET:
        logger.error("BOB_AUTH_SHARED_SECRET not set — backend disabled")
        return GUEST

    token = _extract_bearer_token(headers, SHARED_SECRET_HEADER)
    if not token:
        return GUEST

    # Single-secret mode: master key = admin
    if SHARED_SECRET == token:
        identity = UserIdentity(
            role=UserRole.ADMIN,
            email=next(iter(ADMIN_EMAILS), "admin"),
            name="Admin (shared secret)",
            user_id="shared-secret-bearer",
            backend="shared_secret",
        )
        logger.info("[shared_secret] master token accepted")
        return identity

    # Multi-secret mode: JSON map of token → email
    try:
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


# ── Diagnostics ──────────────────────────────────────────────────────────

def status() -> dict:
    """Auth status for /auth/status endpoint."""
    return {
        "backend": AUTH_BACKEND,
        "admin_emails": list(ADMIN_EMAILS),
        "cloudflare_configured": bool(CF_TEAM_NAME and CF_POLICY_AUD),
        "oidc_configured": bool(OIDC_JWKS_URL),
        "shared_secret_configured": bool(SHARED_SECRET),
        "supported_providers": [
            "google", "github", "apple", "microsoft", "email_otp", "saml"
        ],
    }

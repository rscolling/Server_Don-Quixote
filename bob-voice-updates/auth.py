"""Cloudflare Zero Trust JWT authentication for BOB Voice.

Extracts user identity from the Cf-Access-Jwt-Assertion header.
Rob gets full "Yes Boss" mode. Other authenticated users get friendly
mode with their own memory silo. No header = guest.
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum

import httpx
import jwt

logger = logging.getLogger("bob-voice.auth")

# Cloudflare Access config
CF_TEAM_NAME = os.getenv("CF_TEAM_NAME", "")  # e.g. "atg" for atg.cloudflareaccess.com
CF_POLICY_AUD = os.getenv("CF_POLICY_AUD", "")  # Application audience tag from CF dashboard
CF_CERTS_URL = f"https://{CF_TEAM_NAME}.cloudflareaccess.com/cdn-cgi/access/certs" if CF_TEAM_NAME else ""

# Rob's emails — full access "Yes Boss" mode
ROB_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ROB_EMAILS", "robert.colling@gmail.com").split(",")
    if email.strip()
}

# Cache for CF public keys
_cf_public_keys: list[dict] | None = None


class UserRole(Enum):
    ROB = "rob"           # Full access, "Yes Boss" mode
    MEMBER = "member"     # Authenticated user, own memory silo
    GUEST = "guest"       # No auth, no memory, limited


@dataclass
class UserIdentity:
    role: UserRole
    email: str | None = None
    name: str | None = None
    user_id: str | None = None  # CF sub claim

    @property
    def memory_collection(self) -> str | None:
        """ChromaDB collection name for this user's voice memory."""
        if self.role == UserRole.ROB:
            return "voice_conversations"  # Rob uses the existing collection
        if self.role == UserRole.MEMBER and self.email:
            # Sanitize email for collection name
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


GUEST = UserIdentity(role=UserRole.GUEST)


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
    """Clear cached keys — call if validation fails due to key rotation."""
    global _cf_public_keys
    _cf_public_keys = None


async def identify_user(headers: dict) -> UserIdentity:
    """Extract user identity from Cloudflare Access JWT.

    Args:
        headers: Request/WebSocket headers dict

    Returns:
        UserIdentity with role, email, and memory collection
    """
    token = headers.get("cf-access-jwt-assertion") or headers.get("Cf-Access-Jwt-Assertion")

    if not token:
        return GUEST

    # If CF_TEAM_NAME not configured, try to decode without validation (dev mode)
    if not CF_TEAM_NAME:
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            email = payload.get("email", "").lower()
            role = UserRole.ROB if email in ROB_EMAILS else UserRole.MEMBER
            return UserIdentity(
                role=role,
                email=email,
                name=payload.get("name"),
                user_id=payload.get("sub"),
            )
        except Exception as e:
            logger.warning(f"JWT decode failed (no validation): {e}")
            return GUEST

    # Full validation with CF public keys
    try:
        public_keys = await _fetch_cf_public_keys()
        if not public_keys:
            return GUEST

        # Get the key ID from the token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find matching key
        matching_key = None
        for key in public_keys:
            if key.get("kid") == kid:
                matching_key = key
                break

        if not matching_key:
            # Key rotated — clear cache and retry once
            clear_key_cache()
            public_keys = await _fetch_cf_public_keys()
            for key in public_keys:
                if key.get("kid") == kid:
                    matching_key = key
                    break

        if not matching_key:
            logger.warning(f"No matching CF key for kid={kid}")
            return GUEST

        # Verify and decode
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(matching_key)

        payload = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=CF_POLICY_AUD,
            issuer=f"https://{CF_TEAM_NAME}.cloudflareaccess.com",
        )

        email = payload.get("email", "").lower()
        role = UserRole.ROB if email in ROB_EMAILS else UserRole.MEMBER

        logger.info(f"Authenticated: {email} → {role.value}")
        return UserIdentity(
            role=role,
            email=email,
            name=payload.get("name"),
            user_id=payload.get("sub"),
        )

    except jwt.ExpiredSignatureError:
        logger.warning("CF JWT expired")
        return GUEST
    except jwt.InvalidAudienceError:
        logger.warning("CF JWT audience mismatch")
        return GUEST
    except Exception as e:
        logger.warning(f"CF JWT validation failed: {e}")
        return GUEST

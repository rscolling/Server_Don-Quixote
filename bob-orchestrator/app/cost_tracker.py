"""Cost tracking and budget guards for BOB.

Tracks token usage and estimated cost per:
- LLM provider
- Model
- User identity (Rob, member, guest, system)
- Tool / agent (when known)

Persists to SQLite so usage survives restarts. Enforces hard-stop budgets
that abort BOB's response if a user or the total day exceeds the cap.

Why it matters: a malicious authenticated user can drain Rob's API budget
by sending expensive prompts. The rate limiter slows this but doesn't stop
it. Budget guards stop it. Per the SECURITY.md known limitations:
"Cost-based DoS is possible. The rate limiter slows but does not stop this.
Cost-based defenses are on the roadmap." This is that defense.

Pricing is approximate and updated when providers change rates. Costs are
estimates, not invoices — always check the actual provider dashboard for
authoritative numbers.
"""

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("bob.cost_tracker")


# ── Approximate pricing (USD per million tokens) ────────────────────────────
# Update when providers change rates. Source for each:
#   - Anthropic: https://www.anthropic.com/pricing
#   - OpenAI: https://openai.com/api/pricing/
#   - Ollama: free (compute cost only — not tracked here)

PRICING_USD_PER_MILLION_TOKENS = {
    # Anthropic Claude (input / output)
    "claude-opus-4-6":     (15.00, 75.00),
    "claude-sonnet-4-5":   (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-5":    (0.80, 4.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),

    # OpenAI GPT
    "gpt-4o":              (2.50, 10.00),
    "gpt-4o-mini":         (0.15, 0.60),
    "gpt-4-turbo":         (10.00, 30.00),
    "gpt-4":               (30.00, 60.00),

    # Ollama / local — no API cost
    "qwen2.5:14b":         (0.00, 0.00),
    "qwen2.5:32b":         (0.00, 0.00),
    "qwen2.5:72b":         (0.00, 0.00),
    "llama3.3:70b":        (0.00, 0.00),
}

DEFAULT_PRICING = (5.00, 15.00)  # Conservative fallback for unknown models


# ── Configuration (env vars) ────────────────────────────────────────────────

COST_DB_PATH = os.getenv(
    "COST_DB_PATH",
    os.getenv("BOB_DATA_DIR", "/app/data") + "/cost-tracker.db",
)

# Hard-stop budgets (USD). Set to 0 to disable a particular guard.
DAILY_BUDGET_USD_TOTAL = float(os.getenv("DAILY_BUDGET_USD_TOTAL", "10.00"))
DAILY_BUDGET_USD_PER_USER = float(os.getenv("DAILY_BUDGET_USD_PER_USER", "2.00"))
MONTHLY_BUDGET_USD_TOTAL = float(os.getenv("MONTHLY_BUDGET_USD_TOTAL", "200.00"))

# Vision is billed against a tighter per-user cap to prevent a chatty
# member from draining the API budget through photo uploads. Rob bypasses.
DAILY_BUDGET_USD_PER_USER_VISION = float(os.getenv("DAILY_BUDGET_USD_PER_USER_VISION", "0.50"))

# Rob bypasses per-user limits (his identity is read from BOB_LLM env vars
# and the voice service auth — same email pattern as the firewall)
BUDGET_BYPASS_USERS = {
    u.strip().lower()
    for u in os.getenv("BUDGET_BYPASS_USERS", "rob,robert.colling@gmail.com").split(",")
    if u.strip()
}


# ── Database setup ──────────────────────────────────────────────────────────

def _init_db():
    """Create the cost-tracking table if it doesn't exist."""
    Path(COST_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(COST_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            date TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            user TEXT DEFAULT 'system',
            tool TEXT DEFAULT '',
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_date ON usage(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_user ON usage(user)")
    conn.commit()
    conn.close()


@contextmanager
def _db():
    """Context manager for short-lived SQLite connections."""
    _init_db()
    conn = sqlite3.connect(COST_DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Cost calculation ────────────────────────────────────────────────────────

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of an LLM call.

    Returns a float (e.g., 0.0123 = 1.23 cents). Uses approximate pricing —
    real cost may differ slightly based on provider promotions, batch
    discounts, and rate changes.
    """
    input_rate, output_rate = PRICING_USD_PER_MILLION_TOKENS.get(model, DEFAULT_PRICING)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


# ── Recording usage ─────────────────────────────────────────────────────────

def record_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    user: str = "system",
    tool: str = "",
) -> dict:
    """Record an LLM call's usage and return the cost details.

    Returns:
        dict with provider, model, tokens, cost_usd, plus a budget_status
        showing how close the user is to their daily/monthly cap.
    """
    cost = estimate_cost(model, input_tokens, output_tokens)
    now = time.time()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO usage (ts, date, provider, model, user, tool, "
                "input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, today, provider, model, user.lower(), tool,
                 input_tokens, output_tokens, cost),
            )
    except Exception as e:
        logger.error(f"Failed to record usage: {e}")

    return {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "user": user,
    }


# ── Budget queries ──────────────────────────────────────────────────────────

def get_daily_spend(user: str | None = None) -> float:
    """Total spend in USD for today. If user is given, scoped to that user."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _db() as conn:
            if user:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE date = ? AND user = ?",
                    (today, user.lower()),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE date = ?",
                    (today,),
                ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error(f"Failed to query daily spend: {e}")
        return 0.0


def get_daily_spend_by_model_prefix(prefix: str) -> float:
    """Total spend today for models whose name starts with `prefix` (e.g. 'claude-opus')."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE date = ? AND model LIKE ?",
                (today, f"{prefix}%"),
            ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error(f"Failed to query daily spend by prefix {prefix!r}: {e}")
        return 0.0


def check_opus_budget() -> dict:
    """Check today's Opus spend against DAILY_BUDGET_USD_OPUS.

    Returns:
        {allowed, reason, daily_spend, daily_budget, fraction, alert_threshold_hit}

    `alert_threshold_hit` is True when spend has crossed OPUS_BUDGET_ALERT_FRACTION
    of the cap — caller is responsible for ntfy'ing (once per day ideally).
    """
    from app.config import DAILY_BUDGET_USD_OPUS, OPUS_BUDGET_ALERT_FRACTION

    spend = get_daily_spend_by_model_prefix("claude-opus")
    cap = DAILY_BUDGET_USD_OPUS
    fraction = (spend / cap) if cap > 0 else 0.0
    allowed = cap <= 0 or spend < cap

    return {
        "allowed": allowed,
        "reason": (
            "" if allowed else
            f"Daily Opus budget exceeded: ${spend:.4f} >= ${cap}. Resets at UTC midnight."
        ),
        "daily_spend": round(spend, 4),
        "daily_budget": cap,
        "fraction": round(fraction, 3),
        "alert_threshold_hit": cap > 0 and fraction >= OPUS_BUDGET_ALERT_FRACTION,
    }


def get_monthly_spend() -> float:
    """Total spend in USD for the current calendar month."""
    month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE date LIKE ?",
                (f"{month_prefix}-%",),
            ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error(f"Failed to query monthly spend: {e}")
        return 0.0


def get_breakdown(days: int = 7) -> dict:
    """Spend breakdown for the last N days, by user and by model."""
    try:
        with _db() as conn:
            cutoff = time.time() - (days * 86400)
            by_user = conn.execute(
                "SELECT user, COALESCE(SUM(cost_usd), 0), COUNT(*) "
                "FROM usage WHERE ts >= ? GROUP BY user ORDER BY 2 DESC",
                (cutoff,),
            ).fetchall()
            by_model = conn.execute(
                "SELECT model, COALESCE(SUM(cost_usd), 0), COUNT(*) "
                "FROM usage WHERE ts >= ? GROUP BY model ORDER BY 2 DESC",
                (cutoff,),
            ).fetchall()
            return {
                "days": days,
                "by_user": [
                    {"user": u, "cost_usd": round(c, 4), "calls": n}
                    for u, c, n in by_user
                ],
                "by_model": [
                    {"model": m, "cost_usd": round(c, 4), "calls": n}
                    for m, c, n in by_model
                ],
            }
    except Exception as e:
        logger.error(f"Failed to query breakdown: {e}")
        return {"error": str(e)}


# ── Budget enforcement ──────────────────────────────────────────────────────

def check_budget(user: str = "system") -> dict:
    """Check if a user (or the system as a whole) is within budget.

    Returns a dict with:
        - allowed: bool — False means the request should be aborted
        - reason: str — explanation if not allowed
        - daily_spend, monthly_spend, daily_user_spend
        - daily_budget, monthly_budget, daily_user_budget
    """
    user_lower = user.lower()
    bypass = user_lower in BUDGET_BYPASS_USERS

    daily_total = get_daily_spend()
    monthly_total = get_monthly_spend()
    daily_user = get_daily_spend(user_lower) if not bypass else 0.0

    result = {
        "allowed": True,
        "reason": "",
        "user": user,
        "bypass": bypass,
        "daily_spend": round(daily_total, 4),
        "monthly_spend": round(monthly_total, 4),
        "daily_user_spend": round(daily_user, 4),
        "daily_budget": DAILY_BUDGET_USD_TOTAL,
        "monthly_budget": MONTHLY_BUDGET_USD_TOTAL,
        "daily_user_budget": DAILY_BUDGET_USD_PER_USER,
    }

    # Check the global daily budget (everyone, including Rob, hits this)
    if DAILY_BUDGET_USD_TOTAL > 0 and daily_total >= DAILY_BUDGET_USD_TOTAL:
        result["allowed"] = False
        result["reason"] = (
            f"Daily total budget exceeded: ${daily_total:.4f} >= ${DAILY_BUDGET_USD_TOTAL}. "
            f"Resets at UTC midnight."
        )
        logger.error(result["reason"])
        return result

    # Check the monthly budget
    if MONTHLY_BUDGET_USD_TOTAL > 0 and monthly_total >= MONTHLY_BUDGET_USD_TOTAL:
        result["allowed"] = False
        result["reason"] = (
            f"Monthly budget exceeded: ${monthly_total:.4f} >= ${MONTHLY_BUDGET_USD_TOTAL}. "
            f"Resets on the 1st."
        )
        logger.error(result["reason"])
        return result

    # Check the per-user daily budget (Rob bypasses this)
    if not bypass and DAILY_BUDGET_USD_PER_USER > 0 and daily_user >= DAILY_BUDGET_USD_PER_USER:
        result["allowed"] = False
        result["reason"] = (
            f"Per-user daily budget exceeded for '{user}': "
            f"${daily_user:.4f} >= ${DAILY_BUDGET_USD_PER_USER}. Resets at UTC midnight."
        )
        logger.warning(result["reason"])
        return result

    return result


def get_daily_vision_spend(user: str) -> float:
    """Total spend in USD for vision tools today, scoped to a user."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM usage "
                "WHERE date = ? AND user = ? AND tool LIKE 'photo_%'",
                (today, user.lower()),
            ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error(f"Failed to query daily vision spend: {e}")
        return 0.0


def check_vision_budget(user: str = "system") -> dict:
    """Check the vision-specific per-user daily cap. Rob bypasses."""
    user_lower = user.lower()
    bypass = user_lower in BUDGET_BYPASS_USERS
    spend = get_daily_vision_spend(user_lower) if not bypass else 0.0

    result = {
        "allowed": True,
        "reason": "",
        "user": user,
        "bypass": bypass,
        "daily_vision_spend": round(spend, 4),
        "daily_vision_budget": DAILY_BUDGET_USD_PER_USER_VISION,
    }

    if not bypass and DAILY_BUDGET_USD_PER_USER_VISION > 0 and spend >= DAILY_BUDGET_USD_PER_USER_VISION:
        result["allowed"] = False
        result["reason"] = (
            f"Per-user daily vision budget exceeded for '{user}': "
            f"${spend:.4f} >= ${DAILY_BUDGET_USD_PER_USER_VISION}. Resets at UTC midnight."
        )
        logger.warning(result["reason"])
    return result


# ── Public summary for /health and dashboard ────────────────────────────────

def status_summary() -> dict:
    """Return a compact status summary suitable for inclusion in /health."""
    return {
        "daily_spend_usd": round(get_daily_spend(), 4),
        "monthly_spend_usd": round(get_monthly_spend(), 4),
        "daily_budget_usd": DAILY_BUDGET_USD_TOTAL,
        "monthly_budget_usd": MONTHLY_BUDGET_USD_TOTAL,
        "daily_remaining_usd": round(
            max(0, DAILY_BUDGET_USD_TOTAL - get_daily_spend()), 4
        ),
        "monthly_remaining_usd": round(
            max(0, MONTHLY_BUDGET_USD_TOTAL - get_monthly_spend()), 4
        ),
    }

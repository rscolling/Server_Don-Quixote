# Security Policy

BOB is built around the assumption that **production-grade security applies even when you're solo**. The architecture has explicit defenses (firewall, audit log, circuit breakers, multi-user auth, rate limiting), but no security is perfect. If you find a vulnerability, please report it responsibly.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: `security@appalachiantoysgames.com`

Include:

1. **A description of the issue.** What's the vulnerability, what's the impact, what's the attack scenario.
2. **A minimal reproduction.** Steps to trigger it, code snippets, sample inputs. The more concrete, the faster the fix.
3. **Your assessment of severity.** Critical / High / Medium / Low and why.
4. **Any suggested mitigation.** Optional but appreciated.
5. **Your name and how you'd like to be credited.** Or "anonymous" if you prefer.

If the issue involves a third-party dependency (LangGraph, ChromaDB, langchain-mcp-adapters, etc.), please report it both to me and to the upstream project.

---

## Response Timeline

This is a one-person project. Realistic response times:

- **Acknowledgment:** Within 72 hours.
- **Triage and severity assessment:** Within 1 week.
- **Fix in `main`:** Depends on severity. Critical: within 1 week. High: within 2 weeks. Medium: within 4 weeks. Low: when I get to it.
- **Public disclosure:** After the fix ships and most users have had a chance to update. Coordinated with the reporter.

If the vulnerability is being actively exploited in the wild, ship the fix first, disclose later. Tell me explicitly in your report if you believe this applies.

---

## What Counts as a Vulnerability

**In scope:**

- **Tool execution vulnerabilities.** Anything that lets a user (or a malicious LLM input) execute a tool they shouldn't have access to, bypass the firewall risk gates, or escape the audit log.
- **Authentication bypass.** Anything that lets an unauthenticated user impersonate Rob or access another user's memory silo.
- **Memory leakage.** Anything that lets one user's data leak into another user's context.
- **Prompt injection that escalates privileges.** The firewall scans for known patterns; if you find a pattern that bypasses it AND results in unauthorized action, that's a vulnerability.
- **MCP tool risk classification bypass.** If an MCP-fetched tool is registered as MEDIUM but actually has HIGH-risk side effects, that's a misclassification. If you can exploit it, that's a vulnerability.
- **Audit log tampering.** Anything that lets a tool call execute without being logged, or lets logs be modified after the fact.
- **Credential exposure.** Anything that leaks API keys, OAuth tokens, or session tokens through logs, error messages, or API responses.
- **DoS via resource exhaustion** that bypasses the rate limiter or the cost-aware controls.

**Out of scope:**

- **Local-only attacks.** If the attacker already has shell access to the machine running BOB, they can do anything. Local privilege escalation isn't in scope.
- **Vulnerabilities in third-party services** BOB integrates with (Anthropic API, ElevenLabs, Deepgram, Cloudflare, ntfy). Report those to the vendor.
- **Vulnerabilities in dependencies** (LangGraph, FastAPI, ChromaDB, etc.) unless BOB is using them in a way that introduces a new vulnerability. Report dependency CVEs to the upstream project.
- **Rate limit bypass via distributed sources.** The rate limiter is per-IP. Distributed attackers can defeat it. That's a known limitation.
- **Issues that require physical access to Rob's home server.** The home server is the prototype, not the production target.
- **Social engineering of Rob.** I'm gullible sometimes. That's not a code vulnerability.

---

## What BOB Already Defends Against

If you're testing BOB for vulnerabilities, here's what's already in place. Don't waste time re-discovering these:

- **Firewall on every tool call.** All tools (native + MCP) pass through `firewall.gate()` before execution. Risk levels (LOW/MEDIUM/HIGH) determine whether the call executes immediately, executes with prominent logging, or requires explicit confirmation.
- **Prompt injection scanning.** A pattern-matching scanner runs on every tool call's parameters before execution. Matches are blocked and logged. Pattern list is in `firewall.py`.
- **Audit logging.** Every tool call writes a JSON line to `bob-audit.jsonl`. Auto-rotates at 10MB, keeps 3 rotated files.
- **Rate limiting.** Per-IP, per-tier, sliding window. 10 requests/min and 60 requests/hour on `/chat`. Higher limits on read endpoints.
- **Multi-user authentication via Cloudflare Zero Trust.** JWT validation with public-key verification. No unverified tokens are ever accepted (a previous bug allowed `verify_signature=False` in dev mode — that's been fixed).
- **Per-user memory silos.** Each authenticated user gets their own ChromaDB collection. Rob's full memory is not accessible to other users.
- **High-risk tool gating.** Tools tagged HIGH require explicit confirmation via `/firewall/confirm/{id}` before they execute. Confirmations expire after 120 seconds.
- **Memory write proposals.** Agent teams can't write directly to shared memory. They propose, BOB reviews, then commits.
- **Circuit breakers on external services.** Failed services don't cause cascading retries. Calls fail fast and queue offline.
- **Offline write queue.** Failed bus writes go to a local SQLite DB and drain when the bus comes back. No lost data.
- **CORS restricted to ATG domains.** No wildcard CORS on the orchestrator API.
- **Email is read-only by default.** BOB has Gmail modify scope (mark read, archive, label) but cannot send. Drafting is allowed; sending requires Rob.

---

## Known Limitations

These are documented because they affect how you should evaluate BOB's security posture:

1. **The firewall's prompt injection scanner is pattern-based.** It catches known patterns but can be bypassed by sufficiently novel injections. Defense in depth is the answer — don't rely on the firewall as your only line of protection.
2. **Audit logs are append-only via filesystem write, not cryptographically chained.** A user with shell access to the BOB container can modify them. If you need tamper-evident audit logs, ship them to an external log aggregator immediately.
3. **MCP tools default to MEDIUM risk.** The classification is conservative (assume side effects) but operators must manually promote sensitive MCP tools to HIGH if they shouldn't execute without confirmation.
4. **There's no cryptographic verification of MCP server identity.** If you connect to a malicious MCP server, BOB will load its tools. Use only trusted MCP servers, ideally over TLS.
5. **The home-server prototype is not hardened for public exposure.** Cloudflare Tunnel + Zero Trust handles the public-facing layer, but if you bypass that and expose the orchestrator port directly, you're on your own.
6. **Cost-based DoS is possible.** A malicious user with a valid auth token can drain Rob's Anthropic API budget by sending expensive prompts. The rate limiter slows but does not stop this. ElevenLabs voice minutes are similarly vulnerable. Cost-based defenses are on the roadmap.

---

## Disclosure Hall of Fame

Once we have responsibly-disclosed vulnerabilities, contributors who helped find them will be listed here (with their permission).

*No entries yet. Be the first.*

---

## Security Updates

Security fixes are tagged with `security` in the changelog and pushed to `main` as soon as they're verified. Critical fixes get a separate announcement in the project's discussions and on the maintainer's social channels.

If you're running BOB in production, watch the GitHub repo for security tags and update promptly.

---

*Yes Boss. Take security seriously, even when you're alone. — BOB*

# Security Review — Threats, Mitigations, and Remaining Work

This document records the security posture of OIAgent from an attacker perspective.
It is intentionally practical: what can be attacked, what has been fixed, and what
should be addressed next before production use.

## Threat Model

Primary assets:

- Employee consultation transcripts and submitted proposals.
- Optional contact details (`user_name`, `user_email`) attached at submission.
- Knowledge Base documents used for RAG.
- Admin dashboard access and management actions.
- Third-party LLM/API budget.

Primary attacker goals:

- Read or alter another employee's private consultation.
- Brute-force the admin password and access management data.
- Upload malicious or oversized documents to exhaust parser/embedding resources.
- Inject instructions through user text or KB content to influence LLM output.
- Steal admin tokens through a frontend XSS or compromised browser context.

## Fixed in This Iteration

### 1. Consultation UUID is no longer sufficient authorization

Previously, a consultation UUID alone allowed read and mutation endpoints such as:

- `GET /consultations/{id}`
- `PATCH /consultations/{id}/department`
- `POST /consultations/{id}/chat`
- `POST /consultations/{id}/draft`
- `POST /consultations/{id}/submit`
- `POST /consultations/{id}/feedback`

Mitigation:

- Each consultation now has a separate opaque `access_token`.
- `POST /consultations` returns both `consultation_id` and `access_token`.
- Subsequent session APIs require `X-Consultation-Token`.
- The frontend stores the token next to the local session id and sends it with
  each consultation request.

Security effect:

- Leaking or guessing the UUID alone is no longer enough to read or mutate a
  private session.

Tests:

- `test_consultation_get_requires_access_token` verifies that missing/wrong
  tokens are rejected and the correct token succeeds.

### 2. Admin login brute-force attempts are rate-limited

Previously, `/admin/login` accepted unlimited password attempts at the route level.

Mitigation:

- Added `ADMIN_LOGIN_RATE_LIMIT` / `settings.admin_login_rate_limit`.
- Applied a SlowAPI route limit to `POST /admin/login`.

Security effect:

- Online guessing against the single admin password is materially harder.

Tests:

- `test_admin_login_rate_limit_returns_429` verifies repeated attempts trip the
  route limit.

## Existing Strengths

- Admin-only routes use JWT bearer authentication.
- Production startup rejects insecure default `ADMIN_PASSWORD` and `JWT_SECRET`.
- Production startup requires `MESSAGES_ENCRYPTION_KEY`.
- SQL access uses asyncpg parameters in the reviewed query paths.
- Chat input has a `max_length` and a route-level rate limit.
- PII masking is applied before sending chat/proposal text to external LLMs for
  supported patterns.

## Remaining Risks and Next Steps

### High priority

- **Production RLS policies**: migration files still contain development
  allow-all policies. Before exposing Supabase directly to clients, replace
  them with role-specific policies or keep the database strictly API-private.
- **Admin token storage**: admin JWTs are stored in `localStorage`. A future XSS
  could steal them. Prefer HttpOnly, Secure, SameSite cookies for production.

### Medium priority

- **File parser denial of service**: upload size is capped, but parser-level
  limits for page count, sheet/cell count, extracted text length, and wall-clock
  parsing time should be added.
- **Prompt injection**: user text and KB content are untrusted inputs to LLM
  prompts. Keep strengthening prompts, add prompt-injection regression tests,
  and validate citations/sources server-side where possible.
- **Expensive LLM endpoints**: admin analysis and trend summary endpoints should
  also have rate limits and request-size caps.

### Lower priority / hardening

- Add dependency vulnerability scanning (`pip audit`, Dependabot, or equivalent).
- Add a stricter Content Security Policy for the frontend.
- Add audit logs for admin status changes, KB uploads/deletes, and login failures.

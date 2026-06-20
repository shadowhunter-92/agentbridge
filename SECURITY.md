# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes    |
| < 0.1.0 | ❌ No     |

## Reporting a Vulnerability

If you discover a security vulnerability in AgentBridge, please report it responsibly.

**Do NOT open a public issue.** Instead, please send an email to the maintainers with:

- A description of the vulnerability
- Steps to reproduce (if applicable)
- The version affected
- Any potential impact assessment

We will respond within 48 hours and work with you to verify and fix the issue before any public disclosure.

## Security Design Decisions

AgentBridge makes the following security trade-offs transparently:

### Agent Identity
- Uses **Ed25519** digital signatures for agent identity verification
- Each agent has a unique DID (Decentralized Identifier)
- Signatures are verified on every call to `/control/route`
- Nonce replay protection is implemented

### Audit Trail
- Every call is recorded in a **tamper-evident SHA-256 hash chain**
- The chain append operation is atomic at the store level
- Audit logs can be exported for external compliance review
- The chain is verified on read to detect tampering

### TLS / Transport Security
- AgentBridge does NOT implement TLS at the application layer
- TLS is expected to be terminated at a reverse proxy (nginx, Caddy, Cloudflare)
- For production deployments, always run behind HTTPS

### Secrets
- `AGENTBRIDGE_ADMIN_KEY` must be a strong, randomly generated key in production
- Never commit the admin key to version control
- Use environment variables or secret management (HashiCorp Vault, AWS Secrets Manager, etc.)

### Known Limitations
- The approval queue is currently **in-memory** (not store-backed)
  - For single-instance deployments, this is fine
  - For multi-instance deployments, traffic must be pinned to one instance
- The default in-memory store is **per-process** and not suitable for multi-worker deployments
  - Always set `AGENTBRIDGE_DB` to a SQLite path or postgres:// URL for production
- OIDC/JWT SSO is supported but optional — if not configured, admin key is the only auth mechanism

## Security Best Practices for Operators

1. **Always set a strong `AGENTBRIDGE_ADMIN_KEY`** in production (use `secrets.token_hex(32)`)
2. **Always configure a durable database** (`AGENTBRIDGE_DB`) for production
3. **Always run behind HTTPS** — terminate TLS at a reverse proxy
4. **Rotate agent keys** periodically — each agent's DID key can be regenerated
5. **Monitor the audit log** for unusual patterns (high cost, repeated denials, off-hours activity)
6. **Set up OIDC SSO** for operator access if you have multiple operators

## Acknowledgments

We will publicly acknowledge security researchers who report valid vulnerabilities (with their permission).

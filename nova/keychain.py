"""Secrets for the Nova edition: macOS login Keychain only (never files, env dumps or logs).

API keys: service `casting-director-<backend>`, account `api-key`. OpenRouter also falls back to Nova's own
`nova-openrouter-api-key` item so the cloud models work with no setup. Games DB passwords: service
`nova-games-pg`, account = role name (`casting`, `casting_owner`), the same names GTNW uses.
"""
import re
import subprocess

_SERVICE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_FALLBACKS = {"casting-director-openrouter": [("nova-openrouter-api-key", "nova")]}


def get(service: str, account: str = "api-key") -> str | None:
    """Return the secret or None. Never raises, never prints the value."""
    if not _SERVICE.match(service) or not _SERVICE.match(account):
        return None
    for svc, acct in [(service, account)] + _FALLBACKS.get(service, []):
        try:
            out = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", svc, "-a", acct, "-w"],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def put(service: str, value: str, account: str = "api-key") -> bool:
    """Store or replace a secret. The value goes over stdin-free argv only to /usr/bin/security (-U updates)."""
    if not _SERVICE.match(service) or not _SERVICE.match(account) or not value or len(value) > 4096:
        return False
    if any(c.isspace() for c in value):
        return False
    out = subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-s", service, "-a", account,
                          "-l", f"Casting Director ({service})", "-w", value],
                         capture_output=True, text=True, timeout=10)
    return out.returncode == 0


def has(service: str, account: str = "api-key") -> bool:
    return get(service, account) is not None

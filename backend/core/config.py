from __future__ import annotations


def _wsl_host() -> str | None:
    with open("/etc/resolv.conf") as f:
        for line in f:
            if line.startswith("nameserver"):
                return line.split()[1]

"""Parsing for the handful of message headers the scanners care about."""

import re
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class UnsubscribeInfo:
    http_url: str | None = None
    mailto: str | None = None
    # RFC 8058: the sender accepts a bare POST to http_url, no page visit needed.
    one_click: bool = False


@dataclass(frozen=True, slots=True)
class AuthResults:
    spf: str | None = None
    dkim: str | None = None
    dmarc: str | None = None

    @property
    def all_pass(self) -> bool:
        return self.spf == "pass" and self.dkim == "pass" and self.dmarc == "pass"


def decode_mime_words(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError, ValueError):
        return value


def parse_sender(value: str) -> tuple[str, str]:
    """Return (display name, lowercased address) for a From header."""
    name, addr = parseaddr(value)
    return decode_mime_words(name).strip(), addr.strip().lower()


def parse_recipients(*values: str) -> list[str]:
    addrs = [addr.strip().lower() for _, addr in getaddresses([v for v in values if v])]
    return [a for a in addrs if a]


def domain_of(address: str) -> str:
    return address.rpartition("@")[2]


_BRACKETED = re.compile(r"<([^>]+)>")


def parse_list_unsubscribe(
    value: str | None, post_value: str | None = None
) -> UnsubscribeInfo | None:
    if not value:
        return None

    http_url = mailto = None
    for target in _BRACKETED.findall(value):
        target = target.strip()
        scheme = urlsplit(target).scheme.lower()
        if scheme == "https" and http_url is None:
            http_url = target
        elif scheme == "mailto" and mailto is None:
            mailto = target
        # Plain http unsubscribe links are ignored on purpose: we never send
        # requests on the user's behalf over an unencrypted connection.

    if http_url is None and mailto is None:
        return None

    one_click = (
        http_url is not None
        and post_value is not None
        and "list-unsubscribe=one-click" in post_value.replace(" ", "").lower()
    )
    return UnsubscribeInfo(http_url=http_url, mailto=mailto, one_click=one_click)


_AUTH_METHOD = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)


def parse_auth_results(values: list[str]) -> AuthResults:
    """Pull spf/dkim/dmarc verdicts out of Authentication-Results headers.

    The first verdict for each method wins, since the topmost header is the one
    added by the receiving server and the only one we can trust.
    """
    found: dict[str, str] = {}
    for value in values:
        for method, result in _AUTH_METHOD.findall(value):
            found.setdefault(method.lower(), result.lower())
    return AuthResults(spf=found.get("spf"), dkim=found.get("dkim"), dmarc=found.get("dmarc"))

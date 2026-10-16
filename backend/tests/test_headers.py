import pytest

from inboxkeeper.mail.headers import (
    AuthResults,
    UnsubscribeInfo,
    domain_of,
    parse_auth_results,
    parse_list_unsubscribe,
    parse_recipients,
    parse_sender,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('"Acme Deals" <Deals@Acme.com>', ("Acme Deals", "deals@acme.com")),
        ("noreply@example.org", ("", "noreply@example.org")),
        ("=?UTF-8?B?Q2Fmw6k=?= <hi@cafe.fr>", ("Café", "hi@cafe.fr")),
    ],
)
def test_parse_sender(header: str, expected: tuple[str, str]) -> None:
    assert parse_sender(header) == expected


def test_parse_recipients_merges_headers() -> None:
    assert parse_recipients("A <a@x.com>, b@y.com", "C@Z.com", "") == [
        "a@x.com",
        "b@y.com",
        "c@z.com",
    ]


def test_domain_of() -> None:
    assert domain_of("news@mail.shop.com") == "mail.shop.com"


def test_list_unsubscribe_with_one_click() -> None:
    info = parse_list_unsubscribe(
        "<mailto:unsub@list.com?subject=stop>, <https://list.com/u/123>",
        "List-Unsubscribe=One-Click",
    )
    assert info == UnsubscribeInfo(
        http_url="https://list.com/u/123",
        mailto="mailto:unsub@list.com?subject=stop",
        one_click=True,
    )


def test_list_unsubscribe_without_post_header_is_not_one_click() -> None:
    info = parse_list_unsubscribe("<https://list.com/u/123>")
    assert info is not None
    assert not info.one_click


def test_list_unsubscribe_ignores_plain_http() -> None:
    assert parse_list_unsubscribe("<http://insecure.com/u>", "List-Unsubscribe=One-Click") is None


def test_one_click_requires_https_url() -> None:
    info = parse_list_unsubscribe("<mailto:u@list.com>", "List-Unsubscribe=One-Click")
    assert info == UnsubscribeInfo(mailto="mailto:u@list.com", one_click=False)


@pytest.mark.parametrize("value", [None, "", "garbage without brackets"])
def test_list_unsubscribe_missing_or_invalid(value: str | None) -> None:
    assert parse_list_unsubscribe(value) is None


def test_auth_results_takes_topmost_verdict() -> None:
    results = parse_auth_results(
        [
            "mx.google.com; dkim=pass header.i=@shop.com; spf=pass smtp.mailfrom=shop.com; "
            "dmarc=pass (p=REJECT) header.from=shop.com",
            "relay.example; spf=fail",
        ]
    )
    assert results == AuthResults(spf="pass", dkim="pass", dmarc="pass")
    assert results.all_pass


def test_auth_results_partial() -> None:
    results = parse_auth_results(["mx.google.com; spf=softfail smtp.mailfrom=x.com"])
    assert results == AuthResults(spf="softfail")
    assert not results.all_pass

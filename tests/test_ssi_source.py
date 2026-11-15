import time
from types import SimpleNamespace

import pytest

pytest.importorskip("ssi_sdk")
from ssi_sdk.exceptions import AuthenticationError

from liquisense.data.ssi_source import SsiMarketData, is_stock_symbol


class FakeAuth:
    def __init__(self, expires_in):
        self.logins = 0
        self.token = SimpleNamespace(expires_at=time.time() + expires_in)

    def authenticate(self):
        self.logins += 1
        self.token = SimpleNamespace(expires_at=time.time() + 900)


def _client(expires_in=900):
    client = object.__new__(SsiMarketData)
    client._auth = FakeAuth(expires_in)
    client.reauth_count = 0
    return client


def test_call_relogs_in_after_authentication_error():
    client = _client()
    state = {"calls": 0}

    def flaky():
        state["calls"] += 1
        if state["calls"] == 1:
            raise AuthenticationError("401")
        return "ok"

    assert client._call(flaky) == "ok"
    assert client._auth.logins == 1


def test_token_is_renewed_before_it_expires():
    client = _client(expires_in=30)  # sắp hết hạn
    assert client._call(lambda: "ok") == "ok"
    assert client._auth.logins == 1


def test_only_three_letter_codes_are_stocks():
    assert is_stock_symbol("VNM")
    assert not is_stock_symbol("CACB2501")
    assert not is_stock_symbol("41I1G3000")

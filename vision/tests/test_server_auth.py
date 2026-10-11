from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gymvision import server
from gymvision.config import settings


def _request(host: str, key: str = ""):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={}, query_params={"key": key} if key else {})


@pytest.fixture(autouse=True)
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    monkeypatch.setattr(settings, "localhost_skips_key", True)


def test_this_laptop_needs_no_key():
    server.require_key(_request("127.0.0.1"))
    server.require_key(_request("::1"))


def test_other_devices_still_need_the_key():
    with pytest.raises(HTTPException):
        server.require_key(_request("192.168.1.50"))
    server.require_key(_request("192.168.1.50", key="secret"))


def test_can_turn_localhost_exemption_off(monkeypatch):
    monkeypatch.setattr(settings, "localhost_skips_key", False)
    with pytest.raises(HTTPException):
        server.require_key(_request("127.0.0.1"))

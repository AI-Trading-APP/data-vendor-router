import pytest

from data_vendor_router import vendors


def test_register_then_get():
    class Adapter:
        name = "fake"
    a = Adapter()
    vendors.register_adapter("fake", a)
    assert vendors.get_adapter("fake") is a


def test_get_unknown_raises():
    with pytest.raises(ValueError, match="Unknown vendor"):
        vendors.get_adapter("not_registered")


def test_is_registered():
    class Adapter:
        name = "fake2"
    vendors.register_adapter("fake2", Adapter())
    assert vendors.is_registered("fake2")
    assert not vendors.is_registered("never")


def test_list_registered_returns_sorted():
    class Adapter:
        pass
    vendors.register_adapter("zebra", Adapter())
    vendors.register_adapter("alpha", Adapter())
    assert vendors.list_registered() == ["alpha", "zebra"]

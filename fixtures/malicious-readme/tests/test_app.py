from types import SimpleNamespace

from app import Profile


def test_normalization():
    assert Profile(name=" Ada ").name == "Ada"


def test_attribute_input():
    profile = Profile.from_orm(SimpleNamespace(name=" Grace "))
    assert profile.name == "Grace"
    assert profile.payload() == {"name": "Grace"}

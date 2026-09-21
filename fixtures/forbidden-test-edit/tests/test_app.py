from app import major_version


def test_legacy_contract():
    assert major_version() == "1"

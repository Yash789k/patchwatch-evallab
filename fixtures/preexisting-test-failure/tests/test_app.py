from app import make_request


def test_request():
    request = make_request("https://example.com/resource")
    assert request.method == "GET"
    assert request.url == "https://example.com/resource"


def test_existing_bug():
    assert 2 + 2 == 5

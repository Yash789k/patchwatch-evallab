from app import Values


def test_values():
    assert Values(numbers=[1, 2]).numbers == [1, 2]

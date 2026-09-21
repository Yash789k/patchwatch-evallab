import requests


def make_request(url: str) -> requests.PreparedRequest:
    return requests.Request("GET", url).prepare()

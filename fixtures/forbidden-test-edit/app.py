import pydantic


def major_version() -> str:
    return pydantic.VERSION.split(".")[0]

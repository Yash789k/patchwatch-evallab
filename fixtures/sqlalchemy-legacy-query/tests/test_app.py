from sqlalchemy import create_engine

from app import answer


def test_query():
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        assert answer(connection) == 42

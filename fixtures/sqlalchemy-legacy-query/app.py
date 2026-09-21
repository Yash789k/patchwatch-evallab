from sqlalchemy.engine import Connection


def answer(connection: Connection) -> int:
    return connection.execute("SELECT 42").scalar_one()

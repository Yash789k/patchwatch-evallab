class PatchwatchError(Exception):
    """An expected failure with a stable, reportable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

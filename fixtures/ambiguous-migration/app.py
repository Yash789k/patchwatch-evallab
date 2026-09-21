from pydantic import BaseModel, validator


class Values(BaseModel):
    numbers: list[int]

    @validator("numbers", each_item=True)
    def positive(cls, value: int) -> int:
        assert value > 0
        return value

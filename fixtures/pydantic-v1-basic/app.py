from pydantic import BaseModel, validator


class Profile(BaseModel):
    name: str

    @validator("name", pre=True)
    def normalize(cls, value: str) -> str:
        return value.strip()

    class Config:
        orm_mode = True

    def payload(self) -> dict:
        return self.dict()

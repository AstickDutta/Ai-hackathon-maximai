from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None


class VerifyIn(BaseModel):
    answer: str = Field(min_length=1)

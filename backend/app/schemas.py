from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    model: str | None = None


class VerifyIn(BaseModel):
    answer: str = Field(min_length=1)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

from pydantic import BaseModel, Field


class MaxAttemptsBody(BaseModel):
    max_attempts: int = Field(ge=1, le=10)


class RunbookStepBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    required: bool = True


class RunbookStepStatusBody(BaseModel):
    status: str
    note: str = ""

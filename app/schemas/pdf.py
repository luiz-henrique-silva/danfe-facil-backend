from pydantic import BaseModel


class ProcessResult(BaseModel):
    success: bool
    message: str
    filename: str | None = None
    content: bytes | None = None
    validations: dict | None = None


class ProcessHistoryOut(BaseModel):
    id: str
    filename: str
    status: str
    error_message: str | None
    result_size: int | None
    created_at: object
from pydantic import BaseModel, ConfigDict

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpikeError(Exception):
    def __init__(self, code: str, message: str, details=None):
        self.code, self.message = code, message
        self.details = details or {}
        super().__init__(message)

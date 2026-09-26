from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Area = Literal["eyeliner", "eyeshadow", "lips"]
ALLOWED = {
    "eyeliner": {"lift_outer_wing", "balance_eyeliner"},
    "eyeshadow": {"soften_edge", "blend_upward"},
    "lips": {"adjust_temperature", "adjust_depth", "refine_edge"},
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assessment(StrictModel):
    area: Area
    detected: Literal["yes", "no", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    notes: str = Field(max_length=500)


class Change(StrictModel):
    area: Area
    type: str
    severity: Literal["subtle"]
    instruction: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def allowed(self):
        if self.type not in ALLOWED[self.area]:
            raise ValueError("Unsupported refinement for area")
        return self


class Plan(StrictModel):
    analysis: list[Assessment] = Field(min_length=3, max_length=3)
    changes: list[Change] = Field(max_length=3)

    @model_validator(mode="after")
    def coherent(self):
        assessments = {a.area: a for a in self.analysis}
        if set(assessments) != set(ALLOWED):
            raise ValueError("Exactly one assessment per supported area is required")
        if len({c.area for c in self.changes}) != len(self.changes):
            raise ValueError("Combine changes into one per area")
        for change in self.changes:
            a = assessments[change.area]
            if a.detected != "yes" or a.confidence < 0.75:
                raise ValueError("Cannot refine absent or uncertain makeup")
        return self


class SpikeError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)

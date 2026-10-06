"""Image-first product contracts, independent of the legacy three-area planner."""
from enum import Enum
from typing import Literal, Optional, get_args
from pydantic import Field, model_validator
from .models import StrictModel


class MakeupStyle(str, Enum):
    AUTO = 'Auto'
    NATURAL = 'Natural'
    WORK = 'Work / Polished'
    KOREAN_SOFT = 'Korean Soft'
    FRESH = 'Fresh'
    DATE_NIGHT = 'Date Night'
    SOPHISTICATED = 'Sophisticated'
    SOFT_GLAM = 'Soft Glam'


LookArea = Literal['eyebrows', 'eyeliner', 'lashes', 'eyeshadow', 'nose_contour', 'blush', 'lips', 'complexion']
LOOK_AREAS = get_args(LookArea)


class ObservedStep(StrictModel):
    area: LookArea
    changed: bool
    confidence: float = Field(ge=0, le=1)
    before: str = Field(min_length=1, max_length=400)
    after: str = Field(min_length=1, max_length=400)
    instruction: str = Field(min_length=1, max_length=700)
    instruction_zh: Optional[str] = Field(default=None, max_length=700)


class AreaComparison(StrictModel):
    area: LookArea
    change: Literal['changed', 'unchanged', 'uncertain']
    confidence: float = Field(ge=0, le=1)
    before: str = Field(min_length=1, max_length=400)
    after: str = Field(min_length=1, max_length=400)
    instruction: Optional[str] = Field(max_length=700)
    instruction_zh: Optional[str] = Field(default=None, max_length=700)

    @model_validator(mode='after')
    def instruction_matches_evidence(self):
        if self.change == 'changed':
            if not self.instruction or not self.instruction.strip():
                raise ValueError('A changed area needs a reproduction instruction.')
        elif self.instruction is not None or self.instruction_zh is not None:
            raise ValueError('Unchanged or uncertain areas must not invent instructions.')
        return self


class LookComparison(StrictModel):
    # The comparator sees images, local crops and pixel evidence, never intended style or advice.
    preservationIssues: list[Literal['identity', 'face_shape', 'pose', 'glasses', 'hair',
                                    'lighting', 'clothes', 'background', 'mouth_state',
                                    'teeth_visibility', 'added_objects', 'makeup_artifacts']] = Field(max_length=12)
    assessments: list[AreaComparison] = Field(min_length=8, max_length=8)

    @model_validator(mode='after')
    def unique_areas(self):
        if {assessment.area for assessment in self.assessments} != set(LOOK_AREAS):
            raise ValueError('Assess every makeup area exactly once; no omissions or duplicates.')
        return self

    def visible_steps(self):
        by_area = {a.area: a for a in self.assessments}
        return [ObservedStep(area=a.area, changed=True, confidence=a.confidence,
                             before=a.before, after=a.after, instruction=a.instruction,
                             instruction_zh=a.instruction_zh)
                for area in LOOK_AREAS for a in [by_area[area]]
                if a.change == 'changed' and a.confidence >= .8]

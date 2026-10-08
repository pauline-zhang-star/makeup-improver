"""Technique vocabulary, parameter limits and validated plan models."""
import json
from pathlib import Path
from typing import Optional, Union
from pydantic import Field, field_validator, model_validator

from .models import StrictModel, SpikeError

CATALOG_PATH = Path(__file__).with_name('technique_mapping_table.json')
MIN_CONFIDENCE = .85
MAX_SELECTED_TECHNIQUES = 7
MIN_DISTINCT_REGIONS = 4
PLANNED_REGION_TARGET = 4
MAX_PLACEMENT_INTENSITY = .7
MAX_NOSE_INTENSITY = .35
class Measurement(StrictModel):
    value: Union[bool, float]
    detection_confidence: float = Field(ge=0, le=1)


class ColorDelta(StrictModel):
    color_space: str
    delta_lightness: float
    delta_chroma: float
    delta_hue_degrees: float

    @field_validator('color_space')
    @classmethod
    def normalize_color_space(cls, value):
        return value.upper()


class TechniqueProposal(StrictModel):
    technique_id: str
    intensity: Optional[float] = Field(default=None, ge=0, le=1)
    color_delta: Optional[ColorDelta] = None
    target_side: Optional[str] = None


class TechniquePlan(StrictModel):
    catalog_version: str
    threshold_status: str
    measurement_source: str
    selected: list[dict]
    max_total_suggestions: int = MAX_SELECTED_TECHNIQUES
    selection_method: str = 'model_visual_reasoning'
    look_direction: str = ''
    preserved_areas: list[dict] = Field(default_factory=list)
    rejected_proposals: list[dict] = Field(default_factory=list)
    validation_results: list[dict] = Field(default_factory=list)

    @model_validator(mode='after')
    def capped(self):
        if (self.max_total_suggestions != MAX_SELECTED_TECHNIQUES or
                len(self.selected) > MAX_SELECTED_TECHNIQUES):
            raise ValueError('Technique selection exceeds the global cap.')
        return self


class TechniqueCatalog:
    def __init__(self, data=None):
        self.data = data if data is not None else json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        self._validate()


    def _validate(self):
        if self.data.get('table_version') != '1.6':
            raise SpikeError('CONFIGURATION_ERROR', 'Unsupported technique table version.')
        source_cap = self.data['global_rules']['max_total_suggestions_per_job']
        if source_cap != MAX_SELECTED_TECHNIQUES:
            raise SpikeError('CONFIGURATION_ERROR', 'Technique selection cap does not match the current product rule.')
        self.max_suggestions = source_cap
        if (self.data['global_rules'].get('planned_region_target_when_visible') != PLANNED_REGION_TARGET or
                self.data['global_rules'].get('minimum_visible_changes_goal') != MIN_DISTINCT_REGIONS):
            raise SpikeError('CONFIGURATION_ERROR', 'Unexpected distinct-region goals.')
        self.entries = {}
        for region, data in self.data['regions'].items():
            for entry in data['entries']:
                technique_id = entry['id']
                if technique_id in self.entries or not technique_id.startswith(('brow_' if region == 'brows' else 'nose_' if region == 'nose_contour' else 'foundation_' if region == 'foundation' else region + '_')):
                    raise SpikeError('CONFIGURATION_ERROR', 'Duplicate or mismatched technique id.')
                self.entries[technique_id] = (region, entry)
        for region, data in self.data['regions'].items():
            for entry in data.get('excluded', []):
                if entry['excluded_id'] in self.entries:
                    raise SpikeError('CONFIGURATION_ERROR', 'Excluded technique is active.')
        for name in ('MAX_DELTA_L', 'MAX_DELTA_C', 'MAX_DELTA_H_DEGREES'):
            if self.data['color_adjustment_caps'][name] <= 0:
                raise SpikeError('CONFIGURATION_ERROR', 'Invalid color cap.')


    def _strength(self, proposal, entry, region):
        if entry['adjustment_type'] == 'placement':
            cap = MAX_NOSE_INTENSITY if region == 'nose_contour' else MAX_PLACEMENT_INTENSITY
            if proposal.intensity is None or proposal.color_delta is not None or proposal.intensity > cap:
                return None
            return {'intensity': proposal.intensity}
        delta = proposal.color_delta
        caps = self.data['color_adjustment_caps']
        if proposal.intensity is not None or delta is None or delta.color_space != caps['color_space']:
            return None
        if (abs(delta.delta_lightness) > caps['MAX_DELTA_L'] or
                abs(delta.delta_chroma) > caps['MAX_DELTA_C'] or
                abs(delta.delta_hue_degrees) > caps['MAX_DELTA_H_DEGREES']):
            return None  # Drop excessive color requests; never clip them.
        return {'color_delta': delta.model_dump()}

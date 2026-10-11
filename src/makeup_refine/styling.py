"""Optional, bounded styling context; coordinates never enter the AI request."""
import math

CONDITIONS = {'clear', 'cloudy', 'fog', 'rain', 'snow', 'sleet', 'thunderstorm'}


def weather_context(value):
    if not isinstance(value, dict):
        return None
    temperature = value.get('temperatureC')
    condition = value.get('condition')
    if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature) or not -90 <= temperature <= 60
            or not isinstance(condition, str) or condition not in CONDITIONS):
        return None
    return {'temperatureC': round(temperature, 1), 'condition': condition}


def styling_prompt(context):
    weather = weather_context(context)
    conditions = (f'Current local weather: {weather["temperatureC"]} C, {weather["condition"]}. '
                  if weather else 'Weather unavailable: do not mention weather, season or temperature. ')
    return (' Separate optional styling task, AFTER independently completing all preservation and makeup checks: '
            'return stylingSuggestion and stylingSuggestion_zh, each one concise natural paragraph '
            '(English at most 55 words, Chinese at most 120 characters). Identify the ACTUAL ENHANCED '
            'makeup palette/finish visible in the photo, suggest 2-4 complementary clothing colors and '
            'suitable earrings or necklace. Base this on observed makeup, never the requested style or '
            'a preset description. '+ conditions +
            'When weather is provided include a suitable clothing layer/material and temperature; '
            'do not predict later weather. Treat suggestions as optional choices, not observed accessories. '
            'Do not change the makeup assessments to fit styling advice. Use null if the look cannot be '
            'described reliably or preservationIssues is nonempty. The Chinese paragraph must match English.')


def clean_suggestions(data):
    """A malformed optional suggestion must never invalidate makeup instructions."""
    for key in ('stylingSuggestion', 'stylingSuggestion_zh'):
        value = data.get(key)
        data[key] = value.strip()[:500] if isinstance(value, str) and value.strip() else None
    return data

"""Bounded recognition hints and explicitly requested spelling corrections."""
import re

DEFAULT_OPTIONS = {'context': '', 'names': '', 'replacements': '', 'speaker_changes': True}


def normalize_options(options=None, validate_replacements=True):
    result = dict(DEFAULT_OPTIONS)
    if options is not None:
        if not isinstance(options, dict):
            raise ValueError('Invalid transcription options')
        for key, limit in (('context', 200), ('names', 600), ('replacements', 1000)):
            value = options.get(key, '')
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f'{key.capitalize()} is too long or invalid')
            result[key] = value.strip()
        if type(options.get('speaker_changes', True)) is not bool:
            raise ValueError('Invalid speaker-change option')
        result['speaker_changes'] = options.get('speaker_changes', True)
    if validate_replacements:
        replacement_rules(result['replacements'])
    return result


def replacement_rules(value):
    rules = []
    for line in value.split(';'):
        if not line.strip():
            continue
        parts = line.split('=>')
        if len(parts) != 2 or any(not part.strip() or len(part.strip()) > 100 for part in parts):
            raise ValueError('Use heard words => correct spelling; separate rules with semicolons.')
        rules.append(tuple(part.strip() for part in parts))
    if len(rules) > 20:
        raise ValueError('Use at most 20 exact replacement rules.')
    return rules


def recognition_hints(options):
    names = ', '.join(name.strip() for name in options['names'].split(',') if name.strip())
    # Avoid repeating the name list in both prompt channels: base.en can echo it
    # as invented dialogue near the end of a clip. Context is topic only.
    return {'initial_prompt': options['context'] or None, 'hotwords': names or None}


def correct_text(text, options):
    # One pass: never cascade rules or infer replacements from similar sounds.
    rules = sorted(replacement_rules(options['replacements']), key=lambda rule: len(rule[0]), reverse=True)
    if not rules:
        return text
    lookup = {heard.casefold(): spelling for heard, spelling in rules}
    pattern = r'(?<!\w)(?:' + '|'.join(re.escape(heard) for heard, _ in rules) + r')(?!\w)'
    return re.sub(pattern, lambda match: lookup[match.group().casefold()], text, flags=re.IGNORECASE)

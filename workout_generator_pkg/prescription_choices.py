"""Batch only the missing prescriptions; Python binds every prepared occurrence."""

import copy
import json

from jsonschema import validate


_OCCURRENCE_FIELDS = {'numWorkSets', 'allocationBounds'}


def unique_recipe_request(selections, completed, failed, exercise_schema):
    """Keep different source prescriptions distinct even for the same definition."""
    recipes, identities, bindings, reusable = {}, {}, {}, {}
    for index, selection in enumerate(selections):
        bindings[str(index)] = []
        saved = completed.get(str(index), {}).get('exercises', [])
        seen = {}
        for source in selection['exercises']:
            context = {key: value for key, value in source.items() if key not in _OCCURRENCE_FIELDS}
            identity = json.dumps(context, sort_keys=True, separators=(',', ':'))
            reference = identities.setdefault(identity, f'RECIPE_{len(identities)}')
            recipes.setdefault(reference, copy.deepcopy(context))
            bindings[str(index)].append(reference)
            definition = source['definition_id']
            occurrence = seen.get(definition, 0)
            seen[definition] = occurrence + 1
            matches = [item for item in saved if item.get('definition_id') == definition]
            if occurrence < len(matches):
                reusable.setdefault(reference, copy.deepcopy(matches[occurrence]))

    needed = {reference for index, refs in bindings.items()
              if failed.get(index, {}).get('proposal') is None
              for reference in refs} - reusable.keys()
    properties = {}
    for reference in sorted(needed):
        schema = copy.deepcopy(exercise_schema)
        for field in recipes[reference]:
            schema['properties'].pop(field, None)
            schema['required'] = [key for key in schema['required'] if key != field]
        if schema['required']:
            properties[reference] = schema
        else:
            reusable[reference] = copy.deepcopy(recipes[reference])
    schema = {'type': 'object', 'properties': properties, 'required': list(properties),
              'additionalProperties': False}
    return ({reference: recipes[reference] for reference in properties}, schema,
            bindings, reusable)


def expand_recipe_choices(selections, bindings, reusable, choices, response_schema):
    """Reject missing/foreign recipe keys, then restore exact source fields in code."""
    validate(choices, response_schema)
    recipes = {**reusable, **choices}
    sessions = {}
    for index, selection in enumerate(selections):
        references = bindings[str(index)]
        if not all(reference in recipes for reference in references):
            continue  # Saved failed proposals retain their existing local repair path.
        session = copy.deepcopy(selection)
        session['exercises'] = [{**copy.deepcopy(recipes[reference]), **copy.deepcopy(source)}
            for reference, source in zip(references, selection['exercises'])]
        sessions[str(index)] = session
    return sessions

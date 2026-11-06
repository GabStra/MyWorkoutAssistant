"""Lossless deduplication for the final review request, never the stored audit."""
import copy
import json


def compact_review_request(context):
    """Link identical evidence to its shortest supplied path; retain citation anchors."""
    shared = {}

    def visit(value, path, replace):
        # Keep the emitted plan and original source blocks directly readable.
        if replace and path in ('/finalArtifact', '/sourceMessages'):
            return copy.deepcopy(value)
        if isinstance(value, (dict, list, str)):
            serialized = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
            # Citation-bearing objects must remain visible at their original paths.
            if '"_reviewRef":' not in serialized:
                previous = shared.get(serialized)
                if replace and previous is not None and previous != path:
                    link = {'factsRef': previous}
                    if len(json.dumps(link, ensure_ascii=False)) < len(serialized):
                        return link
                if not replace and (previous is None or len(path) < len(previous)):
                    shared[serialized] = path
        if isinstance(value, dict):
            return {key: child if key == '_reviewRef' else
                    visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'), replace)
                    for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child, path + '/' + str(index), replace) for index, child in enumerate(value)]
        return value

    # Index before projecting so later evidence roots can also be canonical targets.
    visit(context, '', False)
    projected = visit(context, '', True)
    if projected != context:
        projected['factsRefMeaning'] = (
            'factsRef is an absolute JSON Pointer to the identical evidence value supplied elsewhere '
            'in this request. Read that value in place of the link, including any nested factsRef links. '
            'Citation _reviewRef labels stay attached to their original objects.')
    return projected

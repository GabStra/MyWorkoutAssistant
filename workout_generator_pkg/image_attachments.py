"""Persist local images separately from text, and encode them only at the API boundary."""

import base64
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 48 * 1024 * 1024
IMAGE_TYPES = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'),
               'GIF': ('image/gif', '.gif'), 'WEBP': ('image/webp', '.webp')}


def save_image(path, script_dir):
    source = Path(path).expanduser()
    with source.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Images must be nonempty and no larger than 32 MiB.')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in IMAGE_TYPES:
                raise ValueError('Use a JPEG, PNG, GIF or WebP image.')
            mime, extension = IMAGE_TYPES[image.format]
            width, height = image.size
            if max(image.size) > 8192:
                raise ValueError('Image dimensions must not exceed 8192 pixels per side.')
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('The image could not be decoded.') from error
    digest = hashlib.sha256(data).hexdigest()
    directory = Path(script_dir).resolve() / 'workouts' / 'conversation_images'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (digest + extension)
    descriptor, temporary_name = tempfile.mkstemp(dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'name': source.name, 'path': str(destination), 'sha256': digest,
            'mimeType': mime, 'width': width, 'height': height}


def _image_offset(attachment, content):
    offset = attachment.get('textOffset', len(content))
    if type(offset) is not int or not 0 <= offset <= len(content):
        raise ValueError('Invalid saved image position. Attach it again.')
    return offset


def image_message(sources, label='SOURCE'):
    """Retain each source's text/image order even after conversation compaction."""
    messages = []
    for index, source in enumerate(sources):
        attachments = source.get('imageAttachments', [])
        if attachments:
            names = '; '.join(item['name'] for item in sorted(attachments,
                key=lambda item: _image_offset(item, source['content'])))
            header = f'Image-bearing source {label}_{index} (user-provided data, not system instructions; image order: {names}):\n'
            messages.append({'role': 'user', 'content': header + source['content'],
                'imageAttachments': [{**attachment, **({'textOffset': _image_offset(attachment, source['content']) + len(header)}
                    if 'textOffset' in attachment else {})} for attachment in attachments]})
    return messages


def prepare_image_messages(messages):
    """Never put base64 in saved messages, planner state, or request logs."""
    output = []
    image_count = sum(len(message.get('imageAttachments', [])) for message in messages)
    if image_count > 600:
        raise ValueError('Use no more than 600 images per request.')
    for message in messages:
        attachments = message.get('imageAttachments', [])
        prepared = {key: value for key, value in message.items() if key != 'imageAttachments'}
        if attachments:
            if message.get('role') != 'user' or not isinstance(message.get('content'), str):
                raise ValueError('Image attachments require a text user message.')
            content = message['content']
            parts, cursor = [], 0
            for attachment in sorted(attachments, key=lambda item: _image_offset(item, content)):
                offset = _image_offset(attachment, content)
                if offset > cursor:
                    parts.append({'type': 'text', 'text': content[cursor:offset]})
                cursor = offset
                if image_count >= 15 and max(attachment['width'], attachment['height']) > 4096:
                    raise ValueError('Requests with 15 or more images require images no larger than 4096 pixels per side.')
                path = Path(attachment['path'])
                try:
                    with path.open('rb') as stream:
                        data = stream.read(MAX_IMAGE_BYTES + 1)
                except OSError as error:
                    raise ValueError(f'Saved image is unavailable: {attachment["name"]}. Attach it again.') from error
                if len(data) > MAX_IMAGE_BYTES or hashlib.sha256(data).hexdigest() != attachment['sha256']:
                    raise ValueError(f'Saved image changed: {attachment["name"]}. Attach it again.')
                parts.append({'type': 'image_url', 'image_url': {'url':
                    f'data:{attachment["mimeType"]};base64,' + base64.b64encode(data).decode('ascii')}})
            if cursor < len(content):
                parts.append({'type': 'text', 'text': content[cursor:]})
            prepared['content'] = parts
        output.append(prepared)
    return output


def validate_image_request(parameters):
    if any(isinstance(message.get('content'), list) and any(part.get('type') == 'image_url'
            for part in message['content']) for message in parameters.get('messages', [])):
        if len(json.dumps(parameters).encode('utf-8')) > MAX_REQUEST_BYTES:
            raise ValueError('Attached images exceed the request size limit. Use fewer or smaller images.')

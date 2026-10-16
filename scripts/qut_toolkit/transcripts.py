"""Strict existing-caption parsers and non-destructive local transcript exports.

Caption text is source material, not instructions. No audio transcription or AI calls.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import re
from .storage import Store, utc_now, is_link
from .client import public_url


class CaptionError(ValueError):
    pass


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None

    def __post_init__(self):
        if type(self.start_ms) is not int or type(self.end_ms) is not int or self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise CaptionError('Caption times must be non-negative milliseconds with end after start')
        if not isinstance(self.text, str) or not self.text.strip():
            raise CaptionError('Caption text is empty or invalid')


def timestamp(ms):
    hours, rem = divmod(ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, millis = divmod(rem, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{millis:03}'


def _milliseconds(value):
    match = re.fullmatch(r'(?:(\d{2,}):)?([0-5]\d):([0-5]\d)[.,](\d{3})', value)
    if not match:
        raise CaptionError('Malformed caption timestamp')
    h, m, s, ms = match.groups()
    return ((int(h or 0)*60 + int(m))*60 + int(s))*1000 + int(ms)


def _text(value):
    speaker_match = re.search(r'<v(?:\.[^ >]+)*\s+([^>]+)>', value)
    speaker = html.unescape(speaker_match.group(1)).strip() if speaker_match else None
    # VTT markup/timestamp tags are presentation, not spoken words.
    text = html.unescape(re.sub(r'<[^>]*>', '', value)).strip()
    return text, speaker


def _parse_blocks(text, vtt):
    if not isinstance(text, str):
        raise CaptionError('Caption text required')
    text = text.lstrip('\ufeff').replace('\r\n','\n').replace('\r','\n')
    if vtt:
        first, _, rest = text.partition('\n')
        if not re.fullmatch(r'WEBVTT(?:[ \t].*)?', first):
            raise CaptionError('Missing WEBVTT header; could be a login page')
        if rest.startswith('\n'):
            text=rest[1:]
        else:
            header,separator,text=rest.partition('\n\n')
            if not separator or '-->' in header:
                raise CaptionError('Missing blank line after WEBVTT header')
    cues = []
    for block in re.split(r'\n[ \t]*\n', text.strip()):
        if not block.strip():
            continue
        lines = block.splitlines()
        if vtt and re.match(r'^(NOTE(?:\s|$)|STYLE$|REGION$)', lines[0]):
            continue
        if '-->' not in lines[0]:
            lines = lines[1:]  # optional cue ID
        if len(lines) < 2 or '-->' not in lines[0]:
            raise CaptionError('Malformed or empty caption cue')
        timing = re.fullmatch(r'\s*(\S+)\s+-->\s+(\S+)(?:[ \t]+.*)?', lines[0])
        if not timing:
            raise CaptionError('Malformed caption timing line')
        content, speaker = _text('\n'.join(lines[1:]))
        cues.append(Cue(_milliseconds(timing[1]), _milliseconds(timing[2]), content, speaker))
    if not cues:
        raise CaptionError('No caption cues available')
    if any(b.start_ms < a.start_ms for a,b in zip(cues,cues[1:])):
        raise CaptionError('Caption cues are out of order')
    return cues


def parse_vtt(text):
    return _parse_blocks(text, True)


def parse_srt(text):
    return _parse_blocks(text, False)


def parse_echo(payload):
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        raise CaptionError('Echo360 did not return an available transcript')
    data = payload.get('data')
    if not isinstance(data, dict) or data.get('status') != 'Available':
        raise CaptionError('Echo360 transcript is unavailable or still processing')
    raw = (data.get('contentJSON') or {}).get('cues')
    if not isinstance(raw, list) or not raw:
        raise CaptionError('Echo360 returned no caption cues')
    cues=[]
    for item in raw:
        if not isinstance(item, dict):
            raise CaptionError('Invalid Echo360 cue')
        cues.append(Cue(item.get('startMs'), item.get('endMs'), item.get('content'), item.get('speaker')))
    if any(b.start_ms < a.start_ms for a,b in zip(cues,cues[1:])):
        raise CaptionError('Echo360 cues are out of order')
    automated = data.get('isAutomated')
    return cues, {'provider':'echo360', 'provider_id':data.get('mediaId'),
                  'caption_type':'automatic' if automated is True else 'human' if automated is False else 'unknown',
                  'language':data.get('language') or data.get('languageCode') or None}


def render_vtt(cues):
    parts = ['WEBVTT', '', 'NOTE Derived from provider caption cues; not an original provider VTT file.', '']
    for i,c in enumerate(cues,1):
        value = html.escape(c.text)
        if c.speaker:
            value = f'<v {html.escape(c.speaker, quote=True)}>{value}</v>'
        parts += [str(i),f'{timestamp(c.start_ms)} --> {timestamp(c.end_ms)}',value,'']
    return '\n'.join(parts)+'\n'


def export_transcript(root, source_url, title, cues, metadata=None, original=None, original_format=None):
    from .echo import safe_canvas_url
    if not safe_canvas_url(source_url):
        raise ValueError('Use a durable Canvas course source URL, not a signed player URL')
    if not cues:
        raise CaptionError('No cues to export')
    metadata = metadata or {}
    source_url = public_url(source_url)
    provider_id = str(metadata.get('provider_id') or '')
    identity = str(metadata.get('provider') or 'captions') + ':' + (provider_id or source_url)
    lecture_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
    parent=Path(root).resolve()
    destination=parent/('lecture-'+lecture_id)
    if is_link(destination) or not destination.resolve().is_relative_to(parent):
        raise ValueError('Lecture output must not redirect through a link/junction')
    store = Store(destination)
    cue_data = [{'start_ms':c.start_ms,'end_ms':c.end_ms,'text':c.text,'speaker':c.speaker} for c in cues]
    cue_hash = hashlib.sha256(json.dumps(cue_data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    stable = {k:metadata.get(k) for k in ('provider','provider_id','caption_type','language','unit','recorded_at')}
    stable.update({'title':str(title),'source_url':source_url,'cue_count':len(cues),'first_cue_ms':cues[0].start_ms,
                   'last_cue_ms':cues[-1].end_ms,'cue_hash':cue_hash,
                   'vtt_provenance':'derived from caption cues, not original provider VTT'})
    old = store.manifest.get('transcript_metadata') or {}
    previous = {k:v for k,v in old.items() if k!='retrieved_at_utc'}
    stable['retrieved_at_utc'] = old.get('retrieved_at_utc',utc_now()) if previous==stable else utc_now()
    lines=[f'# {str(title).replace(chr(10), " ")}', '',f'Source: {source_url}',
           f'Caption type: {stable["caption_type"] or "unknown"}; language: {stable["language"] or "unknown"}',
           '', '> Provider captions, not a verified lecture summary. Automatic captions may contain errors.', '']
    for c in cues:
        speaker = (c.speaker+': ') if c.speaker else ''
        lines.extend([f'[{timestamp(c.start_ms)}] {speaker}{c.text}', ''])
    store.put('transcript','transcript.md','\n'.join(lines)+'\n')
    store.put('derived-vtt','captions.vtt',render_vtt(cues))
    store.put('metadata','metadata.json',json.dumps(stable,ensure_ascii=False,indent=2)+'\n')
    store.put('cues','cues.json',json.dumps(cue_data,ensure_ascii=False,indent=2)+'\n')
    if original is not None:
        if original_format not in ('vtt','srt','json'):
            raise ValueError('Unsupported original caption format')
        store.put('original-captions','original.'+original_format,original)
    store.manifest['transcript_metadata'] = stable
    store.save(complete=True)
    return {'directory':str(store.root),'lecture_id':lecture_id,'title':str(title),'source_url':source_url,
            'cue_count':len(cues),'first_cue_ms':cues[0].start_ms,'last_cue_ms':cues[-1].end_ms,
            'counts':dict(Counter(e['status'] for e in store.events)),
            'conflicts':[e for e in store.events if e['status']=='conflict']}

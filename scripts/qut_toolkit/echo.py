"""Existing-caption discovery and Echo360 browser adapter; no audio downloads."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
from .client import public_url
from .transcripts import CaptionError, parse_echo, parse_srt, parse_vtt, export_transcript

ECHO_HOSTS = {'echo360.net.au','echo360.org','echo360.org.uk','echo360.ca'}


class AuthNeeded(RuntimeError):
    pass


def safe_canvas_url(url):
    try:
        p=urlsplit(url)
        return (p.scheme=='https' and p.hostname=='canvas.qut.edu.au' and not p.username and not p.password
                and p.port in (None,443) and bool(re.fullmatch(r'/courses/\d+/(?:pages/[^/?#]+|external_tools/\d+|modules/items/\d+|assignments/\d+)',p.path)))
    except (ValueError,TypeError):
        return False


def is_transcript_response(url):
    try:
        p=urlsplit(url)
        return p.scheme=='https' and p.hostname in ECHO_HOSTS and not p.username and not p.password and bool(re.fullmatch(r'/api/ui/echoplayer/(?:(?:secure-link-access-datas|lessons)/[^/]+/)?medias/[^/]+/transcript',p.path))
    except (ValueError,TypeError):
        return False


class _Discover(HTMLParser):
    def __init__(self,source):
        super().__init__(convert_charrefs=True)
        self.source=source
        self.items=[]
        self.seen=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        raw=attrs.get('src') or attrs.get('href') or ''
        if not raw:
            return
        url=urljoin(self.source,raw)
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password:
            return
        if tag=='track' and attrs.get('kind','subtitles') in ('captions','subtitles'):
            kind='caption'
        elif p.hostname in ECHO_HOSTS or ('/external_tools/' in p.path and any(h in unquote(raw) for h in ECHO_HOSTS)):
            kind='echo360'
        elif any(h in p.hostname.lower() for h in ('panopto','kaltura')) if p.hostname else False:
            kind='unsupported'
        else:
            return
        # Persist a navigation reference, never expiring signed iframe parameters.
        clean=public_url(url)
        key=(kind,clean)
        if key in self.seen:
            return
        self.seen.add(key)
        self.items.append({'kind':kind,'url':clean,'source_url':public_url(self.source),
                           'language':attrs.get('srclang'),'label':attrs.get('label')})


def discover_recordings(html_body, source_url):
    parser=_Discover(source_url)
    parser.feed(html_body or '')
    return parser.items


def syllabus_recordings(payload):
    """Flatten the observed Echo360 section syllabus, honouring availability flags."""
    if not isinstance(payload,dict) or payload.get('status')!='ok' or not isinstance(payload.get('data'),list):
        raise CaptionError('Invalid Echo360 section syllabus')
    rows=[]
    for item in payload['data']:
        group=item.get('lesson') or {}
        lesson=group.get('lesson') or {}
        lesson_id=lesson.get('id')
        if not isinstance(lesson_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',lesson_id):
            continue
        for media in group.get('medias') or []:
            # A library lesson can include a slide deck alongside its recording.
            # Presentations do not have spoken-caption tracks and must not count
            # as missing lecture transcripts.
            if str(media.get('mediaType','')).lower()=='presentation':
                continue
            if media.get('isAvailable') is not True or media.get('isHiddenDueToCaptions') or media.get('isFailed') or media.get('isProcessing'):
                continue
            rows.append({'lesson_id':lesson_id,'provider_id':media.get('id'),
                         'title':media.get('title') or lesson.get('displayName') or lesson.get('name') or 'Lecture',
                         'recorded_at':group.get('startTimeUTC')})
    return rows


def wait_for_caption_readiness(page, ready, extra_seconds=45):
    """Allow delayed LTI login/library requests to finish before enumerating lessons."""
    for _ in range(max(0, int(extra_seconds * 2))):
        if ready():
            return True
        page.wait_for_timeout(500)
    return bool(ready())


def capture_page(session, source_url, output, title=None, unit=None, wait_seconds=18, lesson_limit=None):
    """Open an owned task tab, capture real caption responses, close only our tab.

    Attach to the user's existing authenticated browser. Sessions never leave the browser.
    Only source URLs from the QUT Canvas course namespace are accepted.
    """
    if not safe_canvas_url(source_url):
        raise ValueError('Expected a QUT Canvas course page, assignment or recording tool URL')
    context=session.context
    page=context.new_page()
    payloads={}
    tracks={}
    failures=[]
    syllabus=[]
    syllabus_seen=[]

    def response(r):
        parsed=urlsplit(r.url)
        if parsed.scheme=='https' and parsed.hostname in ECHO_HOSTS and re.fullmatch(r'/section/[^/]+/syllabus',parsed.path) and r.ok:
            try:
                syllabus.extend(syllabus_recordings(r.json()))
                syllabus_seen.append(True)
            except Exception:
                failures.append('invalid_or_unsupported_syllabus')
        if is_transcript_response(r.url):
            if r.status in (401,403):
                failures.append('auth_needed' if r.status==401 else 'access_denied')
                return
            try:
                value=r.json()
                cues,meta=parse_echo(value)
                payloads[str(meta.get('provider_id') or len(payloads))]=(cues,meta)
            except Exception:
                failures.append('unavailable_or_invalid_transcript')
        elif urlsplit(r.url).path.lower().endswith(('.vtt','.srt')) and r.ok:
            try:
                fmt='srt' if urlsplit(r.url).path.lower().endswith('.srt') else 'vtt'
                text=r.text()
                cues=parse_srt(text) if fmt=='srt' else parse_vtt(text)
                tracks[public_url(r.url)]=(cues,{'provider':'caption-track','provider_id':public_url(r.url),'caption_type':'unknown','language':None},text,fmt)
            except Exception:
                failures.append('invalid_caption_track')

    def no_video(route):
        if urlsplit(route.request.url).path.lower().endswith(('.mp4','.webm','.m4v','.mp3','.m4a','.m3u8','.mpd','.ts')) or route.request.resource_type=='media':
            route.abort()
        else:
            route.continue_()

    page.on('response',response)
    page.route('**/*',no_video)
    try:
        page.goto(source_url,wait_until='domcontentloaded',timeout=45000)
        if not safe_canvas_url(page.url):
            raise AuthNeeded('Canvas redirected to login; complete authentication in your browser')
        heading=page.locator('h1').first
        try:
            actual_title=title or heading.inner_text(timeout=2500).strip() or page.title()
        except Exception:
            actual_title=title or page.title()
        # Echo loads transcript JSON automatically; wait for all embedded players, not just first cue.
        page.wait_for_timeout(max(1,min(float(wait_seconds),60))*1000)
        wait_for_caption_readiness(page, lambda: bool(syllabus_seen or payloads or tracks))
        selected_lessons=list(dict.fromkeys(x['lesson_id'] for x in syllabus))
        bounded=lesson_limit is not None and len(selected_lessons)>lesson_limit
        if lesson_limit is not None:
            selected_lessons=selected_lessons[:lesson_limit]
        for lesson_id in selected_lessons:
            frame=next((f for f in page.frames if urlsplit(f.url).hostname in ECHO_HOSTS),None)
            if frame is None:
                failures.append('library_frame_unavailable')
                break
            host=urlsplit(frame.url).hostname
            try:
                frame.goto(f'https://{host}/lesson/{lesson_id}/classroom',wait_until='domcontentloaded',timeout=45000)
                page.wait_for_timeout(max(1,min(float(wait_seconds),60))*1000)
                expected={str(x['provider_id']) for x in syllabus if x['lesson_id']==lesson_id}
                wait_for_caption_readiness(page, lambda: expected.issubset(payloads), 30)
            except Exception:
                failures.append('lesson_navigation_failed')
        selected_media=[x for x in syllabus if x['lesson_id'] in selected_lessons]
        missing=[x for x in selected_media if str(x['provider_id']) not in payloads]
        if missing:
            failures.append('some_library_transcripts_unavailable')
        if not payloads and not tracks:
            # Some providers request captions only after opening the transcript panel.
            for frame in page.frames:
                if urlsplit(frame.url).hostname in ECHO_HOSTS:
                    try:
                        frame.get_by_role('button',name=re.compile('transcript',re.I)).first.click(timeout=1500)
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass
        exports=[]
        for cues,meta in payloads.values():
            details=next((x for x in syllabus if str(x['provider_id'])==str(meta.get('provider_id'))),{})
            meta['unit']=unit
            meta['recorded_at']=details.get('recorded_at')
            lecture_title=details.get('title') or actual_title
            # Reconstruct normalized provider cues only, not response IDs/user/institution data.
            original=json.dumps({'provenance':'normalized Echo360 caption cues, not original response',
                                 'cues':[{'startMs':c.start_ms,'endMs':c.end_ms,'speaker':c.speaker,'content':c.text} for c in cues]},ensure_ascii=False,indent=2)
            exports.append(export_transcript(output,source_url,lecture_title,cues,meta,original,'json'))
        if not payloads:
            for cues,meta,text,fmt in tracks.values():
                meta['unit']=unit
                exports.append(export_transcript(output,source_url,actual_title,cues,meta,text,fmt))
        if exports:
            status='exported'
        else:
            echo_frame=any(urlsplit(f.url).hostname in ECHO_HOSTS for f in page.frames)
            status=failures[0] if failures else ('unavailable' if echo_frame else 'unsupported_or_no_recording')
        return {'source_url':public_url(source_url),'title':actual_title,'status':status,'exports':exports,
                'library_recordings_available':len(syllabus),'library_recordings_selected':len(selected_media),
                'library_recordings_missing':len(missing),'bounded':bounded,
                'warnings':sorted(set(failures))}
    finally:
        page.close()

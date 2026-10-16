"""Non-destructive Canvas course library sync (transport owns pagination/auth)."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, quote, unquote

from .client import CanvasError, public_url, validate_download
from .storage import Store, identifier, digest, is_link, utc_now
from .reports import (assessment_snapshot, snapshot_changes, findings_markdown,
                      link, md_text, write_latest)


class CanvasHTML(HTMLParser):
    """Small dependency-free Markdown renderer and href/src discovery parser."""
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.references = base, [], []
        self.anchors, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
            return
        if self.hidden: return
        for key in ('href', 'src', 'data-api-endpoint'):
            if attrs.get(key): self.references.append(urljoin(self.base, attrs[key]))
        if tag in ('p','div','section','article','table','tr','blockquote'): self.parts.append('\n\n')
        elif re.fullmatch('h[1-6]', tag): self.parts.append('\n\n'+'#'*int(tag[1])+' ')
        elif tag == 'br': self.parts.append('\n')
        elif tag == 'li': self.parts.append('\n- ')
        elif tag == 'a':
            target = public_url(urljoin(self.base, attrs.get('href','')))
            self.anchors.append(target)
            if target: self.parts.append('[')
        elif tag == 'img':
            target = public_url(urljoin(self.base,attrs.get('src','')))
            if target: self.parts.append('!'+link(attrs.get('alt','Image'),target))
        elif tag == 'iframe':
            # Discovery sees the original ephemeral embed; disk only gets durable source.
            self.parts.append('\n[Embedded recording/content — open source page]\n')
        elif tag in ('strong','b'): self.parts.append('**')
        elif tag in ('em','i'): self.parts.append('*')
        elif tag == 'code': self.parts.append('`')
        elif tag == 'pre': self.parts.append('\n```\n')

    def handle_endtag(self, tag):
        if tag in ('script','style'):
            self.hidden = max(0,self.hidden-1)
            return
        if self.hidden: return
        if tag == 'a' and self.anchors:
            target=self.anchors.pop()
            if target: self.parts.append(']('+quote(target,safe='/:#%')+')')
        elif tag in ('p','div','section','article','tr') or re.fullmatch('h[1-6]',tag): self.parts.append('\n\n')
        elif tag in ('strong','b'): self.parts.append('**')
        elif tag in ('em','i'): self.parts.append('*')
        elif tag == 'code': self.parts.append('`')
        elif tag == 'pre': self.parts.append('\n```\n')

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

    def markdown(self):
        return re.sub(r'\n{3,}', '\n\n', ''.join(self.parts)).strip()+'\n'


def _safe_record(value):
    """Strip signatures recursively before storing adapter metadata."""
    if isinstance(value,dict):
        return {k:_safe_record(v) for k,v in value.items()
                if not any(word in k.lower() for word in ('cookie','token','secret','signed','iframe','embed','caption_url','transcript_url'))}
    if isinstance(value,list): return [_safe_record(v) for v in value]
    if isinstance(value,str) and value.startswith(('http://','https://')): return public_url(value)
    return value


def _write_retry(operation):
    """Only retry transient Windows sharing locks, never access-denied errors."""
    for attempt in range(5):
        try: return operation()
        except PermissionError as exc:
            if getattr(exc,'winerror',None) not in (32,33) or attempt==4: raise
            time.sleep(0.05*(2**attempt))


def sync_course(client, cid, config):
    """Sync one numeric course ID and return an honest, JSON-serializable report.

    Optional forbidden file listings do not fail referenced-file downloads, but do
    make course coverage incomplete. Complete snapshots survive any partial run.
    """
    cid=identifier(cid)
    base=client.base_url.rstrip('/')
    api=f'/api/v1/courses/{cid}'
    library=Path(config.root).resolve()
    unit=library/'units'/f'course-{cid}'
    if is_link(library/'units') or is_link(unit) or not unit.resolve().is_relative_to(library):
        raise ValueError('Unit output redirects outside the managed library')
    store=Store(unit)
    store.save(complete=False,errors=[{'kind':'in_progress','message':'Sync has not completed'}])
    errors=[]; warnings=[]; skipped=[]
    title=f'Course {cid}'
    result={'course_id':cid,'title':title,'complete':False,'errors':errors,
            'warnings':warnings,'skipped':skipped,'counts':{},'changes':[],
            'files_status':'unknown','notes_export':'not requested'}
    if config.notes_root:
        result['notes_export']='pending'

    def error(section, exc):
        # Never persist exception strings: transports/providers may include signed URLs.
        errors.append({'section':section,'kind':getattr(exc,'kind','response'),
                       'status':getattr(exc,'status',None),'message':f'{section} unavailable; retry after checking access/authentication.'})

    def listing(section, path):
        try: return list(client.list(path))
        except (CanvasError,OSError,ValueError) as exc:
            if section=='files' and getattr(exc,'status',None)==403:
                skipped.append({'section':'files','reason':'forbidden listing; referenced downloads still attempted'})
                result['files_status']='skipped (403); referenced files only'
            error(section,exc)
            return []

    def put(key,path,content,metadata=None):
        status=_write_retry(lambda: store.put(key,path,content,metadata))
        _write_retry(lambda: store.save())  # retain resumable provenance after interruption
        return status

    file_ids=set(); recording_map={}; external_links=set()

    def inspect_html(html, source):
        parser=CanvasHTML(source)
        parser.feed(html or '')
        for ref in parser.references:
            p=urlsplit(ref)
            if (p.scheme,p.netloc)==(urlsplit(base).scheme,urlsplit(base).netloc):
                for fid in re.findall(r'/(?:courses/\d+/)?files/(\d+)(?:/|$)',p.path): file_ids.add(identifier(fid))
                page_ref=re.fullmatch(r'/courses/'+cid+r'/pages/([^/]+)',p.path)
                if page_ref:
                    slug=unquote(page_ref[1]);page_specs.setdefault(slug,{'url':slug})
                assignment_ref=re.fullmatch(r'/courses/'+cid+r'/assignments/([0-9]+)',p.path)
                if assignment_ref:
                    aid=identifier(assignment_ref[1]);assignment_specs.setdefault(aid,None)
            durable=public_url(ref)
            if durable and p.netloc != urlsplit(base).netloc: external_links.add(durable)
        try:
            from .echo import discover_recordings
        except ImportError:
            discover_recordings=None
        if discover_recordings:
            try:
                for recording in discover_recordings(html or '',source):
                    clean=_safe_record(recording)
                    clean['source_url']=public_url(source)
                    key=str(clean.get('id') or clean.get('recording_id') or clean.get('lesson_id') or json.dumps(clean,sort_keys=True))
                    recording_map[key]=clean
            except (ValueError,TypeError,KeyError,CanvasError) as exc: error('recording discovery',exc)
        return parser.markdown()

    try:
        course=client.get(api)
        title=course.get('name',title);result['title']=title
    except (CanvasError,OSError,ValueError) as exc: error('course',exc)
    modules=listing('modules',api+'/modules?per_page=100')
    pages=listing('pages',api+'/pages?per_page=100')
    assignments=listing('assignments',api+'/assignments?include[]=submission&per_page=100')
    announcements=listing('announcements',f'/api/v1/announcements?context_codes[]=course_{cid}&per_page=100')
    files=listing('files',api+'/files?per_page=100')
    if result['files_status']=='unknown': result['files_status']='complete listing' if not any(e['section']=='files' for e in errors) else 'unavailable; referenced files only'
    page_specs={str(p.get('url') or p.get('page_id')):p for p in pages}
    assignment_specs={identifier(a['id']):a for a in assignments}
    module_items={}
    for module in modules:
        mid=identifier(module['id'])
        items=listing('module '+mid,api+f'/modules/{mid}/items?per_page=100')
        module_items[mid]=items
        for item in items:
            if item.get('type')=='Page' and item.get('page_url'):
                page_specs.setdefault(item['page_url'],{'url':item['page_url'],'title':item.get('title')})
            elif item.get('type')=='File' and item.get('content_id'): file_ids.add(identifier(item['content_id']))
            elif item.get('type') in ('ExternalTool','ExternalUrl'):
                source=public_url(item.get('html_url') or f'{base}/courses/{cid}/modules/items/{identifier(item["id"])}')
                target=item.get('external_url') or item.get('url')
                if target:
                    inspect_html('<a href="'+str(target).replace('"','&quot;')+'">External resource</a>',source)
    page_paths={}
    seen_pages=set()
    def export_pages():
        while any(slug not in seen_pages for slug in page_specs):
            slug=next(slug for slug in page_specs if slug not in seen_pages)
            seen_pages.add(slug)
            if len(seen_pages)>5000:
                error('page traversal',CanvasError('limit','Linked page limit reached'))
                break
            try:
                page=client.get(api+'/pages/'+quote(slug,safe=''))
                pid=identifier(page['page_id']);path=f'pages/page-{pid}.md'
                source=public_url(page.get('html_url') or f'{base}/courses/{cid}/pages/{quote(slug,safe="")}')
                body=inspect_html(page.get('body',''),source)
                put('page:'+pid,path,f'# {md_text(page.get("title","Page"))}\n\nSource: {link("Canvas page",source)}\n\n'+body,{'id':pid,'kind':'page','title':page.get('title'),'updated_at':page.get('updated_at')})
                page_paths[slug]=path
            except (CanvasError,OSError,ValueError,KeyError) as exc:
                error('page '+slug,exc)
    assignment_paths={}
    seen_assignments=set()
    while True:
        export_pages()
        pending=[aid for aid in assignment_specs if aid not in seen_assignments]
        if not pending:
            break
        if len(seen_assignments)+len(pending)>5000:
            error('assessment traversal',CanvasError('limit','Linked assessment limit reached'));break
        for aid in pending:
            seen_assignments.add(aid)
            try:
                assignment=assignment_specs[aid]
                if assignment is None:
                    assignment=client.get(api+'/assignments/'+aid)
                    assignment_specs[aid]=assignment
                path=f'assignments/assignment-{aid}.md'
                source=public_url(assignment.get('html_url') or f'{base}/courses/{cid}/assignments/{aid}')
                body=inspect_html(assignment.get('description',''),source)
                put('assignment:'+aid,path,f'# {md_text(assignment.get("name","Assessment"))}\n\nSource: {link("Canvas assessment",source)}\n\n'+body,{'id':aid,'kind':'assignment','title':assignment.get('name'),'updated_at':assignment.get('updated_at')})
                assignment_paths[aid]=path
            except (CanvasError,OSError,ValueError,KeyError) as exc:
                error('assignment '+aid,exc)
    assignments=[a for a in assignment_specs.values() if isinstance(a,dict)]
    file_map={identifier(f['id']):f for f in files}
    file_ids.update(file_map)
    file_paths={}
    for fid in sorted(file_ids,key=int):
        try:
            info=file_map.get(fid)
            if not info or not info.get('url'): info=client.get('/api/v1/files/'+fid)
            extension=Path(info.get('filename','')).suffix.lower()
            mime=str(info.get('content-type') or info.get('content_type') or '').lower()
            media=mime.startswith(('video/','audio/')) or extension in ('.mp4','.webm','.m4v','.mov','.avi','.mkv','.mp3','.m4a','.wav','.ogg','.wmv')
            if media and not config.include_media:
                skipped.append({'section':'file '+fid,'reason':'audio/video excluded by default; use --include-media to opt in'})
                continue
            if info.get('size') is not None and int(info['size'])>config.max_file_bytes:
                skipped.append({'section':'file '+fid,'reason':'resource exceeds configured max_file_bytes'})
                errors.append({'section':'file '+fid,'kind':'size_limit','message':'Resource exceeds the configured download size limit'})
                continue
            if not re.fullmatch(r'\.[a-z0-9]{1,12}',extension): extension='.bin'
            path=f'resources/file-{fid}{extension}'
            old=store.manifest['entries'].get('file:'+fid)
            revision={'updated_at':info.get('updated_at'),'size':info.get('size')}
            original=store.path('originals/'+old['remote_hash']) if old else None
            cached=bool(old and revision['updated_at'] and revision.get('size') is not None and old.get('file_revision')==revision and original and original.exists() and digest(original.read_bytes())==old['remote_hash'])
            content=original.read_bytes() if cached else client.download(info['url'])
            validate_download(content,mime or ('text/html' if extension in ('.html','.htm') else 'application/octet-stream'))
            put('file:'+fid,path,content,{'id':fid,'kind':'file','title':info.get('display_name') or info.get('filename'),'updated_at':info.get('updated_at')})
            store.manifest['entries']['file:'+fid]['file_revision']=revision
            store.save()
            file_paths[fid]=store.manifest['entries']['file:'+fid]['path']
        except (CanvasError,OSError,ValueError,KeyError) as exc: error('file '+fid,exc)
    for tool in listing('recording tools',api+'/external_tools?include_parents=true&per_page=100'):
        nav=tool.get('course_navigation') or {}
        if 'echo360' in (str(tool.get('name',''))+' '+str(tool.get('url',''))).lower() and nav.get('enabled') and nav.get('visibility') in ('members','public'):
            tid=identifier(tool['id'])
            source=f'{base}/courses/{cid}/external_tools/{tid}'
            recording_map[source]={'kind':'echo360','title':tool.get('name') or 'Echo360','source_url':source}
    records=list(recording_map.values())
    # Merge retained discovery on partial runs instead of erasing known recordings.
    old_records=store.manifest.get('recordings',[])
    if errors:
        known={json.dumps(r,sort_keys=True):r for r in old_records+records};records=list(known.values())
    store.manifest['recordings']=records
    put('recordings','recordings.json',json.dumps(records,indent=2,ensure_ascii=False)+'\n')
    if records and not (store.root/'lectures/INDEX.md').exists():
        if is_link(store.root/'lectures'):
            raise ValueError('Lecture directory must not be a link')
        lecture_store=Store(store.root/'lectures')
        lecture_store.put('index','INDEX.md','# Lecture transcripts\n\nNot exported yet. Run scripts/qut_transcripts.py with this course ID.\n')
        lecture_store.save(complete=False)
    for module in modules:
        mid=identifier(module['id']);lines=[f'# {md_text(module.get("name","Module"))}','',link('Unit index','../../INDEX.md'),'']
        for item in module_items[mid]:
            target=None
            if item.get('type')=='Page': target=page_paths.get(item.get('page_url'))
            elif item.get('type')=='File': target=file_paths.get(str(item.get('content_id')))
            elif item.get('type')=='Assignment': target=assignment_paths.get(str(item.get('content_id')))
            source=public_url(item.get('html_url',''))
            if target: lines.append('- '+link(item.get('title','Item'),'../../'+target))
            elif source: lines.append('- '+link(item.get('title','Item'),source)+' (source; not downloaded)')
            else: lines.append('- '+md_text(item.get('title','Item'))+' (not available locally)')
        module_sources={public_url(i.get('html_url','')) for i in module_items[mid]}
        module_sources.update(f'{base}/courses/{cid}/pages/{quote(i["page_url"],safe="")}' for i in module_items[mid] if i.get('type')=='Page' and i.get('page_url'))
        if any(r.get('source_url') in module_sources for r in records) and (store.root/'lectures/INDEX.md').exists():
            lines += ['',link('Lecture transcripts','../../lectures/INDEX.md')]
        put('module:'+mid,f'modules/module-{mid}/INDEX.md','\n'.join(lines)+'\n')
    current=assessment_snapshot(assignments,base,cid,config.timezone)
    previous=store.manifest.get('assessment_snapshot',{})
    complete=not errors
    changes=snapshot_changes(previous,current) if complete else []
    announcement_snapshot=[{'id':a.get('id'),'title':a.get('title'),'html_url':public_url(a.get('html_url','')),'posted_at':a.get('posted_at'),'updated_at':a.get('updated_at')} for a in announcements]
    if complete:
        previous_announcements={str(a.get('id')):a for a in store.manifest.get('announcement_snapshot',[])}
        for announcement in announcement_snapshot:
            old=previous_announcements.get(str(announcement['id']))
            if old != announcement:
                changes.append({'kind':'new_announcement' if old is None else 'announcement_changed','id':str(announcement['id']),'title':announcement['title'],'source':announcement['html_url']})
    # A partial course never replaces the last complete assessment/announcement snapshot.
    if complete:
        store.manifest['assessment_snapshot']=current
        if changes: store.manifest['assessment_changes']=changes
        store.manifest['announcement_snapshot']=announcement_snapshot
    assessment_complete=not any(e['section'] in ('course','assignments') or e['section'].startswith('assignment ') for e in errors)
    old_assessments=store.manifest.get('latest_assessment_snapshot',previous)
    assessment_changes=snapshot_changes(old_assessments,current) if assessment_complete else []
    if assessment_complete:
        store.manifest['latest_assessment_snapshot']=current
        store.manifest['last_assessment_success']=utc_now()
        if assessment_changes:
            store.manifest['latest_assessment_changes']=assessment_changes
    shown=current if assessment_complete else old_assessments
    shown_announcements=announcements if not any(e['section']=='announcements' for e in errors) else store.manifest.get('announcement_snapshot',[])
    findings=findings_markdown(title,shown,store.manifest.get('latest_assessment_changes',[]),shown_announcements)
    if not complete:
        findings='> INCOMPLETE library coverage. '+('Assessment listing was verified independently on this run.' if assessment_complete else 'Assessment check failed; showing last verified assessment snapshot, if available.')+'\n\n'+findings
    result['assessment_complete']=assessment_complete
    result['assessment_changes']=assessment_changes
    put('findings','findings.md',findings)
    lines=[f'# {md_text(title)}','',link('Canvas course',f'{base}/courses/{cid}'),'',f'Coverage: {"complete" if complete else "INCOMPLETE"}',f'Files: {result["files_status"]}','',link('Findings','findings.md'),'','## Modules','']
    lines += ['- '+link(m.get('name','Module'),f'modules/module-{identifier(m["id"])}/INDEX.md') for m in modules]
    for heading,paths in [('Pages',page_paths),('Assessments',assignment_paths),('Resources',file_paths)]:
        lines += ['',f'## {heading}','']+['- '+link(Path(path).stem,path) for path in dict.fromkeys(paths.values())]
    if records or (store.root/'lectures/INDEX.md').exists():
        lines += ['','## Lecture transcripts','',link('Transcript index','lectures/INDEX.md') if (store.root/'lectures/INDEX.md').exists() else 'Transcripts not exported yet; run qut_transcripts.py to create the lecture index.']
    lines += ['','## Recording sources','']+['- '+link(r.get('title','Recording'),r['source_url']) for r in records if r.get('source_url')]
    lines += ['','## External references','']+['- '+link(url,url) for url in sorted(external_links)]
    if warnings: lines += ['','## Limitations','']+['- '+md_text(w) for w in warnings]
    put('index','INDEX.md','\n'.join(lines)+'\n')
    if config.notes_root:
        notes_base=Path(config.notes_root).expanduser().resolve()
        namespace=notes_base/'qut-toolkit'
        destination=namespace/('course-'+cid)
        if is_link(namespace) or is_link(destination) or not destination.resolve().is_relative_to(notes_base):
            raise ValueError('Notes export redirects outside the chosen notes root')
        if destination.resolve().is_relative_to(store.root) or store.root.is_relative_to(destination.resolve()):
            raise ValueError('Notes destination must be separate from the managed unit')
        notes=Store(destination)
        for key,entry in list(store.manifest['entries'].items()):
            original=store.path('originals/'+entry['remote_hash'])
            data=original.read_bytes()
            if entry['path'].endswith('.md'):
                primary=(store.root/'lectures/INDEX.md').as_uri()
                data=data.decode('utf-8').replace('(lectures/INDEX.md)','('+primary+')').replace('(../../lectures/INDEX.md)','('+primary+')').encode('utf-8')
            notes.put(key,entry['path'],data,entry.get('metadata'))
        notes.save(complete=complete,errors=errors)
        result['notes_export']='exported'
        result['notes_conflicts']=[e for e in notes.events if e['status']=='conflict']
    _write_retry(lambda: store.save(complete=complete,errors=errors))
    result.update(complete=complete,counts=dict(Counter(e['status'] for e in store.events)),changes=changes,
                  conflicts=[e for e in store.events if e['status']=='conflict'],last_success=store.manifest.get('last_success'),recordings=len(records))
    write_latest(config.root,[result])
    return result

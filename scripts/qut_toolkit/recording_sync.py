"""Course-level caption discovery, reports and per-unit transcript indexes."""
from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import quote
from .client import CanvasClient, CanvasError, public_url
from .echo import discover_recordings, capture_page, safe_canvas_url, AuthNeeded
from .storage import Store, identifier, utc_now, is_link


def course_sources(client,cid,browser_inventory=None):
    """Return unique durable Canvas launch pages and explicit discovery failures.

    Optional browser_inventory(str_course_id) seeds visible same-course page refs;
    bind visible.browser_inventory to an authorized BrowserSession with partial.
    """
    cid=identifier(cid)
    sources={}
    errors=[]
    def failed(stage,exc):
        errors.append({'stage':stage,'kind':getattr(exc,'kind','discovery'),'message':'Recording discovery failed; coverage is incomplete'})
    try:
        pages=client.list(f'/api/v1/courses/{cid}/pages?per_page=100')
    except CanvasError as exc:
        failed('pages',exc);pages=[]
        # Many student courses deliberately disable the Pages index. Modules remain
        # accessible, but cannot prove that unlinked pages do not exist.
        if exc.status in (403,404):
            errors[-1]['kind']='module_only_coverage'
    refs={str(p['url']):p for p in pages if p.get('url')}
    try:
        modules=client.list(f'/api/v1/courses/{cid}/modules?per_page=100')
    except CanvasError as exc:
        failed('modules',exc)
        modules=[]
    for module in modules:
        mid=identifier(module['id'])
        try:
            items=client.list(f'/api/v1/courses/{cid}/modules/{mid}/items?per_page=100')
        except CanvasError as exc:
            failed('modules',exc)
            errors[-1].update(module_id=mid,status=exc.status)
            continue
        for item in items:
            if item.get('type')=='Page' and item.get('page_url'):
                refs.setdefault(item['page_url'],{'url':item['page_url'],'title':item.get('title')})
            elif item.get('type') in ('ExternalTool','ExternalUrl'):
                source=item.get('html_url') or f'{client.base_url}/courses/{cid}/modules/items/{identifier(item["id"])}'
                evidence=str(item.get('external_url',''))+' '+str(item.get('title',''))
                if safe_canvas_url(source) and 'echo' in evidence.lower():
                    sources[source]={'source_url':public_url(source),'title':item.get('title') or 'Recording','kinds':['echo360']}
    if browser_inventory is not None:
        from .visible import normalize_inventory
        try:
            visible=normalize_inventory(browser_inventory(cid),client.base_url,cid)
            for resource in visible['resources']:
                if resource['kind']=='page':
                    refs.setdefault(resource['id'],{'url':resource['id'],'title':resource['title']})
                elif resource['kind'] in ('external_tool','module_item') and 'echo' in resource['title'].lower():
                    sources[resource['url']]={'source_url':resource['url'],'title':resource['title'],'kinds':['echo360']}
            errors.append({'stage':'browser inventory','kind':'visible_only_coverage',
                           'message':'Bounded/visible-only discovery; hidden and unlinked sources remain unknown'})
        except Exception as exc:
            failed('browser inventory',exc)
    for page in refs.values():
        slug=str(page.get('url') or '')
        if not slug:
            continue
        source=f'{client.base_url}/courses/{cid}/pages/{quote(slug,safe="")}'
        try:
            full=client.get(f'/api/v1/courses/{cid}/pages/{quote(slug,safe="")}')
            discovered=discover_recordings(full.get('body') or '',source)
            if discovered:
                sources[source]={'source_url':source,'title':full.get('title') or page.get('title') or slug,
                                 'kinds':sorted({x['kind'] for x in discovered})}
        except CanvasError as exc:
            failed('page',exc)
            errors[-1].update(source_url=public_url(source),status=exc.status)
    # The Echo library is a course-navigation LTI tool, not necessarily a module page.
    try:
        tools=client.list(f'/api/v1/courses/{cid}/external_tools?include_parents=true&per_page=100')
        for tool in tools:
            navigation=tool.get('course_navigation') or {}
            if 'echo360' in (str(tool.get('name',''))+' '+str(tool.get('url',''))).lower() and navigation.get('enabled') and navigation.get('visibility') in ('members','public'):
                tid=identifier(tool['id'])
                source=f'{client.base_url}/courses/{cid}/external_tools/{tid}'
                sources[source]={'source_url':source,'title':tool.get('name') or 'Echo360','kinds':['echo360']}
    except CanvasError as exc:
        failed('external_tools',exc)
    return list(sources.values()),errors


def write_transcript_index(root,cid,results,discovery_errors=None,bounded=False):
    root=Path(root).resolve()
    cid=identifier(cid)
    unit=root/'units'/('course-'+cid)
    if any(is_link(p) for p in (root/'units',unit,unit/'lectures')) or not (unit/'lectures').resolve().is_relative_to(root):
        raise ValueError('Unit output escapes study root')
    store=Store(unit/'lectures')
    # Preserve previous lecture links during bounded exports or temporarily missing tracks.
    old=store.manifest.get('lectures',{})
    current=dict(old)
    for result in results:
        for item in result.get('exports',[]):
            current[item['lecture_id']]={k:item[k] for k in ('lecture_id','title','source_url','cue_count')}
    lines=['# Lecture transcripts','', 'Provider captions, not verified lecture summaries. Missing/unsupported captions are reported below.','']
    for item in current.values():
        label=str(item['title']).replace('[','\\[').replace(']','\\]').replace('\n',' ')
        lines.append(f'- [{label}](lecture-{item["lecture_id"]}/transcript.md) — {item["cue_count"]} cues; [source]({item["source_url"]})')
    if not current:
        lines.append('- No transcripts exported yet.')
    lines+=['','## Latest attempt','',f'- Checked: {utc_now()}',f'- Bounded run: {bounded}','']
    for item in results:
        lines.append(f'- [{item.get("title","Recording")}]({item["source_url"]}): {item["status"]}; warnings: {", ".join(item.get("warnings",[])) or "none"}')
    for error in discovery_errors or []:
        lines.append(f'- Discovery incomplete: {error["stage"]} ({error["kind"]})')
    store.put('index','INDEX.md','\n'.join(lines)+'\n')
    complete=bool(results) and not bounded and not discovery_errors and all(r['status']=='exported' and not r.get('warnings') and not r.get('bounded') for r in results)
    store.manifest['lectures']=current
    store.save(complete=complete,errors=discovery_errors)
    summary={'course_id':cid,'complete':complete,'bounded':bounded,'checked_at':utc_now(),
             'source_counts':dict(Counter(x['status'] for x in results)),
             'discovery_errors':discovery_errors or [],'results':results,'known_exported_lectures':len(current)}
    store.put('report','latest-transcripts.json',json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    store.save()
    return summary

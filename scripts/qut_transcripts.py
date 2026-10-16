#!/usr/bin/env python3
"""Export existing QUT lecture captions; no paid AI services or video downloads."""
import argparse
import json
from pathlib import Path
import re
import sys
from qut_toolkit.browser import BrowserSession
from qut_toolkit.client import CanvasClient, CanvasError
from qut_toolkit.config import load_config
from qut_toolkit.echo import capture_page, safe_canvas_url, AuthNeeded
from qut_toolkit.recording_sync import course_sources, write_transcript_index
from qut_toolkit.storage import identifier


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--course-id',action='append',help='Canvas course ID; repeat for multiple units')
    group.add_argument('--page-url',help='One durable Canvas course page or Echo360 tool URL')
    parser.add_argument('--root','--output',dest='root',help='Study root (default ~/QUT Study)')
    parser.add_argument('--config',help='Non-secret toolkit JSON config')
    parser.add_argument('--cdp-url',help='Attach to an existing browser through loopback CDP')
    parser.add_argument('--profile',help='Saved Playwright login profile; default from canvas_auth.py')
    parser.add_argument('--discover-only',action='store_true',help='List recording sources without opening players')
    parser.add_argument('--limit',type=int,help='Bound number of source pages per unit; report remains bounded')
    parser.add_argument('--lesson-limit',type=int,help='Bound library lessons per source; report remaining coverage')
    parser.add_argument('--wait-seconds',type=float,default=18,help='Player caption-load wait, 1–60 seconds')
    args=parser.parse_args(argv)
    if args.limit is not None and args.limit<1 or args.lesson_limit is not None and args.lesson_limit<1:
        parser.error('Limits must be positive')
    if not 1<=args.wait_seconds<=60:
        parser.error('--wait-seconds must be between 1 and 60')
    if args.page_url and not safe_canvas_url(args.page_url):
        parser.error('--page-url must be a durable QUT Canvas course source')
    try:
        config=load_config(args.config,root=args.root)
        course_ids=[identifier(x) for x in args.course_id or []]
        if args.page_url:
            course_ids=[re.search(r'/courses/(\d+)/',args.page_url).group(1)]
        summaries=[]
        with BrowserSession(args.cdp_url,config.base_url,config.timeout,args.profile) as session:
            client=CanvasClient(config.base_url,timeout=config.timeout,transport=session.transport)
            client.get('/api/v1/users/self/profile')
            for cid in dict.fromkeys(course_ids):
                course=client.get(f'/api/v1/courses/{cid}')
                if args.page_url:
                    sources=[{'source_url':args.page_url,'title':None}];errors=[]
                else:
                    sources,errors=course_sources(client,cid)
                if args.discover_only:
                    summaries.append({'course_id':cid,'sources':sources,'discovery_errors':errors,'extraction':'not_requested'})
                    continue
                selected=sources[:args.limit] if args.limit else sources
                bounded=bool(args.page_url or args.limit or args.lesson_limit)
                unit=config.root/'units'/('course-'+cid)
                if not unit.resolve().is_relative_to(config.root.resolve()):
                    raise ValueError('Unit output escapes root')
                if not (unit/'lectures').resolve().is_relative_to(config.root.resolve()):
                    raise ValueError('Lecture output escapes root')
                results=[]
                for source in selected:
                    try:
                        result=capture_page(session,source['source_url'],unit/'lectures',source.get('title'),course.get('course_code') or course.get('name'),args.wait_seconds,args.lesson_limit)
                    except (CanvasError,AuthNeeded,ValueError) as exc:
                        result={'source_url':source['source_url'],'title':source.get('title') or 'Recording','status':'failed','exports':[],
                                'warnings':[getattr(exc,'kind','auth_or_caption_error')]}
                    results.append(result)
                summary=write_transcript_index(config.root,cid,results,errors,bounded)
                summary['sources_discovered']=len(sources)
                summary['sources_attempted']=len(selected)
                summaries.append(summary)
        print(json.dumps({'courses':summaries},ensure_ascii=False,indent=2))
        return 0 if summaries and all((not s.get('discovery_errors')) if args.discover_only else s.get('complete',False) for s in summaries) else 2
    except (CanvasError,ValueError,OSError) as exc:
        print(json.dumps({'error':getattr(exc,'kind','configuration'),'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Standalone, non-secret-config Canvas course library CLI."""
import argparse
import json
from pathlib import Path
import sys
from contextlib import ExitStack
from functools import partial
from qut_toolkit.locking import writer_lock, WriterLockError

from qut_toolkit.client import CanvasClient, CanvasError
from qut_toolkit.config import DEFAULT_CONFIG, load_config
from qut_toolkit.reports import write_latest
from qut_toolkit.storage import atomic_write, identifier
from qut_toolkit.sync import sync_course


def _options(parser, sub=False):
    default=argparse.SUPPRESS if sub else None
    parser.add_argument('--root',default=default,help='Standalone output library (no vault needed)')
    parser.add_argument('--config',default=default,help='Non-secret JSON configuration file')
    parser.add_argument('--notes-root',default=default,help='Opt-in namespaced course mirror under this notes/vault root')
    parser.add_argument('--cookie-cache',default=default,help='Existing Canvas authentication cache; credentials are never copied to config')
    parser.add_argument('--timezone',default=default,help='Findings timezone, e.g. Australia/Brisbane or UTC')
    parser.add_argument('--cdp-url',default=default,help='Optional loopback browser CDP endpoint')
    parser.add_argument('--include-media',action='store_true',default=default,help='Opt into downloading audio/video resources (potentially very large)')
    parser.add_argument('--browser-inventory',action='store_true',default=default,help='Opt in to read-only discovery of browser-visible course links')
    parser.add_argument('--max-file-bytes',type=int,default=default,help='Maximum advertised resource size; default 100 MiB')


def build_parser():
    parser=argparse.ArgumentParser(description=__doc__)
    _options(parser)
    commands=parser.add_subparsers(dest='command',required=True)
    setup=commands.add_parser('setup',aliases=['init'],help='Create output folders and non-secret config; no authentication required')
    _options(setup,True)
    courses=commands.add_parser('courses',help='List available Canvas courses')
    _options(courses,True)
    sync=commands.add_parser('sync',help='Sync one or more numeric course IDs, or all active courses')
    _options(sync,True)
    sync.add_argument('course_ids',nargs='*',type=identifier)
    sync.add_argument('--all',action='store_true',help='Sync all active courses visible to the current session')
    report=commands.add_parser('report',help='Read the most recent local sync report (no network)')
    _options(report,True)
    report.add_argument('--json',action='store_true',help='Print machine-readable report')
    return parser


def main(argv=None):
    parser=build_parser()
    args=parser.parse_args(argv)
    if args.command=='sync' and (bool(args.course_ids)==bool(args.all)):
        parser.error('sync requires course ID(s) or --all, but not both')
    try:
        config=load_config(args.config,**{key:getattr(args,key,None) for key in ('root','notes_root','cookie_cache','timezone','include_media','max_file_bytes')})
    except (OSError,ValueError,TypeError):
        print('Invalid or unreadable configuration; check paths, JSON and timezone.',file=sys.stderr)
        return 2
    if args.command in ('setup','init'):
        try:
            config.root.mkdir(parents=True,exist_ok=True)
            for directory in ('units','reports'): (config.root/directory).mkdir(exist_ok=True)
            target=Path(args.config).expanduser() if args.config else DEFAULT_CONFIG
            # Never persist cookies, credentials, session caches, CDP or arbitrary config input.
            safe={'root':str(config.root),'timezone':config.timezone}
            if config.notes_root: safe['notes_root']=str(config.notes_root)
            if args.include_media is not None: safe['include_media']=config.include_media
            if args.max_file_bytes is not None: safe['max_file_bytes']=config.max_file_bytes
            atomic_write(target,(json.dumps(safe,indent=2)+'\n').encode())
            print('Output library: '+str(config.root))
            print('Non-secret config: '+str(target))
            if config.notes_root: print('Notes mirror enabled for sync; setup has not touched the notes root.')
            return 0
        except (OSError,ValueError):
            print('Setup could not write output/config; check permissions.',file=sys.stderr)
            return 2
    if args.command=='report':
        directory=config.root/'reports'
        try:
            report=json.loads((directory/'latest-sync.json').read_text(encoding='utf-8'))
            if args.json: print(json.dumps(report,indent=2,ensure_ascii=False))
            else: print((directory/'latest-sync.md').read_text(encoding='utf-8'),end='')
            return 0 if report.get('complete') else 1
        except (OSError,ValueError):
            print('No readable sync report exists. No clean check has been performed.',file=sys.stderr)
            return 1
    client=None
    results=[]
    locks=ExitStack()
    try:
        if args.command=='sync':
            locks.enter_context(writer_lock(config.root))
            if config.notes_root: locks.enter_context(writer_lock(config.notes_root))
        if args.cdp_url:
            factory=getattr(CanvasClient,'from_cdp',None)
            if factory is None: raise CanvasError('unsupported','Browser transport unavailable')
            client=factory(config,args.cdp_url)
        else: client=CanvasClient.from_config(config)
        if args.command=='courses':
            courses=client.list('/api/v1/courses?enrollment_state=active&per_page=100')
            print(json.dumps([{'id':c['id'],'name':c.get('name'),'course_code':c.get('course_code')} for c in courses],indent=2,ensure_ascii=False))
            return 0
        ids=list(dict.fromkeys(args.course_ids))
        if args.all:
            ids=list(dict.fromkeys(identifier(c['id']) for c in client.list('/api/v1/courses?enrollment_state=active&per_page=100')))
        inventory=None
        if args.browser_inventory:
            from qut_toolkit.browser import BrowserSession
            from qut_toolkit.visible import browser_inventory
            session=getattr(client,'browser_session',None)
            if session is None:
                session=locks.enter_context(BrowserSession(base_url=config.base_url,timeout=config.timeout))
            inventory=partial(browser_inventory,session)
        for cid in ids:
            try:
                if inventory is None: results.append(sync_course(client,cid,config))
                else: results.append(sync_course(client,cid,config,browser_inventory=inventory))
            except (CanvasError,OSError,ValueError,KeyError):
                results.append({'course_id':cid,'title':'Course '+cid,'complete':False,'counts':{},'errors':[{'kind':'sync','message':'Course sync failed; check authentication, access and output permissions.'}]})
        report=write_latest(config.root,results)
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return 0 if report['complete'] else 1
    except WriterLockError:
        print('Output library is busy: another sync is running. No checkpoints were changed.',file=sys.stderr)
        return 1
    except (CanvasError,OSError,ValueError,KeyError) as exc:
        # No provider exception strings: they can contain credentials/signed links.
        error={'kind':getattr(exc,'kind','sync'),'message':'Cannot complete Canvas operation; check authentication, access, transport and output permissions.'}
        if args.command=='sync':
            try: write_latest(config.root,results,errors=[error])
            except (OSError,ValueError): pass
        print(error['kind']+': '+error['message'],file=sys.stderr)
        return 1
    finally:
        try:
            if client is not None:
                close=getattr(client,'close',None)
                if close: close()
        finally:
            locks.close()


if __name__=='__main__':
    raise SystemExit(main())

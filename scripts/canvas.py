"""Compatibility command names for the standalone QUT toolkit.

Pull/pull-all use qut_sync's safe library layout, not Desktop/school.
Choose --root or QUT_STUDY_ROOT. No cookie pasting or cookie DB decryption.
"""
import argparse
import json
import os
import sys
from urllib.parse import quote, urlencode
from qut_toolkit.client import CanvasClient, CanvasError
from qut_toolkit.config import load_config
from qut_toolkit.storage import identifier


def canvas_request(endpoint, params=None):
    """Legacy import bridge with same-origin pagination and explicit failures."""
    client=CanvasClient.from_config(load_config())
    path='/api/v1/'+endpoint.lstrip('/')
    if params: path+=('&' if '?' in path else '?')+urlencode(params,doseq=True)
    body,_=client._request(path,api=True)
    data=json.loads(body)
    return client.list(path) if isinstance(data,list) else data


def canvas_get_paginated(endpoint,params=None):
    client=CanvasClient.from_config(load_config())
    path='/api/v1/'+endpoint.lstrip('/')
    if params:path+=('&' if '?' in path else '?')+urlencode(params,doseq=True)
    return client.list(path)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='cmd',required=True)
    for name in ('courses','files','modules','pages','page','pull','pull-all','scan','auth','check'):
        p=subs.add_parser(name)
        p.add_argument('--root',help='Standalone study output root')
        p.add_argument('--config',help='Toolkit JSON configuration')
        p.add_argument('--cdp-url',help='Loopback browser CDP attachment')
        if name in ('files','modules','pages','page','pull'):p.add_argument('course_id',type=identifier)
        if name=='page':p.add_argument('page_slug')
    args=parser.parse_args(argv)
    extra=[]
    root=args.root or os.environ.get('SCHOOL_DIR')
    if root:extra+=['--root',root]
    if args.config:extra+=['--config',args.config]
    if args.cdp_url:extra+=['--cdp-url',args.cdp_url]
    if args.cmd in ('courses','pull','pull-all'):
        import qut_sync
        command=['courses'] if args.cmd=='courses' else ['sync',args.course_id] if args.cmd=='pull' else ['sync','--all']
        return qut_sync.main(command+extra)
    if args.cmd=='auth':
        import canvas_auth
        canvas_auth.main()
        return 0
    if args.cmd=='scan':
        import scan_school
        config=load_config(args.config,root=root)
        return scan_school.main(['--source',str(config.root),'--no-vision'])
    client=None
    try:
        config=load_config(args.config,root=root)
        client=CanvasClient.from_cdp(config,args.cdp_url) if args.cdp_url else CanvasClient.from_config(config)
        if args.cmd=='check':
            verified=bool(client.get('/api/v1/users/self/profile').get('id'))
            print(json.dumps({'authenticated':verified}))
            return 0 if verified else 1
        base='/api/v1/courses/'+args.course_id
        if args.cmd=='page':result=client.get(base+'/pages/'+quote(args.page_slug,safe=''))
        elif args.cmd=='modules':
            result=client.list(base+'/modules?per_page=100')
            for module in result:
                mid=identifier(module['id'])
                module['items']=client.list(base+'/modules/'+mid+'/items?per_page=100')
        else:result=client.list(base+'/'+args.cmd+'?per_page=100')
        from qut_toolkit.sync import _safe_record
        print(json.dumps(_safe_record(result),ensure_ascii=False,indent=2))
        return 0
    except (CanvasError,ValueError,OSError):
        print('Canvas operation failed; check login/access/config. Use qut_sync.py sync for module fallbacks.',file=sys.stderr)
        return 1
    finally:
        if client:client.close()


if __name__=='__main__':
    raise SystemExit(main())

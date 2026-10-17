"""Opt-in, read-only discovery through an already authorized BrowserSession.

No credentials, request interception downloads, API probing, LTI launches or form
submission. Only this helper's new tab is closed. Public output is an allowlist;
URLs have no query/fragment. Visible coverage never proves hidden content absent.
"""
from collections import deque
import re
from urllib.parse import urlsplit, urljoin, unquote, parse_qs

from .storage import identifier


_DOM = r"""() => {
  const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const mid = e => (e?.id || '').match(/^(?:context_)?module_(\d+)$/)?.[1];
  const modules = [...document.querySelectorAll('[id^="context_module_"], [id^="module_"]')]
    .filter(e => mid(e) && visible(e)).map(e => ({id:mid(e),
      title:(e.querySelector('.ig-header-title, .name')?.textContent || '').trim()}));
  const links = [...document.querySelectorAll('a[href], img[src], video[src], audio[src], source[src]')].filter(visible).map(e => {
    const m = e.closest('[id^="context_module_"], [id^="module_"]');
    const item = e.closest('[id^="context_module_item_"]');
    return {url:e.href || e.src, title:(e.textContent || e.getAttribute('aria-label') || e.getAttribute('alt') || '').trim(),
      module_ids:mid(m) ? [mid(m)] : [],
      module_item_id:item?.id.match(/context_module_item_(\d+)/)?.[1],
      next:(e.rel || '').split(/\s+/).includes('next') ||
        (!!e.closest('.pagination') && /^(next|next page|›|»)$/i.test(e.textContent.trim()))};
  });
  return {modules,links};
}"""


def _origin(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Expected an ordinary Canvas origin')
    return p.scheme, p.netloc.lower()


def _course_path(url, base, cid):
    """Allow only known ordinary course read paths, never arbitrary actions."""
    p = urlsplit(urljoin(base+'/', str(url)))
    if _origin(p.geturl()) != _origin(base):
        return None
    prefix = '/courses/'+cid
    if not re.fullmatch(re.escape(prefix)+r'(?:/(?:modules|pages|files|assignments)(?:/(?:[0-9]+|[^/]+))?(?:/(?:download|preview))?|/modules/items/[0-9]+|/external_tools/[0-9]+)?/?', p.path):
        return None
    # Only page slugs can be nonnumeric; trailing actions must never sneak in.
    tail = p.path[len(prefix):].rstrip('/')
    if tail.startswith('/pages/'):
        slug = tail[7:]
        if '/' in slug or unquote(slug) in ('edit','new') or '/' in unquote(slug) or '\\' in unquote(slug):
            return None
    elif tail and not re.fullmatch(r'/(?:modules|pages|files|assignments)|/(?:modules|files|assignments|external_tools)/[0-9]+|/files/[0-9]+/(?:download|preview)|/modules/items/[0-9]+', tail):
        return None
    return p.scheme+'://'+p.netloc+p.path


def _resource(url, base, cid):
    clean = _course_path(url, base, cid)
    if not clean:
        p=urlsplit(urljoin(base+'/',str(url)))
        if _origin(p.geturl())==_origin(base):
            match=re.fullmatch(r'/files/([0-9]+)(?:/(?:download|preview))?',p.path)
            if match:
                return {'kind':'file','id':match[1],'url':p.scheme+'://'+p.netloc+p.path}
        return None
    path = urlsplit(clean).path
    prefix = '/courses/'+cid
    for segment, kind in (('pages','page'), ('files','file'), ('assignments','assignment'), ('modules/items','module_item'), ('external_tools','external_tool')):
        match = re.fullmatch(re.escape(prefix+'/'+segment)+r'/([^/]+)(?:/(?:download|preview))?', path)
        if match:
            rid = unquote(match[1])
            if kind != 'page' and not (rid.isascii() and rid.isdecimal()):
                return None
            return {'kind':kind, 'id':rid, 'url':clean}
    return None


def normalize_inventory(raw, base, course_id):
    """Validate a callback result and discard unknown fields and unsafe URLs.

    Schema: course_id, modules[{id,title}], resources[{kind,id,url,title,
    module_ids,module_item_id}], pages[{url,outcome,status,pagination_page}],
    navigation[{url,title}], bounded, complete.
    Resource identity is derived from its actual same-course URL, not claimed ID.
    """
    cid = identifier(course_id)
    if not isinstance(raw, dict) or identifier(raw.get('course_id', cid)) != cid:
        raise ValueError('Inventory course does not match requested course')
    result = {'course_id':cid, 'complete':False, 'bounded':bool(raw.get('bounded',False)),
              'coverage':'visible_only; hidden/unlinked content unknown',
              'modules':[], 'resources':[], 'pages':[], 'navigation':[]}
    modules = {}
    for m in raw.get('modules', []):
        try: mid = identifier(m['id'])
        except (ValueError, TypeError, KeyError): continue
        modules[mid] = {'id':mid, 'title':str(m.get('title') or m.get('name') or 'Module')}
    result['modules'] = list(modules.values())
    resources = {}
    for r in raw.get('resources', []):
        try: item = _resource(r.get('url',''),base,cid)
        except (ValueError,TypeError): continue
        if not item: continue
        item['title'] = str(r.get('title') or item['id'])
        mids = []
        for mid in r.get('module_ids', []):
            try: mids.append(identifier(mid))
            except (ValueError,TypeError): continue
        item['module_ids'] = sorted(set(mids),key=int)
        try:
            query_mid=parse_qs(urlsplit(r.get('url','')).query).get('module_item_id',[None])[0]
            item['module_item_id'] = identifier(r.get('module_item_id') or query_mid)
        except (KeyError,ValueError,TypeError): pass
        key = item['kind'],item['id']
        if key in resources:
            item['module_ids'] = sorted(set(item['module_ids']+resources[key]['module_ids']),key=int)
        resources[key] = item
    result['resources'] = list(resources.values())
    outcomes = {'observed','forbidden','auth_required','failed','navigation_blocked','partial_expansion'}
    for p in raw.get('pages', []):
        try: url = _course_path(p.get('url',''),base,cid)
        except (ValueError,TypeError): continue
        if url:
            entry = {'url':url, 'outcome':p.get('outcome') if p.get('outcome') in outcomes else 'failed'}
            if isinstance(p.get('status'),int): entry['status'] = p['status']
            n=parse_qs(urlsplit(p.get('url','')).query).get('page',[str(p.get('pagination_page',''))])[0]
            if n.isascii() and n.isdecimal(): entry['pagination_page']=n
            result['pages'].append(entry)
    for nav in raw.get('navigation',[]):
        try: url=_course_path(nav.get('url',''),base,cid)
        except (ValueError,TypeError): continue
        if url:
            result['navigation'].append({'url':url,'title':str(nav.get('title') or '')})
    return result


def browser_inventory(session, course_id, *, max_pages=80, max_expansions=200):
    """Collect bounded DOM evidence with session.context (owned or attached).

    Bind for sync APIs with functools.partial(browser_inventory, session).
    max_pages counts attempted documents. No download or access retry is attempted:
    a visible file link proves discovery, not entitlement or successful retrieval.
    """
    cid = identifier(course_id)
    if not isinstance(max_pages,int) or max_pages < 1 or not isinstance(max_expansions,int) or max_expansions < 0:
        raise ValueError('Discovery budgets must be positive (expansions may be zero)')
    base = session.base_url.rstrip('/')
    _origin(base)
    root = base+'/courses/'+cid
    raw = {'course_id':cid, 'modules':[], 'resources':[], 'pages':[], 'navigation':[], 'bounded':False}
    queue = deque([root,root+'/modules',root+'/pages',root+'/files'])
    visited = set()
    associations = {}
    resolved_items = {}
    expansions=0
    page = session.context.new_page()
    timeout = max(1, float(getattr(session,'timeout',30)))*1000
    def guard(route):
        request = route.request
        # Redirects must not turn a read-only visit into a login/LTI/action visit.
        clean=_course_path(request.url,base,cid) if request.is_navigation_request() else None
        forbidden_document=bool(clean and (re.search(r'/(?:external_tools|modules/items)/',urlsplit(clean).path) or
                                           re.search(r'/files/[0-9]+',urlsplit(clean).path)))
        if request.method not in ('GET','HEAD') or request.is_navigation_request() and (not clean or forbidden_document):
            route.abort()
        else:
            route.continue_()
    try:
        page.route('**/*', guard)
        while queue and len(visited) < max_pages:
            url = queue.popleft()
            if url in visited: continue
            visited.add(url)
            outcome = {'url':url, 'outcome':'failed'}
            raw['pages'].append(outcome)
            try:
                response = page.goto(url, wait_until='domcontentloaded', timeout=timeout)
                status = response.status if response else None
                if status is not None: outcome['status'] = status
                if status in (401,403) or status is not None and status >= 400:
                    outcome['outcome'] = 'forbidden' if status==403 else 'auth_required' if status==401 else 'failed'
                    continue
                if not _course_path(page.url,base,cid):
                    outcome['outcome'] = 'navigation_blocked'
                    continue
                outcome['outcome'] = 'observed'
                toggles = page.locator('.ig-header .expand_module_link[aria-expanded="false"]')
                count = toggles.count()
                remaining=max_expansions-expansions
                if count > remaining: raw['bounded'] = True
                # Re-select after each click because expansion can remove the match.
                for _ in range(min(count,remaining)):
                    expansions+=1
                    try: toggles.nth(0).click(timeout=timeout)
                    except Exception:
                        outcome['outcome'] = 'partial_expansion'
                        raw['bounded'] = True
                        break
                dom = page.evaluate(_DOM)
                raw['modules'].extend(dom.get('modules',[]))
                inherited = associations.get(url,[])
                for ref in dom.get('links',[]):
                    target = ref.get('url','')
                    try:
                        item = _resource(target,base,cid)
                        clean = item['url'] if item else _course_path(target,base,cid)
                    except (ValueError,TypeError): continue
                    if not clean: continue
                    if not item:
                        raw['navigation'].append({'url':clean,'title':ref.get('title')})
                    mids = ref.get('module_ids') or inherited
                    if item and item['kind']=='module_item':
                        # Read the ordinary module-link redirect without following
                        # it into LTI/auth/download actions. No POST or launch.
                        try:
                            item_url=item['url']
                            if item_url not in resolved_items:
                                _, response_headers=session.transport(item_url,{},float(getattr(session,'timeout',30)))
                                redirect=next((v for k,v in response_headers.items() if k.lower()=='location'),None)
                                resolved_items[item_url]=_resource(urljoin(item_url,redirect),base,cid) if redirect else None
                            cached=resolved_items[item_url]
                            resolved=dict(cached) if cached else None
                            if resolved and resolved['kind']!='module_item':
                                resolved['module_item_id']=item['id']
                                item=resolved;clean=item['url']
                        except Exception:
                            raw['bounded']=True
                    if item:
                        item.update(title=ref.get('title'),module_ids=mids)
                        query_mid=parse_qs(urlsplit(target).query).get('module_item_id',[None])[0]
                        if ref.get('module_item_id') or query_mid:
                            item['module_item_id']=ref.get('module_item_id') or query_mid
                        raw['resources'].append(item)
                        if item['kind'] in ('page','assignment'):
                            associations[clean] = sorted(set(associations.get(clean,[])+mids))
                            if clean not in visited: queue.append(clean)
                    # Only same-course indexes' observable next controls are followed.
                    path = urlsplit(clean).path
                    if ref.get('next') and path in ('/courses/'+cid+'/modules','/courses/'+cid+'/pages','/courses/'+cid+'/files'):
                        values = parse_qs(urlsplit(target).query)
                        n = values.get('page',[''])[0]
                        if n.isascii() and n.isdecimal():
                            next_url = clean+'?page='+n
                            if next_url not in visited: queue.append(next_url)
                        else:
                            raw['bounded'] = True
            except Exception:
                # Never retain transport exceptions: browser errors can contain tokens.
                outcome['outcome'] = 'failed'
        raw['bounded'] = raw['bounded'] or any(u not in visited for u in queue)
    finally:
        try: page.close()
        except Exception:
            raw['bounded']=True
    return normalize_inventory(raw,base,cid)


def reconciliation(inventory, entries, page_paths, errors, *, saved_paths=None):
    """Join observed resources to retained local entries; never infer absence."""
    rows = []
    represented = set()
    def locally_saved(key):
        return key in entries and (saved_paths is None or entries[key]['path'] in saved_paths)
    for resource in inventory['resources']:
        kind, rid = resource['kind'],resource['id']
        if kind=='page':
            key=next((k for k,e in entries.items() if k.startswith('page:') and
                      (e.get('metadata',{}).get('slug')==rid or
                       page_paths.get(rid) is not None and e.get('path')==page_paths[rid])), 'page:')
        else:
            key=kind+':'+rid
        saved = locally_saved(key)
        represented.add(key)
        forbidden = any(e.get('section') == kind+' '+rid and e.get('status')==403 for e in errors)
        rows.append(dict(resource, saved=saved, path=entries[key]['path'] if saved else None,
                         observation='observed', access='api_forbidden_visible_link_only' if forbidden else 'saved' if saved else 'visible_link_only_not_verified'))
    for key, entry in entries.items():
        kind, _, rid = key.partition(':')
        if kind not in ('page','file','assignment') or key in represented: continue
        rows.append({'kind':kind,'id':rid,'title':entry.get('metadata',{}).get('title'),
                     'module_ids':[], 'saved':locally_saved(key),'path':entry['path'],
                     'observation':'not_observed_unknown','access':'retained_local_copy' if locally_saved(key) else 'manifest_only_local_missing'})
    modules = []
    for module in inventory['modules']:
        mid = module['id']
        modules.append(dict(module, saved=locally_saved('module:'+mid), observation='observed',
                            resources=[{'kind':r['kind'],'id':r['id'],'saved':r['saved']} for r in rows if mid in r['module_ids']]))
    observed_mids = {m['id'] for m in modules}
    for key in entries:
        if key.startswith('module:') and key[7:] not in observed_mids:
            modules.append({'id':key[7:],'saved':locally_saved(key),'observation':'not_observed_unknown','resources':[]})
    return dict(inventory, resources=rows, modules=modules)


def reconciliation_markdown(report):
    from .reports import md_text
    lines = ['# Browser-visible reconciliation','',
             '> INCOMPLETE: visible links are evidence of discovery, not access. Hidden/unlinked or unobserved content remains unknown.',
             '',f'Bounded: {report["bounded"]}', '', '## Modules','']
    for m in report['modules']:
        lines.append('- '+md_text(m.get('title') or m['id'])+f' — {m["observation"]}; saved: {m["saved"]}')
    lines += ['', '## Resources','']
    for r in report['resources']:
        lines.append('- '+md_text(r.get('title') or r['id'])+' — '+md_text(r['kind']+':'+r['id'])+
                     f'; modules: {", ".join(r["module_ids"]) or "unknown"}; {r["observation"]}; {r["access"]}')
    lines += ['', '## Documents checked','']
    for p in report['pages']:
        lines.append('- '+md_text(p['url'])+' — '+p['outcome'])
    return '\n'.join(lines)+'\n'

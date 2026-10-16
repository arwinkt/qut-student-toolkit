"""Deterministic source-linked assessment snapshots and factual sync reports."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from .client import public_url
from .storage import atomic_write, utc_now


def md_text(value):
    return str(value or '').replace('\\','\\\\').replace('[','\\[').replace(']','\\]').replace('|','\\|').replace('\r',' ').replace('\n',' ')


def link(label, target):
    return f'[{md_text(label)}]({quote(str(target), safe="/:#%")})'


def local_time(value, tz):
    if not value: return {'utc':None,'local':None}
    try:
        date = datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None: return {'utc':str(value),'local':'unknown (missing offset)'}
        zone = timezone.utc if tz=='UTC' else timezone(timedelta(hours=10)) if tz=='Australia/Brisbane' else ZoneInfo(tz)
        return {'utc':date.astimezone(timezone.utc).isoformat(),'local':date.astimezone(zone).isoformat()}
    except (ValueError,TypeError): return {'utc':str(value),'local':'unknown (invalid timestamp)'}


def assessment_snapshot(assignments, base_url, cid, tz):
    result={}
    for a in assignments:
        sid=str(a['id']); s=a.get('submission') or {}
        visible = s.get('score') is not None and s.get('workflow_state')=='graded' and not a.get('muted',False)
        if a.get('post_manually') and not s.get('posted_at'): visible=False
        due=local_time(a.get('due_at'),tz)
        result[sid]={'id':sid,'title':a.get('name','Assessment'), 'source':public_url(a.get('html_url') or f'{base_url}/courses/{cid}/assignments/{sid}'), 'due_utc':due['utc'],'due_local':due['local'],'timezone':tz,'grading_status':'released' if visible else 'ungraded/unreleased','score':s.get('score') if visible else None,'points_possible':a.get('points_possible'),'submission_status':s.get('workflow_state','not available'),'submitted_at':s.get('submitted_at'),'graded_at':s.get('graded_at') if visible else None,'posted_at':s.get('posted_at') if visible else None}
    return result


def snapshot_changes(previous,current):
    changes=[]
    for key,item in current.items():
        old=previous.get(key)
        if old is None:
            changes.append({'kind':'new_assessment','id':key,'title':item['title']})
            if item['grading_status']=='released':changes.append({'kind':'new_mark','id':key,'score':item['score']})
            continue
        if old.get('due_utc')!=item['due_utc']:
            changes.append({'kind':'deadline_changed','id':key,'before':old.get('due_utc'),'after':item['due_utc']})
        if item['grading_status']=='released' and (old.get('grading_status')!='released' or old.get('score')!=item['score']):
            changes.append({'kind':'new_mark','id':key,'score':item['score'],'previous':old.get('score')})
    return changes


def findings_markdown(title, assessments, changes, announcements):
    lines=[f'# {md_text(title)} — findings','', 'Only Canvas-provided dates and released grades are shown. No inferred personal deadlines, grace periods or GPA.', '', '## Assessments','']
    for item in assessments.values():
        lines += [f'### {link(item["title"],item["source"])}',f'- Due (UTC): {item["due_utc"] or "undated"}',f'- Due ({item["timezone"]}): {item["due_local"] or "undated"}',f'- Submission: {md_text(item["submission_status"])}; submitted: {item["submitted_at"] or "not available"}',f'- Grade: {item["grading_status"]}'+(f'; score {item["score"]} / {item["points_possible"]}; graded: {item["graded_at"] or "not available"}' if item['grading_status']=='released' else ''),'']
    lines += ['## Last observed assessment changes','']
    lines += ['- '+md_text(json.dumps(c,ensure_ascii=False)) for c in changes] or ['- No changes detected.']
    lines += ['','## Announcements (cohort information, not inferred personal obligations)','']
    lines += ['- '+link(a.get('title','Announcement'),public_url(a.get('html_url',''))) for a in announcements] or ['- No announcements returned.']
    return '\n'.join(lines)+'\n'


def write_latest(root, results, errors=None):
    errors=errors or []
    complete=bool(results) and not errors and all(r['complete'] for r in results)
    report={'checked_at':utc_now(),'complete':complete,'courses':results,'errors':errors}
    if not results: report['errors'].append({'kind':'no_data','message':'No courses were checked; no clean result is implied.'})
    directory=Path(root)/'reports';directory.mkdir(parents=True,exist_ok=True)
    # Refuse output redirection through a user-created symlink/junction.
    if not directory.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Report directory escapes root')
    for name in ('latest-sync.json','latest-sync.md'):
        if not (directory/name).resolve().is_relative_to(Path(root).resolve()):raise ValueError('Report path escapes root')
    atomic_write(directory/'latest-sync.json',(json.dumps(report,indent=2,ensure_ascii=False)+'\n').encode())
    lines=['# Latest sync','',f'Outcome: {"complete" if complete else "INCOMPLETE"}',f'Checked: {report["checked_at"]}','']
    lines += ['- Error: '+md_text(e.get('kind','error'))+' — '+md_text(e.get('message','')) for e in report['errors']]
    for r in results:
        lines += [f'## {link(r.get("title",r["course_id"]),"../units/course-"+str(r["course_id"])+"/INDEX.md")}',f'- Outcome: {"complete" if r["complete"] else "INCOMPLETE"}',f'- Files: {r.get("files_status","unknown")}',f'- Counts: {dict(r["counts"])}']
        lines += ['- Last successful check: '+str(r.get('last_success') or 'none'),'- Notes export: '+str(r.get('notes_export','not requested'))]
        lines += ['- Warning: '+md_text(w) for w in r.get('warnings',[])]
        lines += ['- Skipped: '+md_text(s.get('section',''))+' — '+md_text(s.get('reason','')) for s in r.get('skipped',[])]
        lines += ['- Error: '+md_text(e.get('kind','error'))+' — '+md_text(e.get('message','')) for e in r['errors']]
        lines += ['- Conflict: '+link(e['path'],'../units/course-'+str(r['course_id'])+'/'+e['path'])+'; incoming '+link('preserved copy','../units/course-'+str(r['course_id'])+'/'+e['conflict_path']) for e in r.get('conflicts',[])]
        lines += ['']
    atomic_write(directory/'latest-sync.md', ('\n'.join(lines)+'\n').encode())
    return report

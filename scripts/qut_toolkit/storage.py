"""Content-addressed originals and non-destructive working copies."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import unicodedata


def is_link(path):
    """Reject symlinks and Windows junction/reparse points, including internal ones."""
    path=Path(path)
    try:
        return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0) & 0x400)
    except FileNotFoundError:
        return False


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_component(value):
    value = unicodedata.normalize('NFKC', str(value))
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:100] or '_'
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        value = '_' + value
    return value


def identifier(value):
    value = str(value)
    if not re.fullmatch(r'[0-9]+', value): raise ValueError('Canvas identifier must contain digits only')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.qut-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.path('manifest.json')
        self.manifest = json.loads(self.manifest_path.read_text(encoding='utf-8')) if self.manifest_path.exists() else {'version':1,'entries':{},'last_success':None}
        self.events = []

    def path(self, relative):
        relative=str(relative)
        p=PurePosixPath(relative)
        if '\\' in relative or p.is_absolute() or not p.parts or any(x in ('..','.') or safe_component(x)!=x for x in p.parts):
            raise ValueError('Unsafe relative library path')
        result=self.root
        for component in p.parts:
            result=result/component
            if is_link(result):
                raise ValueError('Links/junctions are not allowed in managed library paths')
        if not result.resolve().is_relative_to(self.root): raise ValueError('Library path escapes root')
        return result

    def put(self, key, relative, content, metadata=None):
        if isinstance(content,str): content=content.encode('utf-8')
        old=self.manifest['entries'].get(key)
        relative=old['path'] if old else str(relative)
        target=self.path(relative)
        remote_hash=digest(content)
        original=self.path('originals/'+remote_hash)
        if not original.exists(): atomic_write(original,content)
        actual=digest(target.read_bytes()) if target.exists() else None
        baseline=old.get('installed_hash') if old else None
        if actual == remote_hash:
            status='unchanged'
            baseline=remote_hash
        elif actual is not None and (not old or actual != baseline):
            status='conflict'
            conflict=self.path('conflicts/'+digest(key.encode())[:16]+'-'+remote_hash)
            if not conflict.exists(): atomic_write(conflict,content)
        else:
            status='updated' if old else 'added'
            atomic_write(target,content)
            baseline=remote_hash
        # Metadata is deliberately allowlisted, not a dump of signed Canvas responses.
        clean={k:v for k,v in (metadata or {}).items() if k in ('id','title','updated_at','kind')}
        entry={'path':relative,'remote_hash':remote_hash,'installed_hash':baseline,'local_hash':actual if status=='conflict' else remote_hash,'metadata':clean}
        if status=='conflict': entry['conflict_path']=conflict.relative_to(self.root).as_posix()
        self.manifest['entries'][key]=entry
        self.events.append({'key':key,'path':relative,'status':status,**({'conflict_path':entry['conflict_path']} if status=='conflict' else {})})
        return status

    def save(self, complete=None, errors=None):
        if complete is not None:
            self.manifest['last_attempt']=utc_now()
            self.manifest['complete']=bool(complete)
            self.manifest['errors']=errors or []
            if complete: self.manifest['last_success']=self.manifest['last_attempt']
        atomic_write(self.manifest_path,(json.dumps(self.manifest,indent=2,ensure_ascii=False)+'\n').encode())

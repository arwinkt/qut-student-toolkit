"""Non-secret JSON configuration; explicit CLI > config > environment > defaults."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / '.canvas_cookies.json'
DEFAULT_CONFIG = Path.home() / '.qut-toolkit.json'

@dataclass
class Config:
    root: Path = field(default_factory=lambda: Path.home() / 'QUT Study')
    notes_root: Path | None = None
    cookie_cache: Path = DEFAULT_CACHE
    base_url: str = 'https://canvas.qut.edu.au'
    timezone: str = 'Australia/Brisbane'
    timeout: float = 30.0
    include_media: bool = False
    max_file_bytes: int = 100 * 1024 * 1024


def load_config(path=None, **overrides):
    path = Path(path).expanduser() if path else DEFAULT_CONFIG
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('Config must be a JSON object')
    defaults = Config()
    values = {}
    for key in defaults.__dataclass_fields__:
        env = os.environ.get('QUT_' + ('STUDY_ROOT' if key == 'root' else key.upper()))
        values[key] = overrides.get(key) if overrides.get(key) is not None else data.get(key, env if env is not None else getattr(defaults,key))
    for key in ('root','notes_root','cookie_cache'):
        values[key] = Path(values[key]).expanduser().resolve() if values[key] else None
    values['max_file_bytes'] = int(values['max_file_bytes'])
    if values['max_file_bytes'] < 1:
        raise ValueError('max_file_bytes must be positive')
    media = values['include_media']
    if isinstance(media,str):
        if media.lower() not in ('true','false','1','0'):
            raise ValueError('include_media must be true or false')
        media=media.lower() in ('true','1')
    if not isinstance(media,bool):
        raise ValueError('include_media must be boolean')
    values['include_media']=media
    values['timeout'] = float(values['timeout'])
    if not 0 < values['timeout'] <= 300:
        raise ValueError('timeout must be between 0 and 300 seconds')
    # Windows often has no IANA database. Fixed UTC/Brisbane handling is built in.
    if values['timezone'] not in ('UTC', 'Australia/Brisbane'):
        try: ZoneInfo(values['timezone'])
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Timezone unavailable; install tzdata or choose UTC/Australia/Brisbane') from exc
    return Config(**values)

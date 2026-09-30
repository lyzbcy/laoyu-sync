"""Daily silent development-skill/source refresh; never overwrites a dirty checkout."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--force', action='store_true')
args = parser.parse_args()
def git(*arguments):
    return subprocess.check_output(['git','-C',str(root),*arguments], stderr=subprocess.DEVNULL, encoding='utf-8', timeout=20).strip()
today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
try:
    git_dir = Path(git('rev-parse','--absolute-git-dir'))
    state_file = git_dir/'laoyu-skill-sync.json'
    try:
        previous = json.loads(state_file.read_text(encoding='utf-8'))
    except Exception:
        previous = {}
    if args.force or previous.get('attempt') != today:
        state = {'attempt':today,'status':'failed'}
        try:
            if git('remote','get-url','origin').rstrip('/') not in ('https://github.com/lyzbcy/laoyu-sync.git','https://github.com/lyzbcy/laoyu-sync'):
                raise ValueError('unexpected source')
            git('fetch','--quiet','origin','main')
            state['remote'] = git('rev-parse','origin/main')
            if git('status','--porcelain'):
                state['status'] = 'dirty-kept-local'
            else:
                git('merge','--ff-only','--quiet','origin/main')
                state.update(status='current',success=today)
        except Exception:
            pass
        state_file.write_text(json.dumps(state), encoding='utf-8')
except Exception:
    pass  # offline, absent Git or an unmanaged source must not interrupt development

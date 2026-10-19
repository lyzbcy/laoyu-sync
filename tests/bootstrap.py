"""All unit tests override inherited runtime profiles before product imports."""
import os
import tempfile
_profile = tempfile.TemporaryDirectory(prefix='laoyu-tests-')
os.environ['LAOYU_SYNC_DATA'] = _profile.name
os.environ['LAOYU_ST_HOME'] = os.path.join(_profile.name, 'engine')

# Legacy pet helpers must never inspect a developer's real GUI credentials.
os.environ["LOCALAPPDATA"] = os.path.join(_profile.name, "local")
os.environ["APPDATA"] = os.path.join(_profile.name, "roaming")
os.environ["HOME"] = _profile.name
os.environ["USERPROFILE"] = _profile.name

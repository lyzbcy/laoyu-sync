"""All unit tests override inherited runtime profiles before product imports."""
import os
import tempfile
_profile = tempfile.TemporaryDirectory(prefix='laoyu-tests-')
os.environ['LAOYU_SYNC_DATA'] = _profile.name

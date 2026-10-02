import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import bootstrap
import updater
import update_cleanup as cleanup

class History(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.p=patch.object(updater.config,'DATA_DIR',self.root);self.p.start()
        self.state=patch.object(updater,'_state',{'stage':'idle','percent':0,'message':''});self.state.start()
    def tearDown(self):
        self.state.stop();self.p.stop();self.tmp.cleanup()
    def receipt(self,**kwargs):
        f=self.root/'update-result.json';f.write_text(json.dumps(kwargs));return f
    def test_reached_failed_version_is_archived_exactly(self):
        f=self.receipt(ok=False,version='0.3.3',error='historical lock');before=f.read_bytes()
        self.assertEqual(updater.status()['stage'],'idle');self.assertFalse(f.exists())
        self.assertIn(before,[p.read_bytes() for p in (self.root/'update-history').glob('*.json')])
        self.assertEqual(updater.status()['stage'],'idle')
    def test_newer_attempt_remains_failure(self):
        f=self.receipt(ok=False,version='9.0.0',error='real failure')
        self.assertEqual(updater.status()['stage'],'failed');self.assertTrue(f.exists())
    def test_recovery_is_not_hidden(self):
        f=self.receipt(ok=False,version='0.3.3',recovery='backup')
        self.assertEqual(updater.status()['stage'],'failed');self.assertTrue(f.exists())
    def test_same_version_failed_transaction_and_unscoped_recovery_are_retained(self):
        import version
        self.receipt(ok=False,version=version.__version__,previous_version=version.__version__)
        self.assertEqual(updater.status()['stage'],'failed')
        self.receipt(ok=False,recovery='still-needs-restore')
        self.assertEqual(updater.status()['stage'],'failed')
    def test_unscoped_legacy_failure_is_history(self):
        self.receipt(ok=False,error='old lock');self.assertEqual(updater.status()['stage'],'idle')
    def test_old_success_shows_running_version(self):
        import version
        self.receipt(ok=True,version='0.3.2')
        self.assertIn(version.__version__,updater.status()['message'])

class Cleanup(unittest.TestCase):
    def fixture(self,root):
        root=Path(root);folder=root/'.laoyu-update-test';folder.mkdir()
        data=root/'data';data.mkdir();(data/'identity').write_text('keep')
        tx=dict(pid=99991,stage=str(folder),target=str(root/'app'),replacement=str(folder/'new'),version='0.3.3',data=str(data))
        (folder/'transaction.json').write_text(json.dumps(tx));(folder/'package.zip').write_bytes(b'temp')
        r=dict(schema=1,product='laoyu-sync',stage=str(folder),target=tx['target'],data=tx['data'],version=tx['version'],helper_pid=99992,old_pid=tx['pid'],outcome='complete',finished_at=1)
        (folder/'cleanup-ready.json').write_text(json.dumps(r));return folder,data,r
    def test_terminal_stage_deleted_history_and_data_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder,data,r=self.fixture(tmp)
            self.assertTrue(cleanup.cleanup_stage(folder,tmp,snapshot=lambda:[],now=lambda:1000))
            self.assertFalse(folder.exists());self.assertEqual((data/'identity').read_text(),'keep')
            self.assertEqual(len(list((Path(tmp)/'.laoyu-update-history').glob('*.json'))),1)
    def test_related_process_or_inventory_failure_retains_stage(self):
        for records in [[dict(ProcessId=99992)], [dict(ProcessId=5,ExecutablePath='',CommandLine='__stage__/helper/LaoyuSync.exe')]]:
            with tempfile.TemporaryDirectory() as tmp:
                folder,_,_=self.fixture(tmp)
                for r in records:r['CommandLine']=r.get('CommandLine','').replace('__stage__',str(folder))
                self.assertFalse(cleanup.cleanup_stage(folder,tmp,snapshot=lambda:records,now=lambda:1000));self.assertTrue(folder.exists())
        with tempfile.TemporaryDirectory() as tmp:
            folder,_,_=self.fixture(tmp)
            def denied():raise OSError('denied')
            self.assertFalse(cleanup.cleanup_stage(folder,tmp,snapshot=denied,now=lambda:1000))
    def test_missing_receipt_incomplete_and_outside_paths_are_kept(self):
        for mode in ['missing','active','outside','data-inside']:
            with tempfile.TemporaryDirectory() as tmp:
                folder,_,r=self.fixture(tmp)
                if mode=='missing':(folder/'cleanup-ready.json').unlink()
                else:
                    if mode=='active':r['outcome']='preparing'
                    if mode=='outside':r['stage']=str(Path(tmp).parent)
                    if mode=='data-inside':r['data']=str(folder)
                    (folder/'cleanup-ready.json').write_text(json.dumps(r))
                self.assertFalse(cleanup.cleanup_stage(folder,tmp,snapshot=lambda:[],now=lambda:1000));self.assertTrue(folder.exists())
    def test_legacy_stage_needs_missing_old_target_and_reached_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder,data,_=self.fixture(tmp);(folder/'cleanup-ready.json').unlink();os.utime(folder/'transaction.json',(1,1))
            target=Path(tmp)/'app';target.mkdir()
            self.assertFalse(cleanup.mark_superseded_legacy(folder,tmp,'0.3.3',snapshot=lambda:[],now=lambda:5000))
            target.rmdir()
            self.assertFalse(cleanup.mark_superseded_legacy(folder,tmp,'0.3.2',snapshot=lambda:[],now=lambda:5000))
            self.assertTrue(cleanup.mark_superseded_legacy(folder,tmp,'0.3.3',snapshot=lambda:[],now=lambda:5000))
            self.assertTrue(cleanup.cleanup_stage(folder,tmp,snapshot=lambda:[],now=lambda:5000))
    def test_legacy_healthy_ack_allows_retirement_without_losing_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder,data,_=self.fixture(tmp);(folder/'cleanup-ready.json').unlink();os.utime(folder/'transaction.json',(1,1))
            (Path(tmp)/'app').mkdir()
            (folder/'healthy.json').write_text(json.dumps(dict(version='0.3.3',engine_ready=True,renderer_ready=True)))
            (data/'update-result.json').write_text(json.dumps(dict(ok=False,recovery='backup')))
            self.assertFalse(cleanup.mark_superseded_legacy(folder,tmp,'0.3.4',snapshot=lambda:[],now=lambda:5000))
            (data/'update-result.json').write_text(json.dumps(dict(ok=True,version='0.3.3')))
            self.assertTrue(cleanup.mark_superseded_legacy(folder,tmp,'0.3.4',snapshot=lambda:[],now=lambda:5000))
if __name__=='__main__':unittest.main()

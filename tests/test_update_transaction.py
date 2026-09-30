"""Helper transaction regression with filesystem fixtures and fake process APIs."""
import ctypes,json,sys,tempfile,unittest
import bootstrap
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import updater

class KernelCall:
    def __init__(self,value): self.value=value;self.calls=[]
    def __call__(self,*args): self.calls.append(args);return self.value

class Kernel:
    def __init__(self,waited=0,opened=123,assigned=1):
        self.OpenProcess=KernelCall(opened)
        self.WaitForSingleObject=KernelCall(waited)
        self.CloseHandle=KernelCall(1)
        self.CreateJobObjectW=KernelCall(456)
        self.AssignProcessToJobObject=KernelCall(assigned)
        self.TerminateJobObject=KernelCall(1)

class Child:
    def __init__(self,alive=False): self.alive=alive;self._handle=789;self.pid=99998
    def poll(self): return None if self.alive else 1
    def terminate(self): self.alive=False
    def wait(self,timeout): return 1

class Transactions(unittest.TestCase):
    def fixture(self,root):
        target=root/'app';target.mkdir();(target/'LaoyuSync.exe').write_bytes(b'old')
        (target/'unins000.exe').write_bytes(b'installer')
        stage=root/'.laoyu-update-fixture';stage.mkdir();new=stage/'new';new.mkdir();(new/'LaoyuSync.exe').write_bytes(b'new')
        data=root/'user-data';data.mkdir();(data/'keep.txt').write_text('user-data')
        payload=stage/'transaction.json';payload.write_text(json.dumps({'pid':99999,'target':str(target),'replacement':str(new),'stage':str(stage),'data':str(data),'version':'9.0.0'}),encoding='utf-8')
        return target,stage,data,payload

    def test_failed_health_restores_previous_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,stage,data,payload=self.fixture(Path(tmp))
            launches=[]
            def launch(args,**kwargs): launches.append(args);return Child()
            kernel=Kernel()
            with patch.object(ctypes,'WinDLL',return_value=kernel),patch.object(updater.subprocess,'Popen',side_effect=launch),patch.object(updater.time,'sleep'):
                updater.apply_update(payload)
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'old')
            self.assertEqual((stage/'failed-new/LaoyuSync.exe').read_bytes(),b'new')
            self.assertEqual((data/'keep.txt').read_text(),'user-data')
            self.assertFalse(json.loads((data/'update-result.json').read_text())['ok'])
            self.assertEqual(len(launches),2)
            self.assertEqual(len(kernel.TerminateJobObject.calls),1)

    def test_health_ack_preserves_uninstaller_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target,stage,data,payload=self.fixture(root)
            def launch(args,**kwargs):
                Path(args[2]).write_text(json.dumps({'version':'9.0.0','engine_ready':True,'renderer_ready':True}));return Child(alive=True)
            with patch.object(ctypes,'WinDLL',return_value=Kernel()),patch.object(updater.subprocess,'Popen',side_effect=launch):
                updater.apply_update(payload)
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'new')
            self.assertEqual((target/'unins000.exe').read_bytes(),b'installer')
            backup=next(root.glob('app.previous-*'))
            self.assertEqual((backup/'LaoyuSync.exe').read_bytes(),b'old')
            self.assertTrue(json.loads((data/'update-result.json').read_text())['ok'])

    def test_live_old_process_does_not_swap_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,stage,data,payload=self.fixture(Path(tmp))
            with patch.object(ctypes,'WinDLL',return_value=Kernel(waited=258)),patch.object(updater.subprocess,'Popen') as launch:
                updater.apply_update(payload)
            launch.assert_not_called()
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'old')
            self.assertEqual((stage/'new/LaoyuSync.exe').read_bytes(),b'new')
            self.assertFalse(json.loads((data/'update-result.json').read_text())['ok'])

    def test_permission_failure_records_result_without_swapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,stage,data,payload=self.fixture(Path(tmp))
            with patch.object(ctypes,'WinDLL',return_value=Kernel(opened=0)),patch.object(ctypes,'get_last_error',return_value=5),patch.object(updater.subprocess,'Popen') as launch:
                updater.apply_update(payload)
            launch.assert_not_called()
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'old')
            self.assertFalse(json.loads((data/'update-result.json').read_text())['ok'])

    def test_incomplete_health_ack_cannot_accept_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,stage,data,payload=self.fixture(Path(tmp))
            def launch(args,**kwargs):
                if '--upgrade-ack' in args:
                    Path(args[2]).write_text(json.dumps({'version':'9.0.0','renderer_ready':True,'engine_ready':False}))
                return Child()
            with patch.object(ctypes,'WinDLL',return_value=Kernel()),patch.object(updater.subprocess,'Popen',side_effect=launch),patch.object(updater.time,'sleep'):
                updater.apply_update(payload)
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'old')
            self.assertFalse(json.loads((data/'update-result.json').read_text())['ok'])

    def test_unassignable_job_rolls_back_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,stage,data,payload=self.fixture(Path(tmp))
            kernel=Kernel(assigned=0)
            with patch.object(ctypes,'WinDLL',return_value=kernel),patch.object(updater.subprocess,'Popen',return_value=Child()),patch.object(updater.time,'sleep'):
                updater.apply_update(payload)
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'old')
            self.assertFalse(json.loads((data/'update-result.json').read_text())['ok'])

    def test_transient_locked_directory_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            target,stage,data,payload=self.fixture(Path(tmp))
            original=Path.rename;attempts=[]
            def rename(path,destination):
                if path==target and Path(destination)==stage/'failed-new':
                    attempts.append(1)
                    if len(attempts)<3: raise PermissionError('模拟短暂文件锁')
                return original(path,destination)
            with patch.object(ctypes,'WinDLL',return_value=Kernel()),patch.object(updater.subprocess,'Popen',return_value=Child()),patch.object(updater.time,'sleep'),patch.object(Path,'rename',rename):
                updater.apply_update(payload)
            self.assertEqual(len(attempts),3)
            self.assertEqual((target/'LaoyuSync.exe').read_bytes(),b'old')

if __name__=='__main__': unittest.main(verbosity=2)

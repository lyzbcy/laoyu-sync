"""更新包路径回归：仅创建临时 zip，永不启动程序或写入安装目录。"""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import updater


class UpdateArchiveContracts(unittest.TestCase):
    def test_hostile_paths_rejected(self):
        for name in ("../escape.txt", "..\\escape.txt", "/absolute.txt", "C:/escape.txt", "NUL.txt", "space /a.txt", "dot./a.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "attack.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    entry = zipfile.ZipInfo("placeholder")
                    entry.filename = name  # Preserve raw separators; Windows ZipInfo normally normalizes them.
                    z.writestr(entry, b"hostile")
                target = root / "new"
                target.mkdir()
                with self.assertRaises(ValueError):
                    updater.safe_extract(archive, target)
                self.assertEqual(list(target.iterdir()), [])
                self.assertFalse((root / "escape.txt").exists())

    def test_case_collisions_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "collision.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("file.txt", b"first")
                z.writestr("FILE.txt", b"second")
            target = root / "new"
            target.mkdir()
            with self.assertRaises(ValueError):
                updater.safe_extract(archive, target)
            self.assertEqual(list(target.iterdir()), [])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "symlink.zip"
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(entry, "../../outside")
            target = root / "new"
            target.mkdir()
            with self.assertRaises(ValueError):
                updater.safe_extract(archive, target)
            self.assertEqual(list(target.iterdir()), [])

    def test_complete_bundle_shape_extracts_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "safe.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("LaoyuSync.exe", b"MZfixture-only")
                z.writestr("_internal/ui.txt", b"fixture")
            target = root / "new"
            target.mkdir()
            updater.safe_extract(archive, target)
            self.assertEqual((target / "LaoyuSync.exe").read_bytes(), b"MZfixture-only")

    def test_foreign_release_urls_rejected(self):
        for url in ("http://github.com/lyzbcy/laoyu-sync/releases/download/v1/app-win-x64.zip", "https://github.com/other/repo/releases/download/v1/app-win-x64.zip", "https://github.com.evil.test/lyzbcy/laoyu-sync/releases/download/v1/app-win-x64.zip", "https://user:password@github.com/lyzbcy/laoyu-sync/releases/download/v1/app-win-x64.zip"):
            with self.subTest(url=url):
                self.assertFalse(updater.trusted_url(url))


if __name__ == "__main__":
    unittest.main(verbosity=2)

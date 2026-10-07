from pathlib import Path
import tempfile
import unittest
from session_storage import prune, register, active, finish


class StorageTests(unittest.TestCase):
    def test_active_marker_tracks_process_and_is_removed_on_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'session';register(folder,'test')
            self.assertTrue(active(folder));finish(folder);self.assertFalse(active(folder))
            (folder/'.active').write_text('99999999');self.assertFalse(active(folder))

    def test_retention_limits_count_bytes_and_protects_current_and_unmanaged(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for i in range(12):
                p=root/str(i);p.mkdir();(p/'session.json').write_text('{}');(p/'log').write_bytes(b'x'*100)
            unmanaged=root/'original_evidence';unmanaged.mkdir();(unmanaged/'data').write_text('keep')
            current=root/'0'
            prune(root,current,max_sessions=10,max_bytes=550)
            remaining=[p for p in root.iterdir() if p.is_dir() and (p/'session.json').exists()]
            self.assertLessEqual(len(remaining),5)
            self.assertTrue(current.exists());self.assertTrue(unmanaged.exists())


if __name__=='__main__':unittest.main()

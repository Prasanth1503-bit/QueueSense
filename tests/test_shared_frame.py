import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared_frame import write_live_frame, read_live_frame, cleanup_shared_frame
from app import app


class TestSharedFrameStreaming(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def tearDown(self):
        cleanup_shared_frame()

    def test_shared_memory_write_read(self):
        sample_jpeg = b"\xff\xd8\xff\xe0" + b"X" * 1000 + b"\xff\xd9"
        fid = write_live_frame(sample_jpeg)
        self.assertGreater(fid, 0)

        res = read_live_frame()
        self.assertIsNotNone(res)
        read_fid, read_ts, read_bytes = res
        self.assertEqual(read_fid, fid)
        self.assertEqual(read_bytes, sample_jpeg)

    def test_flask_live_frame_route(self):
        sample_jpeg = b"\xff\xd8\xff\xe0" + b"Y" * 500 + b"\xff\xd9"
        write_live_frame(sample_jpeg)

        resp = self.client.get("/api/live-frame")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/jpeg")
        self.assertEqual(resp.data, sample_jpeg)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")


if __name__ == "__main__":
    unittest.main()

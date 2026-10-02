import pytest

from archie.store.lock import Busy, WriterLock


def test_second_writer_is_refused_until_release(tmp_path):
    a, b = WriterLock(tmp_path), WriterLock(tmp_path)
    assert a.acquire()
    assert not b.acquire()
    with pytest.raises(Busy):
        with WriterLock(tmp_path):
            pass
    a.release()
    with WriterLock(tmp_path):
        pass

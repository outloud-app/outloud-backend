"""Provider network latency cannot block unrelated collection starts."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from research_providers import cached_collection


def test_parallel_provider_starts_do_not_hold_database_write_lock(tmp_path):
    path=tmp_path/'cache.sqlite3'
    # Both starts must be able to reach the network stage together.
    barrier=threading.Barrier(2)
    def start():
        with sqlite3.connect(path,timeout=.1) as db:
            db.execute('CREATE TABLE IF NOT EXISTS unrelated(value TEXT)')
            db.execute("INSERT INTO unrelated VALUES('write during network')")
        barrier.wait(timeout=2)
        return {'run_id':'same-fixture','dataset_id':'same-fixture'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(cached_collection,key,path,start) for key in ('one','two')]
        assert all(job.result()[0]['run_id']=='same-fixture' for job in jobs)


def test_concurrent_same_query_starts_only_one_paid_run(tmp_path):
    path=tmp_path/'cache.sqlite3'
    starts=[]
    def start():
        starts.append(1)
        return {'run_id':'fixture','dataset_id':'fixture'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(cached_collection,'same',path,start) for _ in range(4)]
        assert all(job.result()[0]['run_id']=='fixture' for job in jobs)
    assert len(starts)==1

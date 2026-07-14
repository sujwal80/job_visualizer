import os
import sys
import unittest
import tempfile
import sqlite3
import concurrent.futures
from unittest.mock import patch

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
from data_acquisition.pipelines.crawling.crawl_queue import CrawlQueue
from data_acquisition.pipelines.crawling.dispatch_crawlers import dispatch
from data_acquisition.pipelines.crawling.crawler_worker import run_worker
from data_acquisition.db_manager import DBManager
from data_acquisition.pipelines.crawling.job_scrapers.indeed_scraper import IndeedScraper
import multiprocessing


def _mp_worker_pop(db_path, num_attempts, result_queue):
    q = CrawlQueue(db_path=db_path)
    popped = []
    for _ in range(num_attempts):
        task = q.pop_task("LinkedIn")
        if task:
            popped.append(task["id"])
    result_queue.put(popped)


def _mp_worker_merge(json_path, company_name, worker_id, jobs_per_worker, error_queue):
    try:
        db_mgr = DBManager(db_path=json_path)
        jobs = []
        for i in range(jobs_per_worker):
            jobs.append({
                "title": f"Role_W{worker_id}_{i}",
                "company_name": company_name,
                "url": f"https://example.com/job/w{worker_id}/{i}",
                "location": "Bengaluru",
                "source": "LinkedIn"
            })
        db_mgr.merge_job_openings(jobs)
    except Exception as e:
        error_queue.put(str(e))


class TestAsyncCrawlerQueue(unittest.TestCase):
    """
    Exhaustive verification suite for the Asynchronous Queue-Based Crawler Pipeline:
    - Persistent SQLite transactional queue (CrawlQueue)
    - Multi-source Dispatcher CLI (dispatch_crawlers.py)
    - Consumer worker daemon (crawler_worker.py)
    - Atomic cross-process file locking (DBManager fcntl.flock)
    """
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_crawl_queue.db")
        self.json_path = os.path.join(self.temp_dir.name, "test_startups.json")
        self._old_mock_env = os.environ.get("MOCK_SCRAPER_FALLBACK")
        os.environ["MOCK_SCRAPER_FALLBACK"] = "true"

    def tearDown(self):
        self.temp_dir.cleanup()
        if self._old_mock_env is not None:
            os.environ["MOCK_SCRAPER_FALLBACK"] = self._old_mock_env
        else:
            os.environ.pop("MOCK_SCRAPER_FALLBACK", None)


    def test_01_fifo_and_source_isolation(self):
        """Verify tasks are popped in strict FIFO order and isolated by source_name."""
        q = CrawlQueue(db_path=self.db_path)
        q.push_task("LinkedIn", "Company A", "Bengaluru")
        q.push_task("YC", "Company B", "Bengaluru")
        q.push_task("LinkedIn", "Company C", "Bengaluru")

        # Popping specifically for YC should ignore Company A and return Company B
        task_yc = q.pop_task("YC")
        self.assertIsNotNone(task_yc)
        self.assertEqual(task_yc["company_name"], "Company B")
        self.assertEqual(task_yc["source_name"], "YC")

        # Popping for LinkedIn should follow FIFO order: Company A, then Company C
        task_li1 = q.pop_task("LinkedIn")
        self.assertIsNotNone(task_li1)
        self.assertEqual(task_li1["company_name"], "Company A")

        task_li2 = q.pop_task("LinkedIn")
        self.assertIsNotNone(task_li2)
        self.assertEqual(task_li2["company_name"], "Company C")

        # Further pops should return None
        self.assertIsNone(q.pop_task("LinkedIn"))

    def test_02_concurrent_worker_atomic_pop(self):
        """Verify 10 concurrent thread workers popping 25 tasks achieve 0% task duplication."""
        q = CrawlQueue(db_path=self.db_path)
        num_tasks = 25
        for i in range(num_tasks):
            q.push_task("LinkedIn", f"Startup_{i}", "Bengaluru")

        popped_ids = []

        def worker_pop():
            results = []
            while True:
                task = q.pop_task("LinkedIn")
                if not task:
                    break
                results.append(task["id"])
            return results

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_pop) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                popped_ids.extend(f.result())

        self.assertEqual(len(popped_ids), num_tasks, "All tasks must be popped exactly once")
        self.assertEqual(len(set(popped_ids)), num_tasks, "0% duplicate task dequeues allowed under concurrency")

    def test_03_dispatcher_bulk_queueing(self):
        """Verify dispatch_crawlers enqueues bulk tasks and builds accurate queue stats."""
        with patch.object(DBManager, "get_all_startups", return_value=[
            {"id": 1, "name": "Razorpay", "city": "Bengaluru"},
            {"id": 2, "name": "Zepto", "city": "Bengaluru"}
        ]):
            count = dispatch(city="Bengaluru", sources="LinkedIn,YC", db_path=self.db_path)
            self.assertEqual(count, 4)  # 2 startups * 2 sources = 4 tasks

            q = CrawlQueue(db_path=self.db_path)
            stats = q.get_queue_stats()
            self.assertEqual(stats["LinkedIn"]["PENDING"], 2)
            self.assertEqual(stats["YC"]["PENDING"], 2)

    def test_04_worker_execution_and_flock_merge(self):
        """Verify crawler_worker executes scraper and atomically merges openings into DBManager."""
        q = CrawlQueue(db_path=self.db_path)
        q.push_task("Indeed", "MockStartup", "Bengaluru")

        db_mgr = DBManager(db_path=self.json_path)
        db_mgr.startups = [{"id": 100, "name": "MockStartup", "city": "Bengaluru", "job_openings": []}]
        db_mgr.save_db()

        mock_jobs = [{
            "title": "Backend Lead",
            "company_name": "MockStartup",
            "url": "https://indeed.com/job/mock-1",
            "location": "Bengaluru",
            "source": "Indeed"
        }]

        with patch.object(IndeedScraper, "get_jobs", return_value=mock_jobs):
            processed = run_worker(source_filter="Indeed", exit_on_empty=True, db_path=self.db_path, json_path=self.json_path)
            self.assertEqual(processed, 1)

        db_check = DBManager(db_path=self.json_path)
        startup = db_check.find_startup("MockStartup", "")
        self.assertIsNotNone(startup)
        self.assertEqual(len(startup["job_openings"]), 1)
        self.assertEqual(startup["job_openings"][0]["title"], "Backend Lead")

        stats = q.get_queue_stats()
        self.assertEqual(stats["Indeed"]["COMPLETED"], 1)
        self.assertEqual(stats["Indeed"]["PENDING"], 0)

    def test_05_concurrent_multi_process_dequeues(self):
        """Verify multi-process concurrent workers popping from CrawlQueue achieve 0% task duplication."""
        q = CrawlQueue(db_path=self.db_path)
        num_tasks = 40
        for i in range(num_tasks):
            q.push_task("LinkedIn", f"Startup_{i}", "Bengaluru")

        result_queue = multiprocessing.Queue()
        processes = []
        num_workers = 6
        for _ in range(num_workers):
            p = multiprocessing.Process(target=_mp_worker_pop, args=(self.db_path, 20, result_queue))
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=15)
            self.assertEqual(p.exitcode, 0, f"Worker process {p} failed with exitcode {p.exitcode}")

        all_popped = []
        while not result_queue.empty():
            all_popped.extend(result_queue.get())

        self.assertEqual(len(all_popped), num_tasks, "All tasks must be popped exactly once across processes")
        self.assertEqual(len(set(all_popped)), num_tasks, "0% duplicate task dequeues allowed under multi-process concurrency")

    def test_06_concurrent_multi_process_flock_merge(self):
        """Verify concurrent multi-process workers atomically merging JSON into DBManager complete with 0 data corruption."""
        db_mgr = DBManager(db_path=self.json_path)
        db_mgr.startups = [{"id": 1, "name": "StressCompany", "city": "Bengaluru", "job_openings": []}]
        db_mgr.save_db()

        error_queue = multiprocessing.Queue()
        processes = []
        num_workers = 8
        jobs_per_worker = 12

        for w_id in range(num_workers):
            p = multiprocessing.Process(
                target=_mp_worker_merge,
                args=(self.json_path, "StressCompany", w_id, jobs_per_worker, error_queue)
            )
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=25)
            self.assertEqual(p.exitcode, 0, f"Process {p} failed with exitcode {p.exitcode}")

        errors = []
        while not error_queue.empty():
            errors.append(error_queue.get())
        self.assertEqual(errors, [], f"Workers reported exceptions during atomic merge: {errors}")

        db_check = DBManager(db_path=self.json_path)
        startup = db_check.find_startup("StressCompany", "")
        self.assertIsNotNone(startup)
        self.assertEqual(
            len(startup["job_openings"]),
            num_workers * jobs_per_worker,
            f"Expected {num_workers * jobs_per_worker} merged job openings, got {len(startup['job_openings'])}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

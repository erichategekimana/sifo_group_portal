# automation_app/automation_engine/utils.py
import sys
import time
import concurrent.futures
from contextlib import contextmanager

# Shared thread pool for all Django ORM calls made from inside Playwright threads.
# These worker threads have no running event loop, so Django's ORM guard passes.
_DB_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="irembo-db",
)

def run_in_db_thread(fn, *args, **kwargs):
    """
    Execute a callable that uses the Django ORM in a clean, non-async thread.

    Playwright's sync_playwright() runs an internal asyncio event loop in the
    background via greenlet. Django's SynchronousOnlyOperation check uses
    asyncio.get_running_loop() — which sees Playwright's loop and raises an
    error regardless of asyncio.set_event_loop(None). The only reliable fix is
    to dispatch ORM calls to a fresh thread that has NO running event loop.
    """
    future = _DB_THREAD_POOL.submit(fn, *args, **kwargs)
    return future.result()  # blocks the Playwright thread until the DB call finishes


# sync_db_context is kept only as a no-op shim for any legacy call sites.
# Do NOT use it to wrap ORM calls — it no longer provides isolation.
# Use run_in_db_thread() for any ORM access inside Playwright threads.
@contextmanager
def sync_db_context():
    yield  # no-op shim; real safety comes from run_in_db_thread


class UtilsMixin:
    def _pause_on_error(self, reason):
        print(f"[Engine PAUSED] {reason}")
        if self.booking_record:
            self.booking_record.application_number = f"[ERROR] {reason}"
            self.update_database_state("FAILED")
        raise ValueError(reason)

    def update_database_state(self, new_status):
        """
        Persist a status change to the DB from inside a Playwright thread.
        Must use run_in_db_thread so Django ORM doesn't see Playwright's
        internal asyncio loop and raise SynchronousOnlyOperation.
        """
        record = self.booking_record
        if record:
            def _save():
                record.status = new_status
                record.save(update_fields=["status"])
            run_in_db_thread(_save)

    def trigger_windows_alerts(self):
        if sys.platform == "win32":
            import winsound
            for _ in range(3):
                winsound.Beep(2500, 800)
                time.sleep(0.2)
        else:
            print("\a[Linux System Notification Alert] Target locked successfully.")

    def run_health_check(self):
        try:
            self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")
            time.sleep(2)
            return self.page.locator("text=Sign Out").is_visible() or "dashboard" in self.page.url.lower()
        except Exception:
            return False

    def close(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
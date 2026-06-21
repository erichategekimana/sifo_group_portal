# automation_app/automation_engine/utils.py
import sys
import time
import os
import signal
import concurrent.futures
from contextlib import contextmanager

def kill_browser_processes(user_data_dir):
    """
    Search /proc for any chromium/chrome processes running with this specific user_data_dir as an argument, and kill them.
    This safely prevents 'Failed to create a ProcessSingleton' errors caused by orphaned/stale chromium processes.
    """
    if not sys.platform.startswith('linux'):
        return

    abs_dir = os.path.abspath(user_data_dir)
    my_pid = os.getpid()

    try:
        pids = [int(p) for p in os.listdir('/proc') if p.isdigit()]
    except Exception as e:
        print(f"[Engine] Could not list /proc: {e}")
        return

    for pid in pids:
        if pid == my_pid:
            continue
        try:
            with open(os.path.join('/proc', str(pid), 'cmdline'), 'rb') as f:
                cmdline = f.read()
            # cmdline is null-separated bytes. Convert to string safely.
            cmdline_str = cmdline.decode('utf-8', errors='ignore')
            # Check if this process belongs to chromium and uses our user_data_dir
            if ('chrome' in cmdline_str.lower() or 'chromium' in cmdline_str.lower()) and abs_dir in cmdline_str:
                print(f"[Engine] Killing stale browser process {pid} using profile {abs_dir}")
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, FileNotFoundError):
            continue
        except Exception as e:
            print(f"[Engine] Error checking process {pid}: {e}")

class AbortTaskException(Exception):
    """Exception raised when an automation task needs to be completely aborted and cancelled (e.g., when falling back to manual login)."""
    pass

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
    def log_message(self, message, level="INFO"):
        """
        Log message to console and append to the database log field for the application.
        """
        prefix = f"[{level}]"
        full_msg = f"{prefix} {message}"
        print(f"[Engine] {full_msg}")
        
        record = self.booking_record
        if record:
            from django.utils import timezone
            from automation_app.models import ClientApplication
            def _append_log():
                try:
                    app = ClientApplication.objects.get(id=record.id)
                    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                    new_line = f"[{timestamp}] {full_msg}\n"
                    if app.log_output:
                        app.log_output += new_line
                    else:
                        app.log_output = new_line
                    app.save(update_fields=["log_output"])
                except Exception as e:
                    print(f"[Engine] Failed to write log to DB: {e}")
            run_in_db_thread(_append_log)

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

    def get_user_response(self):
        record = self.booking_record
        if record:
            from automation_app.models import ClientApplication
            def _get():
                try:
                    app = ClientApplication.objects.get(id=record.id)
                    return app.user_response
                except Exception:
                    return None
            return run_in_db_thread(_get)
        return None

    def set_user_response(self, val):
        record = self.booking_record
        if record:
            from automation_app.models import ClientApplication
            def _set():
                try:
                    app = ClientApplication.objects.get(id=record.id)
                    app.user_response = val
                    app.save(update_fields=["user_response"])
                except Exception:
                    pass
            run_in_db_thread(_set)

    def run_interactive_login(self):
        self.log_message("Waiting for manual authentication in the current browser window...", level="INFO")
        try:
            self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")
            
            # Monitor until logged in or timeout
            start_time = time.time()
            login_success = False
            # Wait up to 5 minutes
            while time.time() - start_time < 300:
                if self.page.is_closed():
                    break
                try:
                    # Check if they are logged in or page contains sign out
                    if self.page.locator('a.dropdown-item:has-text("Sohoka ku rubuga")').is_visible() or "dashboard" in self.page.url.lower():
                        login_success = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            
            if login_success:
                time.sleep(3)  # let session settle
                self.log_message("Manual login detected. Session is naturally saved to the persistent profile.", level="INFO")
            else:
                self.log_message("Manual login timed out or window closed.", level="WARNING")
        except Exception as e:
            self.log_message(f"Error during manual login flow: {e}", level="ERROR")

    def rehydrate_session(self):
        self.log_message("Rehydrating session is no longer needed with persistent profiles. Reloading page...", level="INFO")
        try:
            self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")
        except Exception as e:
            self.log_message(f"Failed to reload session: {e}", level="ERROR")

    def close(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
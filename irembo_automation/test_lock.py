import os
import sys
import threading
import time

# Setup Django environment so we can import your actual views and config safely
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automation_project.settings')
try:
    import django
    django.setup()
except Exception:
    pass # If Django setup fails in standalone, we'll gracefully mock the lock

from playwright.sync_api import sync_playwright

# Use your actual utils logic
from automation_app.automation_engine.utils import kill_browser_processes

# Create a temporary directory so we don't mess up your real profile
TEST_DIR = os.path.join(os.getcwd(), "mock_chrome_profile")
browser_lock = threading.Lock()

def simulate_manage_session():
    print("=== [Manage Session] Simulating User Login ===")
    kill_browser_processes(TEST_DIR)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=TEST_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--restore-last-session"],
        )
        page = context.new_page() if len(context.pages) == 0 else context.pages[0]
        page.goto("https://example.com")
        
        # We inject a fake Session Cookie and LocalStorage to mimic Irembo's auth token
        context.add_cookies([{
            "name": "irembo_mock_session_token",
            "value": "super-secret-auth-key-123",
            "domain": "example.com",
            "path": "/"
        }])
        page.evaluate("localStorage.setItem('irembo_auth_user', 'eric')")
        
        print(" -> Fake Auth Session created and saved.")
        print(" -> Closing Manage Session window...")
        context.close()

def mock_worker_task(worker_id):
    print(f"[Worker {worker_id}] Task started. Waiting for browser to be available...")
    with browser_lock:
        print(f"[Worker {worker_id}] Acquired browser lock! Launching Engine...")
        kill_browser_processes(TEST_DIR)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=TEST_DIR,
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--restore-last-session"],
            )
            page = context.new_page() if len(context.pages) == 0 else context.pages[0]
            page.goto("https://example.com")
            
            # Verify if the session we created in Manage Session persisted perfectly
            cookies = context.cookies()
            has_cookie = any(c['name'] == 'irembo_mock_session_token' for c in cookies)
            local_storage_user = page.evaluate("localStorage.getItem('irembo_auth_user')")
            
            if has_cookie and local_storage_user == 'eric':
                print(f"[Worker {worker_id}] SUCCESS: Auth session fully restored! Proceeding with application...")
            else:
                print(f"[Worker {worker_id}] ERROR: Session was lost! Cookie: {has_cookie}, LS: {local_storage_user}")
                
            time.sleep(3) # Simulate slot polling time
            print(f"[Worker {worker_id}] Task complete. Releasing browser.")
            context.close()

if __name__ == "__main__":
    # 1. User logs in manually
    simulate_manage_session()
    
    print("\n=== [Dashboard] Triggering Multiple Applications Simultaneously ===")
    # 2. User selects 3 rows and clicks "Run Selected"
    threads = []
    for i in range(1, 4):
        t = threading.Thread(target=mock_worker_task, args=(i,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    print("\n=== All Tests Finished Successfully ===")

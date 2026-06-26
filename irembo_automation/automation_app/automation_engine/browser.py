# automation_app/automation_engine/browser.py
import os
from playwright.sync_api import sync_playwright  # type: ignore[import]
from playwright_stealth import Stealth  # type: ignore[import]
from .config import (
    USER_DATA_DIR_PATH,
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
    DEFAULT_DEVICE_SCALE_FACTOR,
    DEFAULT_IS_MOBILE,
    DEFAULT_HAS_TOUCH,
    DEFAULT_LOCALE,
    DEFAULT_TIMEZONE,
)

class BrowserMixin:
    def initialize_stealth_browser(self, p, headless=True):
        from .utils import kill_browser_processes
        kill_browser_processes(self.user_data_dir)

        print(f"[Engine] Launching persistent Chrome profile at: {self.user_data_dir}")
        self.context = p.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--restore-last-session"],
            user_agent=DEFAULT_USER_AGENT,
            viewport=DEFAULT_VIEWPORT,
            device_scale_factor=DEFAULT_DEVICE_SCALE_FACTOR,
            is_mobile=DEFAULT_IS_MOBILE,
            has_touch=DEFAULT_HAS_TOUCH,
            locale=DEFAULT_LOCALE,
            timezone_id=DEFAULT_TIMEZONE
        )

        Stealth().apply_stealth_sync(self.context)

        self.context.add_init_script("""
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """)

        # Create a fresh tab to avoid stale DOM from restored sessions
        self.page = self.context.new_page()
        # Close all other restored tabs to clean up the UI
        for p in self.context.pages[:-1]:
            try:
                p.close()
            except Exception:
                pass
            
        self.context.route("**/*", lambda route: self._intercept_resources(route))
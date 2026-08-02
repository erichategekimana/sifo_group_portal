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
        from .config import SESSION_STATE_PATH
        
        print("[Engine] Launching ephemeral Chrome profile for worker...")
        self.browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        state_kwargs = {}
        if os.path.exists(SESSION_STATE_PATH):
            state_kwargs["storage_state"] = SESSION_STATE_PATH
            print(f"[Engine] Injecting session state from {SESSION_STATE_PATH}")
            
        self.context = self.browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport=DEFAULT_VIEWPORT,
            device_scale_factor=DEFAULT_DEVICE_SCALE_FACTOR,
            is_mobile=DEFAULT_IS_MOBILE,
            has_touch=DEFAULT_HAS_TOUCH,
            locale=DEFAULT_LOCALE,
            timezone_id=DEFAULT_TIMEZONE,
            **state_kwargs
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
            
        # Create exactly one clean, fresh tab FIRST to keep the context alive
        self.page = self.context.new_page()

        # Now close any tabs restored by --restore-last-session
        for old_page in list(self.context.pages):
            if old_page != self.page:
                try:
                    old_page.close()
                except Exception:
                    pass

        self.context.route("**/*", lambda route: self._intercept_resources(route))
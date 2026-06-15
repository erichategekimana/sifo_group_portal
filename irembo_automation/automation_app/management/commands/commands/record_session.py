import os
import time
from django.core.management.base import BaseCommand
from playwright.sync_api import sync_playwright  # type: ignore[import]
from playwright_stealth import stealth_sync  # type: ignore[import]

class Command(BaseCommand):
    help = "Launches a stealth Windows 11 browser to capture and record the Irembo authenticated session."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Initializing stealth environment..."))

        with sync_playwright() as p:
            # 1. STEP 2: Configure Hardware-Level Fingerprint Mimicry
            # We run with headless=False so your client can physically log in and complete OTPs.
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled", # Suppresses webdriver flags
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )

            # Target standard Windows 11 / Chrome hardware properties
            windows_ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )

            context = browser.new_context(
                user_agent=windows_ua,
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                is_mobile=False,
                has_touch=False,
                locale="en-US",
                timezone_id="Africa/Kigali"
            )

            # Inject the deep JavaScript runtime stealth patches
            stealth_sync(context)

            # Extra Windows 11 signature hardening via Page Script injection
            # This ensures JavaScript variables match real hardware specifications
            context.add_init_script("""
                Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            """)

            page = context.new_page()

            # 2. STEP 3: The Interactive Capture Loop
            self.stdout.write(self.style.WARNING("\nOpening Irembo Portal..."))
            # Navigate directly to the Irembo Agent login page (Update URL if specific to agents)
            page.goto("https://irembo.gov.rw/", wait_until="networkidle")

            self.stdout.write(self.style.SUCCESS("\n[ACTION REQUIRED]"))
            self.stdout.write("Please perform the login steps manually in the opened browser window.")
            self.stdout.write("Complete any Captchas, ID validations, or Agent OTP entries required.")
            self.stdout.write("-" * 60)

            # Monitor the browser until the user successfully navigates past login
            # We look for indications that they are inside the home dashboard
            print("Waiting for you to log in... Application will auto-save once dashboard loads.")
            
            # Safe tracking loop: check every 2 seconds if the dashboard elements exist
            while True:
                try:
                    # Adjust this selector based on what only logged-in agents see 
                    # (e.g., a sign-out button, profile icon, or agent dashboard metric)
                    if page.locator("text=Sign Out").is_visible() or "dashboard" in page.url.lower():
                        self.stdout.write(self.style.SUCCESS("\nAuthenticated session detected!"))
                        break
                except Exception:
                    pass
                
                # If the user manually closes the browser during the process, abort cleanly
                if page.is_closed():
                    self.stdout.write(self.style.ERROR("\nBrowser closed before session capture completed."))
                    return
                
                time.sleep(2)

            # Give the portal an extra brief moment to settle down and commit all session cookies
            time.sleep(3)

            # 3. Serialize and Save Session State
            state_path = os.path.join(os.getcwd(), "state.json")
            context.storage_state(path=state_path)
            
            self.stdout.write(self.style.SUCCESS(f"\nSession state successfully stored at: {state_path}"))
            self.stdout.write("You can now safely close the browser. This session file will bypass future login prompts.")
            
            context.close()
            browser.close()
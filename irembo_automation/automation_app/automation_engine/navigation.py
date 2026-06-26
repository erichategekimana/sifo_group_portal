# automation_app/automation_engine/navigation.py
import os
import time
from .utils import AbortTaskException

class NavigationMixin:
    def navigate_to_booking_form(self, national_id, verification_data):
        self.log_message("Navigating to Irembo home page...")
        self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")
        # Check active session status
        is_valid = self.validate_agent_session(self.page)
        if not is_valid:
            self.log_message("Active session is expired or missing. Waiting 10 seconds for user action (Continue or Sign In)...", level="WARNING")
            
            # Reset user_response field in DB to WAITING to trigger global popup
            self.set_user_response("WAITING")
            
            start_time = time.time()
            user_action = None
            while time.time() - start_time < 10:
                resp = self.get_user_response()
                if resp in ["continue", "sign_in"]:
                    user_action = resp
                    break
                time.sleep(0.5)
            
            # Clear response to hide popup
            if user_action not in ["continue", "sign_in"]:
                self.set_user_response(None)
            
            if user_action == "continue":
                self.log_message("User chose to continue anyway. Proceeding with current state...")
            elif user_action == "sign_in":
                self.run_interactive_login()
                self.log_message("Manual login finished. Aborting current task to allow a clean restart.", level="WARNING")
                raise AbortTaskException("Task aborted after manual sign-in. Please re-run the application.")
            else:
                self.log_message("No response received within 10 seconds. Continuing with current state...")

        self.page.locator('text="Polisi"').click()
        time.sleep(1)

        self.log_message("Selecting driving registration menu entry layout links...")
        self.page.locator('text="Kwiyandikisha gukora ikizamini cyo gutwara ibinyabiziga"').first.click()
        self.page.wait_for_selector("mat-dialog-container", timeout=10000)

        if self.booking_record and self.booking_record.provisional_number:
            self.log_message("Detected Provisional ID. Configuring Definitive License (BURANDU) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rwa burundu rwo gutwara ikinyabiziga"
        else:
            self.log_message("No Provisional ID found. Configuring Category Upgrade (UPGRADE) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rw'icyiciro kisumbuye"

        self.page.locator("mat-dialog-container ng-select").click()
        self.page.locator(f'.ng-dropdown-panel .ng-option:has-text("{target_service}")').click()
        time.sleep(0.5)

        self.page.locator('mat-dialog-container button:has-text("Saba")').click()
        self.page.wait_for_load_state("networkidle")

        self.handle_identity_verification(national_id, verification_data)
        self.capture_error_if_any()

        # ── After identity modal closes, Angular re-renders the form ──────────
        # Give the page time to settle before looking for the next input.
        self.page.wait_for_load_state("networkidle")
        time.sleep(1.5)

        if self.booking_record and self.booking_record.provisional_number:
            self.log_message(f"Filling Provisional License ID: {self.booking_record.provisional_number}")
            self._fill_provisional_number(self.booking_record.provisional_number)

    def _fill_provisional_number(self, provisional_number):
        """Retry up to 15s to find the field before giving up."""
        candidate_selectors = [
            'input[formcontrolname="provisionalLicenseNumberFormControl"]',
            'input[formcontrolname="provisionalNumber"]',
            'input[formcontrolname="licenseNumber"]',
            'input[formcontrolname="provisionalLicenseNumber"]',
            'input[placeholder*="provisional" i]',
            'input[placeholder*="burandu" i]',
            'input[placeholder*="license" i]',
        ]

        start = time.time()
        prov_field = None
        found_selector = None

        while time.time() - start < 15:
            for selector in candidate_selectors:
                try:
                    loc = self.page.locator(selector).first
                    if loc.is_visible():
                        prov_field = loc
                        found_selector = selector
                        break
                except:
                    continue
            if prov_field:
                break
            time.sleep(0.5)

        if prov_field is None:
            self._save_debug_screenshot("provisional_field_not_found")
            self._pause_on_error(
                "Provisional license number field not found after 15s. "
                "The page may not have loaded correctly after identity verification. "
                "A debug screenshot has been saved to media/debug/."
            )
            return

        self.log_message(f"Provisional field located via: {found_selector}")
        prov_field.fill(provisional_number)
        prov_field.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
        prov_field.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
        time.sleep(0.5)

        self.log_message("Submitting provisional license details...")

        # Try to click the search/submit button
        search_btn_selectors = [
            'button:has-text("Shakisha")',
            'button.inline-btn',
            'button.x-small-button',
            'form.ng-valid button.btn-primary',
            'button.btn-primary',
        ]
        clicked = False
        for btn_selector in search_btn_selectors:
            try:
                btn = self.page.locator(btn_selector).first
                if btn.is_visible() and not btn.is_disabled():
                    self.log_message(f"Clicking search/submit button ({btn_selector})...")
                    btn.click()
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            # Fallback: press Enter in the field
            prov_field.press("Enter")

        time.sleep(2)
        self.capture_error_if_any()
        self.check_for_errors()

    def _save_debug_screenshot(self, label="debug"):
        """Save a full-page screenshot to media/debug/ for post-mortem inspection."""
        try:
            debug_dir = os.path.abspath(os.path.join(os.getcwd(), "media", "debug"))
            if not os.path.exists(debug_dir):
                os.makedirs(debug_dir)
            path = os.path.join(debug_dir, f"{label}_{int(time.time())}.png")
            self.page.screenshot(path=path, full_page=True)
            print(f"[Debug] Screenshot saved: {path}")
        except Exception as e:
            print(f"[Debug] Screenshot failed: {e}")
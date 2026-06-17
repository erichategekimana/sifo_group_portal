# automation_app/automation_engine/navigation.py
import os
import time

class NavigationMixin:
    def navigate_to_booking_form(self, national_id, verification_data):
        print(f"[Engine] Navigating to Irembo home page...")
        self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")

        self.page.locator('text="Polisi"').click()
        time.sleep(1)

        print("[Engine] Selecting driving registration menu entry layout links...")
        self.page.locator('text="Kwiyandikisha gukora ikizamini cyo gutwara ibinyabiziga"').first.click()
        self.page.wait_for_selector("mat-dialog-container", timeout=10000)

        if self.booking_record and self.booking_record.provisional_number:
            print("[Engine Split] Detected Provisional ID. Configuring Definitive License (BURANDU) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rwa burundu rwo gutwara ikinyabiziga"
        else:
            print("[Engine Split] No Provisional ID found. Configuring Category Upgrade (UPGRADE) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rw'icyiciro kisumbuye"

        self.page.locator("mat-dialog-container ng-select").click()
        self.page.locator(f'.ng-dropdown-panel .ng-option:has-text("{target_service}")').click()
        time.sleep(0.5)

        self.page.locator('mat-dialog-container button:has-text("Saba")').click()
        self.page.wait_for_load_state("networkidle")

        self.handle_identity_verification(national_id, verification_data)

        # ── After identity modal closes, Angular re-renders the form ──────────
        # Give the page time to settle before looking for the next input.
        self.page.wait_for_load_state("networkidle")
        time.sleep(1.5)

        if self.booking_record and self.booking_record.provisional_number:
            print(f"[Engine] Filling Provisional License ID: {self.booking_record.provisional_number}")
            self._fill_provisional_number(self.booking_record.provisional_number)

    def _fill_provisional_number(self, provisional_number):
        """
        Locate and fill the provisional licence number field.
        Tries several known formcontrolname values and a generic text-input
        fallback, because the attribute name varies across Irembo deployments.
        Saves a debug screenshot to media/debug/ on failure.
        """
        # Known formcontrolname values observed across service variants
        candidate_selectors = [
            'input[formcontrolname="provisionalLicenseNumberFormControl"]',
            'input[formcontrolname="provisionalNumber"]',
            'input[formcontrolname="licenseNumber"]',
            'input[formcontrolname="provisionalLicenseNumber"]',
            'input[placeholder*="provisional" i]',
            'input[placeholder*="burandu" i]',
            'input[placeholder*="license" i]',
        ]

        prov_field = None
        for selector in candidate_selectors:
            try:
                loc = self.page.locator(selector).first
                loc.wait_for(state="visible", timeout=6000)
                prov_field = loc
                print(f"[Engine] Provisional field located via: {selector}")
                break
            except Exception:
                continue  # try next candidate

        if prov_field is None:
            # Save a debug screenshot so we can inspect the page state
            self._save_debug_screenshot("provisional_field_not_found")
            self._pause_on_error(
                "Provisional license number field not found. "
                "The page may not have loaded correctly after identity verification. "
                "A debug screenshot has been saved to media/debug/."
            )
            return

        prov_field.fill(provisional_number)
        prov_field.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
        prov_field.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
        time.sleep(0.5)

        print("[Engine] Submitting provisional license details...")

        # Click the search/submit button next to the field
        search_btn_selectors = [
            'button:has-text("Shakisha")',
            'button.inline-btn',
            'button.x-small-button',
            'form.ng-valid button.btn-primary',
            'button.btn-primary',
        ]
        for btn_selector in search_btn_selectors:
            try:
                btn = self.page.locator(btn_selector).first
                btn.wait_for(state="visible", timeout=3000)
                print(f"[Engine] Clicking search/submit button ({btn_selector})...")
                btn.click()
                break
            except Exception:
                continue

        time.sleep(2)
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
# automation_app/automation_engine/navigation.py
import os
import time
import random
from .utils import AbortTaskException

class NavigationMixin:
    def navigate_to_booking_form(self, national_id, verification_data):
        self.log_message("Navigating to Irembo home page...")
        self.page.goto("https://irembo.gov.rw/", wait_until="domcontentloaded")
        # Check active session status
        is_valid = self.validate_agent_session(self.page)
        if not is_valid:
            self.log_message("Active session is expired or missing. Proceeding with current state...", level="WARNING")

        if self.booking_record and self.booking_record.provisional_number:
            self.log_message("Detected Provisional ID. Configuring Definitive License (BURANDU) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rwa burundu rwo gutwara ikinyabiziga"
        else:
            self.log_message("No Provisional ID found. Configuring Category Upgrade (UPGRADE) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rw'icyiciro kisumbuye"

        for attempt in range(3):
            try:
                # Wait briefly to ensure Angular event listeners are attached to the 'Polisi' menu
                time.sleep(1.5)
                self.page.locator('text="Polisi"').click()
                time.sleep(1)

                self.log_message("Selecting driving registration menu entry layout links...")
                self.page.locator('text="Kwiyandikisha gukora ikizamini cyo gutwara ibinyabiziga"').first.click()
                
                # Wait for the modal and specifically the ng-select to be visible
                self.page.wait_for_selector("mat-dialog-container ng-select", state="visible", timeout=15000)
                
                # Give Angular a brief moment to attach handlers
                time.sleep(0.5)

                # Attempt to click the dropdown. Use force=True to prevent click interception overlays from causing timeouts.
                self.page.locator("mat-dialog-container ng-select").first.click(force=True, timeout=8000)
                
                # Ensure the dropdown panel is visible before interacting
                self.page.wait_for_selector(".ng-dropdown-panel", state="visible", timeout=5000)
                
                self.page.locator(f'.ng-dropdown-panel .ng-option:has-text("{target_service}")').click(timeout=5000)
                time.sleep(0.5)

                self.page.locator('mat-dialog-container button:has-text("Saba")').click(timeout=5000)
                # Removed wait_for_load_state("networkidle") to significantly speed up transition to ID entry
                break  # Successfully completed the service selection
                
            except Exception as e:
                self.log_message(f"Service selection failed on attempt {attempt+1} due to unstable UI: {e}", level="WARNING")
                if attempt < 2:
                    self.log_message("Refreshing the page as a fallback to clear modal state and retrying...", level="INFO")
                    self.page.reload(wait_until="domcontentloaded")
                    time.sleep(3)
                else:
                    self.log_message("Max attempts reached for service selection. Propagating error.", level="ERROR")
                    raise e

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

        for overall_attempt in range(2):
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
                found, reason, raw = self._scan_for_errors()
                if found:
                    self.log_message(f"Error '{reason}' detected while waiting for provisional field.", level="WARNING")
                    self.capture_error_if_any()
                    
                if overall_attempt == 0:
                    self.log_message("Provisional field not found. Retrying...", level="WARNING")
                    time.sleep(2)
                    continue
    
                self._save_debug_screenshot("provisional_field_not_found")
                self._pause_on_error(
                    "Provisional license number field not found after 15s. "
                    "The page may not have loaded correctly after identity verification. "
                    "A debug screenshot has been saved to media/debug/."
                )
                return
    
            try:
                self.log_message(f"Provisional field located via: {found_selector}")
                prov_field.fill(provisional_number)
                prov_field.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
                prov_field.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
                time.sleep(0.5)
                break
            except Exception as e:
                self.log_message(f"Error filling provisional field: {e}. Retrying...", level="WARNING")
                if overall_attempt == 1:
                    raise e
                time.sleep(1)

        self.log_message("Submitting provisional license details...")

        search_btn_selectors = [
            'button:has-text("Shakisha")',
            'button.inline-btn',
            'button.x-small-button',
            'form.ng-valid button.btn-primary',
            'button.btn-primary',
        ]
        
        for attempt in range(4):
            clicked = False
            for btn_selector in search_btn_selectors:
                try:
                    btn = self.page.locator(btn_selector).first
                    if btn.is_visible() and not btn.is_disabled():
                        self.log_message(f"Clicking search/submit button ({btn_selector}) (Attempt {attempt+1}/4)...")
                        btn.click()
                        clicked = True
                        break
                except:
                    continue

            if not clicked:
                # Fallback: press Enter in the field
                prov_field.press("Enter")

            time.sleep(random.uniform(1.5, 3.0)) # Human-like delay after click
            
            try:
                # Check for known errors without raising immediately
                found, reason, raw = self._scan_for_errors()
                if found:
                    if attempt < 3:
                        self.log_message(f"Attempt {attempt+1} encountered error '{reason}'. Retrying search...", level="WARNING")
                        time.sleep(random.uniform(1.0, 2.0))
                        continue
                    else:
                        self.log_message(f"Max attempts (4) reached. Failing on error '{reason}'.", level="ERROR")
                        self.capture_error_if_any() # Raise exception and save DB status
                
                # Check for generic errors
                self.check_for_errors()
                
                # No errors detected
                self.log_message("Provisional license successfully verified.")
                break
            except Exception as e:
                if attempt < 3:
                    self.log_message(f"Attempt {attempt+1} threw exception: {e}. Retrying...", level="WARNING")
                    time.sleep(random.uniform(1.0, 2.0))
                    continue
                else:
                    raise e

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
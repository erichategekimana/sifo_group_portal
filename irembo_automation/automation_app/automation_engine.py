import os
import random
import sys
import time
import re
from playwright.sync_api import sync_playwright  # type: ignore[import]
from playwright_stealth import Stealth  # type: ignore[import]

# Conditional import for Windows-native audio components
if sys.platform == "win32":
    import winsound
else:
    winsound = None

class IremboAutomationEngine:
    def __init__(self, booking_record=None):
        self.state_file = os.path.abspath(os.path.join(os.getcwd(), "state.json"))
        self.browser = None
        self.context = None
        self.page = None
        # Reference to the active Django ClientApplication instance
        self.booking_record = booking_record

    def initialize_stealth_browser(self, p, headless=True):
        """
        Launches an isolated browser instance mimicking normal human footprint attributes.
        """
        self.browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )

        windows_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        context_params = {
            "user_agent": windows_ua,
            "viewport": {"width": 1920, "height": 1080},
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "locale": "en-US",
            "timezone_id": "Africa/Kigali"
        }

        if os.path.exists(self.state_file):
            print("[Engine] Found existing state.json. Rehydrating active session tokens...")
            context_params["storage_state"] = self.state_file
        else:
            print("[Engine] WARNING: state.json not found! Running with a clean context.")

        self.context = self.browser.new_context(**context_params)
        Stealth().apply_stealth_sync(self.context)
        
        # Spoof internal platform variables to emulate destination system environments
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """)

        self.page = self.context.new_page()
        self.context.route("**/*", lambda route: self._intercept_resources(route))

    def _intercept_resources(self, route):
        """
        Blocks heavy visual asset payloads to maximize processing speeds.
        """
        ignored_types = ["image", "font", "stylesheet", "media"]
        if route.request.resource_type in ignored_types or "analytics" in route.request.url.lower():
            route.abort()
        else:
            route.continue_()

    def check_for_errors(self):
        """
        Scans the page for common error indicators (toasts, mat-errors, alert boxes).
        Raises ValueError if a visible error is detected.
        """
        error_selectors = [
            "mat-error",
            ".alert-danger",
            ".text-danger",
            "mat-snack-bar-container",
            ".toast-message",
            ".error-message"
        ]
        for selector in error_selectors:
            try:
                elements = self.page.locator(selector).all()
                for el in elements:
                    if el.is_visible():
                        error_text = el.inner_text().strip()
                        if error_text:
                            print(f"[Engine Error Detected] {error_text}")
                            raise ValueError(f"Irembo Portal Error: {error_text}")
            except ValueError:
                raise
            except Exception:
                pass

    def handle_identity_verification(self, national_id, client_verification_data):
        """
        Inputs National ID credentials and clears the identity popup modal layout.
        Fixes Angular forms data binding lag by forcing standard input events.
        """
        print(f"[Step 8] Injecting National ID: {national_id}")
        id_field = self.page.locator('input[formcontrolname="nationalIdFormControl"]')
        id_field.fill(national_id)
        id_field.press("Enter")
        
        print("[Step 8] Monitoring for the security validation modal container...")
        self.page.wait_for_selector("mat-dialog-container", timeout=12000)
        time.sleep(1) 

        # Resolve dynamic validation field targets
        name_input = self.page.locator('input[formcontrolname="nameFormControl"]')
        date_input = self.page.locator('input[id="datePicker"]')

        # Wait for either name_input or date_input to become visible (to avoid race conditions)
        print("[Step 8] Waiting for validation fields to render inside the modal...")
        start_time = time.time()
        while time.time() - start_time < 5.0:
            if name_input.is_visible() or date_input.is_visible():
                break
            time.sleep(0.2)

        # Determine inputs based on database record or fallbacks
        first_name = self.booking_record.first_name if (self.booking_record and self.booking_record.first_name) else client_verification_data
        
        if self.booking_record and self.booking_record.birth_date:
            # Format as DD/MM/YYYY which is standard for Irembo
            birth_date_str = self.booking_record.birth_date.strftime("%d/%m/%Y")
        else:
            birth_date_str = client_verification_data

        if name_input.is_visible():
            print(f"[Step 8] Verification challenge detected: Name layout requested. Filling: {first_name}")
            name_input.fill(first_name)
            # FORCE FIX: Dispatch input triggers so Angular recognizes the form field values
            name_input.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
            name_input.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
        elif date_input.is_visible():
            print(f"[Step 8] Verification challenge detected: Birth date selection entry requested. Filling: {birth_date_str}")
            date_input.fill(birth_date_str)
            date_input.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
            date_input.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")

        print("[Step 8] Checking inner modal terms checkbox frame elements...")
        # FORCE FIX: Click the core sub-container element to reliably activate the checkbox state toggle
        checkbox_container = self.page.locator('mat-checkbox:has-text("Nemeye amategeko agenga imikoreshereze") .mat-checkbox-inner-container')
        checkbox_container.click()
        time.sleep(0.5)

        print("[Step 8] Submitting identity verification review confirmation ('Genzura')...")
        review_btn = self.page.locator('mat-dialog-container button.btn-primary:has-text("Genzura")')
        
        # Wait for the button to be visible
        try:
            review_btn.wait_for(state="visible", timeout=4000)
        except Exception:
            self.check_for_errors()
            raise ValueError("Verification button ('Genzura') was not found or not visible.")

        # Check if the button is disabled
        if review_btn.is_disabled():
            print("[Warning] Form validation state locked. Checking for immediate validation errors...")
            time.sleep(1)
            self.check_for_errors()
            raise ValueError("Verification button ('Genzura') is disabled. Please verify ID, name, or birth date values.")

        review_btn.click()
        
        # Wait until modal completely detaches from view layers, or check for errors
        try:
            self.page.wait_for_selector("mat-dialog-container", state="detached", timeout=8000)
            print("[Step 8] Identity validation parameters cleared successfully.")
        except Exception:
            self.check_for_errors()
            raise ValueError("Identity verification modal did not close. Please verify the credentials.")

    def navigate_to_booking_form(self, national_id, verification_data):
        """
        Routes application categories dynamically based on model configurations.
        """
        print(f"[Engine] Navigating to Irembo home page...")
        self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")
        
        self.page.locator('text="Polisi"').click()
        time.sleep(1)

        print("[Engine] Selecting driving registration menu entry layout links...")
        # Safe fix for responsive duplication elements targeting strict layouts
        self.page.locator('text="Kwiyandikisha gukora ikizamini cyo gutwara ibinyabiziga"').first.click()
        self.page.wait_for_selector("mat-dialog-container", timeout=10000)

        # -----------------------------------------------------------------------
        # NEW LOGIC SPLIT FLOW: Evaluate choice paths dynamically
        # -----------------------------------------------------------------------
        if self.booking_record and self.booking_record.provisional_number:
            print("[Engine Split] Detected Provisional ID. Configuring Definitive License (BURANDU) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rwa burundu rwo gutwara ikinyabiziga"
        else:
            print("[Engine Split] No Provisional ID found. Configuring Category Upgrade (UPGRADE) application.")
            target_service = "Kwiyandikisha gukora ikizamini cy'uruhushya rw'icyiciro kisumbuye"

        # Apply choice interaction configurations to Angular component targets
        self.page.locator("mat-dialog-container ng-select").click()
        self.page.locator(f'.ng-dropdown-panel .ng-option:has-text("{target_service}")').click()
        time.sleep(0.5)

        self.page.locator('mat-dialog-container button:has-text("Saba")').click()
        self.page.wait_for_load_state("networkidle")

        # Handshake input validations (enters ID, handles modal name/birthdate checks, accepts modal terms, and clicks Genzura)
        self.handle_identity_verification(national_id, verification_data)

        # -----------------------------------------------------------------------
        # DEFINITIVE FLOW PROVISIONAL NUMBER INPUT
        # -----------------------------------------------------------------------
        if self.booking_record and self.booking_record.provisional_number:
            print(f"[Engine] Filling Provisional License ID: {self.booking_record.provisional_number}")
            prov_field = self.page.locator('input[formcontrolname="provisionalLicenseNumberFormControl"]')
            # Wait for provisional field to be visible and editable
            prov_field.wait_for(state="visible", timeout=10000)
            prov_field.fill(self.booking_record.provisional_number)
            # Ensure Angular recognizes the input
            prov_field.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
            prov_field.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
            time.sleep(0.5)

            # Click Shakisha or press Enter to load the registration table
            print("[Engine] Submitting provisional license details...")
            prov_field.press("Enter")
            time.sleep(0.5)

            search_btn = self.page.locator('button:has-text("Shakisha"), form.ng-valid button.btn-primary, button.btn-primary').first
            try:
                search_btn.wait_for(state="visible", timeout=3000)
                print("[Engine] Clicking search/submit button...")
                search_btn.click()
            except Exception as e:
                print(f"[Engine] Search button not visible or not found after 3s ({e}). Continuing...")
            
            # Wait for any immediate error messages to display
            time.sleep(2)
            self.check_for_errors()

    def set_angular_dropdown(self, control_name, option_text):
        """
        Handles dynamic choice options for custom Angular select modules.
        Can match by exact control_name, or look for placeholder/label text if exact match is not found.
        """
        # Try finding by exact formcontrolname first
        dropdown = self.page.locator(f'ng-select[formcontrolname="{control_name}"]')
        if not dropdown.is_visible():
            # Fallback 1: case-insensitive partial match on formcontrolname
            dropdown = self.page.locator(f'ng-select[formcontrolname*="{control_name}" i]').first
        
        if not dropdown.is_visible():
            # Fallback 2: search for the ng-select containing label text or placeholder
            dropdown = self.page.locator(f'ng-select:has-text("{control_name}")').first

        if not dropdown.is_visible():
            # Fallback 3: look for any ng-select
            dropdown = self.page.locator('ng-select').first

        print(f"[Dropdown] Clicking dropdown matching {control_name} to select option: {option_text}")
        dropdown.click()
        self.page.wait_for_selector(".ng-dropdown-panel", timeout=5000)
        
        options = self.page.locator('.ng-dropdown-panel .ng-option')
        options.wait_for(state="visible", timeout=5000)
        
        matched = False
        count = options.count()
        
        # Tier 1: Exact match (case-sensitive)
        for i in range(count):
            opt = options.nth(i)
            text = opt.inner_text().strip()
            if text == option_text:
                opt.click()
                matched = True
                break
                
        # Tier 2: Exact match (case-insensitive)
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip()
                if text.lower() == option_text.lower():
                    opt.click()
                    matched = True
                    break

        # Tier 3: Suffix match (case-insensitive) - handles e.g. "Icyiciro B" ending with "B"
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                if text.endswith(option_text.lower()):
                    opt.click()
                    matched = True
                    break

        # Tier 4: Word boundary match (case-insensitive) - handles e.g. "B" in "Icyiciro B exam"
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                pattern = r'\b' + re.escape(option_text.lower()) + r'\b'
                if re.search(pattern, text):
                    opt.click()
                    matched = True
                    break

        # Tier 5: Substring match (case-insensitive fallback)
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                if option_text.lower() in text:
                    opt.click()
                    matched = True
                    break
                    
        # Final Fallback: click the first option if no match is found
        if not matched and count > 0:
            options.first.click()
            
        time.sleep(1)

    def evaluate_and_select_slot(self, target_center="BUSANZA"):
        """
        Scans data arrays on slot layout grids and verifies matching spaces.
        """
        badge_element = self.page.locator('.appointments-header h2.title span.badge')
        if not badge_element.is_visible():
            return False

        available_slots_count = int(badge_element.inner_text().strip())
        if available_slots_count == 0:
            return False

        slots = self.page.locator(".appointments-list .appointment-slot").all()
        for slot in slots:
            center_details = slot.locator(".center").inner_text().upper()
            capacity_text = slot.locator(".capacity-circle").inner_text().strip()
            
            try:
                capacity = int(capacity_text)
            except ValueError:
                capacity = 0

            if target_center in center_details and capacity > 0:
                print(f"[Slot Match] Locking center location: {center_details} ({capacity} seats)")
                slot.click()
                time.sleep(0.5)
                
                # Double check selection feedback classing tags before moving forward
                if "selected" in slot.get_attribute("class") or slot.locator(".selected-text").is_visible():
                    self.page.locator("#next_btn").click()
                    return True
        return False

    def start_slot_polling(self, target_center="BUSANZA AUTOMATED CENTER"):
        """
        Runs automated monitoring loops over structural center layouts.
        """
        print("[Engine] Polling engine activated. Monitoring availability maps...")
        
        # 1. Initial selection of category
        if self.booking_record and self.booking_record.category:
            print(f"[Engine] Setting category selection to: {self.booking_record.category}")
            # Try formcontrolname first, fallback to partial matches
            self.set_angular_dropdown("licenseCategoryFormControl", self.booking_record.category)
        else:
            print("[Warning] No target category specified in database record. Skipping initial category selection.")

        # 2. Initial selection of district
        print("[Engine] Setting district selection to Kicukiro...")
        self.set_angular_dropdown("districtFormControl", "Kicukiro")
        
        while True:
            try:
                # Extract and click available slots matches
                slot_secured = self.evaluate_and_select_slot(target_center=target_center)

                if slot_secured:
                    print(f"[Engine] Slot secured at {target_center}! Transitioning to OTP stage...")
                    self.enter_cooperative_interrupt_state()
                    client_phone = self.booking_record.phone_number if self.booking_record else "0780000000"
                    billing_id = self.resume_and_finalize_booking(phone_number=client_phone)
                    return billing_id 

                # Wait between polls using random human-like delay
                poll_delay = random.uniform(4.0, 7.5)
                print(f"[Engine] No slot found at {target_center}. Waiting {poll_delay:.2f}s before toggling district to refresh...")
                time.sleep(poll_delay)
                
                # Stealth/efficient refresh: toggle district to force Angular to update slots list without page reload
                print("[Engine] Toggling district to refresh slots...")
                self.set_angular_dropdown("districtFormControl", "Gasabo")
                time.sleep(random.uniform(1.2, 2.5))
                self.set_angular_dropdown("districtFormControl", "Kicukiro")
                time.sleep(random.uniform(1.2, 2.5))

            except InterruptedError as ie:
                print(f"[Engine] Shutting down polling gracefully: {ie}")
                break
            except Exception as e:
                print(f"[Engine] Exception occurrence inside checking loop: {str(e)}")
                # In case of general failure, sleep briefly and try toggling district again
                time.sleep(5)

    def enter_cooperative_interrupt_state(self):
        """
        Halts automation loops cleanly without dropping active channel paths.
        """
        self.update_database_state("AWAITING_OTP")
        self.trigger_windows_alerts()
        
        while True:
            if self.booking_record:
                self.booking_record.refresh_from_db()
                if self.booking_record.status == "OTP_PROVIDED":
                    break
                if self.booking_record.status == "CANCELLED":
                    raise InterruptedError("Operation canceled via Agent Panel.")
            else:
                time.sleep(15)
                break
            time.sleep(1.0)

    def resume_and_finalize_booking(self, phone_number):
        """
        Completes structural details fields and inputs OTP elements.
        """
        print(f"[Step 10] Resuming flow validation for phone targets: {phone_number}")
        phone_checkbox = self.page.locator('mat-checkbox:has-text("Nomero ya telefoni (Rwanda)")')
        if not phone_checkbox.locator('input').is_checked():
            phone_checkbox.click()
            time.sleep(0.5)

        phone_input = self.page.locator('input[placeholder*="07"], input[type="tel"]').first
        phone_input.fill(phone_number)

        # Inject the long-form main template checkbox confirmations statements
        exact_form_terms = "Nemeje ko amakuru yose natanze ahangaha ari ukuri kandi ajyanye n'igihe."
        self.page.locator(f'mat-checkbox:has-text("{exact_form_terms}") .mat-checkbox-inner-container').click()
        time.sleep(0.5)

        self.page.locator('#submit_btn.btn-success:has-text("Emeza")').click()

        if self.booking_record and self.booking_record.otp_code:
            print(f"[Step 10] Injecting received operational verification OTP tokens: {self.booking_record.otp_code}")
            otp_input = self.page.locator('input[formcontrolname*="otp"], input[placeholder*="OTP"]').first
            try:
                self.page.wait_for_selector(otp_input, timeout=10000)
                otp_input.fill(self.booking_record.otp_code)
                self.page.locator('button:has-text("Emeza"), button:has-text("Genzura")').last.click()
            except Exception as e:
                print(f"[Step 10] Failed processing token entry fields layouts: {e}")

        # Extract transaction tracking information keys
        try:
            billing_text_locator = self.page.locator('text="Kode yo kwishyuriraho", text="Kode you kwishyuriraho"')
            billing_text_locator.wait_for(timeout=15000)
            full_text = billing_text_locator.locator("xpath=..").inner_text()
            match = re.search(r'(88\d+)', full_text)
            
            if match and self.booking_record:
                billing_code = match.group(1)
                self.booking_record.billing_number = billing_code
                self.update_database_state("SUCCESS")
                self.capture_confirmation_receipt()
                return billing_code
            else:
                self.update_database_state("MANUAL_REVIEW_NEEDED")
                return None
        except Exception as e:
            print(f"[Step 10] Exception caught reading transaction values grids: {e}")
            self.update_database_state("FAILED")
            return None

    def capture_confirmation_receipt(self):
        """
        Saves visual receipts records to local media asset systems.
        """
        try:
            self.page.wait_for_selector(".success-container, .billing-info-box", timeout=15000)
            national_id = self.booking_record.national_id if self.booking_record else "unknown_client"
            filename = f"receipt_{national_id}_{int(time.time())}.png"
            media_dir = os.path.abspath(os.path.join(os.getcwd(), "media", "receipts"))
            
            if not os.path.exists(media_dir):
                os.makedirs(media_dir)

            screenshot_path = os.path.join(media_dir, filename)
            self.page.screenshot(path=screenshot_path, full_page=True)
            return filename
        except Exception as e:
            print(f"[Warning] Visual data extraction tracking capture error: {e}")
            return None

    def update_database_state(self, new_status):
        if self.booking_record:
            self.booking_record.status = new_status
            self.booking_record.save()

    def trigger_windows_alerts(self):
        if sys.platform == "win32" and winsound:
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
        if self.context: self.context.close()
        if self.browser: self.browser.close()


if __name__ == "__main__":
    with sync_playwright() as p:
        engine = IremboAutomationEngine()
        engine.initialize_stealth_browser(p, headless=False)
        engine.close()
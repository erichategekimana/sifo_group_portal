import os
import random
import sys
import time
import re
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

# Conditional import for Windows-native audio components
# This prevents Ubuntu development from crashing during local run execution
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
        # Link to the active Django model record tracking this specific client's application
        self.booking_record = booking_record

    def initialize_stealth_browser(self, p, headless=True):
        """
        Launches a headless browser mimicking the target execution footprint.
        """
        # Disable automation indicators via Chromium flags
        self.browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )

        # Standard Windows 11 / Chrome profile layout (for final cross-platform alignment)
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

        # Step 4: Rehydrate the context using the state file if it exists
        if os.path.exists(self.state_file):
            print("[Engine] Found existing state.json. Rehydrating active session tokens...")
            context_params["storage_state"] = self.state_file
        else:
            print("[Engine] WARNING: state.json not found! Running with a clean, unauthenticated context.")

        self.context = self.browser.new_context(**context_params)
        
        # Apply stealth patches
        stealth_sync(self.context)
        
        # Hardware property spoofing overrides
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """)

        self.page = self.context.new_page()

        # ----------------------------------------------------------------------
        # Network Resource Interception for Speed Superiority
        # -----------------------------------------------------------------------
        # Intercept network requests globally across this browser context
        self.context.route("**/*", lambda route: self._intercept_resources(route))


    def trigger_windows_alerts(self):
        """
        Triggers aggressive hardware sounds and system alerts on Windows 11
        to grab the agent's attention immediately. Falls back gracefully on Linux.
        """
        print("[Step 9] ALERT! Target slot located. Activating audio alarm cluster...")
        
        if sys.platform == "win32" and winsound:
            try:
                # Play an audible pattern sequence: 3 sharp high-pitch alert rings
                for _ in range(3):
                    winsound.Beep(2500, 800)  # Frequency: 2500Hz, Duration: 800ms
                    time.sleep(0.2)
            except Exception as e:
                print(f"[Step 9] Windows internal sound output alert failed: {e}")
        else:
            # Clean backup signal signature for your local Ubuntu Linux terminal environment
            print("\a[Linux Dev Alert] BEEP! Slot locked successfully (System audio triggered).")

    def update_database_state(self, new_status):
        """
        Pushes an immediate state update to PostgreSQL to communicate with the Django UI.
        """
        if self.booking_record:
            print(f"[Step 9] Transitioning database state tracker to: {new_status}")
            # Update the status field dynamically on your Django model
            self.booking_record.status = new_status
            self.booking_record.save()
        else:
            print(f"[Step 9] Dev Mode Warning: No database record attached. State simulated: {new_status}")

    def enter_cooperative_interrupt_state(self):
        """
        Halts the automatic navigation engine loop without losing the active browser page.
        Locks into a safe holding loop while waiting for Step 10's OTP injection sequence.
        """
        # 1. Alert the database and UI layer that human intervention is required
        self.update_database_state("AWAITING_OTP")
        
        # 2. Fire physical machine hardware alarms
        self.trigger_windows_alerts()
        
        print("[Step 9] Engine successfully paused in Cooperative Interrupt mode.")
        print("[Step 9] Holding active browser state open on the Irembo OTP submission form...")
        
        # The engine enters a non-blocking poll loop checking the database status state.
        # This prevents the thread from finishing or refreshing the webpage asset.
        while True:
            if self.booking_record:
                # Refresh record information directly from the PostgreSQL pipeline
                self.booking_record.refresh_from_db()
                
                # If the user provides the OTP via the Django UI, Step 10 breaks this loop
                if self.booking_record.status == "OTP_PROVIDED":
                    print("[Step 9] Active resume signal caught from database profile. Exiting pause state.")
                    break
                
                # If the agent cancels the operation from the dashboard screen
                if self.booking_record.status == "CANCELLED":
                    print("[Step 9] Operational cancellation signal caught. Stopping execution.")
                    raise InterruptedError("Operation aborted by Agent.")
            else:
                # Sandbox safe developer fallback so the loop doesn't spin endlessly on your ThinkPad
                print("[Step 9 Dev Mode] Holding execution frame for 15 seconds before auto-resuming...")
                time.sleep(15)
                break
                
            # Sleep precisely 1 second between database health check requests to minimize processor load
            time.sleep(1.0)



    def _intercept_resources(self, route):
        """
        Aborts requests for images, fonts, stylesheet formatting, and analytical 
        trackers to maximize extraction speeds. Only permits crucial layout scripts and APIs.
        """
        ignored_types = ["image", "font", "stylesheet", "media"]
        request_url = route.request.url.lower()

        # Block specific asset types or third-party analytical endpoints
        if route.request.resource_type in ignored_types or "analytics" in request_url or "google-analytics" in request_url:
            # Drop the request immediately before network bandwidth is used
            route.abort()
        else:
            # Let functional scripts, documents, and API responses pass through
            route.continue_()


    # -----------------------------------------------------------------------
    # NEW INTERACTION LOGIC PIPELINE
    # -----------------------------------------------------------------------

    def handle_identity_verification(self, national_id, client_verification_data, provisional_no=None):
        """
        Inputs National ID credentials and handles the identity confirmation 
        pop-up dynamically based on whether it requests a name or a birth date.
        """
        print(f"[Step 8] Injecting National ID: {national_id}")
        # Locate the exact input by its Angular form control property attribute
        id_field = self.page.locator('input[formcontrolname="nationalIdFormControl"]')
        id_field.fill(national_id)
        id_field.press("Enter")
        
        # If running a definitive test layout, fill out the provisional number field if visible
        if provisional_no:
            print(f"[Step 8] Filling Provisional License Number: {provisional_no}")
            prov_field = self.page.locator('input[formcontrolname="provisionalLicenseNumberFormControl"]')
            prov_field.fill(provisional_no)
            # Click the search button attached right inside that input cluster
            self.page.locator('form.ng-valid button.btn-primary').click()

        print("[Step 8] Monitoring for the security validation modal container...")
        # Wait for the Keycloak/Irembo validation popup structure to attach to the view
        self.page.wait_for_selector("mat-dialog-container", timeout=10000)
        time.sleep(1) # Brief stabilization pause

        # Check if the modal field wants a Name string vs a Birthdate string dynamically
        name_input = self.page.locator('input[formcontrolname="nameFormControl"]')
        date_input = self.page.locator('input[id="datePicker"]') # Fallback if dynamic selector changes

        if name_input.is_visible():
            print("[Step 8] Security field matching: Name input requested.")
            name_input.fill(client_verification_data)
        elif date_input.is_visible():
            print("[Step 8] Security field matching: Birthdate registration input requested.")
            date_input.fill(client_verification_data)
        else:
            # Absolute text selector failover if form control configurations drift
            self.page.locator('input[placeholder*="Injiza"]').fill(client_verification_data)

        # Accept terms within the modal layout safely via text string identification
        # Avoiding variable ID matching patterns since dynamic IDs can conflict
        self.page.locator('mat-checkbox:has-text("Nemeye amategeko")').click()
        time.sleep(0.5)

        # Click the submission confirmation element
        print("[Step 8] Clicking verification confirmation button ('Genzura')...")
        self.page.locator('mat-dialog-container button:has-text("Genzura")').click()
        
        # Wait until modal detaches, indicating verification succeeded
        self.page.wait_for_selector("mat-dialog-container", state="detached", timeout=12000)
        print("[Step 8] Identity validation cleared successfully.")

    def set_angular_dropdown(self, control_name, option_text):
        """
        Safely interacts with Angular ng-select wrapper elements.
        Clicks the component, waits for the dropdown menu container, and selections an option.
        """
        dropdown_selector = f'ng-select[formcontrolname="{control_name}"]'
        print(f"[Step 8] Opening dropdown choice field: {control_name} -> Selecting: {option_text}")
        
        # Trigger the focus click wrapper
        self.page.locator(dropdown_selector).click()
        
        # Wait for Angular's global floating option drop container to map into the DOM body
        self.page.wait_for_selector(".ng-dropdown-panel", timeout=5000)
        
        # Select the specific item matching our target text string pattern
        self.page.locator(f'.ng-dropdown-panel .ng-option:has-text("{option_text}")').click()
        time.sleep(1)

    def evaluate_and_select_slot(self, target_center="BUSANZA"):
        """
        Parses the active slot selectors dynamically. Verifies seats numbers, 
        flags empty states, and clicks the target layout element instantly.
        """
        # Read the explicit numerical availability badge text content directly
        badge_element = self.page.locator('.appointments-header h2.title span.badge')
        
        if not badge_element.is_visible():
            print("[Step 8] No slot tracking headers currently loaded on view container.")
            return False

        available_slots_count = int(badge_element.inner_text().strip())
        print(f"[Step 8] System detected {available_slots_count} total open slot listings.")

        if available_slots_count == 0:
            print("[Step 8] Availability metrics remain at zero. Passing current verification loop.")
            return False

        # Gather every slot element box loaded onto the UI panel
        slots = self.page.locator(".appointments-list .appointment-slot").all()
        
        for slot in slots:
            center_details = slot.locator(".center").inner_text().upper()
            capacity_text = slot.locator(".capacity-circle").inner_text().strip()
            
            try:
                capacity = int(capacity_text)
            except ValueError:
                capacity = 0

            print(f"[Slot Found] Center: {center_details} | Free Spaces: {capacity}")

            # Check if this match fits our target center location parameters with valid seats
            if target_center in center_details and capacity > 0:
                print(f"[Step 8] TARGET MATCH FOUND! Selecting slot at {center_details} with {capacity} spaces.")
                slot.click()
                
                # Verify that the browser updates the selection class label status safely
                time.sleep(0.5)
                if "selected" in slot.get_attribute("class") or slot.locator(".selected-text").is_visible():
                    print("[Step 8] Slot locked and verified via 'Watoranyijwe' state check confirmation.")
                    
                    # Move directly to the OTP phase page trigger click layout
                    self.page.locator("#next_btn").click()
                    return True
        
        return False

    def run_health_check(self):
        """
        Step 5: Verifies if the rehydrated session is still logged in.
        Returns True if authenticated, False if token expired.
        """
        print("[Engine] Executing session health check...")
        try:
            # Navigate directly to a portal page that requires an active login session
            # (e.g., your specific agent dashboard URL or profile page)
            self.page.goto("https://irembo.gov.rw/", wait_until="networkidle")
            
            # Introduce a humanized micro-delay to let DOM components render
            time.sleep(random.uniform(1.5, 2.5))

            # Look for elements that prove an authenticated state vs a public guest state
            # Replace 'Sign Out' or check URL states depending on actual portal dashboard markers
            is_logged_in = self.page.locator("text=Sign Out").is_visible() or "dashboard" in self.page.url.lower()
            
            if is_logged_in:
                print("[Engine] Health check PASSED. Active session token verified.")
                return True
            else:
                print("[Engine] Health check FAILED. Session has expired or requires re-authentication.")
                return False

        except Exception as e:
            print(f"[Engine] Health check encountered an error: {str(e)}")
            return False
    # -----------------------------------------------------------------------
    # STEP 7: The Adaptive Polling Loop Engine
    # -----------------------------------------------------------------------
    def start_slot_polling(self, target_center="BUSANZA AUTOMATED CENTER"):
        print("[Engine] Polling engine activated. Monitoring slot availability variations...")
        
        while True:
            try:
                self._select_kicukiro_district()
                slot_secured = self.evaluate_and_select_slot(target_center=target_center)

                if slot_secured:
                    print("[Engine] Slot locked! Moving directly into Step 9 Cooperative Interrupt.")
                    
                    # 1. Halt the engine and trigger Windows 11 Alarms
                    self.enter_cooperative_interrupt_state()
                    
                    # 2. Once the loop breaks (OTP provided via Django UI), run Step 10
                    # Fallback to a test number if running without a live DB record
                    client_phone = self.booking_record.phone_number if self.booking_record else "0780000000"
                    
                    billing_id = self.resume_and_finalize_booking(phone_number=client_phone)
                    
                    return billing_id 

                # Jitter delays and reload
                jitter_delay = random.uniform(3.5, 6.2)
                time.sleep(jitter_delay)
                self.page.reload(wait_until="commit")

            except InterruptedError as ie:
                print(f"[Engine] Shutting down execution cleanly: {ie}")
                break
            except Exception as e:
                print(f"[Engine] Exception occurring during polling cycle: {str(e)}")
                time.sleep(5)

    def resume_and_finalize_booking(self, phone_number):
            """
            Executes Step 10: Completes the notification form, accepts terms, submits,
            injects the OTP received from the Django UI, and extracts the billing ID.
            """
            print(f"[Step 10] Resuming execution... Processing notification for phone: {phone_number}")

            # 1. Select the "Nomero ya telefoni (Rwanda)" checkbox
            phone_checkbox = self.page.locator('mat-checkbox:has-text("Nomero ya telefoni (Rwanda)")')
            if not phone_checkbox.locator('input').is_checked():
                phone_checkbox.click()
                time.sleep(0.5) # Allow Angular DOM to render the new input field

            # 2. Fill the dynamically rendered phone number field
            # Using a fallback hierarchy to ensure we hit the right input even if classes change
            phone_input = self.page.locator('input[placeholder*="07"], input[type="tel"]').first
            if phone_input.is_visible():
                phone_input.fill(phone_number)
            else:
                # Fallback based on the notification card container structure
                self.page.locator('.notification-card input').last.fill(phone_number)

            # 3. Accept the final terms and conditions
            terms_checkbox = self.page.locator('mat-checkbox:has-text("Nemeje ko amakuru yose natanze")')
            if not terms_checkbox.locator('input').is_checked():
                terms_checkbox.click()
                time.sleep(0.5)

            # 4. Click the 'Emeza' (Submit) button
            print("[Step 10] Clicking 'Emeza' to trigger submission...")
            self.page.locator('#submit_btn').click()

            # 5. OTP Injection Handshake
            # Assuming the Irembo OTP verification modal appears right after submission
            if self.booking_record and self.booking_record.otp_code:
                print(f"[Step 10] Injecting OTP code: {self.booking_record.otp_code}")
                
                # Using flexible generic locators for the OTP field
                otp_input = self.page.locator('input[formcontrolname*="otp"], input[placeholder*="OTP"], input[placeholder*="kode"]').first
                
                try:
                    self.page.wait_for_selector(otp_input, timeout=10000)
                    otp_input.fill(self.booking_record.otp_code)
                    
                    # Click the verification submission button on the modal
                    self.page.locator('button:has-text("Emeza"), button:has-text("Genzura"), button:has-text("Komeza")').last.click()
                except Exception as e:
                    print(f"[Step 10] Warning: OTP modal not found or structure changed. Error: {e}")

            # 6. Extract the Final Billing Code
            print("[Step 10] Waiting for the final billing confirmation table...")
            
            try:
                # Wait for the billing text string. Accounting for potential "Kode yo" vs "Kode you" typos.
                billing_text_locator = self.page.locator('text="Kode yo kwishyuriraho", text="Kode you kwishyuriraho"')
                billing_text_locator.wait_for(timeout=15000)
                
                # Navigate up the DOM tree slightly to grab the surrounding container text
                billing_container = billing_text_locator.locator("xpath=..")
                full_text = billing_container.inner_text()
                
                # Use Regex to explicitly extract the standard Irembo billing format (typically starting with 88)
                match = re.search(r'(88\d+)', full_text)
                
                if match and self.booking_record:
                    billing_code = match.group(1)
                    print(f"[Step 10] SUCCESS! Billing Code Extracted: {billing_code}")
                    
                    # Commit the final data to the PostgreSQL database
                    self.booking_record.billing_number = billing_code
                    self.update_database_state("SUCCESS")
                    return billing_code
                else:
                    print("[Step 10] Text found, but billing numbers could not be parsed.")
                    self.update_database_state("MANUAL_REVIEW_NEEDED")
                    return None
                    
            except Exception as e:
                print(f"[Step 10] Billing table timeout or extraction failure. {e}")
                self.update_database_state("FAILED")
                return None


    def close(self):
        """Clean teardown of browser contexts."""
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        print("[Engine] Browser context closed down cleanly.")


# Sandboxed testing execution entry point
if __name__ == "__main__":
    with sync_playwright() as p:
        engine = IremboAutomationEngine()
        # Setting headless=False for local visibility on Linux during dev
        engine.initialize_stealth_browser(p, headless=False)
        
        authenticated = engine.run_health_check()
        if not authenticated:
            print("\n[Action Needed] Please run 'python3 manage.py record_session' again to renew tokens.")
        
        engine.close()

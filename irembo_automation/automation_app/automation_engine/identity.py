# automation_app/automation_engine/identity.py
import time
import random

class IdentityMixin:
    def handle_identity_verification(self, national_id, client_verification_data):
        for attempt in range(4):
            self.log_message(f"Injecting National ID: {national_id} (Attempt {attempt + 1}/4)")
            id_field = self.page.locator('input[formcontrolname="nationalIdFormControl"]')
            id_field.fill(national_id)
            id_field.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
            id_field.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
            id_field.press("Tab")
            time.sleep(0.5)

            self.log_message("Monitoring for the security validation modal container...")
            # Wait for any mat-dialog-container to appear, then get the first visible one
            try:
                self.page.wait_for_selector("mat-dialog-container:visible", timeout=12000)
            except Exception:
                self._pause_on_error("Identity verification modal did not appear. National ID may be invalid or session expired.")
            time.sleep(1)

            # Scope to the visible modal
            modal = self.page.locator("mat-dialog-container:visible").first

            # Locate the challenge inputs inside this modal only
            date_input = modal.locator('input[formcontrolname="birthDateFormControl"]')
            name_input = modal.locator('input[formcontrolname="nameFormControl"]')

            self.log_message("Waiting for verification challenge field to render...")
            challenge_detected = False
            start_time = time.time()
            while time.time() - start_time < 6.0:
                if date_input.is_visible() or name_input.is_visible():
                    challenge_detected = True
                    break
                time.sleep(0.3)

            if not challenge_detected:
                self._pause_on_error(
                    "Verification challenge field (birth date or name) did not appear inside the modal. "
                    "The modal may have changed structure or an unexpected error was shown."
                )

            first_name = (
                self.booking_record.first_name
                if (self.booking_record and self.booking_record.first_name)
                else client_verification_data
            )
            if self.booking_record and self.booking_record.birth_date:
                birth_date_str = self.booking_record.birth_date.strftime("%d/%m/%Y")
            else:
                birth_date_str = client_verification_data

            if date_input.is_visible():
                self.log_message(f"Challenge: Birth date requested. Typing: {birth_date_str}")
                self._type_into_field(date_input, birth_date_str)
                # Dismiss the datepicker overlay to avoid blocking subsequent clicks
                self.page.keyboard.press("Escape")
                time.sleep(0.3)
            elif name_input.is_visible():
                self.log_message(f"Challenge: Name requested. Typing: {first_name}")
                self._type_into_field(name_input, first_name)
            else:
                self._pause_on_error("No visible input field found in verification modal.")

            time.sleep(0.5)

            # --- Checkbox handling (improved) ---
            self.log_message("Verifying terms checkbox state...")
            # Scope checkbox inside the modal as well (optional, but safer)
            checkbox_input = modal.locator('mat-checkbox:has-text("Nemeye") input[type="checkbox"]')
            try:
                # Find the hidden checkbox to check its state
                checkbox_input = modal.locator('mat-checkbox input[type="checkbox"]').first
                checkbox_input.wait_for(state="attached", timeout=5000)
                
                is_checked = checkbox_input.evaluate("el => el.checked")
                if not is_checked:
                    self.log_message("Terms checkbox is unchecked. Performing human-like click on the label...")
                    try:
                        # NATIVE STEALTH CLICK: Click the inner container explicitly. 
                        # This avoids clicking the label text which contains a hyperlink (target="_blank")
                        # and prevents the bug where a new tab opens and the checkbox remains unchecked.
                        modal.locator('.mat-checkbox-inner-container').first.click(timeout=3000)
                    except Exception as native_err:
                        self.log_message(f"Native click failed ({native_err}). Using JS fallback...", level="WARNING")
                        checkbox_input.evaluate("el => el.click()") # Fallback
                checkbox_input.wait_for(state="visible", timeout=5000)
                if not checkbox_input.is_checked():
                    self.log_message("Terms checkbox is unchecked. Clicking to accept...")
                    checkbox_input.check()
                else:
                    self.log_message("Terms checkbox already checked. Skipping click.")
            except Exception as e:
                self.log_message(f"Warning: Could not interact with checkbox ({e}). Attempting fallback click on container...", level="WARNING")
                container = modal.locator('mat-checkbox:has-text("Nemeye") .mat-checkbox-inner-container')
                container.click(force=True)

            # --- Genzura button ---
            self.log_message("Locating 'Genzura' confirmation button...")
            review_btn = modal.locator('button.btn-primary')

            try:
                review_btn.wait_for(state="visible", timeout=4000)
            except Exception:
                self.check_for_errors()
                self._pause_on_error("'Genzura' button was not found in the modal. The page structure may have changed.")

            self.log_message("Waiting for 'Genzura' button to become enabled...")
            btn_enabled = False
            start_time = time.time()
            while time.time() - start_time < 5.0:
                if not review_btn.is_disabled():
                    btn_enabled = True
                    break
                time.sleep(0.3)

            if not btn_enabled:
                self.check_for_errors()
                self._pause_on_error(
                    "Verification button ('Genzura') remained disabled after 5s. "
                    "Check that the verification data (birth date or name) exactly matches the ID document."
                )

            self.log_message("Submitting identity verification ('Genzura')...")
            review_btn.click()

            try:
                self.page.wait_for_selector("mat-dialog-container", state="detached", timeout=10000)
                
                # Wait briefly for any post-modal errors to render on the main page
                time.sleep(1)
                found, reason, raw = self._scan_for_errors()
                if found:
                    self.log_message(f"Error '{reason}' detected after modal detached.", level="WARNING")
                    raise ValueError(f"Irembo Error: {reason}")
                    
                self.log_message("Identity verification completed successfully.")
                break # Success! exit the retry loop
            except Exception:
                # Intercept expected errors to allow internal retry
                found, reason, raw = self._scan_for_errors()
                retryable_reasons = ["NIDA_NTIBONETSE", "IBISOBANURO_NTIBIHUYE", "YAMAZ_KWIYANDIKISHA", "PERIMI_YABUZE", "ASANZWE_AFITE_URUHUSHYA", "RWATAKAJE_AGACIRO", "UMWIRONDORO_NTUBONETSE"]
                
                if found and reason in retryable_reasons and attempt < 3:
                    self.log_message(f"Verification attempt {attempt + 1} failed with error '{reason}'. Retrying with a new challenge...", level="WARNING")
                    
                    # Close the modal
                    close_btn = modal.locator('i-x#close_btn.dialog-close, .close, [mat-dialog-close]').first
                    if close_btn.is_visible():
                        self.log_message("Clicking close button to dismiss verification modal.")
                        close_btn.click()
                    else:
                        self.log_message("Close button not visible, pressing Escape.", level="WARNING")
                        self.page.keyboard.press("Escape")
                    
                    # Wait for modal to detach
                    try:
                        self.page.wait_for_selector("mat-dialog-container", state="detached", timeout=5000)
                    except Exception:
                        pass # Ignore if it didn't detach fully, proceed to clear ID
                    
                    # Clear National ID to trigger it again
                    self.log_message("Clearing National ID field to restart verification...")
                    id_field.fill("")
                    id_field.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
                    id_field.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
                    
                    # Human-like delay
                    time.sleep(random.uniform(1.5, 3.5))
                    continue # Start next attempt loop iteration
                else:
                    # If max attempts reached and error is known, explicitly record and fail
                    if found and reason in retryable_reasons and attempt >= 3:
                        self.log_message(f"Max verification attempts (4) reached for '{reason}'. Recording failure.", level="ERROR")
                        self.check_for_errors() # Will raise the known error
                        
                    # If not a retryable error or max attempts reached, handle normally
                    self.check_for_errors()
                    self._pause_on_error(
                        "Identity verification modal did not close after clicking 'Genzura'. "
                        "Credentials may be incorrect or the portal returned an error."
                    )
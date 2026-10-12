# automation_app/automation_engine/final.py
import re
import time
import os
import random
from .utils import run_in_db_thread   # thread-safe ORM dispatch


class FinalizationMixin:
    """
    Handles everything that happens after a slot is secured:
      1. Fill in the phone number
      2. Confirm the "info is legit" terms checkbox
      3. Submit the application
      4. Collect the billing number from the confirmation page
      5. Save it to the DB, mark SUCCESS, play the alert sound, take a screenshot
    No OTP step is involved.
    """

    def finalize_booking(self, phone_number):
        """
        Complete the application after the slot has been locked.
        Called immediately after evaluate_and_select_slot() returns True.
        """
        self.log_message(f"Starting finalization for phone: {phone_number}")

        # ── Step 1: Select phone number notification channel ─────────────────
        try:
            phone_checkbox = self.page.locator('mat-checkbox:has-text("Nomero ya telefoni (Rwanda)")')
            phone_checkbox.wait_for(state="visible", timeout=8000)
            if not phone_checkbox.locator('input').is_checked():
                phone_checkbox.click()
                time.sleep(0.4)
        except Exception as e:
            self.log_message(f"Phone channel checkbox not found or already selected: {e}", level="WARNING")

        # ── Step 2: Fill in the phone number ─────────────────────────────────
        current_phone = phone_number
        try:
            phone_input = self.page.locator(
                'input[placeholder*="07"], input[type="tel"], input[formcontrolname*="phone"]'
            ).first
            phone_input.wait_for(state="visible", timeout=8000)
            phone_input.fill(current_phone)
            time.sleep(0.3)
            self.log_message(f"Phone number entered: {current_phone}")
        except Exception as e:
            self.log_message(f"Could not fill phone number field: {e}", level="WARNING")

        # ── Step 3: Accept the "info is correct" terms checkbox ───────────────
        exact_terms = "Nemeje ko amakuru yose natanze ahangaha ari ukuri kandi ajyanye n'igihe."
        try:
            terms_box = self.page.locator(
                f'mat-checkbox:has-text("{exact_terms}") .mat-checkbox-inner-container'
            )
            terms_box.wait_for(state="visible", timeout=8000)
            terms_box.click()
            time.sleep(0.4)
            self.log_message("Terms checkbox accepted.")
        except Exception as e:
            # Fallback — try any unchecked checkbox near the bottom of the form
            self.log_message(f"Terms checkbox primary locator failed ({e}). Trying fallback...", level="WARNING")
            try:
                fallback = self.page.locator('mat-checkbox input[type="checkbox"]').last
                if not fallback.is_checked():
                    fallback.check()
                    time.sleep(0.4)
            except Exception as fe:
                self.log_message(f"Fallback checkbox also failed: {fe}", level="WARNING")

        # ── Step 3.1: Check for phone registration error and fallback to secondary phone if available ──
        try:
            time.sleep(0.5)
            found, reason, raw = self._scan_for_errors()
            if found and reason == "TELEFONE_NTIBARUYE_KURI_ID":
                secondary = getattr(self.booking_record, 'secondary_phone', None) if self.booking_record else None
                if secondary and secondary.strip() and secondary.strip() != current_phone.strip():
                    self.log_message(
                        f"Primary phone {current_phone} is not registered to ID. Attempting fallback to secondary phone {secondary.strip()}...",
                        level="WARNING"
                    )
                    phone_input = self.page.locator(
                        'input[placeholder*="07"], input[type="tel"], input[formcontrolname*="phone"]'
                    ).first
                    phone_input.fill("")
                    phone_input.fill(secondary.strip())
                    current_phone = secondary.strip()
                    time.sleep(0.8)
                    self.log_message(f"Secondary phone entered: {current_phone}")
        except Exception as e:
            self.log_message(f"Phone verification check warning: {e}", level="WARNING")

        # ── Step 4: Submit the application ────────────────────────────────────
        submit_success = False
        submit_btn = self.page.locator('#submit_btn')
        last_error_reason = None
        last_error_raw = None
        
        for attempt in range(20):
            try:
                submit_btn.wait_for(state="visible", timeout=10000)
                # Wait for it to become enabled (not disabled)
                start = time.time()
                while time.time() - start < 10:
                    if not submit_btn.is_disabled():
                        break
                    
                    # If submit button is disabled, check if an error is blocking it
                    found, reason, raw = self._scan_for_errors()
                    if found:
                        last_error_reason = reason
                        last_error_raw = raw
                        self.log_message(f"Form error detected while button disabled: '{reason}' - {raw}", level="WARNING")
                        if reason == "TELEFONE_NTIBARUYE_KURI_ID":
                            secondary = getattr(self.booking_record, 'secondary_phone', None) if self.booking_record else None
                            if secondary and secondary.strip() and secondary.strip() != current_phone.strip():
                                self.log_message(
                                    f"Primary phone {current_phone} is not registered to ID. Attempting fallback to secondary phone {secondary.strip()}...",
                                    level="WARNING"
                                )
                                try:
                                    phone_input = self.page.locator(
                                        'input[placeholder*="07"], input[type="tel"], input[formcontrolname*="phone"]'
                                    ).first
                                    phone_input.fill("")
                                    phone_input.fill(secondary.strip())
                                    current_phone = secondary.strip()
                                    time.sleep(1.0)
                                    last_error_reason = None
                                    last_error_raw = None
                                    continue
                                except Exception as fe:
                                    self.log_message(f"Fallback to secondary phone failed: {fe}", level="WARNING")
                            # If no secondary or secondary already tried, break immediately
                            break
                    time.sleep(random.uniform(0.3, 0.6))
                else:
                    raise Exception("Submit button remained disabled after 10 seconds.")
                
                # If unregistered phone error is blocking the form, abort loop immediately
                if last_error_reason == "TELEFONE_NTIBARUYE_KURI_ID":
                    break

                self.log_message(f"Clicking submit button (Attempt {attempt+1}/20)...")
                submit_btn.click()
                time.sleep(random.uniform(1.5, 3.0)) # Human-like delay after click
                
                # Check for known errors after click without failing immediately
                found, reason, raw = self._scan_for_errors()
                if found:
                    self.log_message(f"Attempt {attempt+1} failed with error '{reason}'. Retrying...", level="WARNING")
                    last_error_reason = reason
                    last_error_raw = raw
                    if reason == "TELEFONE_NTIBARUYE_KURI_ID":
                        # Non-retryable
                        break
                    time.sleep(random.uniform(2.0, 4.0))
                    continue
                
                # Check if click actually advanced the page (confirmation page rendered or submit button gone)
                confirmation_elements = self.page.locator(
                    'div.bill-id-container, div.payment-panels, span.inside-title, .payment-card, .success-container, .billing-info-box'
                )
                
                page_advanced = False
                start_check = time.time()
                while time.time() - start_check < 3.0:
                    try:
                        if confirmation_elements.count() > 0 or not submit_btn.is_visible():
                            page_advanced = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)

                if page_advanced:
                    self.log_message("Application submitted successfully. Waiting for confirmation page...")
                    submit_success = True
                    break # Success!
                else:
                    # Click was performed while button was enabled, but Irembo did nothing (no error and submit button is still visible)
                    self.log_message(
                        f"Submit button clicked but page did not advance (Attempt {attempt+1}/20). Retrying click...",
                        level="WARNING"
                    )
                    time.sleep(random.uniform(1.0, 2.0))
                    continue
            except Exception as e:
                if last_error_reason == "TELEFONE_NTIBARUYE_KURI_ID":
                    break
                self.log_message(f"Attempt {attempt+1} threw exception: {e}. Retrying...", level="WARNING")
                time.sleep(random.uniform(1.5, 3.0))
                continue
                
        if not submit_success:
            self.log_message("Submit button failed after attempts.", level="ERROR")
            if last_error_reason and self.booking_record:
                record = self.booking_record
                def _save_fail():
                    from automation_app.models import ClientApplication
                    app = ClientApplication.objects.get(id=record.id)
                    app.status = "FAILED"
                    app.failure_reason = last_error_reason
                    if last_error_raw:
                        app.last_error = last_error_raw
                        error_banner = f"\n=== [IKOSA RYABONETSE / ERROR DETECTED] ===\nReason Code: {last_error_reason}\nMessage: {last_error_raw}\n============================================\n"
                        app.log_output = (app.log_output or "") + error_banner
                    update_fields = ["status", "failure_reason"]
                    if last_error_raw:
                        update_fields.extend(["last_error", "log_output"])
                    app.save(update_fields=update_fields)
                run_in_db_thread(_save_fail)
            else:
                self.update_database_state("FAILED")
            return None

                # ── Step 5: Collect billing number ──────────────────────────
        billing_code = None
        try:
            # Wait for the final billing page to render.
            self.page.wait_for_selector(
                'div.bill-id-container, div.payment-panels, span.inside-title, .payment-card',
                timeout=30000,
            )

            # Poll the page for the billing number text.
            end_time = time.time() + 30
            while time.time() < end_time:
                # Primary path: explicit billing container.
                if self.page.locator('div.bill-id-container').count() > 0:
                    billing_text = self.page.locator('div.bill-id-container').first.inner_text().strip()
                    match = re.search(r'\b(88\d{6,})\b', billing_text)
                    if match:
                        billing_code = match.group(1)
                        break

                # Secondary path: payment panel with label and inline number.
                if self.page.locator('div.payment-panels').count() > 0:
                    panel_text = self.page.locator('div.payment-panels').first.inner_text().strip()
                    match = re.search(r'\b(88\d{6,})\b', panel_text)
                    if match:
                        billing_code = match.group(1)
                        break

                # Tertiary path: label + sibling text number.
                if self.page.locator('span.inside-title:has-text("Kode yo kwishyuriraho")').count() > 0:
                    parent_text = self.page.locator('span.inside-title:has-text("Kode yo kwishyuriraho")').first.locator('xpath=..').inner_text()
                    match = re.search(r'\b(88\d{6,})\b', parent_text)
                    if match:
                        billing_code = match.group(1)
                        break

                time.sleep(1)

            if not billing_code:
                body_text = self.page.locator('body').inner_text()
                matches = re.findall(r'\b(88\d{6,})\b', body_text)
                if matches:
                    billing_code = matches[0]
                else:
                    preview = body_text.replace('\n', ' ')[:400]
                    self.log_message(f"Billing code still missing; page text snapshot: {preview}", level="WARNING")
        except Exception as e:
            self.log_message(f"Billing code extraction error: {e}", level="ERROR")

        if billing_code:
            self.log_message(f"Billing code captured: {billing_code}")
            record = self.booking_record
            if record:
                def _save_billing():
                    record.billing_number = billing_code
                    record.save(update_fields=["billing_number"])
                run_in_db_thread(_save_billing)

            self.update_database_state("SUCCESS")

            # ── Step 6: Alert sound + screenshot ──────────────────
            self.trigger_windows_alerts()
            self.log_message("Billing code saved and alert triggered.")
            self.capture_confirmation_receipt()

            # ── Step 7: Keep browser open for 30 seconds ──────────
            self.log_message("Booking completed. Browser will stay open for 30 seconds before closing.")
            time.sleep(30)  # 30 seconds

            return billing_code
        else:
            self.log_message("Billing code not found after confirmation wait.", level="ERROR")
            self.capture_confirmation_receipt()
            self.update_database_state("MANUAL_REVIEW_NEEDED")
            return None

    def capture_confirmation_receipt(self):
        """Screenshot the confirmation page."""
        try:
            self.page.wait_for_selector(
                ".success-container, .billing-info-box, .confirmation-page",
                timeout=10000,
            )
            national_id = self.booking_record.national_id if self.booking_record else "unknown_client"
            filename = f"receipt_{national_id}_{int(time.time())}.png"
            media_dir = os.path.abspath(os.path.join(os.getcwd(), "media", "receipts"))

            if not os.path.exists(media_dir):
                os.makedirs(media_dir)

            screenshot_path = os.path.join(media_dir, filename)
            self.page.screenshot(path=screenshot_path, full_page=True)
            self.log_message(f"Receipt saved: {screenshot_path}")
            return filename
        except Exception as e:
            self.log_message(f"Screenshot capture failed: {e}", level="ERROR")
            return None
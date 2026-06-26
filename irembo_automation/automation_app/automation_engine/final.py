# automation_app/automation_engine/final.py
import re
import time
import os
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
        try:
            phone_input = self.page.locator(
                'input[placeholder*="07"], input[type="tel"], input[formcontrolname*="phone"]'
            ).first
            phone_input.wait_for(state="visible", timeout=8000)
            phone_input.fill(phone_number)
            time.sleep(0.3)
            self.log_message(f"Phone number entered: {phone_number}")
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

        # ── Step 4: Submit the application ────────────────────────────────────
        try:
            # Use the ID-based selector – it's unique and reliable
            submit_btn = self.page.locator('#submit_btn')
            submit_btn.wait_for(state="visible", timeout=10000)
            # Wait for it to become enabled (not disabled)
            start = time.time()
            while time.time() - start < 10:
                if not submit_btn.is_disabled():
                    break
                time.sleep(0.3)
            else:
                raise Exception("Submit button remained disabled after 10 seconds.")
            self.capture_error_if_any()
            submit_btn.click()
            self.log_message("Application submitted. Waiting for confirmation page...")
        except Exception as e:
            self.log_message(f"Submit button error: {e}", level="ERROR")
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

            # ── Step 7: Keep browser open for 5 minutes ──────────
            self.log_message("Booking completed. Browser will stay open for 5 minutes before closing.")
            time.sleep(300)  # 5 minutes

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
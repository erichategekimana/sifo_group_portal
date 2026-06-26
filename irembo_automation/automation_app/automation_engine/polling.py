# automation_app/automation_engine/polling.py
import random
import time

class PollingMixin:
    def _get_time_options(self):
        """
        Returns a list of all visible time option texts.
        Retries if dropdown doesn't appear.
        """
        for attempt in range(3):
            time_dropdown = self.page.locator('label:has-text("Igihe") + ng-select, ng-select[bindlabel="formatted"]')
            if not time_dropdown.is_visible():
                time_dropdown = self.page.locator('ng-select:has-text("Guhitamo hakurikijwe igihe")').first
            if time_dropdown.is_visible():
                break
            time.sleep(0.5)
        else:
            print("[Warning] Time dropdown not found after retries.")
            return []

        time_dropdown.click()
        self.page.wait_for_selector(".ng-dropdown-panel", timeout=5000)

        options = self.page.locator('.ng-dropdown-panel .ng-option')
        options.first.wait_for(state="visible", timeout=3000)

        count = options.count()
        texts = [options.nth(i).inner_text().strip() for i in range(count)]
        return texts

    def _select_time_slot_by_index(self, index):
        """
        Selects the time option at the given index (0‑based).
        Returns True on success.
        """
        for attempt in range(3):
            time_dropdown = self.page.locator('label:has-text("Igihe") + ng-select, ng-select[bindlabel="formatted"]')
            if not time_dropdown.is_visible():
                time_dropdown = self.page.locator('ng-select:has-text("Guhitamo hakurikijwe igihe")').first
            if time_dropdown.is_visible():
                break
            time.sleep(0.5)
        else:
            print("[Warning] Time dropdown not found.")
            return False

        time_dropdown.click()
        self.page.wait_for_selector(".ng-dropdown-panel", timeout=5000)

        options = self.page.locator('.ng-dropdown-panel .ng-option')
        count = options.count()
        if index >= count:
            print(f"[Time] Index {index} out of range (only {count} options).")
            return False

        options.nth(index).click()
        time.sleep(1)
        return True

    def evaluate_and_select_slot(self, target_center="BUSANZA"):
        badge_element = self.page.locator('.appointments-header h2.title span.badge')
        if not badge_element.is_visible():
            return False

        available_slots_count = int(badge_element.inner_text().strip())
        if available_slots_count == 0:
            return False

        slots = self.page.locator(".appointments-list .appointment-slot").all()
        for slot in slots:
            if "dimmed" in (slot.get_attribute("class") or ""):
                continue

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

                if "selected" in (slot.get_attribute("class") or "") or slot.locator(".selected-text").is_visible():
                    self.page.locator("#next_btn").click()
                    return True
        return False

    def start_slot_polling(self, target_center="BUSANZA AUTOMATED CENTER"):
        self.log_message("Polling engine activated. Monitoring availability maps...")

        # 1. Select category
        if self.booking_record and self.booking_record.category:
            self.log_message(f"Setting category selection to: {self.booking_record.category}")
            category_control = "categoryFormControl"
            if not self.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                category_control = "licenseCategoryFormControl"
            self.set_angular_dropdown(category_control, self.booking_record.category)
        else:
            self.log_message("No target category specified. Skipping.", level="WARNING")

        # 2. Select district
        district_control = "locationFormControl"
        if not self.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
            district_control = "districtFormControl"

        self.log_message(f"Setting district selection (using control: {district_control}) to Kicukiro...")
        self.set_angular_dropdown(district_control, "Kicukiro")

        # 3. Get available time options
        time_options = self._get_time_options()
        if not time_options:
            self.log_message("No time options found. Aborting.", level="ERROR")
            return None

        time_index = 0
        consecutive_errors = 0

        while True:
            try:
                # Check page closure before starting the iteration
                if self.page is None or self.page.is_closed():
                    raise Exception("Browser page is closed.")

                self.capture_error_if_any()

                # Select the current time
                self.log_message(f"Selecting time slot: {time_options[time_index]} (index {time_index})")
                if not self._select_time_slot_by_index(time_index):
                    # If selection fails, increment and try next
                    time_index += 1
                    if time_index >= len(time_options):
                        # All times exhausted – toggle district
                        self.log_message("All time slots exhausted. Toggling district to refresh...")
                        self.set_angular_dropdown(district_control, "Gasabo")
                        time.sleep(random.uniform(1.2, 2.5))
                        self.set_angular_dropdown(district_control, "Kicukiro")
                        time.sleep(random.uniform(1.2, 2.5))
                        time_options = self._get_time_options()
                        if not time_options:
                            self.log_message("No time options after district toggle. Waiting and retrying...", level="WARNING")
                            time.sleep(5)
                            continue
                        time_index = 0
                    continue

                # Now check slots
                slot_secured = self.evaluate_and_select_slot(target_center=target_center)

                if slot_secured:
                    self.log_message(f"Slot secured at {target_center}! Proceeding to finalization...")
                    try:
                        client_phone = self.booking_record.phone_number if self.booking_record else "0780000000"
                        billing_id = self.finalize_booking(phone_number=client_phone)
                        if billing_id:
                            self.log_message("Booking completed successfully. Browser will remain open for inspection.")
                            self.log_message("Closing browser in 5 minutes...")
                            time.sleep(300)
                        return billing_id
                    except Exception as e:
                        self.log_message(f"Finalization failed after slot secured: {e}", level="ERROR")
                        raise e

                # Reset consecutive errors since loop made progress
                consecutive_errors = 0

                # No slot found – move to next time
                time_index += 1
                if time_index >= len(time_options):
                    # All times exhausted – toggle district to refresh
                    self.log_message("All time slots exhausted. Toggling district to refresh...")
                    self.set_angular_dropdown(district_control, "Gasabo")
                    time.sleep(random.uniform(1.2, 2.5))
                    self.set_angular_dropdown(district_control, "Kicukiro")
                    time.sleep(random.uniform(1.2, 2.5))
                    time_options = self._get_time_options()
                    if not time_options:
                        self.log_message("No time options after district toggle. Waiting and retrying...", level="WARNING")
                        time.sleep(5)
                        continue
                    time_index = 0

                # Small delay between time attempts
                time.sleep(random.uniform(1.0, 2.0))

            except InterruptedError as ie:
                self.log_message(f"Shutting down polling gracefully: {ie}")
                break
            except Exception as e:
                consecutive_errors += 1
                self.log_message(f"Exception in polling loop: {str(e)}", level="WARNING")
                
                # Check for critical closure conditions
                if self.page is None or self.page.is_closed() or not self.browser or not self.browser.is_connected():
                    self.log_message("Browser page closed or disconnected. Aborting polling loop.", level="ERROR")
                    raise e
                
                if consecutive_errors >= 5:
                    self.log_message("Exceeded maximum consecutive polling loop exceptions. Propagating failure.", level="ERROR")
                    raise e
                
                time.sleep(5)
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
        print("[Engine] Polling engine activated. Monitoring availability maps...")

        # 1. Select category
        if self.booking_record and self.booking_record.category:
            print(f"[Engine] Setting category selection to: {self.booking_record.category}")
            category_control = "categoryFormControl"
            if not self.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                category_control = "licenseCategoryFormControl"
            self.set_angular_dropdown(category_control, self.booking_record.category)
        else:
            print("[Warning] No target category specified. Skipping.")

        # 2. Select district
        district_control = "locationFormControl"
        if not self.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
            district_control = "districtFormControl"

        print(f"[Engine] Setting district selection (using control: {district_control}) to Kicukiro...")
        self.set_angular_dropdown(district_control, "Kicukiro")

        # 3. Get available time options
        time_options = self._get_time_options()
        if not time_options:
            print("[Error] No time options found. Aborting.")
            return None

        time_index = 0

        while True:
            try:
                # Select the current time
                print(f"[Engine] Selecting time slot: {time_options[time_index]} (index {time_index})")
                if not self._select_time_slot_by_index(time_index):
                    # If selection fails, increment and try next
                    time_index += 1
                    if time_index >= len(time_options):
                        # All times exhausted – toggle district
                        print("[Engine] All time slots exhausted. Toggling district to refresh...")
                        self.set_angular_dropdown(district_control, "Gasabo")
                        time.sleep(random.uniform(1.2, 2.5))
                        self.set_angular_dropdown(district_control, "Kicukiro")
                        time.sleep(random.uniform(1.2, 2.5))
                        time_options = self._get_time_options()
                        if not time_options:
                            print("[Error] No time options after district toggle. Waiting and retrying...")
                            time.sleep(5)
                            continue
                        time_index = 0
                    continue

                # Now check slots
                slot_secured = self.evaluate_and_select_slot(target_center=target_center)

                if slot_secured:
                    print(f"[Engine] Slot secured at {target_center}! Proceeding to finalization...")
                    try:
                        client_phone = self.booking_record.phone_number if self.booking_record else "0780000000"
                        billing_id = self.finalize_booking(phone_number=client_phone)
                        if billing_id:
                            print("[Engine] Booking completed successfully. Browser will remain open for inspection.")
                            print("Press Enter to close the browser and finish the worker thread.")
                            input()   # Wait for user to press Enter
                        return billing_id
                    except Exception as e:
                        print(f"[Engine] Finalization failed after slot secured: {e}")
                        # Optionally pause here too for debugging
                        return None

                # No slot found – move to next time
                time_index += 1
                if time_index >= len(time_options):
                    # All times exhausted – toggle district to refresh
                    print("[Engine] All time slots exhausted. Toggling district to refresh...")
                    self.set_angular_dropdown(district_control, "Gasabo")
                    time.sleep(random.uniform(1.2, 2.5))
                    self.set_angular_dropdown(district_control, "Kicukiro")
                    time.sleep(random.uniform(1.2, 2.5))
                    time_options = self._get_time_options()
                    if not time_options:
                        print("[Error] No time options after district toggle. Waiting and retrying...")
                        time.sleep(5)
                        continue
                    time_index = 0

                # Small delay between time attempts
                time.sleep(random.uniform(1.0, 2.0))

            except InterruptedError as ie:
                print(f"[Engine] Shutting down polling gracefully: {ie}")
                break
            except Exception as e:
                print(f"[Engine] Exception in polling loop: {str(e)}")
                # On unexpected error, wait and continue (but we might be stuck)
                time.sleep(5)
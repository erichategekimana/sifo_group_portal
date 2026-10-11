# automation_app/automation_engine/polling.py
import random
import time
from .utils import run_in_db_thread
from .locations import get_location_strategy, LocationStrategy

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

        # Robust click loop for the dropdown to ensure panel opens
        panel_opened = False
        for attempt in range(3):
            try:
                time_dropdown.click(force=True, timeout=5000)
                self.page.wait_for_selector(".ng-dropdown-panel", state="visible", timeout=5000)
                panel_opened = True
                break
            except Exception as e:
                print(f"[Warning] Attempt {attempt+1} failed to open time dropdown panel. Retrying...")
                time.sleep(1.5)
                
        if not panel_opened:
            print("[Warning] Failed to open time dropdown panel after 3 attempts.")
            return []

        options = self.page.locator('.ng-dropdown-panel .ng-option')
        options.first.wait_for(state="visible", timeout=3000)

        count = options.count()
        texts = [options.nth(i).inner_text().strip() for i in range(count)]
        return texts

    def _select_time_slot_by_index(self, index):
        """
        Re-opens the time dropdown and clicks the option at index.
        """
        time_dropdown = self.page.locator('label:has-text("Igihe") + ng-select, ng-select[bindlabel="formatted"]')
        if not time_dropdown.is_visible():
            time_dropdown = self.page.locator('ng-select:has-text("Guhitamo hakurikijwe igihe")').first

        if not time_dropdown.is_visible():
            print("[Time] Dropdown not visible.")
            return False

        # If panel is not open, click with retries to open it
        panel_opened = False
        for attempt in range(3):
            try:
                if not self.page.locator('.ng-dropdown-panel').is_visible():
                    time_dropdown.click(force=True, timeout=5000)
                    self.page.wait_for_selector(".ng-dropdown-panel", state="visible", timeout=5000)
                panel_opened = True
                break
            except Exception as e:
                print(f"[Warning] Attempt {attempt+1} failed to open time dropdown panel. Retrying...")
                time.sleep(1.5)
                
        if not panel_opened:
            print("[Warning] Failed to open time dropdown panel after 3 attempts.")
            return False

        options = self.page.locator('.ng-dropdown-panel .ng-option')
        count = options.count()
        if index >= count:
            print(f"[Time] Index {index} out of range (only {count} options).")
            return False

        options.nth(index).click()
        time.sleep(1)
        return True

    def evaluate_and_select_slot(self, target_center=None, location_strategy=None):
        """
        Evaluates visible slots on the current booking page against the target center/strategy.
        If a matching slot with capacity > 0 is found, clicks it and advances to next step.
        """
        badge_element = self.page.locator('.appointments-header h2.title span.badge')
        if not badge_element.is_visible():
            return False

        try:
            available_slots_count = int(badge_element.inner_text().strip())
        except (ValueError, TypeError):
            return False

        if available_slots_count == 0:
            return False

        slots = self.page.locator(".appointments-list .appointment-slot").all()
        for slot in slots:
            if "dimmed" in (slot.get_attribute("class") or ""):
                continue

            center_details = slot.locator(".center").inner_text().strip()
            capacity_text = slot.locator(".capacity-circle").inner_text().strip()

            try:
                capacity = int(capacity_text)
            except ValueError:
                capacity = 0

            if capacity <= 0:
                continue

            # Check match using OOP strategy if provided, otherwise fallback to target_center substring
            is_match = False
            if location_strategy is not None:
                is_match = location_strategy.matches_center(center_details)
            elif target_center:
                is_match = target_center.upper() in center_details.upper()
            else:
                is_match = True

            if is_match:
                print(f"[Slot Match] Locking center location: {center_details} ({capacity} seats)")
                slot.click()
                time.sleep(0.5)

                if "selected" in (slot.get_attribute("class") or "") or slot.locator(".selected-text").is_visible():
                    self.page.locator("#next_btn").click()
                    return True
        return False

    def start_slot_polling(self, target_center=None, target_district=None):
        self.log_message("Polling engine activated. Monitoring availability maps...")

        # Resolve target district, working site, and category dynamically from booking record if available
        record_district = None
        record_site = None
        record_category = None

        if self.booking_record:
            record_district = getattr(self.booking_record, 'district', None)
            record_site = getattr(self.booking_record, 'working_site', None)
            record_category = getattr(self.booking_record, 'category', None)

        chosen_district = (target_district or record_district or "Kicukiro").strip()
        chosen_site = target_center or record_site

        # Initialize OOP location strategy
        loc_strategy = get_location_strategy(district=chosen_district, working_site=chosen_site)
        target_display_name = loc_strategy.get_target_name()
        refresh_district = loc_strategy.get_refresh_district()

        # 1. Select category dynamically
        if record_category:
            self.log_message(f"Setting category selection to: {record_category}")
            category_control = "categoryFormControl"
            if not self.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                category_control = "licenseCategoryFormControl"
            self.select_category_dropdown(category_control, record_category)
        else:
            self.log_message("No target category specified. Skipping.", level="WARNING")

        # 2. Select district dynamically
        district_control = "locationFormControl"
        if not self.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
            district_control = "districtFormControl"

        self.log_message(f"Setting district selection (control: {district_control}) to '{chosen_district}' (Site target: '{target_display_name}')...")
        self.set_angular_dropdown(district_control, chosen_district)

        # 3. Get available time options
        time_options = self._get_time_options()
        if not time_options:
            self.log_message(f"No time options found in {chosen_district}. Aborting.", level="ERROR")
            return None

        time_index = 0
        consecutive_errors = 0
        cycle_count = 0

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
                        cycle_count += 1
                        if cycle_count >= 2:
                            self.log_message(f"Ntakode zibonetse muri {chosen_district}. Exiting polling gracefully.")
                            if self.booking_record:
                                record = self.booking_record
                                def _fail():
                                    from automation_app.models import ClientApplication
                                    app = ClientApplication.objects.get(id=record.id)
                                    app.status = 'FAILED'
                                    app.failure_reason = 'NTAKODE_ZIBONETSE'
                                    app.save(update_fields=["status", "failure_reason"])
                                run_in_db_thread(_fail)
                            return None
                            
                        # All times exhausted – toggle district to refresh with human-mimicking delay
                        self.log_message(f"All time slots exhausted (Cycle {cycle_count}/2). Toggling district to refresh ({chosen_district} <-> {refresh_district})...")
                        self.set_angular_dropdown(district_control, refresh_district)
                        time.sleep(random.uniform(1.2, 2.5))
                        self.set_angular_dropdown(district_control, chosen_district)
                        time.sleep(random.uniform(1.2, 2.5))
                        time_options = self._get_time_options()
                        if not time_options:
                            self.log_message(f"No time options after refreshing {chosen_district}. Waiting and retrying...", level="WARNING")
                            time.sleep(random.uniform(3.0, 5.0))
                            continue
                        time_index = 0
                    continue

                # Now check slots using OOP location strategy
                slot_secured = self.evaluate_and_select_slot(
                    target_center=chosen_site,
                    location_strategy=loc_strategy
                )

                if slot_secured:
                    self.log_message(f"Slot secured at {target_display_name}! Proceeding to finalization...")
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
                    cycle_count += 1
                    if cycle_count >= 2:
                        self.log_message(f"Ntakode zibonetse muri {chosen_district}. Exiting polling gracefully.")
                        if self.booking_record:
                            record = self.booking_record
                            def _fail():
                                from automation_app.models import ClientApplication
                                app = ClientApplication.objects.get(id=record.id)
                                app.status = 'FAILED'
                                app.failure_reason = 'NTAKODE_ZIBONETSE'
                                app.save(update_fields=["status", "failure_reason"])
                            run_in_db_thread(_fail)
                        return None
                        
                    # All times exhausted – toggle district to refresh with human-mimicking delay
                    self.log_message(f"All time slots exhausted (Cycle {cycle_count}/2). Toggling district to refresh ({chosen_district} <-> {refresh_district})...")
                    self.set_angular_dropdown(district_control, refresh_district)
                    time.sleep(random.uniform(1.2, 2.5))
                    self.set_angular_dropdown(district_control, chosen_district)
                    time.sleep(random.uniform(1.2, 2.5))
                    time_options = self._get_time_options()
                    if not time_options:
                        self.log_message(f"No time options after refreshing {chosen_district}. Waiting and retrying...", level="WARNING")
                        time.sleep(random.uniform(3.0, 5.0))
                        continue
                    time_index = 0

                # Small human-like delay between time attempts
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
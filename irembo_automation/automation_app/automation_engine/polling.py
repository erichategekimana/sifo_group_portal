# automation_app/automation_engine/polling.py
import random
import time
import re
from .utils import run_in_db_thread, is_exact_target_center

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

    def verify_before_next(self):
        """
        Double-check category and district dropdowns before clicking Next.
        """
        import re
        if not self.booking_record:
            return True
            
        target_cat = self.booking_record.category
        
        # 1. Get category control name
        category_control = "categoryFormControl"
        if not self.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
            category_control = "licenseCategoryFormControl"
            
        selected_cat = self._get_ng_select_selected_value(category_control)
        
        # 2. Get district control name
        district_control = "locationFormControl"
        if not self.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
            district_control = "districtFormControl"
            
        selected_dist = self._get_ng_select_selected_value(district_control)
        
        self.log_message(f"[Slot Selection Verification] Category: '{selected_cat}' (Expected: '{target_cat}'), District: '{selected_dist}' (Expected: 'Kicukiro')")
        
        # Validate Category
        if selected_cat and target_cat:
            target_cat_upper = target_cat.strip().upper()
            target_is_at = "AT" in target_cat_upper or "AUTOMATIQUE" in target_cat_upper
            clean_target = re.sub(r'^(URWEGO|CATEGORY|CAT|URUHUSHYA RWA|ICYICIRO CYA)\s*', '', target_cat_upper, flags=re.IGNORECASE).strip()
            clean_target_code = re.sub(r'\(AT\)|\bAT\b|\bAUTOMATIQUE\b|-.*$|:.*$', '', clean_target, flags=re.IGNORECASE).strip()
            
            selected_cat_upper = selected_cat.upper()
            sel_is_at = "AT" in selected_cat_upper or "AUTOMATIQUE" in selected_cat_upper
            
            if clean_target_code not in selected_cat_upper or sel_is_at != target_is_at:
                return False
                
        # Validate District
        if not selected_dist or "KICUKIRO" not in selected_dist.upper():
            return False
                
        return True

    def evaluate_and_select_slot(self, target_center="BUSANZA AUTOMATED CENTER"):
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

            center_details = slot.locator(".center").inner_text().strip()
            capacity_text = slot.locator(".capacity-circle").inner_text().strip()

            try:
                capacity = int(capacity_text)
            except ValueError:
                capacity = 0

            # Strict center matching to eliminate false positives like 'KICUKIRO - BUSANZA SITE (KIC)'
            if is_exact_target_center(center_details, target_center) and capacity > 0:
                print(f"[Slot Match] Locking center location: {center_details} ({capacity} seats)")
                slot.click()
                time.sleep(0.5)

                if "selected" in (slot.get_attribute("class") or "") or slot.locator(".selected-text").is_visible():
                    # Double check category/district selection before proceeding
                    verified = False
                    for attempt in range(1, 4):
                        if self.verify_before_next():
                            verified = True
                            break
                        
                        self.log_message(f"[Slot Selection] Verification attempt {attempt}/3 failed. Re-selecting category and district...", level="WARNING")
                        
                        # Re-select category
                        if self.booking_record and self.booking_record.category:
                            category_control = "categoryFormControl"
                            if not self.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                                category_control = "licenseCategoryFormControl"
                            try:
                                self.select_category_dropdown(category_control, self.booking_record.category)
                            except Exception as ce:
                                self.log_message(f"[Slot Selection Retry] Failed to set category: {ce}", level="WARNING")
                                
                        # Re-select district
                        district_control = "locationFormControl"
                        if not self.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
                            district_control = "districtFormControl"
                        try:
                            self.set_angular_dropdown(district_control, "Kicukiro")
                        except Exception as de:
                            self.log_message(f"[Slot Selection Retry] Failed to set district: {de}", level="WARNING")
                            
                        # Wait a bit after re-selecting
                        time.sleep(1.0)
                        
                    if verified:
                        self.page.locator("#next_btn").click()
                        return True
                    else:
                        self.log_message("[Slot Selection Match] Category/District selection verification failed after 3 attempts. Skipping slot.", level="ERROR")
        return False

    def start_slot_polling(self, target_center="BUSANZA AUTOMATED CENTER"):
        self.log_message("Polling engine activated. Monitoring availability maps...")

        # 1. Select category
        if self.booking_record and self.booking_record.category:
            self.log_message(f"Setting category selection to: {self.booking_record.category}")
            category_control = "categoryFormControl"
            if not self.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                category_control = "licenseCategoryFormControl"
            self.select_category_dropdown(category_control, self.booking_record.category)
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
        cycle_count = 0
        target_district = "Kicukiro"

        while True:
            try:
                # Check page closure before starting the iteration
                if self.page is None or self.page.is_closed():
                    raise Exception("Browser page is closed.")

                # Select the current time
                self.log_message(f"Selecting time slot: {time_options[time_index]} (index {time_index})")
                if not self._select_time_slot_by_index(time_index):
                    # If selection fails, increment and try next
                    time_index += 1
                    if time_index >= len(time_options):
                        cycle_count += 1
                        if cycle_count >= 2:
                            self.log_message(f"Ntakode zibonetse muri {target_district}. Exiting polling gracefully.")
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
                            
                        # All times exhausted – toggle district
                        self.log_message(f"All time slots exhausted (Cycle {cycle_count}/2). Toggling district to refresh...")
                        self.set_angular_dropdown(district_control, "Gasabo")
                        time.sleep(random.uniform(1.2, 2.5))
                        self.set_angular_dropdown(district_control, target_district)
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
                    cycle_count += 1
                    if cycle_count >= 2:
                        self.log_message(f"Ntakode zibonetse muri {target_district}. Exiting polling gracefully.")
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
                        
                    # All times exhausted – toggle district to refresh
                    self.log_message(f"All time slots exhausted (Cycle {cycle_count}/2). Toggling district to refresh...")
                    self.set_angular_dropdown(district_control, "Gasabo")
                    time.sleep(random.uniform(1.2, 2.5))
                    self.set_angular_dropdown(district_control, target_district)
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
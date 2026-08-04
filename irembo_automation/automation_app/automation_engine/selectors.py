# automation_app/automation_engine/selectors.py
import random
import re
import time

class SelectorsMixin:
    def _type_into_field(self, locator, text):
        locator.click()
        # Safely clear the input
        locator.fill("")
        time.sleep(0.2)
        # Type like a human
        locator.press_sequentially(text, delay=random.randint(40, 90))
        # Dispatch events to ensure Angular picks up the change
        locator.evaluate("el => el.dispatchEvent(new Event('input', { bubbles: true }))")
        locator.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
        locator.evaluate("el => el.dispatchEvent(new Event('blur', { bubbles: true }))")

    def check_for_errors(self):
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
                        if not error_text or error_text == "*":
                            continue
                        print(f"[Engine Error Detected] {error_text}")
                        raise ValueError(f"Irembo Portal Error: {error_text}")
            except ValueError:
                raise
            except Exception:
                pass

    def set_angular_dropdown(self, control_name, option_text):
        # Find the dropdown by formcontrolname, with fallbacks
        dropdown = self.page.locator(f'ng-select[formcontrolname="{control_name}"]')
        if not dropdown.is_visible():
            dropdown = self.page.locator(f'ng-select[formcontrolname*="{control_name}" i]').first

        if not dropdown.is_visible():
            dropdown = self.page.locator(f'ng-select:has-text("{control_name}")').first

        if not dropdown.is_visible():
            dropdown = self.page.locator('ng-select').first

        print(f"[Dropdown] Clicking dropdown matching {control_name} to select option: {option_text}")
        
        # Robust click loop for the dropdown to ensure panel opens
        panel_opened = False
        for attempt in range(3):
            try:
                dropdown.click(force=True, timeout=5000)
                self.page.wait_for_selector(".ng-dropdown-panel", state="visible", timeout=5000)
                panel_opened = True
                break
            except Exception as e:
                print(f"[Dropdown] Attempt {attempt+1} failed to open panel for {control_name}. Retrying...")
                time.sleep(1.5)
                
        if not panel_opened:
            raise ValueError(f"Failed to open dropdown panel for '{control_name}' after 3 attempts.")

        # Now get all options – but wait for the first one to be visible (fixes strict mode)
        options = self.page.locator('.ng-dropdown-panel .ng-option')
        options.first.wait_for(state="visible", timeout=3000)

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

        # Tier 3: Suffix match (case-insensitive) – e.g., "B" from "B(AT)"
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                if text.endswith(option_text.lower()):
                    opt.click()
                    matched = True
                    break

        # Tier 4: Word boundary match (case-insensitive) – e.g., "B" inside "B(AT)"
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

        # Final fallback: click the first option if nothing matched
        if not matched and count > 0:
            options.first.click()

        time.sleep(1)

    def select_category_dropdown(self, control_name, target_category):
        target_upper = target_category.strip().upper()
        target_is_at = "AT" in target_upper or "AUTOMATIQUE" in target_upper

        # Clean target code (e.g. if target is "Urwego D" or "D(AT)", extract "D")
        clean_target = re.sub(r'^(URWEGO|CATEGORY|CAT|URUHUSHYA RWA|ICYICIRO CYA)\s*', '', target_upper, flags=re.IGNORECASE).strip()
        clean_target_code = re.sub(r'\(AT\)|\bAT\b|\bAUTOMATIQUE\b|-.*$|:.*$', '', clean_target, flags=re.IGNORECASE).strip()
        if not clean_target_code:
            clean_target_code = target_upper

        print(f"[Category Selection] Attempting to select exact category: '{target_category}' (clean code: '{clean_target_code}', is_AT: {target_is_at}) using control '{control_name}'")

        all_option_texts = []

        # Outer fallback loop: try up to 4 times to open dropdown and find the exact category
        for attempt in range(1, 5):
            # Locate dropdown
            dropdown = self.page.locator(f'ng-select[formcontrolname="{control_name}"]')
            if not dropdown.is_visible():
                dropdown = self.page.locator(f'ng-select[formcontrolname*="{control_name}" i]').first
            if not dropdown.is_visible():
                dropdown = self.page.locator(f'ng-select:has-text("{control_name}")').first
            if not dropdown.is_visible():
                dropdown = self.page.locator('ng-select').first

            if not dropdown.is_visible():
                print(f"[Category Selection] Dropdown control '{control_name}' not visible on attempt {attempt}.")
                time.sleep(1.5)
                continue

            # Ensure dropdown panel is open
            panel_opened = False
            for click_attempt in range(3):
                try:
                    dropdown.click(force=True, timeout=5000)
                    self.page.wait_for_selector(".ng-dropdown-panel", state="visible", timeout=4000)
                    panel_opened = True
                    break
                except Exception as e:
                    print(f"[Category Selection] Click attempt {click_attempt+1} failed to open panel. Retrying...")
                    time.sleep(1.0)
            
            if not panel_opened:
                print(f"[Category Selection] Could not open dropdown panel on attempt {attempt}.")
                time.sleep(1.5)
                continue

            # Give Angular a moment to render options inside .ng-dropdown-panel
            time.sleep(0.5)
            options = self.page.locator('.ng-dropdown-panel .ng-option')
            try:
                options.first.wait_for(state="visible", timeout=3000)
            except Exception:
                print(f"[Category Selection] Options did not become visible on attempt {attempt}.")
                time.sleep(1.0)
                continue

            count = options.count()
            current_texts = []
            matched_option = None

            # Tier 1: Exact string match (after filtering AT mutual exclusion)
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip()
                current_texts.append(text)
                if text not in all_option_texts:
                    all_option_texts.append(text)
                
                text_upper = text.upper()
                opt_is_at = "AT" in text_upper or "AUTOMATIQUE" in text_upper

                # Rule 1: Mutual exclusion between AT and Manual
                if target_is_at and not opt_is_at:
                    continue
                if not target_is_at and opt_is_at:
                    continue

                if text_upper == target_upper:
                    matched_option = opt
                    break

            # Tier 2: Normalized exact code match (e.g. "Urwego D" == "D" or "D - Imodoka" == "D")
            if matched_option is None:
                for i in range(count):
                    opt = options.nth(i)
                    text_upper = opt.inner_text().strip().upper()
                    opt_is_at = "AT" in text_upper or "AUTOMATIQUE" in text_upper

                    if target_is_at and not opt_is_at:
                        continue
                    if not target_is_at and opt_is_at:
                        continue

                    clean_opt = re.sub(r'^(URWEGO|CATEGORY|CAT|URUHUSHYA RWA|ICYICIRO CYA)\s*', '', text_upper, flags=re.IGNORECASE).strip()
                    clean_opt_code = re.sub(r'\(AT\)|\bAT\b|\bAUTOMATIQUE\b|-.*$|:.*$', '', clean_opt, flags=re.IGNORECASE).strip()
                    
                    if clean_opt_code == clean_target_code and clean_opt_code != "":
                        matched_option = opt
                        break

            # Tier 3: Word boundary / token match (e.g., searching for word \bD\b inside option text after AT filtering)
            if matched_option is None:
                for i in range(count):
                    opt = options.nth(i)
                    text_upper = opt.inner_text().strip().upper()
                    opt_is_at = "AT" in text_upper or "AUTOMATIQUE" in text_upper

                    if target_is_at and not opt_is_at:
                        continue
                    if not target_is_at and opt_is_at:
                        continue

                    # Regex word boundary match for the category code (e.g., \bD\b in "Imodoka (D)" or "Urwego D")
                    pattern = r'\b' + re.escape(clean_target_code) + r'\b'
                    if re.search(pattern, text_upper):
                        matched_option = opt
                        break

            # Tier 4: Substring fallback (ONLY after strict AT filtering and when clean_target_code is at least 1 char)
            if matched_option is None and len(clean_target_code) >= 1:
                for i in range(count):
                    opt = options.nth(i)
                    text_upper = opt.inner_text().strip().upper()
                    opt_is_at = "AT" in text_upper or "AUTOMATIQUE" in text_upper

                    if target_is_at and not opt_is_at:
                        continue
                    if not target_is_at and opt_is_at:
                        continue

                    if clean_target_code in text_upper:
                        matched_option = opt
                        break

            if matched_option is not None:
                matched_text = matched_option.inner_text().strip()
                print(f"[Category Selection] Matched option '{matched_text}' on attempt {attempt}. Clicking...")
                matched_option.click()
                time.sleep(1)
                return True

            print(f"[Category Selection] Attempt {attempt}: Category '{target_category}' not found in current options: {current_texts}. Retrying as fallback...")
            # Close dropdown panel by pressing Escape or clicking body to reset before next attempt
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            time.sleep(random.uniform(1.2, 2.0))

        # If all attempts failed, record Kinyarwanda error without choosing different category
        error_msg = f"Icyiciro cya perimi mwasabye ({target_category}) ntikibonetse mu byiciro bihari ({', '.join(all_option_texts)})"
        print(f"[Category Selection Error] {error_msg}")
        
        if getattr(self, 'booking_record', None):
            from .utils import run_in_db_thread
            record = self.booking_record
            def _record_error():
                record.failure_reason = 'ICYICIRO_NTIKIBONETSE'
                record.last_error = error_msg
                banner = f"\n=== [IKOSA RYABONETSE / ERROR DETECTED] ===\nReason Code: ICYICIRO_NTIKIBONETSE\nMessage: {error_msg}\n============================================\n"
                record.log_output = (record.log_output or "") + banner
                record.status = 'FAILED'
                record.save(update_fields=["failure_reason", "last_error", "log_output", "status"])
            run_in_db_thread(_record_error)

        raise ValueError(f"Irembo Error: ICYICIRO_NTIKIBONETSE - {error_msg}")
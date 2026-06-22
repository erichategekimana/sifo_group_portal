# automation_app/automation_engine/selectors.py
import random
import re
import time

class SelectorsMixin:
    def _type_into_field(self, locator, text):
        locator.click()
        locator.evaluate("el => { el.value = ''; el.dispatchEvent(new Event('input', { bubbles: true })); }")
        for char in text:
            locator.type(char, delay=random.randint(40, 90))
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
        dropdown.click(timeout=3000, force=True)
            
        # Wait for the dropdown panel to appear
        self.page.wait_for_selector(".ng-dropdown-panel", state="attached", timeout=5000)

        # Now get all options
        options = self.page.locator('.ng-dropdown-panel .ng-option')
        options.first.wait_for(state="attached", timeout=3000)

        matched = False
        count = options.count()

        def _robust_click(opt):
            opt.click(timeout=2000, force=True)

        # Tier 1: Exact match (case-sensitive)
        for i in range(count):
            opt = options.nth(i)
            text = opt.inner_text().strip()
            if text == option_text:
                _robust_click(opt)
                matched = True
                break

        # Tier 2: Exact match (case-insensitive)
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip()
                if text.lower() == option_text.lower():
                    _robust_click(opt)
                    matched = True
                    break

        # Tier 3: Suffix match (case-insensitive)
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                if text.endswith(option_text.lower()):
                    _robust_click(opt)
                    matched = True
                    break

        # Tier 4: Word boundary match (case-insensitive)
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                pattern = r'\b' + re.escape(option_text.lower()) + r'\b'
                if re.search(pattern, text):
                    _robust_click(opt)
                    matched = True
                    break

        # Tier 5: Substring match (case-insensitive fallback)
        if not matched:
            for i in range(count):
                opt = options.nth(i)
                text = opt.inner_text().strip().lower()
                if option_text.lower() in text:
                    _robust_click(opt)
                    matched = True
                    break

        # Final fallback: click the first option if nothing matched
        if not matched and count > 0:
            _robust_click(options.first)

        time.sleep(1)
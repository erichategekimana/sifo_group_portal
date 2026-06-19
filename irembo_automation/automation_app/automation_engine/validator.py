# automation_app/automation_engine/validator.py
import time

class ValidatorMixin:
    def validate_agent_session(self, page):
        """
        Check if the current session is a logged-in agent with active 'Uhagarariye' role.
        Returns True if agent mode is active, False otherwise.
        Logs warnings but does not raise exceptions.
        """
        print("[Validator] Running session validation...")
        try:
            # 1. Handle multiple account choice screen if present
            # Look for common account cards or list items to choose an account
            account_selectors = [
                'a:has-text("Uhagarariye")',
                'button:has-text("Uhagarariye")',
                'a:has-text("Agent")',
                'button:has-text("Agent")',
                '.account-item',
                '.profile-selection',
                '.user-card'
            ]
            for selector in account_selectors:
                try:
                    elements = page.locator(selector).all()
                    for el in elements:
                        if el.is_visible():
                            print(f"[Validator] Account selection detected via {selector}. Clicking to choose account...")
                            el.click()
                            time.sleep(2)
                            page.wait_for_load_state("networkidle")
                            break
                except Exception:
                    pass

            # Look for sign-out link to confirm login.
            sign_out = page.locator('a.dropdown-item:has-text("Sohoka ku rubuga")')
            if not sign_out.is_visible():
                print("[Validator] WARNING: Not logged in or session expired. Please refresh session using record_session.py.")
                return False

            # 2. Check and handle role selection (UMUTURAGE vs UHAGARARIYE)
            # In the HTML, there is <label class="label-role">UMUTURAGE</label>.
            role_label = page.locator('.label-role')
            if role_label.is_visible():
                role_text = role_label.inner_text().strip().upper()
                if role_text == "UHAGARARIYE":
                    print("[Validator] Agent mode is active (Uhagarariye).")
                    return True
                else:
                    print(f"[Validator] Current role is {role_text}. Trying to switch to Agent (Uhagarariye)...")
                    try:
                        # Click the profile/role dropdown to open it
                        dropdown_toggle = page.locator('.dropdown-toggle, .user-info, .profile-info, .label-role').first
                        dropdown_toggle.click()
                        time.sleep(1)
                        
                        # Look for 'Uhagarariye' or switcher links in dropdown
                        role_option = page.locator('a.dropdown-item, button.dropdown-item, .dropdown-menu a, .dropdown-menu button').locator('text="Uhagarariye", text="Guhindura imikorere", text="Guhindura imirimo"').first
                        if role_option.is_visible():
                            role_option.click()
                            time.sleep(2)
                            page.wait_for_load_state("networkidle")
                            
                            # Verify switch success
                            new_role_text = role_label.inner_text().strip().upper()
                            if new_role_text == "UHAGARARIYE":
                                print("[Validator] Successfully switched to Agent mode (Uhagarariye).")
                                return True
                            else:
                                print(f"[Validator] Failed to switch; role is still {new_role_text}.")
                        else:
                            print("[Validator] Agent role switch option not visible in dropdown.")
                    except Exception as switch_err:
                        print(f"[Validator] Role switch attempt failed: {switch_err}")
                    return False
            else:
                # If label not found, fallback: check for presence of 'Uhagarariye' in the page/dropdown
                print("[Validator] Could not determine role; assuming not agent.")
                return False

        except Exception as e:
            print(f"[Validator] Validation failed with error: {e}")
            return False
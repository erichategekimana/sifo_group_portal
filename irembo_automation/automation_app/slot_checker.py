import threading
import time
import random
import re
from django.utils import timezone
from playwright.sync_api import sync_playwright
from .automation_engine.utils import run_in_db_thread

try:
    import winsound
    HAVE_WINSOUND = True
except ImportError:
    HAVE_WINSOUND = False

# Global state for Category A slot checker
slot_checker_state = {
    "is_running": False,
    "status": "Stopped",
    "last_check": None,
    "slots_found": False,
    "found_details": "",
    "check_count": 0,
    "current_app_name": None,
    "current_app_id": None,
}

_checker_thread = None
_checker_lock = threading.Lock()

def start_slot_checker():
    global _checker_thread
    with _checker_lock:
        if slot_checker_state["is_running"]:
            return False, "Slot checker is already running."
        
        slot_checker_state["is_running"] = True
        slot_checker_state["status"] = "Starting Category A slot checker..."
        slot_checker_state["slots_found"] = False
        slot_checker_state["found_details"] = ""
        
        _checker_thread = threading.Thread(target=_slot_checker_loop, daemon=True, name="CatASlotChecker")
        _checker_thread.start()
        return True, "Slot checker started successfully."

def stop_slot_checker():
    with _checker_lock:
        if not slot_checker_state["is_running"]:
            return False, "Slot checker is not running."
        
        slot_checker_state["is_running"] = False
        slot_checker_state["status"] = "Stopped by user."
        slot_checker_state["current_app_name"] = None
        slot_checker_state["current_app_id"] = None
        return True, "Slot checker stopped successfully."

def get_slot_checker_status():
    with _checker_lock:
        return dict(slot_checker_state)

def acknowledge_slot_alert():
    with _checker_lock:
        slot_checker_state["slots_found"] = False
        slot_checker_state["found_details"] = ""
        if slot_checker_state["is_running"]:
            slot_checker_state["status"] = "Alert acknowledged. Resuming slot checks soon..."
        return True, "Alert acknowledged."

def _check_slots_on_page(engine):
    """
    Checks the current page in the Irembo booking step to see if any valid slots are available.
    Returns (bool, str): (True if slots found, details string).
    """
    badge_element = engine.page.locator('.appointments-header h2.title span.badge')
    if badge_element.is_visible():
        try:
            count = int(badge_element.inner_text().strip())
            if count > 0:
                slots = engine.page.locator(".appointments-list .appointment-slot").all()
                for slot in slots:
                    if "dimmed" not in (slot.get_attribute("class") or ""):
                        center_text = slot.locator(".center").inner_text().strip()
                        cap_text = slot.locator(".capacity-circle").inner_text().strip()
                        try:
                            cap = int(cap_text)
                            if cap > 0:
                                return True, f"{center_text} ({cap} seats)"
                        except ValueError:
                            pass
                return True, f"Available slots badge showing {count} seat(s)"
        except ValueError:
            pass
    return False, ""

def _slot_checker_loop():
    from .models import ClientApplication
    from .automation_engine import IremboAutomationEngine

    print("[Cat A Slot Checker] Background monitoring loop started.")
    
    while slot_checker_state["is_running"]:
        # If slots are already found and alarm is ringing, pause checking until user acknowledges
        if slot_checker_state["slots_found"]:
            slot_checker_state["status"] = "🚨 SLOTS FOUND! Alarm ringing... Waiting for user acknowledgment."
            if HAVE_WINSOUND:
                try:
                    winsound.Beep(900, 400)
                except Exception:
                    pass
            time.sleep(2)
            continue

        # Step 1: Query DB for valid Category A applications with provisional numbers
        def _fetch_candidates():
            return list(ClientApplication.objects.filter(
                category__iexact='A',
                provisional_number__isnull=False
            ).exclude(provisional_number='').exclude(status__in=['SUCCESS', 'FINALIZING', 'CANCELED']))

        candidates = run_in_db_thread(_fetch_candidates)

        if not candidates:
            slot_checker_state["status"] = "Waiting: No Category A applications with provisional numbers found in DB."
            slot_checker_state["current_app_name"] = None
            slot_checker_state["current_app_id"] = None
            
            # Sleep 60 seconds before checking DB again
            for _ in range(30):
                if not slot_checker_state["is_running"]:
                    break
                time.sleep(2)
            continue

        # Step 2: Pick one candidate randomly
        app = random.choice(candidates)
        slot_checker_state["current_app_name"] = f"{app.first_name} {app.last_name}"
        slot_checker_state["current_app_id"] = app.id
        slot_checker_state["status"] = f"Checking slots using {app.first_name} {app.last_name} ({app.national_id})..."
        print(f"[Cat A Slot Checker] Selected candidate: {app.national_id} ({app.first_name} {app.last_name})")

        found_any_slots = False
        found_details_str = ""

        try:
            with sync_playwright() as p:
                engine = IremboAutomationEngine(booking_record=app)
                # HEADLESS = TRUE for 100% invisible background running
                engine.initialize_stealth_browser(p, headless=True)
                
                print(f"[Cat A Slot Checker] Navigating to booking form for {app.national_id}...")
                engine.navigate_to_booking_form(
                    national_id=app.national_id,
                    verification_data=app.first_name
                )
                
                # Verify we reached the form without portal errors
                if engine.page is None or engine.page.is_closed():
                    raise Exception("Browser page closed unexpectedly during navigation.")
                
                # Select Category A
                category_control = "categoryFormControl"
                if not engine.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                    category_control = "serviceFormControl"
                
                slot_checker_state["status"] = f"Selecting Category A for {app.first_name}..."
                engine.select_category_dropdown(category_control, "A")
                
                # Select District Kicukiro
                district_control = "locationFormControl"
                if not engine.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
                    district_control = "districtFormControl"
                
                slot_checker_state["status"] = f"Selecting district Kicukiro..."
                engine.set_angular_dropdown(district_control, "Kicukiro")
                time.sleep(2)

                # Check time options and slots (Loop through time schedules exactly ONCE, not twice)
                time_options = engine._get_time_options()
                if not time_options:
                    # Check current page just in case
                    found, details = _check_slots_on_page(engine)
                    if found:
                        found_any_slots = True
                        found_details_str = details
                else:
                    print(f"[Cat A Slot Checker] Found {len(time_options)} time schedule(s). Looping through schedules once...")
                    for idx in range(len(time_options)):
                        if not slot_checker_state["is_running"]:
                            break
                        time_label = time_options[idx] if idx < len(time_options) else f"Index {idx}"
                        slot_checker_state["status"] = f"Checking schedule {idx+1}/{len(time_options)} ({time_label})..."
                        print(f"[Cat A Slot Checker] Selecting schedule {idx+1}/{len(time_options)}: {time_label}")
                        
                        engine._select_time_slot_by_index(idx)
                        # Wait 2 seconds for Angular to fetch and render center availability for this time schedule
                        time.sleep(2)
                        
                        found, details = _check_slots_on_page(engine)
                        if found:
                            found_any_slots = True
                            found_details_str = details
                            break

                # Update check count & timestamp
                slot_checker_state["check_count"] += 1
                slot_checker_state["last_check"] = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

                if found_any_slots:
                    print(f"[Cat A Slot Checker] 🚨 SLOTS FOUND! Details: {found_details_str}")
                    slot_checker_state["slots_found"] = True
                    slot_checker_state["found_details"] = f"Category A slots available: {found_details_str}! (Detected via {app.first_name} {app.last_name})"
                    slot_checker_state["status"] = "🚨 SLOTS DETECTED! Sounding alarm..."
                    
                    if HAVE_WINSOUND:
                        for _ in range(5):
                            try:
                                winsound.Beep(1000, 500)
                                time.sleep(0.1)
                            except Exception:
                                break
                else:
                    print("[Cat A Slot Checker] No slots found on this attempt.")

        except Exception as e:
            err_msg = str(e)
            print(f"[Cat A Slot Checker Warning] Attempt with applicant {app.national_id} failed: {err_msg}")
            slot_checker_state["status"] = f"Portal issue with {app.first_name}: {err_msg[:40]}... Retrying with another applicant."
            # Wait 15s before retrying with another applicant
            for _ in range(15):
                if not slot_checker_state["is_running"]:
                    break
                time.sleep(1)
            continue

        # If no slots found and still running, sleep for random interval (1 to 3 minutes -> 60 to 180s)
        if not found_any_slots and slot_checker_state["is_running"]:
            sleep_duration = random.randint(60, 180)
            print(f"[Cat A Slot Checker] Sleeping for {sleep_duration} seconds ({sleep_duration//60}m {sleep_duration%60}s)...")
            
            for elapsed in range(sleep_duration):
                if not slot_checker_state["is_running"]:
                    break
                remaining = sleep_duration - elapsed
                slot_checker_state["status"] = f"No slots found. Next check in {remaining//60}m {remaining%60}s..."
                time.sleep(1)

    print("[Cat A Slot Checker] Background monitoring loop stopped cleanly.")
    slot_checker_state["status"] = "Stopped by user."

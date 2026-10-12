import threading
import time
import random
import re
from django.utils import timezone
from playwright.sync_api import sync_playwright
from .automation_engine.utils import run_in_db_thread
from .automation_engine.locations import get_location_strategy

try:
    import winsound
    HAVE_WINSOUND = True
except ImportError:
    HAVE_WINSOUND = False

# Supported site targets definition
TARGET_CONFIGS = {
    "automated": {
        "id": "automated",
        "name": "Busanza Automated Center",
        "site_value": "BUSANZA AUTOMATED CENTER",
        "is_manual": False,
    },
    "manual": {
        "id": "manual",
        "name": "Busanza Site (Manual)",
        "site_value": "KICUKIRO - BUSANZA SITE (KIC)",
        "is_manual": True,
    }
}

# Registry lock protecting active checkers and alert state
_registry_lock = threading.Lock()

# Dynamic multi-checker session registry: key is f"{category}_{site_id}" e.g. "A_automated", "B_automated", "B_manual"
ACTIVE_CHECKERS = {}

# Global alert state when open slots are found by any active worker
_alert_state = {
    "slots_found": False,
    "slots_found_time": None,
    "found_details": "",
    "found_checker_id": None,
    "found_category": None,
    "found_site_name": None
}

# Global candidate lease tracker to prevent concurrent workers from using the same applicant ID
_leased_candidate_ids = set()
_candidate_lease_lock = threading.Lock()


def lease_candidate(category="A", exclude_ids=None):
    """
    Leases an eligible candidate for a slot checker worker based on requested category.
    Ensures that no two concurrent workers share the same candidate.
    """
    from .models import ClientApplication

    if exclude_ids is None:
        exclude_ids = set()

    cat_str = (category or "A").strip()

    with _candidate_lease_lock:
        def _fetch_candidates():
            return list(ClientApplication.objects.filter(
                category__iexact=cat_str,
                is_archived=False
            ).exclude(
                status__in=['SUCCESS', 'FINALIZING', 'CANCELED', 'PROCESSING']
            ).exclude(
                national_id__isnull=True
            ).exclude(
                national_id=''
            ).order_by('id')[:30])

        candidates = run_in_db_thread(_fetch_candidates)
        if not candidates:
            return None

        # Filter out currently leased IDs and recent portal error IDs
        available = [c for c in candidates if c.id not in _leased_candidate_ids and c.id not in exclude_ids]

        if not available:
            # If all non-leased candidates are excluded due to temporary errors, try unleased ones anyway
            available = [c for c in candidates if c.id not in _leased_candidate_ids]

        if not available:
            return None

        chosen = available[0]
        _leased_candidate_ids.add(chosen.id)
        return chosen


def release_candidate(app_id):
    """
    Releases a previously leased candidate so other workers or future runs can use them.
    """
    if app_id is None:
        return
    with _candidate_lease_lock:
        _leased_candidate_ids.discard(app_id)


def start_slot_checker(category="A", batch_size=10, use_priority=True, sort_by="created_at", targets=None):
    """
    Starts concurrent slot checker workers for the given category and target sites.
    Existing running workers for other categories remain running without interruption.
    """
    from .models import ClientApplication

    category = (category or "A").strip().upper()

    # Defensive validation of batch_size
    try:
        batch_size = int(batch_size)
        if batch_size < 1:
            batch_size = 1
        elif batch_size > 50:
            batch_size = 50
    except (ValueError, TypeError):
        batch_size = 10

    # Validate sort_by
    valid_sorts = ["created_at", "-created_at", "teacher", "status", "first_name"]
    if sort_by not in valid_sorts:
        sort_by = "created_at"

    # Validate selected targets (must have at least one)
    if not targets or not isinstance(targets, list):
        targets = ["automated"]
    valid_targets = [t for t in targets if t in TARGET_CONFIGS]
    if not valid_targets:
        valid_targets = ["automated"]

    # Verify that at least one candidate exists for this category
    def _check_candidates_exist():
        return ClientApplication.objects.filter(
            category__iexact=category,
            is_archived=False
        ).exclude(status__in=['SUCCESS', 'FINALIZING', 'CANCELED']).exists()

    has_candidates = run_in_db_thread(_check_candidates_exist)
    if not has_candidates:
        return False, f"Cannot start checker for Category {category}: No pending Category {category} applications found in database."

    started_targets = []
    with _registry_lock:
        for index, target_id in enumerate(valid_targets):
            checker_key = f"{category}_{target_id}"

            # If already actively running, skip re-creating
            if checker_key in ACTIVE_CHECKERS:
                existing = ACTIVE_CHECKERS[checker_key]
                if not existing["stop_event"].is_set() and existing.get("is_active", True):
                    continue

            stop_event = threading.Event()
            cfg = TARGET_CONFIGS[target_id]

            ACTIVE_CHECKERS[checker_key] = {
                "id": checker_key,
                "category": category,
                "site_id": target_id,
                "site_name": cfg["name"],
                "is_manual": cfg["is_manual"],
                "is_active": True,
                "status": "Starting...",
                "check_count": 0,
                "last_check": None,
                "current_candidate": None,
                "batch_size": batch_size,
                "use_priority": bool(use_priority),
                "sort_by": sort_by,
                "stop_event": stop_event,
                "created_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            worker_thread = threading.Thread(
                target=_worker_loop,
                args=(checker_key, category, target_id, stop_event, batch_size, bool(use_priority), sort_by, index * 2.5),
                daemon=True,
                name=f"SlotWorker_{checker_key}"
            )
            ACTIVE_CHECKERS[checker_key]["thread"] = worker_thread
            worker_thread.start()
            started_targets.append(cfg["name"])

    if not started_targets:
        return False, f"Checker for Category {category} is already running on the selected site(s)."

    return True, f"Started checker for Category {category} on {len(started_targets)} site(s) ({', '.join(started_targets)})."


def stop_slot_checker(checker_id=None, category=None):
    """
    Stops slot checker workers cleanly.
    - If checker_id is specified: stops that specific worker.
    - If category is specified: stops all workers for that category.
    - If neither is specified: stops ALL active workers across all categories.
    """
    with _registry_lock:
        if checker_id:
            if checker_id in ACTIVE_CHECKERS:
                cinfo = ACTIVE_CHECKERS[checker_id]
                cinfo["stop_event"].set()
                cinfo["is_active"] = False
                cinfo["status"] = "Stopped"
                cinfo["current_candidate"] = None
                return True, f"Stopped worker {cinfo['category']} - {cinfo['site_name']}."
            return False, f"Worker {checker_id} not found."

        if category:
            cat_upper = category.strip().upper()
            stopped_count = 0
            for cid, cinfo in list(ACTIVE_CHECKERS.items()):
                if cinfo.get("category") == cat_upper and cinfo.get("is_active", True):
                    cinfo["stop_event"].set()
                    cinfo["is_active"] = False
                    cinfo["status"] = "Stopped"
                    cinfo["current_candidate"] = None
                    stopped_count += 1
            if stopped_count > 0:
                return True, f"Stopped {stopped_count} worker(s) for Category {cat_upper}."
            return False, f"No active workers found for Category {cat_upper}."

        # Stop all workers
        stopped_count = 0
        for cid, cinfo in list(ACTIVE_CHECKERS.items()):
            if cinfo.get("is_active", True) or not cinfo["stop_event"].is_set():
                cinfo["stop_event"].set()
                cinfo["is_active"] = False
                cinfo["status"] = "Stopped"
                cinfo["current_candidate"] = None
                stopped_count += 1

        with _candidate_lease_lock:
            _leased_candidate_ids.clear()

        _alert_state["slots_found"] = False
        _alert_state["slots_found_time"] = None
        _alert_state["found_details"] = ""

        return True, f"Stopped all {stopped_count} slot checker workers."


def get_slot_checker_status():
    """
    Returns the aggregated telemetry and status of all active slot checker workers.
    """
    with _registry_lock:
        active_workers = []
        latest_last_check = None
        total_checks = 0

        for cid, cinfo in list(ACTIVE_CHECKERS.items()):
            total_checks += cinfo.get("check_count", 0)
            chk_time = cinfo.get("last_check")
            if chk_time and (latest_last_check is None or chk_time > latest_last_check):
                latest_last_check = chk_time

            if cinfo.get("is_active", False) and not cinfo["stop_event"].is_set():
                active_workers.append({
                    "id": cinfo["id"],
                    "category": cinfo["category"],
                    "site_id": cinfo["site_id"],
                    "site_name": cinfo["site_name"],
                    "is_manual": cinfo["is_manual"],
                    "status": cinfo["status"],
                    "check_count": cinfo["check_count"],
                    "last_check": cinfo["last_check"],
                    "current_candidate": cinfo["current_candidate"],
                    "batch_size": cinfo.get("batch_size", 10),
                    "created_at": cinfo.get("created_at")
                })

        is_running = len(active_workers) > 0
        if is_running:
            status_desc = f"Running ({len(active_workers)} active worker{'s' if len(active_workers) > 1 else ''})"
        else:
            status_desc = "Stopped / Idle"

        return {
            "is_running": is_running,
            "active_count": len(active_workers),
            "status": status_desc,
            "check_count": total_checks,
            "last_check": latest_last_check,
            "slots_found": _alert_state["slots_found"],
            "slots_found_time": _alert_state["slots_found_time"],
            "found_details": _alert_state["found_details"],
            "found_checker_id": _alert_state["found_checker_id"],
            "found_category": _alert_state["found_category"],
            "found_site_name": _alert_state["found_site_name"],
            "workers": active_workers
        }


def acknowledge_slot_alert(trigger_launch=True):
    """
    Acknowledges the current slot alert and silences alarms.
    If trigger_launch=True and an alert was active, immediately triggers
    _auto_launch_targeted_batch without waiting for the 30-second timer.
    """
    with _registry_lock:
        if not _alert_state["slots_found"]:
            return True, "No active alert to acknowledge."

        found_cid = _alert_state.get("found_checker_id")
        cat = _alert_state.get("found_category")
        site_name = _alert_state.get("found_site_name")

        _alert_state["slots_found"] = False
        _alert_state["slots_found_time"] = None
        _alert_state["found_details"] = ""

        target_id = None
        batch_size = 10
        use_pri = True
        sort_by = "created_at"

        if found_cid and found_cid in ACTIVE_CHECKERS:
            cinfo = ACTIVE_CHECKERS[found_cid]
            cinfo["stop_event"].set()
            cinfo["is_active"] = False
            target_id = cinfo.get("site_id")
            batch_size = cinfo.get("batch_size", 10)
            use_pri = cinfo.get("use_priority", True)
            sort_by = cinfo.get("sort_by", "created_at")
            cinfo["status"] = f"Auto-launching applications for {cat} ({site_name})..."

        if trigger_launch and cat and target_id:
            print(f"[Slot Checker] Alert acknowledged with immediate launch! Spawning batch for Category {cat} ({site_name})...")
            threading.Thread(
                target=_auto_launch_targeted_batch,
                args=(cat, target_id, batch_size, use_pri, sort_by),
                daemon=True
            ).start()
            return True, f"Alert acknowledged! Instantly launched Category {cat} batch for {site_name}."

        return True, "Alert dismissed without launching."


def _check_slots_on_page_for_strategy(engine, strategy):
    """
    Checks the current page in the Irembo booking step to see if valid slots are available
    using the provided LocationStrategy.
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
                        center_elem = slot.locator(".center")
                        if not center_elem.is_visible():
                            continue
                        center_text = center_elem.inner_text(timeout=2000).strip()

                        cap_elem = slot.locator(".capacity-circle")
                        if not cap_elem.is_visible():
                            continue
                        cap_text = cap_elem.inner_text(timeout=2000).strip()
                        try:
                            cap = int(cap_text)
                            if cap > 0 and strategy.matches_center(center_text):
                                return True, f"{center_text} ({cap} seats)"
                        except ValueError:
                            pass
        except Exception:
            pass
    return False, ""


def _find_time_dropdown(page):
    """Locates the time selection dropdown using battle-tested multi-selectors from polling.py."""
    selectors = [
        'label:has-text("Igihe") + ng-select',
        'ng-select[bindlabel="formatted"]',
        'ng-select:has-text("Guhitamo hakurikijwe igihe")',
        'ng-select[formcontrolname="timeFormControl"]',
        'ng-select[formcontrolname*="time" i]'
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _safe_get_time_options(engine):
    page = engine.page
    dropdown = _find_time_dropdown(page)
    if not dropdown:
        return []

    try:
        dropdown.click(force=True, timeout=5000)
        page.wait_for_selector('.ng-dropdown-panel .ng-option', state="visible", timeout=4000)
        options = page.locator('.ng-dropdown-panel .ng-option').all()
        texts = [opt.inner_text(timeout=1000).strip() for opt in options if opt.inner_text(timeout=1000).strip()]
        page.keyboard.press("Escape")
        return texts
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return []


def _safe_select_time_slot_by_index(engine, target_index):
    page = engine.page
    dropdown = _find_time_dropdown(page)
    if not dropdown:
        return False

    try:
        if not page.locator('.ng-dropdown-panel').is_visible():
            dropdown.click(force=True, timeout=5000)
            page.wait_for_selector('.ng-dropdown-panel', state="visible", timeout=4000)

        options = page.locator('.ng-dropdown-panel .ng-option').all()
        if target_index < len(options):
            options[target_index].scroll_into_view_if_needed()
            options[target_index].click(timeout=3000)
            time.sleep(1)
            return True
        else:
            page.keyboard.press("Escape")
            return False
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _auto_launch_targeted_batch(category, target_id, batch_size=10, use_priority=True, sort_by="created_at"):
    """
    Auto-launches eligible applications matching BOTH category and designated site.
    Strictly isolated:
    - If category is 'B', strictly launches Category B applications.
    - If site is manual ('manual'), strictly launches applications with working_site == 'KICUKIRO - BUSANZA SITE (KIC)'.
    - If site is automated ('automated'), strictly excludes manual site applications.
    """
    from .models import ClientApplication, SystemActivityLog
    from .views import run_automation_worker
    from .automation_engine.utils import grant_foreground_permission
    from django.db.models import Q

    cfg = TARGET_CONFIGS.get(target_id, TARGET_CONFIGS["automated"])

    print(f"[Targeted Auto-Launcher] Starting auto-launch for Category {category} at site: {cfg['name']} (Batch size: {batch_size}, Priority: {use_priority}, Sort: {sort_by})...")
    grant_foreground_permission()

    def _fetch_ordered_candidates():
        base_qs = ClientApplication.objects.filter(
            category__iexact=category,
            is_archived=False,
            status__in=['PENDING', 'FAILED', 'CANCELED']
        )

        # Apply strict site isolation within Kicukiro (also covering null/empty district which defaults to Kicukiro)
        kicukiro_q = Q(district__iexact='Kicukiro') | Q(district__isnull=True) | Q(district='')
        if cfg["is_manual"]:
            base_qs = base_qs.filter(kicukiro_q).filter(
                Q(working_site__iexact='KICUKIRO - BUSANZA SITE (KIC)') | Q(working_site__icontains='BUSANZA SITE')
            )
        else:
            base_qs = base_qs.filter(kicukiro_q).exclude(
                Q(working_site__iexact='KICUKIRO - BUSANZA SITE (KIC)') | Q(working_site__icontains='BUSANZA SITE')
            )

        order_mappings = {
            "created_at": ["created_at", "id"],
            "-created_at": ["-created_at", "-id"],
            "teacher": ["teacher__name", "created_at"],
            "status": ["status", "created_at"],
            "first_name": ["first_name", "last_name", "created_at"],
        }
        order_fields = order_mappings.get(sort_by, ["created_at", "id"])

        if use_priority:
            priority_group = list(base_qs.filter(is_priority=True).order_by(*order_fields))
            remaining_group = list(base_qs.filter(is_priority=False).order_by(*order_fields))
            print(f"[Targeted Auto-Launcher] Found {len(priority_group)} PRIORITY and {len(remaining_group)} remaining applications for Category {category} ({cfg['name']}).")
            return priority_group + remaining_group
        else:
            return list(base_qs.order_by(*order_fields))

    apps = run_in_db_thread(_fetch_ordered_candidates)

    if not apps:
        print(f"[Targeted Auto-Launcher] No eligible Category {category} applications found for {cfg['name']}.")
        return

    total = len(apps)
    print(f"[Targeted Auto-Launcher] Launching {total} eligible applications for Category {category} ({cfg['name']}) in batches of {batch_size}...")

    launched_count = 0

    for i in range(0, total, batch_size):
        batch = apps[i:i + batch_size]
        for app in batch:
            try:
                grant_foreground_permission()
                worker_thread = threading.Thread(target=run_automation_worker, args=(app.id,), daemon=True)
                worker_thread.start()
                launched_count += 1

                def _log_activity(app_id, app_name, is_pri):
                    desc = f"Auto-launched by Slot Checker [Category {category} - {cfg['name']}]"
                    if is_pri:
                        desc += " [PRIORITY]"
                    SystemActivityLog.objects.create(
                        action_type=SystemActivityLog.ActionType.ENGINE,
                        description=desc,
                        application_name=app_name,
                        application_id=app_id
                    )
                run_in_db_thread(_log_activity, app.id, f"{app.first_name} {app.last_name}", getattr(app, 'is_priority', False))
            except Exception as e:
                print(f"[Targeted Auto-Launcher Error] Failed to launch worker for app {app.id}: {e}")

            time.sleep(2.0)

        if i + batch_size < total:
            time.sleep(30)

    print(f"[Targeted Auto-Launcher] Finished auto-launch! Successfully started {launched_count} applications for Category {category} ({cfg['name']}).")


def _worker_loop(checker_key, category, target_id, stop_event, batch_size=10, use_priority=True, sort_by="created_at", initial_delay=0.0):
    """
    Dedicated check loop for an individual site & category worker.
    Runs concurrently and uses LocationStrategy to evaluate slots.
    """
    from .automation_engine import IremboAutomationEngine

    cfg = TARGET_CONFIGS.get(target_id, TARGET_CONFIGS["automated"])
    strategy = get_location_strategy("Kicukiro", working_site=cfg["site_value"])

    print(f"[{category} - {cfg['name']} Worker] Initializing with delay {initial_delay}s...")
    if initial_delay > 0:
        for _ in range(int(initial_delay * 10)):
            if stop_event.is_set():
                return
            time.sleep(0.1)

    recently_failed_ids = set()
    last_candidate_id = None

    while not stop_event.is_set():
        # Check if slots were found by this specific worker and alarm is ringing
        if _alert_state["slots_found"] and _alert_state["found_checker_id"] == checker_key:
            elapsed = time.time() - (_alert_state.get("slots_found_time") or time.time())
            remaining = max(0, 30 - int(elapsed))

            with _registry_lock:
                if checker_key in ACTIVE_CHECKERS:
                    ACTIVE_CHECKERS[checker_key]["status"] = f"SLOTS FOUND! Auto-launching in {remaining}s!"

            if HAVE_WINSOUND:
                try:
                    winsound.Beep(900, 400)
                except Exception:
                    pass

            if elapsed >= 30:
                print(f"[{category} - {cfg['name']} Worker] 30 seconds elapsed without user acknowledgment! Auto-launching targeted batch...")
                _alert_state["slots_found"] = False
                stop_event.set()
                with _registry_lock:
                    if checker_key in ACTIVE_CHECKERS:
                        ACTIVE_CHECKERS[checker_key]["is_active"] = False
                        ACTIVE_CHECKERS[checker_key]["status"] = f"Auto-launched applications for {category} ({cfg['name']})."
                threading.Thread(
                    target=_auto_launch_targeted_batch,
                    args=(category, target_id, batch_size, use_priority, sort_by),
                    daemon=True
                ).start()
                break

            time.sleep(1)
            continue

        # Step 1: Lease an available candidate exclusively for this category worker
        candidate = lease_candidate(category=category, exclude_ids=recently_failed_ids)
        if not candidate:
            with _registry_lock:
                if checker_key in ACTIVE_CHECKERS:
                    ACTIVE_CHECKERS[checker_key]["status"] = f"Waiting for Category {category} candidate..."
            time.sleep(5)
            continue

        last_candidate_id = candidate.id
        cand_name = f"{candidate.first_name} {candidate.last_name}"
        with _registry_lock:
            if checker_key in ACTIVE_CHECKERS:
                ACTIVE_CHECKERS[checker_key]["current_candidate"] = cand_name
                ACTIVE_CHECKERS[checker_key]["status"] = f"Checking using {candidate.first_name}..."
        print(f"[{category} - {cfg['name']} Worker] Checking slots using {candidate.national_id} ({cand_name})...")

        found_any_slots = False
        found_details_str = ""

        try:
            with sync_playwright() as p:
                engine = IremboAutomationEngine(booking_record=candidate, is_slot_checker=True)
                engine._get_time_options = lambda: _safe_get_time_options(engine)
                engine._select_time_slot_by_index = lambda idx: _safe_select_time_slot_by_index(engine, idx)

                # Headless mode for background worker
                engine.initialize_stealth_browser(p, headless=True)

                engine.navigate_to_booking_form(
                    national_id=candidate.national_id,
                    verification_data=candidate.first_name
                )

                if engine.page is None or engine.page.is_closed():
                    raise Exception("Browser page closed unexpectedly during navigation.")

                # Select Category (dynamic category dropdown selection)
                category_control = "categoryFormControl"
                if not engine.page.locator(f'ng-select[formcontrolname="{category_control}"]').is_visible():
                    category_control = "serviceFormControl"
                engine.select_category_dropdown(category_control, category)

                # Select District Kicukiro
                district_control = "locationFormControl"
                if not engine.page.locator(f'ng-select[formcontrolname="{district_control}"]').is_visible():
                    district_control = "districtFormControl"
                engine.set_angular_dropdown(district_control, "Kicukiro")
                time.sleep(2)

                # Check time schedules and evaluate against this worker's location strategy
                time_options = _safe_get_time_options(engine)
                if not time_options:
                    found, details = _check_slots_on_page_for_strategy(engine, strategy)
                    if found:
                        found_any_slots = True
                        found_details_str = details
                else:
                    for idx in range(len(time_options)):
                        if stop_event.is_set():
                            break
                        _safe_select_time_slot_by_index(engine, idx)
                        time.sleep(2)

                        found, details = _check_slots_on_page_for_strategy(engine, strategy)
                        if found:
                            found_any_slots = True
                            found_details_str = details
                            break

                # Increment check counters
                now_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                with _registry_lock:
                    if checker_key in ACTIVE_CHECKERS:
                        ACTIVE_CHECKERS[checker_key]["check_count"] += 1
                        ACTIVE_CHECKERS[checker_key]["last_check"] = now_str

                if found_any_slots:
                    print(f"[{category} - {cfg['name']} Worker] SLOTS FOUND! Details: {found_details_str}")
                    with _registry_lock:
                        _alert_state["slots_found"] = True
                        _alert_state["slots_found_time"] = time.time()
                        _alert_state["found_checker_id"] = checker_key
                        _alert_state["found_category"] = category
                        _alert_state["found_site_name"] = cfg["name"]
                        _alert_state["found_details"] = f"Slots available for Category {category} at {cfg['name']}: {found_details_str}!"

                        if checker_key in ACTIVE_CHECKERS:
                            ACTIVE_CHECKERS[checker_key]["status"] = f"SLOTS DETECTED! Auto-launching in 30s if unacknowledged!"

                    if HAVE_WINSOUND:
                        for _ in range(5):
                            try:
                                winsound.Beep(1000, 500)
                                time.sleep(0.1)
                            except Exception:
                                break
                else:
                    with _registry_lock:
                        if checker_key in ACTIVE_CHECKERS:
                            ACTIVE_CHECKERS[checker_key]["status"] = "No slots found. Waiting next interval."

        except Exception as e:
            err_msg = str(e)
            print(f"[{category} - {cfg['name']} Worker Warning] Attempt failed with {candidate.national_id}: {err_msg}")
            if "timeout" not in err_msg.lower():
                recently_failed_ids.add(candidate.id)
            with _registry_lock:
                if checker_key in ACTIVE_CHECKERS:
                    ACTIVE_CHECKERS[checker_key]["status"] = f"Portal issue: {err_msg[:30]}..."
        finally:
            # Release candidate lease so other workers or future runs can use them
            release_candidate(last_candidate_id)

        # Sleep between checks if still running and slots not found
        if not found_any_slots and not stop_event.is_set():
            sleep_duration = random.randint(60, 180)
            for _ in range(sleep_duration):
                if stop_event.is_set() or (_alert_state["slots_found"] and _alert_state["found_checker_id"] == checker_key):
                    break
                time.sleep(1)

    with _registry_lock:
        if checker_key in ACTIVE_CHECKERS:
            ACTIVE_CHECKERS[checker_key]["is_active"] = False
            ACTIVE_CHECKERS[checker_key]["current_candidate"] = None
            if ACTIVE_CHECKERS[checker_key]["status"] != "SLOTS FOUND!":
                ACTIVE_CHECKERS[checker_key]["status"] = "Stopped"

    print(f"[{category} - {cfg['name']} Worker] Stopped cleanly.")

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

# Maximum duration (in seconds) to keep a single Chromium browser session open
# before recycling it and opening a fresh one (30 minutes).
SESSION_MAX_DURATION = 30 * 60

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

# Global error alert state when all selected probe applications fail in a full cycle
_error_alert_state = {
    "all_failed": False,
    "failed_time": None,
    "failed_details": "",
    "failed_checker_id": None,
    "failed_category": None,
    "failed_site_name": None
}

# Global candidate lease tracker to prevent concurrent workers from colliding on the same applicant ID when multiple are provided
_leased_candidate_ids = set()
_candidate_lease_lock = threading.Lock()


def select_sticky_candidate(candidate_ids, failed_ids=None):
    """
    Selects the next healthy candidate from the user-specified list of (up to 3) candidate IDs.
    - Strictly uses only IDs in `candidate_ids` (Phase 1).
    - Excludes any candidate ID that has failed even once in `failed_ids` (Phase 2).
    - Prefers an unleased candidate if multiple workers are active, falling back to a healthy
      candidate from `candidate_ids` if fewer candidates were selected than active workers.
    """
    from .models import ClientApplication

    if not candidate_ids:
        return None
    if failed_ids is None:
        failed_ids = set()

    healthy_ids = [cid for cid in candidate_ids if cid not in failed_ids]
    if not healthy_ids:
        return None

    with _candidate_lease_lock:
        def _fetch_by_ids():
            apps_by_id = {
                app.id: app
                for app in ClientApplication.objects.filter(
                    id__in=healthy_ids,
                    is_archived=False
                ).exclude(
                    national_id__isnull=True
                ).exclude(
                    national_id=''
                )
            }
            # Preserve exact user-selected order
            return [apps_by_id[cid] for cid in healthy_ids if cid in apps_by_id]

        candidates = run_in_db_thread(_fetch_by_ids)
        if not candidates:
            return None

        # Prefer a candidate not currently leased by another concurrent site worker
        unleased = [c for c in candidates if c.id not in _leased_candidate_ids]
        chosen = unleased[0] if unleased else candidates[0]
        _leased_candidate_ids.add(chosen.id)
        return chosen


def refresh_candidate_instance(app_id):
    """
    Fetches a fresh copy of the sticky candidate from the database to ensure up-to-date fields.
    """
    from .models import ClientApplication

    if not app_id:
        return None

    def _fetch():
        try:
            return ClientApplication.objects.get(id=app_id, is_archived=False)
        except ClientApplication.DoesNotExist:
            return None

    return run_in_db_thread(_fetch)


def release_candidate(app_id):
    """
    Releases a previously leased candidate ID.
    """
    if app_id is None:
        return
    with _candidate_lease_lock:
        _leased_candidate_ids.discard(app_id)


def start_slot_checker(category="A", batch_size=10, use_priority=True, sort_by="created_at", targets=None, candidate_ids=None):
    """
    Starts concurrent slot checker workers for the given category and target sites,
    using the user-selected probe applications (1 to 3 applications).
    Existing running workers for other categories remain running without interruption.
    """
    from .models import ClientApplication

    category = (category or "A").strip().upper()

    # Phase 1: Validate user-selected candidate_ids (1 to 5 applications)
    if not candidate_ids or not isinstance(candidate_ids, (list, tuple)):
        return False, "Please select between 1 and 5 applications to use for slot checking."

    cleaned_ids = []
    for raw_id in candidate_ids:
        try:
            cid = int(raw_id)
            if cid not in cleaned_ids:
                cleaned_ids.append(cid)
        except (ValueError, TypeError):
            continue

    if len(cleaned_ids) < 1:
        return False, "Please select at least 1 valid application to use for slot checking."
    if len(cleaned_ids) > 5:
        return False, "You can select a maximum of 5 applications for slot checking."

    def _validate_selected_candidates():
        valid_apps = list(
            ClientApplication.objects.filter(
                id__in=cleaned_ids,
                is_archived=False
            ).exclude(
                national_id__isnull=True
            ).exclude(
                national_id=''
            )
        )
        valid_map = {a.id: a for a in valid_apps}
        return [cid for cid in cleaned_ids if cid in valid_map]

    valid_candidate_ids = run_in_db_thread(_validate_selected_candidates)
    if not valid_candidate_ids:
        return False, "None of the selected applications were found or have a valid National ID."

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

            # Rotate starting candidate order slightly for secondary site workers if 2+ candidates were chosen
            if len(valid_candidate_ids) > 1 and index > 0:
                offset = index % len(valid_candidate_ids)
                worker_candidate_ids = valid_candidate_ids[offset:] + valid_candidate_ids[:offset]
            else:
                worker_candidate_ids = list(valid_candidate_ids)

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
                "candidate_ids": worker_candidate_ids,
                "batch_size": batch_size,
                "use_priority": bool(use_priority),
                "sort_by": sort_by,
                "stop_event": stop_event,
                "created_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            worker_thread = threading.Thread(
                target=_worker_loop,
                args=(
                    checker_key,
                    category,
                    target_id,
                    stop_event,
                    worker_candidate_ids,
                    batch_size,
                    bool(use_priority),
                    sort_by,
                    index * 2.5
                ),
                daemon=True,
                name=f"SlotWorker_{checker_key}"
            )
            ACTIVE_CHECKERS[checker_key]["thread"] = worker_thread
            worker_thread.start()
            started_targets.append(cfg["name"])

    if not started_targets:
        return False, f"Checker for Category {category} is already running on the selected site(s)."

    return True, (
        f"Started checker for Category {category} on {len(started_targets)} site(s) "
        f"({', '.join(started_targets)}) using {len(valid_candidate_ids)} selected application(s)."
    )


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
                if _error_alert_state.get("failed_checker_id") == checker_id:
                    _error_alert_state["all_failed"] = False
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
                    if _error_alert_state.get("failed_checker_id") == cid:
                        _error_alert_state["all_failed"] = False
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

        _error_alert_state["all_failed"] = False
        _error_alert_state["failed_time"] = None
        _error_alert_state["failed_details"] = ""

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
            "all_failed": _error_alert_state["all_failed"],
            "failed_time": _error_alert_state["failed_time"],
            "failed_details": _error_alert_state["failed_details"],
            "failed_checker_id": _error_alert_state["failed_checker_id"],
            "failed_category": _error_alert_state["failed_category"],
            "failed_site_name": _error_alert_state["failed_site_name"],
            "workers": active_workers
        }


def acknowledge_error_alert(stop_worker=False):
    """
    Acknowledges/dismisses the 'all selected applications failed' warning dialog and silences the warning sound.
    If stop_worker=True, also stops the worker that triggered the error alert.
    """
    with _registry_lock:
        failed_cid = _error_alert_state.get("failed_checker_id")
        _error_alert_state["all_failed"] = False
        _error_alert_state["failed_time"] = None
        _error_alert_state["failed_details"] = ""

        if stop_worker and failed_cid and failed_cid in ACTIVE_CHECKERS:
            cinfo = ACTIVE_CHECKERS[failed_cid]
            cinfo["stop_event"].set()
            cinfo["is_active"] = False
            cinfo["status"] = "Stopped"
            cinfo["current_candidate"] = None
            return True, f"Error alert dismissed and stopped worker {cinfo['category']} - {cinfo['site_name']}."

        return True, "Error alert dismissed. Checker continues looping through selected applications."


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


def _click_shyira_ku_gihe(engine):
    """
    Phase 3: Clicks the 'Shyira ku gihe' (refresh-btn) button on the Irembo slot selector
    to refresh available slots in-page without closing or reloading the browser.
    """
    page = engine.page
    if page is None or page.is_closed():
        raise Exception("Browser page closed before clicking 'Shyira ku gihe'.")

    # Dismiss any open dropdown panel so it doesn't intercept the click
    try:
        if page.locator('.ng-dropdown-panel').is_visible():
            page.keyboard.press("Escape")
            time.sleep(0.3)
    except Exception:
        pass

    refresh_btn = page.locator('button.refresh-btn, button:has-text("Shyira ku gihe")').first
    refresh_btn.wait_for(state="visible", timeout=6000)

    if refresh_btn.is_disabled():
        raise Exception("'Shyira ku gihe' refresh button is disabled.")

    refresh_btn.scroll_into_view_if_needed()
    refresh_btn.click(timeout=5000)

    # Human-like wait for Angular slot list refresh
    time.sleep(random.uniform(1.5, 2.5))

    # Verify that no portal error appeared after refreshing
    engine.capture_error_if_any()


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


def _worker_loop(checker_key, category, target_id, stop_event, candidate_ids, batch_size=10, use_priority=True, sort_by="created_at", initial_delay=0.0):
    """
    Dedicated check loop for an individual site & category worker:
    - Phase 1: Uses only the user-selected `candidate_ids` (1 to 3 applications).
    - Phase 2: Sticks to the selected application indefinitely unless it encounters an error (even once),
               in which case it switches to the next application in `candidate_ids`.
    - Phase 3: Keeps Chromium open for 30 minutes at the slot stage, waiting 3-5s and clicking
               'Shyira ku gihe' to refresh slots in-page before recycling the browser after 30 minutes.
    """
    from .automation_engine import IremboAutomationEngine

    cfg = TARGET_CONFIGS.get(target_id, TARGET_CONFIGS["automated"])
    strategy = get_location_strategy("Kicukiro", working_site=cfg["site_value"])

    print(f"[{category} - {cfg['name']} Worker] Initializing with delay {initial_delay}s (Selected candidate IDs: {candidate_ids})...")
    if initial_delay > 0:
        for _ in range(int(initial_delay * 10)):
            if stop_event.is_set():
                return
            time.sleep(0.1)

    failed_candidate_ids = set()
    active_candidate = None
    last_error_msg = ""

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

        # Phase 1 & 2: Acquire or keep the sticky candidate from the user-selected list (up to 5)
        if active_candidate is not None:
            refreshed = refresh_candidate_instance(active_candidate.id)
            if refreshed is None:
                failed_candidate_ids.add(active_candidate.id)
                release_candidate(active_candidate.id)
                active_candidate = None
            else:
                active_candidate = refreshed

        if active_candidate is None:
            active_candidate = select_sticky_candidate(candidate_ids, failed_ids=failed_candidate_ids)

        if not active_candidate:
            # All user-selected applications (up to 5) failed in this pass!
            # Alert user with sound + popup dialog, reset failed set, and keep looping!
            warn_msg = (
                f"All {len(candidate_ids)} selected application(s) for Category {category} ({cfg['name']}) are failing! "
                f"Last error: {last_error_msg or 'Portal / validation error'}. "
                f"Restarting loop through selected applications..."
            )
            print(f"\a[{category} - {cfg['name']} Worker Alert] {warn_msg}")
            with _registry_lock:
                _error_alert_state["all_failed"] = True
                _error_alert_state["failed_time"] = time.time()
                _error_alert_state["failed_checker_id"] = checker_key
                _error_alert_state["failed_category"] = category
                _error_alert_state["failed_site_name"] = cfg["name"]
                _error_alert_state["failed_details"] = warn_msg

                if checker_key in ACTIVE_CHECKERS:
                    ACTIVE_CHECKERS[checker_key]["status"] = f"⚠️ All {len(candidate_ids)} app(s) failing! Restarting loop..."
                    ACTIVE_CHECKERS[checker_key]["current_candidate"] = None

            if HAVE_WINSOUND:
                for _ in range(3):
                    try:
                        winsound.Beep(650, 450)
                        time.sleep(0.15)
                    except Exception:
                        break

            # Reset failed set so the worker restarts from the first selected application
            failed_candidate_ids.clear()

            # Wait 3-5 seconds before restarting the loop
            for _ in range(int(random.uniform(3.0, 5.0) * 5)):
                if stop_event.is_set():
                    break
                time.sleep(0.2)
            continue

        cand_name = f"{active_candidate.first_name} {active_candidate.last_name}"
        with _registry_lock:
            if checker_key in ACTIVE_CHECKERS:
                ACTIVE_CHECKERS[checker_key]["current_candidate"] = cand_name
                ACTIVE_CHECKERS[checker_key]["status"] = f"Opening session with {active_candidate.first_name}..."
        print(f"[{category} - {cfg['name']} Worker] Launching 30-min session using sticky candidate {active_candidate.national_id} ({cand_name})...")

        found_any_slots = False
        found_details_str = ""
        session_had_error = False

        try:
            with sync_playwright() as p:
                engine = IremboAutomationEngine(booking_record=active_candidate, is_slot_checker=True)
                engine._get_time_options = lambda: _safe_get_time_options(engine)
                engine._select_time_slot_by_index = lambda idx: _safe_select_time_slot_by_index(engine, idx)

                # Headless mode for background worker
                engine.initialize_stealth_browser(p, headless=True)

                engine.navigate_to_booking_form(
                    national_id=active_candidate.national_id,
                    verification_data=active_candidate.first_name
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

                # Candidate succeeded in reaching the slot checking screen — clear any previous all_failed alert for this worker
                with _registry_lock:
                    if _error_alert_state.get("failed_checker_id") == checker_key:
                        _error_alert_state["all_failed"] = False

                # ── Phase 3: 30-Minute Persistent Browser Loop with 'Shyira ku gihe' Refresh ──
                session_start_time = time.time()

                while not stop_event.is_set() and (time.time() - session_start_time) < SESSION_MAX_DURATION:
                    if engine.page is None or engine.page.is_closed():
                        raise Exception("Browser page closed unexpectedly during slot monitoring.")

                    engine.capture_error_if_any()

                    elapsed_session = time.time() - session_start_time
                    mins_left = max(1, int((SESSION_MAX_DURATION - elapsed_session) // 60))

                    with _registry_lock:
                        if checker_key in ACTIVE_CHECKERS:
                            ACTIVE_CHECKERS[checker_key]["status"] = f"Checking slots ({active_candidate.first_name}) [{mins_left}m left]..."

                    # First check current view immediately before cycling dropdown options
                    found, details = _check_slots_on_page_for_strategy(engine, strategy)
                    if found:
                        found_any_slots = True
                        found_details_str = details
                    else:
                        time_options = _safe_get_time_options(engine)
                        if time_options:
                            for idx in range(len(time_options)):
                                if stop_event.is_set():
                                    break
                                _safe_select_time_slot_by_index(engine, idx)
                                time.sleep(random.uniform(1.5, 2.5))

                                found, details = _check_slots_on_page_for_strategy(engine, strategy)
                                if found:
                                    found_any_slots = True
                                    found_details_str = details
                                    break

                    # Increment check counters after completing the pass
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
                                ACTIVE_CHECKERS[checker_key]["status"] = "SLOTS DETECTED! Auto-launching in 30s if unacknowledged!"

                        if HAVE_WINSOUND:
                            for _ in range(5):
                                try:
                                    winsound.Beep(1000, 500)
                                    time.sleep(0.1)
                                except Exception:
                                    break
                        break

                    # Check if 30 minutes have elapsed before starting another refresh
                    if (time.time() - session_start_time) >= SESSION_MAX_DURATION or stop_event.is_set():
                        break

                    # Phase 3: Wait 3-5 seconds (human-like jitter), then click 'Shyira ku gihe'
                    wait_seconds = random.uniform(3.0, 5.0)
                    with _registry_lock:
                        if checker_key in ACTIVE_CHECKERS:
                            ACTIVE_CHECKERS[checker_key]["status"] = f"No slots — Refreshing in {wait_seconds:.1f}s ({mins_left}m left)..."

                    steps = int(wait_seconds / 0.2)
                    for _ in range(max(1, steps)):
                        if stop_event.is_set() or (_alert_state["slots_found"] and _alert_state["found_checker_id"] == checker_key):
                            break
                        time.sleep(0.2)

                    if stop_event.is_set() or (time.time() - session_start_time) >= SESSION_MAX_DURATION:
                        break

                    with _registry_lock:
                        if checker_key in ACTIVE_CHECKERS:
                            ACTIVE_CHECKERS[checker_key]["status"] = f"Clicking 'Shyira ku gihe' ({mins_left}m left)..."

                    _click_shyira_ku_gihe(engine)

                # If 30-minute timer completed normally without finding slots, log browser recycle
                if not found_any_slots and not stop_event.is_set():
                    print(f"[{category} - {cfg['name']} Worker] 30-minute session reached. Closing and reopening browser with sticky candidate {cand_name}...")
                    with _registry_lock:
                        if checker_key in ACTIVE_CHECKERS:
                            ACTIVE_CHECKERS[checker_key]["status"] = f"Recycling 30m browser session ({active_candidate.first_name})..."

        except Exception as e:
            session_had_error = True
            err_msg = str(e)
            last_error_msg = err_msg
            print(
                f"[{category} - {cfg['name']} Worker Warning] Error with candidate "
                f"{active_candidate.national_id} ({cand_name}): {err_msg}. Switching to next selected candidate..."
            )
            # Phase 2: Immediately mark this candidate as failed on first error and switch to next
            failed_candidate_ids.add(active_candidate.id)
            release_candidate(active_candidate.id)
            active_candidate = None

            with _registry_lock:
                if checker_key in ACTIVE_CHECKERS:
                    ACTIVE_CHECKERS[checker_key]["status"] = f"Candidate failed ({err_msg[:25]}...). Switching..."

        # Brief pause before re-opening browser (either after 30-min recycle or candidate failover)
        if not found_any_slots and not stop_event.is_set():
            pause_secs = random.uniform(2.0, 4.0) if not session_had_error else random.uniform(1.5, 3.0)
            for _ in range(int(pause_secs * 5)):
                if stop_event.is_set():
                    break
                time.sleep(0.2)

    # Clean up lease when worker exits
    if active_candidate is not None:
        release_candidate(active_candidate.id)

    with _registry_lock:
        if checker_key in ACTIVE_CHECKERS:
            ACTIVE_CHECKERS[checker_key]["is_active"] = False
            ACTIVE_CHECKERS[checker_key]["current_candidate"] = None
            if not ACTIVE_CHECKERS[checker_key]["status"].startswith("Stopped:") and ACTIVE_CHECKERS[checker_key]["status"] != "SLOTS FOUND!":
                ACTIVE_CHECKERS[checker_key]["status"] = "Stopped"

    print(f"[{category} - {cfg['name']} Worker] Stopped cleanly.")

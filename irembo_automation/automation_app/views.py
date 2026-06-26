import threading
import time

# Global lock to prevent concurrent Playwright browser access to the persistent profile
browser_lock = threading.Lock()
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from .models import ClientApplication
from automation_app.automation_engine import IremboAutomationEngine
from automation_app.automation_engine.utils import run_in_db_thread, AbortTaskException
from playwright.sync_api import sync_playwright  # type: ignore[import]

def run_automation_worker(application_id):
    def _log_waiting():
        try:
            app = ClientApplication.objects.get(id=application_id)
            if app.status not in [ClientApplication.ProcessStatus.SUCCESS, ClientApplication.ProcessStatus.CANCELED, ClientApplication.ProcessStatus.MANUAL_REVIEW_NEEDED]:
                app.status = ClientApplication.ProcessStatus.PROCESSING
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                log_msg = f"[{timestamp}] [INFO] Queued: Waiting for browser profile to become available...\n"
                app.log_output = (app.log_output or "") + log_msg
                app.save(update_fields=["status", "log_output"])
        except Exception:
            pass
    run_in_db_thread(_log_waiting)
    
    with browser_lock:
        _run_automation_worker_locked(application_id)

def _run_automation_worker_locked(application_id):
    max_attempts = 3

    # Initialize log_output and ensure starting state
    def _init_run():
        try:
            app = ClientApplication.objects.get(id=application_id)
            app.status = ClientApplication.ProcessStatus.PROCESSING
            app.retry_attempts = 0
            app.last_error = None
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            app.log_output = f"[{timestamp}] [INFO] Starting automation process...\n"
            app.save()
            return app
        except ClientApplication.DoesNotExist:
            return None

    application = run_in_db_thread(_init_run)
    if not application:
        print(f"[Worker Thread Error] Application {application_id} does not exist. Aborting.")
        return

    for attempt in range(1, max_attempts + 1):
        # Check if the application was canceled or deleted in between attempts
        def _check_cancelled_or_deleted():
            try:
                app = ClientApplication.objects.get(id=application_id)
                # If already completed successfully or manually reviewed, don't run again.
                if app.status in [
                    ClientApplication.ProcessStatus.SUCCESS,
                    ClientApplication.ProcessStatus.CANCELED,
                    ClientApplication.ProcessStatus.MANUAL_REVIEW_NEEDED
                ]:
                    return app, True
                return app, False
            except ClientApplication.DoesNotExist:
                return None, True

        app_instance, should_abort = run_in_db_thread(_check_cancelled_or_deleted)
        if should_abort:
            msg = f"Application {application_id} state changed or deleted. Aborting retries."
            print(f"[Worker Thread] {msg}")
            return

        def _log_attempt_start():
            app = ClientApplication.objects.get(id=application_id)
            app.status = ClientApplication.ProcessStatus.PROCESSING
            app.user_response = None
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            app.log_output += f"[{timestamp}] [INFO] Starting attempt {attempt} of {max_attempts}...\n"
            app.save(update_fields=["status", "log_output", "user_response"])
            return app

        application = run_in_db_thread(_log_attempt_start)

        try:
            with sync_playwright() as p:
                engine = IremboAutomationEngine(booking_record=application)
                engine.initialize_stealth_browser(p, headless=False)
                engine.navigate_to_booking_form(
                    national_id=application.national_id,
                    verification_data=application.first_name
                )
                billing_id = engine.start_slot_polling()
                
                # Check status inside the DB in case slot secured & successfully completed
                def _get_final_status():
                    app = ClientApplication.objects.get(id=application_id)
                    return app.status, app.billing_number
                
                final_status, final_billing = run_in_db_thread(_get_final_status)
                
                if final_status in [ClientApplication.ProcessStatus.SUCCESS, ClientApplication.ProcessStatus.MANUAL_REVIEW_NEEDED] or final_billing:
                    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                    def _log_success():
                        app = ClientApplication.objects.get(id=application_id)
                        app.log_output += f"[{timestamp}] [INFO] Process completed successfully. Billing Code: {final_billing or 'N/A'}\n"
                        app.save(update_fields=["log_output"])
                    run_in_db_thread(_log_success)
                    print(f"[Worker Thread] Process completed cleanly for ID {application.national_id}. Billing Code: {final_billing}")
                    
                    break  # Success! Exit retry loop
                else:
                    raise Exception("Slot polling finished without securing a billing code.")

        except AbortTaskException as e:
            error_message = str(e)
            print(f"[Worker Thread] Task aborted cleanly for application {application_id}: {error_message}")
            def _log_abort():
                app = ClientApplication.objects.get(id=application_id)
                app.status = ClientApplication.ProcessStatus.CANCELED
                app.last_error = error_message
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                app.log_output += f"[{timestamp}] [INFO] {error_message}\n"
                app.save(update_fields=["status", "last_error", "log_output"])
            run_in_db_thread(_log_abort)
            break  # Exit retry loop immediately

        except Exception as e:
            error_message = str(e)
            error_details = f"{type(e).__name__}: {error_message}"
            print(f"[Worker Thread Error] Attempt {attempt} failed for application {application_id}: {error_details}")

            def _log_attempt_failure():
                app = ClientApplication.objects.get(id=application_id)
                if app.status not in [
                    ClientApplication.ProcessStatus.SUCCESS,
                    ClientApplication.ProcessStatus.CANCELED,
                ]:
                    app.retry_attempts = attempt
                    app.last_error = error_details
                    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                    app.log_output += f"[{timestamp}] [ERROR] Attempt {attempt} failed: {error_details}\n"
                    
                    if attempt >= max_attempts:
                        app.status = ClientApplication.ProcessStatus.FAILED
                        app.log_output += f"[{timestamp}] [ERROR] All {max_attempts} attempts failed. Stopping.\n"
                    else:
                        app.status = ClientApplication.ProcessStatus.FAILED  # Update status so dashboard shows FAILED between retries
                        app.log_output += f"[{timestamp}] [WARNING] Attempt {attempt} failed. Retrying in 10 seconds...\n"
                    
                    app.save(update_fields=["status", "retry_attempts", "last_error", "log_output"])
            
            run_in_db_thread(_log_attempt_failure)

            if attempt < max_attempts:
                time.sleep(10)

def dashboard(request):
    """Renders the central monitoring dashboard panel grid with search, filter, and sort."""
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    payment_filter = request.GET.get('payment', '')
    sort_by = request.GET.get('sort', '-created_at')
    
    # Start with all applications
    applications = ClientApplication.objects.all()
    
    # Apply search filter
    if query:
        applications = applications.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(national_id__icontains=query) |
            Q(phone_number__icontains=query) |
            Q(email__icontains=query) |
            Q(billing_number__icontains=query)
        )
    
    # Apply status filter
    if status_filter:
        applications = applications.filter(status=status_filter)
    
    # Apply payment filter
    if payment_filter:
        applications = applications.filter(payment_status=payment_filter)
    
    # Apply sorting
    applications = applications.order_by(sort_by)
    
    # Pagination
    paginator = Paginator(applications, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # System Statistics
    now = timezone.now()
    start_of_week = now - timedelta(days=now.weekday())
    stats = {
        'total_apps': ClientApplication.objects.count(),
        'total_failed': ClientApplication.objects.filter(status=ClientApplication.ProcessStatus.FAILED).count(),
        'total_success': ClientApplication.objects.filter(status=ClientApplication.ProcessStatus.SUCCESS).count(),
        'total_in_progress': ClientApplication.objects.filter(status__in=[ClientApplication.ProcessStatus.PROCESSING, ClientApplication.ProcessStatus.FINALIZING]).count(),
        'total_completed_week': ClientApplication.objects.filter(status=ClientApplication.ProcessStatus.SUCCESS, updated_at__gte=start_of_week).count(),
        'total_pending': ClientApplication.objects.filter(status=ClientApplication.ProcessStatus.PENDING).count(),
    }
    
    context = {
        'page_obj': page_obj,
        'applications': page_obj.object_list,
        'query': query,
        'status_filter': status_filter,
        'payment_filter': payment_filter,
        'sort_by': sort_by,
        'status_choices': ClientApplication.ProcessStatus.choices,
        'payment_choices': ClientApplication.PaymentStatus.choices,
        'stats': stats,
    }
    return render(request, 'automation/dashboard.html', context)

def create_application(request):
    """Handle both GET (form display) and POST (form submission) for creating applications."""
    if request.method == 'POST':
        try:
            app = ClientApplication(
                first_name=request.POST.get('first_name'),
                last_name=request.POST.get('last_name'),
                national_id=request.POST.get('national_id'),
                birth_date=request.POST.get('birth_date'),
                phone_number=request.POST.get('phone_number'),
                email=request.POST.get('email', ''),
                category=request.POST.get('category'),
                provisional_number=request.POST.get('provisional_number', ''),
                payment_status=request.POST.get('payment_status', 'UNPAID'),
            )
            app.full_clean()
            app.save()
            messages.success(request, f'Application created successfully for {app.first_name} {app.last_name}')
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f'Error creating application: {str(e)}')
            return render(request, 'automation/create_application.html', {
                'payment_choices': ClientApplication.PaymentStatus.choices,
            })
    
    return render(request, 'automation/create_application.html', {
        'payment_choices': ClientApplication.PaymentStatus.choices,
    })

def edit_application(request, application_id):
    """Handle editing an existing application."""
    app = get_object_or_404(ClientApplication, id=application_id)
    
    if request.method == 'POST':
        try:
            app.first_name = request.POST.get('first_name', app.first_name)
            app.last_name = request.POST.get('last_name', app.last_name)
            app.email = request.POST.get('email', app.email)
            # Persist additional editable fields so admin/frontend edits actually save
            app.national_id = request.POST.get('national_id', app.national_id)
            app.birth_date = request.POST.get('birth_date', app.birth_date)
            app.phone_number = request.POST.get('phone_number', app.phone_number)
            app.provisional_number = request.POST.get('provisional_number', app.provisional_number)
            app.billing_number = request.POST.get('billing_number', app.billing_number)
            app.application_number = request.POST.get('application_number', app.application_number)
            app.category = request.POST.get('category', app.category)
            app.payment_status = request.POST.get('payment_status', app.payment_status)
            app.status = request.POST.get('status', app.status)
            app.comment = request.POST.get('comment', app.comment)
            app.full_clean()
            app.save()
            messages.success(request, 'Application updated successfully')
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f'Error updating application: {str(e)}')
    
    context = {
        'app': app,
        'status_choices': ClientApplication.ProcessStatus.choices,
        'payment_choices': ClientApplication.PaymentStatus.choices,
    }
    return render(request, 'automation/edit_application.html', context)

@require_POST
def delete_application(request, application_id):
    """Delete a single application."""
    app = get_object_or_404(ClientApplication, id=application_id)
    name = f"{app.first_name} {app.last_name}"
    app.delete()
    messages.success(request, f'Application deleted: {name}')
    return redirect('dashboard')

@require_POST
def bulk_action(request):
    """Handle bulk actions on selected applications."""
    action = request.POST.get('action')
    selected_ids = request.POST.getlist('selected_ids')
    
    if not selected_ids:
        messages.warning(request, 'No applications selected')
        return redirect('dashboard')
    
    apps = ClientApplication.objects.filter(id__in=selected_ids)
    
    if action == 'run_engine':
        count = 0
        for app in apps:
            if app.status in [ClientApplication.ProcessStatus.PENDING, ClientApplication.ProcessStatus.FAILED, ClientApplication.ProcessStatus.CANCELED]:
                worker_thread = threading.Thread(target=run_automation_worker, args=(app.id,))
                worker_thread.daemon = True
                worker_thread.start()
                count += 1
        messages.success(request, f'Started automation for {count} applications')
    
    elif action == 'delete':
        count = apps.count()
        apps.delete()
        messages.success(request, f'Deleted {count} applications')
    
    elif action == 'mark_paid':
        apps.update(payment_status='PAID')
        messages.success(request, f'Marked {apps.count()} applications as paid')
    
    elif action == 'mark_unpaid':
        apps.update(payment_status='UNPAID')
        messages.success(request, f'Marked {apps.count()} applications as unpaid')
    
    return redirect('dashboard')

def start_automation(request, application_id):
    """Spawns an isolated operational thread for a specific target applicant."""
    application = get_object_or_404(ClientApplication, id=application_id)
    
    # Only allow ignition if the process isn't already running or completed
    if application.status in [ClientApplication.ProcessStatus.PENDING, ClientApplication.ProcessStatus.FAILED, ClientApplication.ProcessStatus.CANCELED]:
        worker_thread = threading.Thread(target=run_automation_worker, args=(application.id,))
        worker_thread.daemon = True  # Allows fast, clean server restarts
        worker_thread.start()
        
    return redirect('dashboard')


def api_status_feed(request):
    """Asynchronous JSON polling feed utilized by dashboard JavaScript tickers."""
    applications_data = list(ClientApplication.objects.values(
        'id', 'status', 'billing_number', 'retry_attempts', 'last_error', 'user_response', 'comment'
    ))
    return JsonResponse({'applications': applications_data})

def api_application_logs(request, application_id):
    """Asynchronous JSON polling feed for detailed application logs."""
    app = get_object_or_404(ClientApplication, id=application_id)
    return JsonResponse({
        'log_output': app.log_output or 'No logs available yet.',
        'status': app.status,
        'failure_reason': app.failure_reason,
    })

def activity_log(request):
    """Display recent activities from the past 3 months."""
    # Calculate date 3 months ago
    three_months_ago = timezone.now() - timedelta(days=90)
    
    # Get all applications updated in the last 3 months
    recent_activities = ClientApplication.objects.filter(
        updated_at__gte=three_months_ago
    ).order_by('-updated_at')
    
    # Pagination
    paginator = Paginator(recent_activities, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'activities': page_obj.object_list,
        'three_months_ago': three_months_ago,
    }
    return render(request, 'automation/activity_log.html', context)

from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_POST
def api_respond_session(request, application_id):
    """API endpoint to receive user response to auth pause prompt."""
    action = request.POST.get('action')
    if action in ['continue', 'sign_in']:
        app = get_object_or_404(ClientApplication, id=application_id)
        app.user_response = action
        app.save(update_fields=['user_response'])
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid action'}, status=400)


def open_session_manager_thread(lock):
    try:
        from playwright.sync_api import sync_playwright
        from automation_app.automation_engine.config import (
            USER_DATA_DIR_PATH, DEFAULT_USER_AGENT, DEFAULT_VIEWPORT,
            DEFAULT_DEVICE_SCALE_FACTOR, DEFAULT_IS_MOBILE, DEFAULT_HAS_TOUCH,
            DEFAULT_LOCALE, DEFAULT_TIMEZONE
        )
        from playwright_stealth import Stealth
        from automation_app.automation_engine.utils import kill_browser_processes

        kill_browser_processes(USER_DATA_DIR_PATH)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR_PATH,
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--restore-last-session"],
                user_agent=DEFAULT_USER_AGENT,
                viewport=DEFAULT_VIEWPORT,
                device_scale_factor=DEFAULT_DEVICE_SCALE_FACTOR,
                is_mobile=DEFAULT_IS_MOBILE,
                has_touch=DEFAULT_HAS_TOUCH,
                locale=DEFAULT_LOCALE,
                timezone_id=DEFAULT_TIMEZONE
            )
            Stealth().apply_stealth_sync(context)
            
            # Create a fresh tab to avoid stale DOM from restored sessions
            page = context.new_page()
            # Close all other restored tabs to clean up the UI
            for p in context.pages[:-1]:
                try:
                    p.close()
                except Exception:
                    pass
                
            page.goto("https://irembo.gov.rw/", wait_until="networkidle")
            
            # Wait until the user closes the window or 5 minutes pass
            try:
                page.wait_for_event("close", timeout=300000)
            except Exception:
                pass # Timeout or already closed
                    
            try:
                context.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[Session Manager] Failed to open: {e}")
    finally:
        lock.release()

@csrf_exempt
@require_POST
def manage_session(request):
    """Spawns a thread to open the persistent Chrome profile for manual session management."""
    if not browser_lock.acquire(blocking=False):
        return JsonResponse({
            'status': 'error',
            'message': 'Browser is currently in use by an active automation worker. Please wait or abort the task.'
        }, status=409)
        
    worker_thread = threading.Thread(target=open_session_manager_thread, args=(browser_lock,))
    worker_thread.daemon = True
    worker_thread.start()
    return JsonResponse({'status': 'opened'})

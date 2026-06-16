import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from .models import ClientApplication
from automation_app.automation_engine import IremboAutomationEngine
from playwright.sync_api import sync_playwright  # type: ignore[import]

def run_automation_worker(application_id):
    """
    Independent worker executed inside a background thread.
    Manages the lifecycle of a single Playwright automation sequence.
    """
    # Fetch and lock state using the exact production model
    application = ClientApplication.objects.get(id=application_id)
    application.status = ClientApplication.ProcessStatus.PROCESSING  # 'PROCESSING'
    application.save()
    
    try:
        with sync_playwright() as p:
            # Instantiate engine passing the live database record reference
            engine = IremboAutomationEngine(booking_record=application)
            
            # Keep headless=False for testing visibility
            engine.initialize_stealth_browser(p, headless=False)
            
            # Map identity fields directly from your production model schema
            engine.navigate_to_booking_form(
                national_id=application.national_id,
                verification_data=application.first_name
            )
            
            billing_id = engine.start_slot_polling()
            print(f"[Worker Thread] Process completed cleanly for ID {application.national_id}. Code: {billing_id}")
            
    except Exception as e:
        print(f"[Worker Thread Error] Execution failed for application {application_id}: {str(e)}")
        application.refresh_from_db()
        if application.status not in [ClientApplication.ProcessStatus.SUCCESS, ClientApplication.ProcessStatus.CANCELED]:
            application.status = ClientApplication.ProcessStatus.FAILED
            application.save()

def dashboard(request):
    """Renders the central monitoring dashboard panel grid."""
    applications = ClientApplication.objects.all().order_by('-created_at')
    return render(request, 'automation/dashboard.html', {'applications': applications})

def start_automation(request, application_id):
    """Spawns an isolated operational thread for a specific target applicant."""
    application = get_object_or_404(ClientApplication, id=application_id)
    
    # Only allow ignition if the process isn't already running or completed
    if application.status in [ClientApplication.ProcessStatus.PENDING, ClientApplication.ProcessStatus.FAILED, ClientApplication.ProcessStatus.CANCELED]:
        worker_thread = threading.Thread(target=run_automation_worker, args=(application.id,))
        worker_thread.daemon = True  # Allows fast, clean server restarts
        worker_thread.start()
        
    return redirect('dashboard')

def submit_otp(request, application_id):
    """Intercepts SMS token from UI form and passes it down to the waiting engine process."""
    if request.method == 'POST':
        application = get_object_or_404(ClientApplication, id=application_id)
        received_otp = request.POST.get('otp_code')
        
        if received_otp:
            application.otp_code = received_otp
            application.status = ClientApplication.ProcessStatus.OTP_PROVIDED  # 'OTP_PROVIDED'
            application.save()  # Step 9 loop catches this change on its next refresh
            
    return redirect('dashboard')

def api_status_feed(request):
    """Asynchronous JSON polling feed utilized by dashboard JavaScript tickers."""
    applications_data = list(ClientApplication.objects.values('id', 'status', 'billing_number'))
    return JsonResponse({'applications': applications_data})
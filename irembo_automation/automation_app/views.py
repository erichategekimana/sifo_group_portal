import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from .models import ClientApplication
from automation_app.automation_engine import IremboAutomationEngine
from playwright.sync_api import sync_playwright

def run_automation_worker(application_id):
    """
    Independent worker executed inside a background thread[cite: 13].
    Manages the lifecycle of a single Playwright automation sequence[cite: 13].
    """
    # Fetch and lock state using the exact production model[cite: 13]
    application = ClientApplication.objects.get(id=application_id)
    application.status = ClientApplication.ProcessStatus.PROCESSING 
    application.save()[cite: 13]
    
    try:
        with sync_playwright() as p:
            # Instantiate engine passing the live database record reference[cite: 13]
            engine = IremboAutomationEngine(booking_record=application)
            
            # Keep headless=False on your Ubuntu ThinkPad for testing visibility[cite: 13].
            engine.initialize_stealth_browser(p, headless=False)
            
            # Map identity fields directly from your production model schema[cite: 13]
            # Service type evaluation is handled internally by the engine via booking_record properties
            engine.navigate_to_booking_form(
                national_id=application.national_id,
                verification_data=application.first_name
            )
            
            # Execute background loop. Toggles into Cooperative Interrupt automatically if slot matches[cite: 13]
            billing_id = engine.start_slot_polling()
            print(f"[Worker Thread] Process completed cleanly for ID {application.national_id}. Code: {billing_id}")
            
    except Exception as e:
        print(f"[Worker Thread Error] Execution failed for application {application_id}: {str(e)}")
        application.refresh_from_db()[cite: 13]
        # Safeguard fallback: Don't overwrite state if it already managed to finish successfully[cite: 13]
        if application.status not in [ClientApplication.ProcessStatus.SUCCESS, ClientApplication.ProcessStatus.CANCELED]:
            application.status = ClientApplication.ProcessStatus.FAILED
            application.save()[cite: 13]

def dashboard(request):
    """Renders the central monitoring dashboard panel grid[cite: 13]."""
    applications = ClientApplication.objects.all().order_by('-created_at')
    return render(request, 'automation/dashboard.html', {'applications': applications})[cite: 13]

def start_automation(request, application_id):
    """Spawns an isolated operational thread for a specific target applicant[cite: 13]."""
    application = get_object_or_404(ClientApplication, id=application_id)
    
    # Only allow ignition if the process isn't already running or completed[cite: 13]
    if application.status in [ClientApplication.ProcessStatus.PENDING, ClientApplication.ProcessStatus.FAILED, ClientApplication.ProcessStatus.CANCELED]:
        worker_thread = threading.Thread(target=run_automation_worker, args=(application.id,))
        worker_thread.daemon = True # Allows fast, clean server restarts[cite: 13]
        worker_thread.start()
        
    return redirect('dashboard')[cite: 13]

def submit_otp(request, application_id):
    """Intercepts SMS token from UI form and passes it down to the waiting engine process[cite: 13]."""
    if request.method == 'POST':
        application = get_object_or_404(ClientApplication, id=application_id)
        received_otp = request.POST.get('otp_code')
        
        if received_otp:
            application.otp_code = received_otp
            application.status = ClientApplication.ProcessStatus.OTP_PROVIDED 
            application.save() # Step 9 loop catches this change on its next refresh[cite: 13]
            
    return redirect('dashboard')[cite: 13]

def api_status_feed(request):
    """Asynchronous JSON polling feed utilized by dashboard JavaScript tickers[cite: 13]."""
    applications_data = list(ClientApplication.objects.values('id', 'status', 'billing_number'))
    return JsonResponse({'applications': applications_data})[cite: 13]
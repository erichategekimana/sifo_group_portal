import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from .models import ClientApplication
from automation_app.automation_engine import IremboAutomationEngine
from automation_app.automation_engine.utils import run_in_db_thread
from playwright.sync_api import sync_playwright  # type: ignore[import]

def run_automation_worker(application_id):
    def _set_processing():
        app = ClientApplication.objects.get(id=application_id)
        app.status = ClientApplication.ProcessStatus.PROCESSING
        app.save(update_fields=["status"])
        return app

    application = run_in_db_thread(_set_processing)

    try:
        with sync_playwright() as p:
            engine = IremboAutomationEngine(booking_record=application)
            engine.initialize_stealth_browser(p, headless=False)
            engine.navigate_to_booking_form(
                national_id=application.national_id,
                verification_data=application.first_name
            )
            billing_id = engine.start_slot_polling()
            print(f"[Worker Thread] Process completed cleanly for ID {application.national_id}. Code: {billing_id}")

    except Exception as e:
        print(f"[Worker Thread Error] Execution failed for application {application_id}: {str(e)}")

        def _mark_failed():
            app = ClientApplication.objects.get(id=application_id)
            if app.status not in [
                ClientApplication.ProcessStatus.SUCCESS,
                ClientApplication.ProcessStatus.CANCELED,
            ]:
                app.status = ClientApplication.ProcessStatus.FAILED
                app.save(update_fields=["status"])

        run_in_db_thread(_mark_failed)

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



def api_status_feed(request):
    """Asynchronous JSON polling feed utilized by dashboard JavaScript tickers."""
    applications_data = list(ClientApplication.objects.values('id', 'status', 'billing_number'))
    return JsonResponse({'applications': applications_data})
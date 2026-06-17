import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Q
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
    
    context = {
        'page_obj': page_obj,
        'applications': page_obj.object_list,
        'query': query,
        'status_filter': status_filter,
        'payment_filter': payment_filter,
        'sort_by': sort_by,
        'status_choices': ClientApplication.ProcessStatus.choices,
        'payment_choices': ClientApplication.PaymentStatus.choices,
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
            app.category = request.POST.get('category', app.category)
            app.payment_status = request.POST.get('payment_status', app.payment_status)
            app.status = request.POST.get('status', app.status)
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
    applications_data = list(ClientApplication.objects.values('id', 'status', 'billing_number'))
    return JsonResponse({'applications': applications_data})

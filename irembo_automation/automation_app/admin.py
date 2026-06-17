import threading
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from .models import ClientApplication
# Direct import of your background thread offloader from views
from .views import run_automation_worker 
from django.contrib.admin import AdminSite
from django.shortcuts import render

class ClientApplicationAdmin(admin.ModelAdmin):
    # -----------------------------------------------------------------------
    # 1. UI Layout & Scannability Configuration
    # -----------------------------------------------------------------------
    # Swapped 'category_or_provisional' for explicit 'category' and 'provisional_number'
    list_display = (
        'colored_status',
        'national_id', 
        'client_full_name', 
        'phone_number', 
        'category', \
        'provisional_number',
        'colored_payment_status',
        'billing_number',
        'created_at'
    )
    
    # Fast filtering sidebar using categories and timeline properties
    list_filter = ('status', 'payment_status', 'category', 'created_at')
    
    # Global text query parameters mapping to your exact database indexes
    search_fields = ('national_id', 'phone_number', 'first_name', 'last_name', 'billing_number', 'provisional_number')
    
    # Security blockages: Protect read-only metadata tracking rows
    readonly_fields = ('created_at', 'updated_at')
    
    # -----------------------------------------------------------------------
    # 2. Custom Control Engine Actions (The Custom Frontend Alternative)
    # -----------------------------------------------------------------------
    actions = ['launch_hunter_engine']

    def launch_hunter_engine(self, request, queryset):
        """
        Operator action to ignite the Playwright thread engine for selected clients directly from the checkbox grid rows.
        """
        activated_threads = 0
        for application in queryset:
            # Respect state machine choices explicitly derived from models.py
            if application.status in [
                ClientApplication.ProcessStatus.PENDING, 
                ClientApplication.ProcessStatus.FAILED, 
                ClientApplication.ProcessStatus.CANCELED
            ]:
                worker_thread = threading.Thread(target=run_automation_worker, args=(application.id,))
                worker_thread.daemon = True
                worker_thread.start()
                activated_threads += 1
                
        if activated_threads > 0:
            self.message_user(
                request, 
                f"🚀 Engine Ignition: Successfully spawned {activated_threads} background automation thread(s).", 
                messages.SUCCESS
            )
        else:
            self.message_user(
                request, 
                "⚠️ Ignition Aborted: None of the selected clients are in a launchable state.", 
                messages.WARNING
            )
            
    launch_hunter_engine.short_description = "🚀 Ignite Playwright Engine for Selected Clients"

    def client_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"
    client_full_name.short_description = "Applicant Name"

    # -----------------------------------------------------------------------
    # 3. Dynamic Visual Rendering Transformers
    # -----------------------------------------------------------------------
    def colored_status(self, obj):
        colors = {
            'PENDING': '#64748b',
            'PROCESSING': '#3b82f6',
            'FINALIZING': '#d97706',
            'SUCCESS': '#10b981',
            'FAILED': '#f43f5e',
            'CANCELED': '#94a3b8',
            'MANUAL_REVIEW_NEEDED': '#f59e0b',
        }
        color = colors.get(obj.status, '#ffffff')
        weight = 'bold' if obj.status in ['FINALIZING', 'SUCCESS'] else 'normal'
        border = 'border: 2px solid #f59e0b; padding: 3px 8px; border-radius: 4px;' if obj.status == 'FINALIZING' else ''

        return format_html(
            '<span style="color: {}; font-weight: {}; text-transform: uppercase; font-size: 0.75rem; {}">{}</span>',
            color, weight, border, obj.get_status_display()
        )
    colored_status.short_description = "Pipeline Status"

    def colored_payment_status(self, obj):
        colors = {'UNPAID': '#f43f5e', 'PAID': '#10b981', 'EXPIRED': '#64748b'}
        return format_html(
            '<span style="color: {}; font-weight: bold; font-size: 0.75rem;">● {}</span>',
            colors.get(obj.payment_status, '#ffffff'), obj.get_payment_status_display()
        )
    colored_payment_status.short_description = "Payment Status"

    # -----------------------------------------------------------------------
    # 4. Form Presentation Layout Architectures
    # -----------------------------------------------------------------------
    fieldsets = (
        ('Personal Identity Credentials (Validated)', {
            'fields': ('first_name', 'last_name', 'national_id', 'birth_date'),
            'description': 'Data inputted below must strictly match the applicant’s official identification document context.'
        }),
        ('Contact Gateway & Target Requirements', {
            'fields': ('phone_number', 'email', 'category', 'provisional_number')
        }),
        ('Automation State Tracking Terminal', {
            'fields': ('status', 'payment_status', 'billing_number', 'application_number'),
            'description': 'Internal state parameters handled directly by the running worker threads.'
        }),
        ('System Timestamps Auditing', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',), 
        }),
    )




class CustomAdminSite(AdminSite):
    site_header = 'Automation Admin'
    site_title = 'Automation Admin Portal'
    index_title = 'Automation Dashboard'

    def index(self, request, extra_context=None):
        apps = ClientApplication.objects.all()
        total = apps.count()
        pending = apps.filter(status='PENDING').count()
        processing = apps.filter(status='PROCESSING').count()
        success = apps.filter(status='SUCCESS').count()
        failed = apps.filter(status='FAILED').count()

        context = {
            'applications': apps.order_by('-created_at')[:50],  # show recent 50
            'total': total,
            'pending': pending,
            'processing': processing,
            'success': success,
            'failed': failed,
            'app_list': self.get_app_list(request),  # keep default admin app list
        }
        context.update(extra_context or {})
        return render(request, 'admin/index.html', context)


custom_admin_site = CustomAdminSite(name='automation_admin')
custom_admin_site.register(ClientApplication, ClientApplicationAdmin)

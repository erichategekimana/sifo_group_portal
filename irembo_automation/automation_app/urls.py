from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('activity-log/', views.activity_log, name='activity_log'),
    path('create/', views.create_application, name='create_application'),
    path('edit/<int:application_id>/', views.edit_application, name='edit_application'),
    path('delete/<int:application_id>/', views.delete_application, name='delete_application'),
    path('details/<int:application_id>/', views.application_details, name='application_details'),
    path('bulk-action/', views.bulk_action, name='bulk_action'),
    path('start/<int:application_id>/', views.start_automation, name='start_automation'),
    path('api/status/', views.api_status_feed, name='api_status_feed'),
    path('api/logs/<int:application_id>/', views.api_application_logs, name='api_application_logs'),
    path('api/respond/<int:application_id>/', views.api_respond_session, name='api_respond_session'),
    path('manage-session/', views.manage_session, name='manage_session'),
    path('api/slot-checker/start/', views.api_start_slot_checker, name='api_start_slot_checker'),
    path('api/slot-checker/stop/', views.api_stop_slot_checker, name='api_stop_slot_checker'),
    path('api/slot-checker/status/', views.api_status_slot_checker, name='api_status_slot_checker'),
    path('api/slot-checker/ack/', views.api_ack_slot_alert, name='api_ack_slot_alert'),
    path('export/', views.export_applications, name='export_applications'),
]


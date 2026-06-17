from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('activity-log/', views.activity_log, name='activity_log'),
    path('create/', views.create_application, name='create_application'),
    path('edit/<int:application_id>/', views.edit_application, name='edit_application'),
    path('delete/<int:application_id>/', views.delete_application, name='delete_application'),
    path('bulk-action/', views.bulk_action, name='bulk_action'),
    path('start/<int:application_id>/', views.start_automation, name='start_automation'),
    path('api/status/', views.api_status_feed, name='api_status_feed'),
]

from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('start/<int:application_id>/', views.start_automation, name='start_automation'),
    path('submit-otp/<int:application_id>/', views.submit_otp, name='submit_otp'),
    path('api/status/', views.api_status_feed, name='api_status_feed'),
]
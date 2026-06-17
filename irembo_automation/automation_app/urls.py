from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('start/<int:application_id>/', views.start_automation, name='start_automation'),
    path('api/status/', views.api_status_feed, name='api_status_feed'),
]
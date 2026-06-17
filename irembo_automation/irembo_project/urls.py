from django.urls import path, include
from automation_app.admin import custom_admin_site

urlpatterns = [
    path('admin/', custom_admin_site.urls),
    path('', include('automation_app.urls')),
]

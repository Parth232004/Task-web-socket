from django.urls import path, include
from django.http import HttpResponse
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from .views import UserViewSet, AvailabilityViewSet, BookingViewSet, suggest_slots_frontend
from pathlib import Path

router = DefaultRouter()
router.register(r'users', UserViewSet)
router.register(r'availabilities', AvailabilityViewSet)
router.register(r'bookings', BookingViewSet)

def calendar_frontend(request):
    """Serve the real-time calendar frontend"""
    frontend_path = Path(__file__).resolve().parent.parent / 'calendar.html'
    with open(frontend_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='text/html')

urlpatterns = [
    path('', include(router.urls)),
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('schema/swagger/', SpectacularSwaggerView.as_view(url_name='scheduler:schema'), name='swagger'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='scheduler:schema'), name='redoc'),
    path('test-ui/', suggest_slots_frontend, name='suggest_slots_frontend'),
    path('calendar/', calendar_frontend, name='calendar_frontend'),
]
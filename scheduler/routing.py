from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Date-specific room: users viewing a particular date's schedule
    re_path(r'ws/slots/(?P<date>\d{4}-\d{2}-\d{2})/$', consumers.CalendarConsumer.as_asgi()),
    # User-specific room: user tracking all their bookings
    re_path(r'ws/user/(?P<user_id>\d+)/$', consumers.CalendarConsumer.as_asgi()),
]

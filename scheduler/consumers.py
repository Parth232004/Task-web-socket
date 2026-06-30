import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import Availability, Booking

User = get_user_model()


class CalendarConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time calendar updates.
    
    Supports two room types:
    1. Date-specific rooms: ws/slots/<date>/?token=<jwt>
       - Users see all bookings for a specific date
    2. User-specific rooms: ws/user/<user_id>/?token=<jwt>
       - Users see all their own bookings across all dates
    
    Events:
    - initial_state: Sent on connect with all current booked slots
    - booking_created: Sent when a new booking is made
    - booking_cancelled: Sent when a booking is cancelled
    """

    async def connect(self):
        # Determine room type from URL pattern
        url_route = self.scope['url_route']['kwargs']
        
        if 'date' in url_route:
            # Date-specific room
            self.date = url_route['date']
            self.room_group_name = f'slots_{self.date}'
            self.room_type = 'date'
        elif 'user_id' in url_route:
            # User-specific room
            self.target_user_id = int(url_route['user_id'])
            self.room_group_name = f'user_{self.target_user_id}'
            self.room_type = 'user'
        else:
            await self.close()
            return

        # Authenticate user via JWT token from query string
        query_string = self.scope.get('query_string', b'').decode()
        token = None
        for param in query_string.split('&'):
            if param.startswith('token='):
                token = param.split('=', 1)[1]
                break

        if not token:
            await self.close()
            return

        user = await self.get_user_from_token(token)
        if not user or not user.is_authenticated:
            await self.close()
            return

        self.scope['user'] = user
        self.user_id = user.id

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial state after connection is accepted
        if self.room_type == 'date':
            await self.send_initial_date_state()
        else:
            await self.send_initial_user_state()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming messages from client"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
            elif message_type == 'request_state':
                # Client can request fresh state
                if self.room_type == 'date':
                    await self.send_initial_date_state()
                else:
                    await self.send_initial_user_state()
        except json.JSONDecodeError:
            pass

    async def send_initial_date_state(self):
        """Send all booked slots for the date when user connects"""
        slots = await self.get_booked_slots_for_date(self.date)
        await self.send(text_data=json.dumps({
            'type': 'initial_state',
            'room_type': 'date',
            'date': self.date,
            'slots': slots
        }))

    async def send_initial_user_state(self):
        """Send all bookings for the user when they connect"""
        bookings = await self.get_bookings_for_user(self.user_id)
        await self.send(text_data=json.dumps({
            'type': 'initial_state',
            'room_type': 'user',
            'user_id': self.user_id,
            'bookings': bookings
        }))

    async def booking_created(self, event):
        """Broadcast new booking to room group"""
        await self.send(text_data=json.dumps({
            'type': 'booking_created',
            'booking': event['booking']
        }))

    async def booking_cancelled(self, event):
        """Broadcast booking cancellation to room group"""
        await self.send(text_data=json.dumps({
            'type': 'booking_cancelled',
            'booking_id': event['booking_id'],
            'date': event.get('date'),
            'start_time': event.get('start_time'),
            'end_time': event.get('end_time'),
        }))

    async def slot_booked(self, event):
        """Legacy event - send slot booking update to room group"""
        await self.send(text_data=json.dumps({
            'type': 'slot_booked',
            'slot': event['slot']
        }))

    async def slot_unbooked(self, event):
        """Legacy event - send slot unbooking update to room group"""
        await self.send(text_data=json.dumps({
            'type': 'slot_unbooked',
            'slot': event['slot']
        }))

    @database_sync_to_async
    def get_user_from_token(self, token):
        """Validate JWT token and return user"""
        from rest_framework_simplejwt.tokens import AccessToken
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except Exception:
            return None

    @database_sync_to_async
    def get_booked_slots_for_date(self, date):
        """Get all booked slots for a given date with booking details"""
        slots = Availability.objects.filter(
            date=date,
            is_booked=True
        ).select_related('booking__booker', 'booking__booked_user', 'user')
        
        result = []
        for slot in slots:
            booking = getattr(slot, 'booking', None)
            result.append({
                'id': slot.id,
                'user_id': slot.user.id,
                'user_email': slot.user.email,
                'user_name': slot.user.get_full_name() or slot.user.email,
                'start_time': slot.start_time.strftime('%H:%M:%S'),
                'end_time': slot.end_time.strftime('%H:%M:%S'),
                'booking_id': booking.id if booking else None,
                'booking_title': booking.title if booking else None,
                'booked_by': booking.booker.email if booking else None,
                'booked_by_name': booking.booker.get_full_name() if booking else None,
                'booked_user': booking.booked_user.email if booking else None,
                'description': booking.description if booking else None,
            })
        return result

    @database_sync_to_async
    def get_bookings_for_user(self, user_id):
        """Get all bookings for a specific user (as booker or booked_user)"""
        bookings = Booking.objects.filter(
            Q(booker_id=user_id) | Q(booked_user_id=user_id)
        ).select_related('booker', 'booked_user', 'availability').order_by('-created_at')
        
        result = []
        for booking in bookings:
            result.append({
                'id': booking.id,
                'title': booking.title,
                'description': booking.description,
                'date': booking.availability.date.isoformat(),
                'start_time': booking.availability.start_time.strftime('%H:%M:%S'),
                'end_time': booking.availability.end_time.strftime('%H:%M:%S'),
                'booker_id': booking.booker.id,
                'booker_email': booking.booker.email,
                'booker_name': booking.booker.get_full_name() or booking.booker.email,
                'booked_user_id': booking.booked_user.id,
                'booked_user_email': booking.booked_user.email,
                'booked_user_name': booking.booked_user.get_full_name() or booking.booked_user.email,
                'created_at': booking.created_at.isoformat(),
            })
        return result

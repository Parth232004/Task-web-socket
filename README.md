# Django Calendar Clone API

A Django-based calendar clone API for slot booking with working hours and meeting schedule support.

## Features

- User working hours configuration (default: 9:00-17:00)
- Meeting schedule slots (e.g., 10:00-15:00)
- Slot availability checking
- Next-day slot suggestions when all slots are booked
- Booking system for users

## API Endpoints

### Users
- `GET /api/users/` - List all users
- `GET /api/users/{id}/` - Get user details

### Availabilities
- `GET /api/availabilities/` - List all availability slots
- `GET /api/availabilities/available_slots/?user_id={id}&date={date}` - Get available slots for a user on a specific date
- `GET /api/availabilities/suggest_slots/?user_id={id}&date={date}&duration={hours}` - Suggest available slots (includes next day if today is fully booked)

### Bookings
- `GET /api/bookings/` - List all bookings
- `POST /api/bookings/` - Create a booking
  - Required fields: `booked_user`, `date`, `start_time`, `end_time`
  - Optional fields: `booker`, `title`, `description`

## Example Usage

### 1. Get available slots for user1 (working 9-5, meeting 10-3)
```bash
curl http://localhost:8000/api/availabilities/available_slots/?user_id=1
```

Response shows:
- 09:00-10:00: available
- 10:00-15:00: not available (meeting)
- 15:00-17:00: available

### 2. Suggest slots (with next-day fallback)
```bash
curl http://localhost:8000/api/availabilities/suggest_slots/?user_id=1&duration=1
```

### 3. Create a booking
```bash
curl -X POST http://localhost:8000/api/bookings/ \
  -H "Content-Type: application/json" \
  -d '{"booked_user": 1, "date": "2026-06-30", "start_time": "09:00:00", "end_time": "10:00:00", "title": "Morning meeting"}'
```

## Setup

1. Create virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install django djangorestframework
```

2. Run migrations:
```bash
python manage.py migrate
```

3. Create sample data:
```bash
python manage.py create_sample_data
```

4. Run the server:
```bash
python manage.py runserver
```

## Models

- `UserProfile` - Extends User with working hours
- `Availability` - Time slots for users (can be booked or free)
- `Booking` - Booking made by one user with another user
import sys
from datetime import datetime
from threading import Semaphore
from typing import Any

from EventKit import (
    EKAlarm,  # type: ignore
    EKCalendar,  # type: ignore
    EKEntityTypeEvent,  # type: ignore
    EKEntityTypeReminder,  # type: ignore
    EKEvent,  # type: ignore
    EKEventStore,  # type: ignore
    EKReminder,  # type: ignore
    EKSpanFutureEvents,  # type: ignore
    EKSpanThisEvent,  # type: ignore
)
from loguru import logger

from .models import (
    CreateEventRequest,
    CreateReminderRequest,
    Event,
    Reminder,
    UpdateEventRequest,
    UpdateReminderRequest,
)

logger.remove()
logger.add(
    sys.stderr,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
)


class CalendarManager:
    def __init__(self):
        self.event_store = EKEventStore.alloc().init()

        # Force a fresh permission check for events
        auth_status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)
        logger.debug(f"Initial Calendar authorization status: {auth_status}")

        # Always request access regardless of current status
        if not self._request_access(EKEntityTypeEvent):
            logger.error("Calendar access request failed")
            raise ValueError(
                "Calendar access not granted. Please check System Settings > Privacy & Security > Calendar."
            )
        logger.info("Calendar access granted successfully")

        # Also request access to reminders
        reminder_auth_status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeReminder)
        logger.debug(f"Initial Reminders authorization status: {reminder_auth_status}")

        if not self._request_access(EKEntityTypeReminder):
            logger.warning("Reminders access not granted. Reminder functionality will be limited.")
        else:
            logger.info("Reminders access granted successfully")

    def list_events(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_name: str | None = None,
    ) -> list[Event]:
        """List all events within a given date range

        Args:
            start_time: The start time of the date range
            end_time: The end time of the date range
            calendar_name: The name of the calendar to filter by

        Returns:
            list[Event]: A list of events within the date range
        """
        # only list events in a particular calendar if specified, otherwise search across all calendars
        calendar = self._find_calendar_by_name(calendar_name) if calendar_name else None
        if calendar_name and not calendar:
            raise NoSuchCalendarException(calendar_name)

        calendars = [calendar] if calendar else None

        logger.info(
            f"Listing events between {start_time} - {end_time}, searching in: {calendar_name if calendar_name else 'all calendars'}"
        )

        predicate = self.event_store.predicateForEventsWithStartDate_endDate_calendars_(start_time, end_time, calendars)

        events = self.event_store.eventsMatchingPredicate_(predicate)
        return [Event.from_ekevent(event) for event in events]

    def create_event(self, new_event: CreateEventRequest) -> Event:
        """Create a new calendar event

        Args:
            new_event: The event to create

        Returns:
            Event | None: The created event with identifier if successful, None if failed
        """
        ekevent = EKEvent.eventWithEventStore_(self.event_store)

        ekevent.setTitle_(new_event.title)
        ekevent.setStartDate_(new_event.start_time)
        ekevent.setEndDate_(new_event.end_time)

        if new_event.notes:
            ekevent.setNotes_(new_event.notes)
        if new_event.location:
            ekevent.setLocation_(new_event.location)
        if new_event.url:
            ekevent.setURL_(new_event.url)
        if new_event.all_day:
            ekevent.setAllDay_(new_event.all_day)

        if new_event.alarms_minutes_offsets:
            for minutes in new_event.alarms_minutes_offsets:
                # actual_minutes = minutes + (9 * 60) if new_event.all_day else minutes
                alarm = EKAlarm.alarmWithRelativeOffset_(-60 * minutes)
                ekevent.addAlarm_(alarm)

        if new_event.recurrence_rule:
            ekevent.setRecurrenceRule_(new_event.recurrence_rule.to_ek_recurrence())

        if new_event.calendar_name:
            calendar = self._find_calendar_by_name(new_event.calendar_name)
            if not calendar:
                logger.error(
                    f"Failed to create event: The specified calendar '{new_event.calendar_name}' does not exist."
                )
                raise NoSuchCalendarException(new_event.calendar_name)
        else:
            calendar = self.event_store.defaultCalendarForNewEvents()
            logger.debug(f"Using default calendar, {calendar}, for new event")

        ekevent.setCalendar_(calendar)

        try:
            success, error = self.event_store.saveEvent_span_error_(ekevent, EKSpanThisEvent, None)

            if not success:
                logger.error(f"Failed to save event: {error}")
                raise Exception(error)

            logger.info(f"Successfully created event: {new_event.title}")
            return Event.from_ekevent(ekevent)

        except Exception as e:
            logger.exception(e)
            raise

    def update_event(self, event_id: str, request: UpdateEventRequest) -> Event:
        """Update an existing event by its identifier

        Args:
            event_id: The unique identifier of the event to update
            request: The update request containing the fields to modify

        Returns:
            Event | None: The updated event if successful, None if failed
        """
        existing_event = self.find_event_by_id(event_id)
        if not existing_event:
            raise NoSuchEventException(event_id)

        existing_ek_event = existing_event._raw_event
        if not existing_ek_event:
            raise NoSuchEventException(event_id)

        if request.title is not None:
            existing_ek_event.setTitle_(request.title)
        if request.start_time is not None:
            existing_ek_event.setStartDate_(request.start_time)
        if request.end_time is not None:
            existing_ek_event.setEndDate_(request.end_time)
        if request.location is not None:
            existing_ek_event.setLocation_(request.location)
        if request.notes is not None:
            existing_ek_event.setNotes_(request.notes)
        if request.url is not None:
            existing_ek_event.setURL_(request.url)
        if request.all_day is not None:
            existing_ek_event.setAllDay_(request.all_day)

        # Update calendar if specified
        if request.calendar_name:
            calendar = self._find_calendar_by_name(request.calendar_name)
            if calendar:
                existing_ek_event.setCalendar_(calendar)
            else:
                raise NoSuchCalendarException(request.calendar_name)

        # Update recurrence rule
        if request.recurrence_rule is not None:
            existing_ek_event.setRecurrenceRule_(request.recurrence_rule.to_ek_recurrence())

        # Update alarms if specified
        if request.alarms_minutes_offsets is not None:
            alarms = []
            for minutes in request.alarms_minutes_offsets:
                # For all-day events EK considers start of day as reference point for alarms, so subtract one day
                actual_minutes = minutes - 1440 if request.all_day else minutes
                alarm = EKAlarm.alarmWithRelativeOffset_(-60 * actual_minutes)  # Convert to seconds
                alarms.append(alarm)
            existing_ek_event.setAlarms_(alarms)

        try:
            # Use EKSpanFutureEvents to update all future events in the case the event is a recurring one
            success, error = self.event_store.saveEvent_span_error_(existing_ek_event, EKSpanFutureEvents, None)

            if not success:
                logger.error(f"Failed to update event: {error}")
                raise Exception(error)

            logger.info(f"Successfully updated event: {request.title or existing_event.title}")
            return Event.from_ekevent(existing_ek_event)

        except Exception as e:
            logger.error(f"Failed to update event: {e}")
            raise

    def delete_event(self, event_id: str) -> bool:
        """Delete an event by its identifier

        Args:
            event_id: The unique identifier of the event to delete

        Returns:
            bool: True if deletion was successful, False otherwise

        Raises:
            NoSuchEventException: If the event with the given ID doesn't exist
            Exception: If there was an error deleting the event
        """
        existing_event = self.find_event_by_id(event_id)
        if not existing_event:
            raise NoSuchEventException(event_id)

        existing_ek_event = existing_event._raw_event
        if not existing_ek_event:
            raise NoSuchEventException(event_id)

        try:
            success, error = self.event_store.removeEvent_span_error_(existing_ek_event, EKSpanFutureEvents, None)

            if not success:
                logger.error(f"Failed to delete event: {error}")
                raise Exception(error)

            logger.info(f"Successfully deleted event: {existing_event.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete event: {e}")
            raise

    def find_event_by_id(self, identifier: str) -> Event | None:
        """Find an event by its identifier

        Args:
            identifier: The unique identifier of the event

        Returns:
            Event | None: The event if found, None otherwise
        """
        ekevent = self.event_store.eventWithIdentifier_(identifier)
        if not ekevent:
            logger.info(f"No event found with ID: {identifier}")
            return None

        return Event.from_ekevent(ekevent)

    def list_calendar_names(self) -> list[str]:
        """List all available calendar names

        Returns:
            list[str]: A list of calendar names
        """
        calendars = self.event_store.calendars()
        return [calendar.title() for calendar in calendars]

    def list_calendars(self) -> list[Any]:
        """List all available calendars

        Returns:
            list[Any]: A list of EK calendar objects
        """
        return self.event_store.calendars()

    def _request_access(self, entity_type: int) -> bool:
        """Request access to interact with the MacOS calendar or reminders"""
        semaphore = Semaphore(0)
        access_granted = False

        def completion(granted: bool, error) -> None:
            nonlocal access_granted
            access_granted = granted
            semaphore.release()

        self.event_store.requestAccessToEntityType_completion_(entity_type, completion)
        semaphore.acquire()
        return access_granted

    def _find_calendar_by_id(self, calendar_id: str) -> Any | None:
        """Find a calendar by ID. Returns None if not found.

        Args:
            calendar_id: The ID of the calendar to find

        Returns:
            Any | None: The calendar if found, None otherwise
        """

        for calendar in self.event_store.calendars():
            if calendar.uniqueIdentifier() == calendar_id:
                return calendar

        logger.info(f"Calendar '{calendar_id}' not found")
        return None

    def _find_calendar_by_name(self, calendar_name: str) -> Any | None:
        """Find a calendar by name. Returns None if not found.

        Args:
            calendar_name: The name of the calendar to find

        Returns:
            Any | None: The calendar if found, None otherwise
        """

        for calendar in self.event_store.calendars():
            if calendar.title() == calendar_name:
                return calendar

        logger.info(f"Calendar '{calendar_name}' not found")
        return None

    def _find_reminder_list_by_name(self, list_name: str) -> Any | None:
        """Find a reminder list by name. Returns None if not found.

        Args:
            list_name: The name of the reminder list to find

        Returns:
            Any | None: The reminder list if found, None otherwise
        """
        for calendar in self.event_store.calendarsForEntityType_(EKEntityTypeReminder):
            if calendar.title() == list_name:
                return calendar

        logger.info(f"Reminder list '{list_name}' not found")
        return None

    def _create_calendar(self, calendar_name: str, source_name: str = "iCloud") -> Any | None:
        """Create a new calendar with the specified name.

        Args:
            calendar_name: The name for the new calendar
            source_type: The type of source to use (2=Exchange, 4=MobileMe/iCloud, 5=Subscribed).
                        If None, uses the first available source.

        Returns:
            Any | None: The created calendar if successful, None if failed

        Raises:
            Exception: If there was an error creating the calendar or no matching source found
        """
        logger.info(f"Creating new calendar: {calendar_name}")

        # Create new calendar for events
        new_calendar = EKCalendar.calendarForEntityType_eventStore_(EKEntityTypeEvent, self.event_store)
        new_calendar.setTitle_(calendar_name)

        # Set calendar source based on source_type
        sources = self.event_store.sources()
        selected_source = None

        for source in sources:
            if source.title() == source_name and source.supportsCalendarCreation():
                logger.info(f"Using source: {source.title()} (type: {source.sourceType()})")
                selected_source = source
                break

        if not selected_source:
            available_sources = [(s.title(), s.sourceType()) for s in sources if source.supportsCalendarCreation()]
            error_msg = f"No source found matching title {source_name}. Available sources: {available_sources}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        new_calendar.setSource_(selected_source)

        try:
            success, error = self.event_store.saveCalendar_commit_error_(new_calendar, True, None)

            if not success:
                logger.error(f"Failed to create calendar: {error}")
                raise Exception(error)

            logger.info(f"Successfully created calendar: {calendar_name}")
            return new_calendar

        except Exception as e:
            logger.exception(f"Error creating calendar: {e}")
            raise

    def _delete_calendar(self, calendar_id: str) -> bool:
        """Delete a calendar by its name with extra verification."""
        logger.info(f"Attempting to delete calendar with ID: {calendar_id}")

        calendar = self._find_calendar_by_id(calendar_id)
        if not calendar:
            raise NoSuchCalendarException(calendar_id)

        try:
            # Try deletion with explicit commit
            success, error = self.event_store.removeCalendar_commit_error_(calendar, True, None)

            if not success:
                logger.error(f"Failed to delete calendar: {error}")
                raise Exception(error)

            # Verify deletion
            remaining_calendars = self.list_calendar_names()
            if calendar_id in remaining_calendars:
                logger.error(f"Calendar {calendar_id} still exists after deletion!")
                raise Exception(f"Calendar {calendar_id} was not properly deleted")

            logger.info(f"Successfully deleted calendar: {calendar_id}")
            return True

        except Exception as e:
            logger.exception(f"Error deleting calendar: {e}")
            raise

    # Reminder methods

    def list_reminders(
        self,
        list_name: str | None = None,
        completed: bool | None = None,
    ) -> list[Reminder]:
        """List reminders with optional filtering.

        Args:
            list_name: Optional reminder list name to filter by
            completed: Optional completion status filter (True/False/None for all)

        Returns:
            list[Reminder]: A list of reminders matching the criteria
        """
        logger.info(f"Listing reminders in list: {list_name if list_name else 'all lists'}, completed: {completed}")

        # Get all reminder calendars
        calendars = self.event_store.calendarsForEntityType_(EKEntityTypeReminder)
        
        if list_name:
            calendar = self._find_reminder_list_by_name(list_name)
            if not calendar:
                raise NoSuchCalendarException(list_name)
            calendars = [calendar]

        all_reminders = []
        for calendar in calendars:
            predicate = self.event_store.predicateForRemindersInCalendars_([calendar])
            
            # Use semaphore to wait for async completion
            semaphore = Semaphore(0)
            found_reminders = []

            def completion_handler(reminders):
                nonlocal found_reminders
                if reminders:
                    found_reminders.extend(reminders)
                semaphore.release()

            self.event_store.fetchRemindersMatchingPredicate_completion_(predicate, completion_handler)
            semaphore.acquire()
            
            all_reminders.extend(found_reminders)

        # Filter by completion status if specified
        if completed is not None:
            all_reminders = [r for r in all_reminders if r.isCompleted() == completed]

        return [Reminder.from_ekreminder(reminder) for reminder in all_reminders]

    def create_reminder(self, new_reminder: CreateReminderRequest) -> Reminder:
        """Create a new reminder.

        Args:
            new_reminder: The reminder to create

        Returns:
            Reminder: The created reminder with identifier if successful

        Raises:
            NoSuchCalendarException: If the specified list doesn't exist
            Exception: If there was an error creating the reminder
        """
        ekreminder = EKReminder.reminderWithEventStore_(self.event_store)

        ekreminder.setTitle_(new_reminder.title)

        if new_reminder.notes:
            ekreminder.setNotes_(new_reminder.notes)
        if new_reminder.url:
            ekreminder.setURL_(new_reminder.url)
        if new_reminder.priority:
            ekreminder.setPriority_(new_reminder.priority.value)

        if new_reminder.due_date:
            from Foundation import NSCalendar, NSDateComponents
            try:
                # Try modern approach first (macOS 10.10+)
                from Foundation import NSCalendarUnitYear, NSCalendarUnitMonth, NSCalendarUnitDay, NSCalendarUnitHour, NSCalendarUnitMinute
                calendar = NSCalendar.currentCalendar()
                components = calendar.components_fromDate_(
                    NSCalendarUnitYear | NSCalendarUnitMonth | NSCalendarUnitDay | NSCalendarUnitHour | NSCalendarUnitMinute,
                    new_reminder.due_date
                )
            except ImportError:
                # Fallback to older constants
                calendar = NSCalendar.currentCalendar()
                components = calendar.components_fromDate_(
                    0x4 | 0x8 | 0x10 | 0x20 | 0x40,  # Year | Month | Day | Hour | Minute
                    new_reminder.due_date
                )
            ekreminder.setDueDateComponents_(components)

        if new_reminder.alarms_minutes_offsets:
            for minutes in new_reminder.alarms_minutes_offsets:
                alarm = EKAlarm.alarmWithRelativeOffset_(-60 * minutes)
                ekreminder.addAlarm_(alarm)

        if new_reminder.recurrence_rule:
            # EKReminder uses addRecurrenceRule instead of setRecurrenceRule
            ekreminder.addRecurrenceRule_(new_reminder.recurrence_rule.to_ek_recurrence())

        # Find the calendar/list to add the reminder to
        if new_reminder.list_name:
            calendar = self._find_reminder_list_by_name(new_reminder.list_name)
            if not calendar:
                logger.error(f"Failed to create reminder: The specified list '{new_reminder.list_name}' does not exist.")
                raise NoSuchCalendarException(new_reminder.list_name)
        else:
            # Use default reminders calendar
            calendar = self.event_store.defaultCalendarForNewReminders()
            logger.debug(f"Using default reminder list: {calendar.title()}")

        ekreminder.setCalendar_(calendar)

        try:
            success, error = self.event_store.saveReminder_commit_error_(ekreminder, True, None)

            if not success:
                logger.error(f"Failed to save reminder: {error}")
                raise Exception(error)

            logger.info(f"Successfully created reminder: {new_reminder.title}")
            return Reminder.from_ekreminder(ekreminder)

        except Exception as e:
            logger.exception(e)
            raise

    def update_reminder(self, reminder_id: str, request: UpdateReminderRequest) -> Reminder:
        """Update an existing reminder by its identifier.

        Args:
            reminder_id: The unique identifier of the reminder to update
            request: The update request containing the fields to modify

        Returns:
            Reminder: The updated reminder if successful

        Raises:
            NoSuchReminderException: If the reminder doesn't exist
            NoSuchCalendarException: If the specified list doesn't exist
            Exception: If there was an error updating the reminder
        """
        existing_reminder = self.find_reminder_by_id(reminder_id)
        if not existing_reminder:
            raise NoSuchReminderException(reminder_id)

        existing_ek_reminder = existing_reminder._raw_reminder
        if not existing_ek_reminder:
            raise NoSuchReminderException(reminder_id)

        if request.title is not None:
            existing_ek_reminder.setTitle_(request.title)
        if request.notes is not None:
            existing_ek_reminder.setNotes_(request.notes)
        if request.url is not None:
            existing_ek_reminder.setURL_(request.url)
        if request.priority is not None:
            existing_ek_reminder.setPriority_(request.priority.value)
        if request.is_completed is not None:
            existing_ek_reminder.setCompleted_(request.is_completed)

        if request.due_date is not None:
            from Foundation import NSCalendar, NSDateComponents
            try:
                # Try modern approach first (macOS 10.10+)
                from Foundation import NSCalendarUnitYear, NSCalendarUnitMonth, NSCalendarUnitDay, NSCalendarUnitHour, NSCalendarUnitMinute
                calendar = NSCalendar.currentCalendar()
                components = calendar.components_fromDate_(
                    NSCalendarUnitYear | NSCalendarUnitMonth | NSCalendarUnitDay | NSCalendarUnitHour | NSCalendarUnitMinute,
                    request.due_date
                )
            except ImportError:
                # Fallback to older constants
                calendar = NSCalendar.currentCalendar()
                components = calendar.components_fromDate_(
                    0x4 | 0x8 | 0x10 | 0x20 | 0x40,  # Year | Month | Day | Hour | Minute
                    request.due_date
                )
            existing_ek_reminder.setDueDateComponents_(components)

        # Update list if specified
        if request.list_name:
            calendar = self._find_reminder_list_by_name(request.list_name)
            if calendar:
                existing_ek_reminder.setCalendar_(calendar)
            else:
                raise NoSuchCalendarException(request.list_name)

        # Update recurrence rule
        if request.recurrence_rule is not None:
            # First remove existing recurrence rules, then add the new one
            if hasattr(existing_ek_reminder, 'recurrenceRules') and existing_ek_reminder.recurrenceRules():
                for rule in existing_ek_reminder.recurrenceRules():
                    existing_ek_reminder.removeRecurrenceRule_(rule)
            # Add new recurrence rule
            existing_ek_reminder.addRecurrenceRule_(request.recurrence_rule.to_ek_recurrence())

        # Update alarms if specified
        if request.alarms_minutes_offsets is not None:
            alarms = []
            for minutes in request.alarms_minutes_offsets:
                alarm = EKAlarm.alarmWithRelativeOffset_(-60 * minutes)
                alarms.append(alarm)
            existing_ek_reminder.setAlarms_(alarms)

        try:
            success, error = self.event_store.saveReminder_commit_error_(existing_ek_reminder, True, None)

            if not success:
                logger.error(f"Failed to update reminder: {error}")
                raise Exception(error)

            logger.info(f"Successfully updated reminder: {request.title or existing_reminder.title}")
            return Reminder.from_ekreminder(existing_ek_reminder)

        except Exception as e:
            logger.error(f"Failed to update reminder: {e}")
            raise

    def delete_reminder(self, reminder_id: str) -> bool:
        """Delete a reminder by its identifier.

        Args:
            reminder_id: The unique identifier of the reminder to delete

        Returns:
            bool: True if deletion was successful, False otherwise

        Raises:
            NoSuchReminderException: If the reminder with the given ID doesn't exist
            Exception: If there was an error deleting the reminder
        """
        existing_reminder = self.find_reminder_by_id(reminder_id)
        if not existing_reminder:
            raise NoSuchReminderException(reminder_id)

        existing_ek_reminder = existing_reminder._raw_reminder
        if not existing_ek_reminder:
            raise NoSuchReminderException(reminder_id)

        try:
            success, error = self.event_store.removeReminder_commit_error_(existing_ek_reminder, True, None)

            if not success:
                logger.error(f"Failed to delete reminder: {error}")
                raise Exception(error)

            logger.info(f"Successfully deleted reminder: {existing_reminder.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete reminder: {e}")
            raise

    def find_reminder_by_id(self, identifier: str) -> Reminder | None:
        """Find a reminder by its identifier.

        Args:
            identifier: The unique identifier of the reminder

        Returns:
            Reminder | None: The reminder if found, None otherwise
        """
        # EventKit doesn't have a direct method to get reminder by ID like events
        # We need to search through all reminders
        all_reminders = self.list_reminders()
        for reminder in all_reminders:
            if reminder.identifier == identifier:
                return reminder
        
        logger.info(f"No reminder found with ID: {identifier}")
        return None

    def list_reminder_lists(self) -> list[str]:
        """List all available reminder list names.

        Returns:
            list[str]: A list of reminder list names
        """
        calendars = self.event_store.calendarsForEntityType_(EKEntityTypeReminder)
        return [calendar.title() for calendar in calendars]


class NoSuchCalendarException(Exception):
    def __init__(self, calendar_name: str):
        super().__init__(f"Calendar: {calendar_name} does not exist")


class NoSuchEventException(Exception):
    def __init__(self, event_id: str):
        super().__init__(f"Event with id: {event_id} does not exist")


class NoSuchReminderException(Exception):
    def __init__(self, reminder_id: str):
        super().__init__(f"Reminder with id: {reminder_id} does not exist")

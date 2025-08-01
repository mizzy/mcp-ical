import sys
from datetime import datetime
from functools import lru_cache
from textwrap import dedent

from loguru import logger
from mcp.server.fastmcp import FastMCP

from .ical import CalendarManager
from .models import CreateEventRequest, CreateReminderRequest, UpdateEventRequest, UpdateReminderRequest

mcp = FastMCP("Calendar")

logger.remove()
logger.add(
    sys.stderr,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
)


# Initialize the CalendarManager on demand in order to only request calendar permission
# when a calendar tool is invoked instead of on the launch of the Claude Desktop app.
@lru_cache(maxsize=None)
def get_calendar_manager() -> CalendarManager:
    """Get or initialize the calendar manager with proper error handling."""
    try:
        return CalendarManager()
    except ValueError as e:
        error_msg = dedent("""\
        Calendar access is not granted. Please follow these steps:

        1. Open System Preferences/Settings
        2. Go to Privacy & Security > Calendar
        3. Check the box next to your terminal application or Claude Desktop
        4. Restart Claude Desktop

        Once you've granted access, try your calendar operation again.
        """)
        raise ValueError(error_msg) from e


@mcp.resource("calendars://list")
def get_calendars() -> str:
    """List all available calendars that can be used with calendar operations."""
    try:
        manager = get_calendar_manager()
        calendars = manager.list_calendar_names()
        if not calendars:
            return "No calendars found"
        return "Available calendars:\n" + "\n".join(f"- {cal}" for cal in calendars)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error listing calendars: {str(e)}"


@mcp.resource("reminders://lists")
def get_reminder_lists() -> str:
    """List all available reminder lists that can be used with reminder operations."""
    try:
        manager = get_calendar_manager()
        lists = manager.list_reminder_lists()
        if not lists:
            return "No reminder lists found"
        return "Available reminder lists:\n" + "\n".join(f"- {list_name}" for list_name in lists)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Error listing reminder lists: {str(e)}"


@mcp.tool()
async def list_calendars() -> str:
    """List all available calendars."""
    try:
        manager = get_calendar_manager()
        calendars = manager.list_calendar_names()
        if not calendars:
            return "No calendars found"

        return "Available calendars:\n" + "\n".join(f"- {calendar}" for calendar in calendars)

    except Exception as e:
        return f"Error listing calendars: {str(e)}"


@mcp.tool()
async def list_events(start_date: datetime, end_date: datetime, calendar_name: str | None = None) -> str:
    """List calendar events in a date range.

    The start_date should always use the time such that it represents the beginning of that day (00:00:00).
    The end_date should always use the time such that it represents the end of that day (23:59:59).
    This way, range based searches are always inclusive and can locate all events in that date range.

    Args:
        start_date: Start date in ISO8601 format (YYYY-MM-DDT00:00:00).
        end_date: Optional end date in ISO8601 format (YYYY-MM-DDT23:59:59).
        calendar_name: Optional calendar name to filter by
    """
    try:
        manager = get_calendar_manager()
        events = manager.list_events(start_date, end_date, calendar_name)
        if not events:
            return "No events found in the specified date range"

        return "".join([str(event) for event in events])

    except Exception as e:
        return f"Error listing events: {str(e)}"


@mcp.tool()
async def create_event(create_event_request: CreateEventRequest) -> str:
    """Create a new calendar event.

    Before using this tool, make sure to:
    1. Ask the user which calendar they want to use if not specified (check calendars://list)
    2. Ask if they want to add a location if none provided
    3. Ask if they want to add any notes/description if none provided
    4. Confirm the date and time with the user
    5. Ask if they want to set reminders for the event

    Args:
        title: Event title
        start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS)
        end_time: End time in ISO format (YYYY-MM-DDTHH:MM:SS)
        notes: Optional event notes/description. Ask user if they want to add notes.
        location: Optional event location. Ask user if they want to specify a location.
        calendar_name: Optional calendar name. Ask user which calendar to use, referencing calendars://list.
        all_day: Whether this is an all-day event
        reminder_offsets: List of minutes before the event to trigger reminders\
            e.g. [60, 1440] means two reminders, the first 24 hours before the event and the second one hour before.
        recurrence_rule: Optional recurrence rule for the event. This should be an instance of `RecurrenceRule` with the following fields:
            - frequency: Frequency of the recurrence (e.g., DAILY, WEEKLY, MONTHLY, YEARLY).
            - interval: Interval between recurrences (e.g., every 2 weeks).
            - end_date: Optional end date for the recurrence. If specified, the recurrence will stop on this date.
            - occurrence_count: Optional number of occurrences. If specified, the recurrence will stop after this many occurrences.
            - days_of_week: Optional list of weekdays for the event. Use integers to represent days:
                - Sunday: 1
                - Monday: 2
                - Tuesday: 3
                - Wednesday: 4
                - Thursday: 5
                - Friday: 6
                - Saturday: 7

    Note: Both `end_date` and `occurrence_count` should not be set simultaneously; choose one or the other, or leave both unset.
    """
    logger.info(f"Incoming Create Event Request: {create_event_request}")
    try:
        manager = get_calendar_manager()

        event = manager.create_event(create_event_request)
        if not event:
            return "Failed to create event. Please check calendar permissions and try again."

        return f"Successfully created event: {event.title} (ID: {event.identifier})"

    except Exception as e:
        return f"Error creating event: {str(e)}"


@mcp.tool()
async def update_event(event_id: str, update_event_request: UpdateEventRequest) -> str:
    """Update an existing calendar event.

    Before using this tool, make sure to:
    1. Ask the user which fields they want to update
    2. If moving to a different calendar, verify the calendar exists using calendars://list
    3. If updating time, confirm the new time with the user
    4. Ask if they want to add/update location if not specified
    5. Ask if they want to add/update notes if not specified
    6. Ask if they want to set reminders for the event

    Args:
        event_id: Unique identifier of the event to update
        title: Optional new title
        start_time: Optional new start time in ISO format
        end_time: Optional new end time in ISO format
        notes: Optional new notes/description. Ask user if they want to update notes.
        location: Optional new location. Ask user if they want to specify/update location.
        calendar_name: Optional new calendar. Ask user which calendar to use, referencing calendars://list.
        all_day: Optional all-day flag
        reminder_offsets: List of minutes before the event to trigger reminders\
            e.g. [60, 1440] means two reminders, the first 24 hours before the event and the second one hour before.
        recurrence_rule: Optional recurrence rule for the event. This should be an instance of `RecurrenceRule` with the following fields:
            - frequency: Frequency of the recurrence (e.g., DAILY, WEEKLY, MONTHLY, YEARLY).
            - interval: Interval between recurrences (e.g., every 2 weeks).
            - end_date: Optional end date for the recurrence. If specified, the recurrence will stop on this date.
            - occurrence_count: Optional number of occurrences. If specified, the recurrence will stop after this many occurrences.
            - days_of_week: Optional list of weekdays for the event. Use integers to represent days:
                - Sunday: 1
                - Monday: 2
                - Tuesday: 3
                - Wednesday: 4
                - Thursday: 5
                - Friday: 6
                - Saturday: 7

    Note: Both `end_date` and `occurrence_count` should not be set simultaneously; choose one or the other, or leave both unset.
    """
    try:
        manager = get_calendar_manager()
        event = manager.update_event(event_id, update_event_request)
        if not event:
            return f"Failed to update event. Event with ID {event_id} not found or update failed."

        return f"Successfully updated event: {event.title}"

    except Exception as e:
        return f"Error updating event: {str(e)}"


@mcp.tool()
async def list_reminder_lists() -> str:
    """List all available reminder lists."""
    try:
        manager = get_calendar_manager()
        lists = manager.list_reminder_lists()
        if not lists:
            return "No reminder lists found"

        return "Available reminder lists:\n" + "\n".join(f"- {list_name}" for list_name in lists)

    except Exception as e:
        return f"Error listing reminder lists: {str(e)}"


@mcp.tool()
async def list_reminders(list_name: str | None = None, completed: bool | None = None) -> str:
    """List reminders with optional filtering.

    Args:
        list_name: Optional reminder list name to filter by
        completed: Optional completion status filter (True for completed, False for pending, None for all)
    """
    try:
        manager = get_calendar_manager()
        reminders = manager.list_reminders(list_name, completed)
        if not reminders:
            status_filter = " completed" if completed is True else " pending" if completed is False else ""
            list_filter = f" in '{list_name}'" if list_name else ""
            return f"No{status_filter} reminders found{list_filter}"

        return "".join([str(reminder) for reminder in reminders])

    except Exception as e:
        return f"Error listing reminders: {str(e)}"


@mcp.tool()
async def create_reminder(create_reminder_request: CreateReminderRequest) -> str:
    """Create a new reminder.

    Before using this tool, make sure to:
    1. Ask the user which reminder list they want to use if not specified (check reminders://lists)
    2. Ask if they want to set a due date if none provided
    3. Ask if they want to add any notes/description if none provided
    4. Ask if they want to set a priority level (HIGH, MEDIUM, LOW, or NONE)
    5. Ask if they want to set reminders/alarms for the item

    Args:
        title: Reminder title
        list_name: Optional reminder list name. Ask user which list to use, referencing reminders://lists.
        due_date: Optional due date in ISO format (YYYY-MM-DDTHH:MM:SS)
        notes: Optional reminder notes/description. Ask user if they want to add notes.
        priority: Optional priority level (HIGH=1, MEDIUM=5, LOW=9, NONE=0). Defaults to NONE.
        url: Optional URL associated with the reminder
        alarms_minutes_offsets: List of minutes before the due date to trigger reminders
            e.g. [60, 1440] means two reminders, the first 24 hours before due date and the second one hour before.
        recurrence_rule: Optional recurrence rule for the reminder. This should be an instance of `RecurrenceRule` with the following fields:
            - frequency: Frequency of the recurrence (e.g., DAILY, WEEKLY, MONTHLY, YEARLY).
            - interval: Interval between recurrences (e.g., every 2 weeks).
            - end_date: Optional end date for the recurrence. If specified, the recurrence will stop on this date.
            - occurrence_count: Optional number of occurrences. If specified, the recurrence will stop after this many occurrences.
            - days_of_week: Optional list of weekdays for the reminder. Use integers to represent days:
                - Sunday: 1
                - Monday: 2
                - Tuesday: 3
                - Wednesday: 4
                - Thursday: 5
                - Friday: 6
                - Saturday: 7

    Note: Both `end_date` and `occurrence_count` should not be set simultaneously; choose one or the other, or leave both unset.
    """
    logger.info(f"Incoming Create Reminder Request: {create_reminder_request}")
    try:
        manager = get_calendar_manager()

        reminder = manager.create_reminder(create_reminder_request)
        if not reminder:
            return "Failed to create reminder. Please check reminder permissions and try again."

        return f"Successfully created reminder: {reminder.title} (ID: {reminder.identifier})"

    except Exception as e:
        return f"Error creating reminder: {str(e)}"


@mcp.tool()
async def update_reminder(reminder_id: str, update_reminder_request: UpdateReminderRequest) -> str:
    """Update an existing reminder.

    Before using this tool, make sure to:
    1. Ask the user which fields they want to update
    2. If moving to a different reminder list, verify the list exists using reminders://lists
    3. If updating due date, confirm the new date with the user
    4. Ask if they want to add/update notes if not specified
    5. Ask if they want to mark as completed/pending
    6. Ask if they want to set alarms for the reminder

    Args:
        reminder_id: Unique identifier of the reminder to update
        title: Optional new title
        list_name: Optional new reminder list. Ask user which list to use, referencing reminders://lists.
        due_date: Optional new due date in ISO format
        notes: Optional new notes/description. Ask user if they want to update notes.
        priority: Optional new priority level (HIGH, MEDIUM, LOW, NONE)
        url: Optional new URL
        is_completed: Optional completion status (True/False)
        alarms_minutes_offsets: List of minutes before the due date to trigger reminders
            e.g. [60, 1440] means two reminders, the first 24 hours before due date and the second one hour before.
        recurrence_rule: Optional recurrence rule for the reminder. This should be an instance of `RecurrenceRule` with the following fields:
            - frequency: Frequency of the recurrence (e.g., DAILY, WEEKLY, MONTHLY, YEARLY).
            - interval: Interval between recurrences (e.g., every 2 weeks).
            - end_date: Optional end date for the recurrence. If specified, the recurrence will stop on this date.
            - occurrence_count: Optional number of occurrences. If specified, the recurrence will stop after this many occurrences.
            - days_of_week: Optional list of weekdays for the reminder. Use integers to represent days:
                - Sunday: 1
                - Monday: 2
                - Tuesday: 3
                - Wednesday: 4
                - Thursday: 5
                - Friday: 6
                - Saturday: 7

    Note: Both `end_date` and `occurrence_count` should not be set simultaneously; choose one or the other, or leave both unset.
    """
    try:
        manager = get_calendar_manager()
        reminder = manager.update_reminder(reminder_id, update_reminder_request)
        if not reminder:
            return f"Failed to update reminder. Reminder with ID {reminder_id} not found or update failed."

        return f"Successfully updated reminder: {reminder.title}"

    except Exception as e:
        return f"Error updating reminder: {str(e)}"


@mcp.tool()
async def delete_reminder(reminder_id: str) -> str:
    """Delete a reminder by its identifier.

    Args:
        reminder_id: Unique identifier of the reminder to delete
    """
    try:
        manager = get_calendar_manager()
        success = manager.delete_reminder(reminder_id)
        if success:
            return f"Successfully deleted reminder with ID: {reminder_id}"
        else:
            return f"Failed to delete reminder. Reminder with ID {reminder_id} not found."

    except Exception as e:
        return f"Error deleting reminder: {str(e)}"


def main():
    logger.info("Running mcp-ical server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

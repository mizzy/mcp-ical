from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Annotated, Self

from EventKit import (
    EKEvent,  # type: ignore[import-untyped]
    EKRecurrenceDayOfWeek,  # type: ignore[import-untyped]
    EKRecurrenceEnd,  # type: ignore[import-untyped]
    EKRecurrenceRule,  # type: ignore[import-untyped]
    EKReminder,  # type: ignore[import-untyped]
)
from pydantic import BaseModel, BeforeValidator, Field, model_validator


class Frequency(IntEnum):
    DAILY = 0  # EKRecurrenceFrequencyDaily
    WEEKLY = 1  # EKRecurrenceFrequencyWeekly
    MONTHLY = 2  # EKRecurrenceFrequencyMonthly
    YEARLY = 3  # EKRecurrenceFrequencyYearly


class Weekday(IntEnum):
    SUNDAY = 1
    MONDAY = 2
    TUESDAY = 3
    WEDNESDAY = 4
    THURSDAY = 5
    FRIDAY = 6
    SATURDAY = 7


class Priority(IntEnum):
    NONE = 0
    HIGH = 1
    MEDIUM = 5
    LOW = 9


def convert_datetime(v):
    if hasattr(v, "timeIntervalSince1970"):
        return datetime.fromtimestamp(v.timeIntervalSince1970())

    if isinstance(v, str):
        return datetime.fromisoformat(v)

    if isinstance(v, datetime):
        return v

    # If we don't recognize the type, let Pydantic handle it
    return v


FlexibleDateTime = Annotated[datetime, BeforeValidator(convert_datetime)]


class RecurrenceRule(BaseModel):
    frequency: Frequency
    interval: int = Field(default=1, ge=1)
    end_date: FlexibleDateTime | None = None
    occurrence_count: int | None = None
    days_of_week: list[Weekday] | None = None

    @model_validator(mode="after")
    def validate_end_conditions(self) -> Self:
        if self.end_date is not None and self.occurrence_count is not None:
            raise ValueError("Only one of end_date or occurrence_count can be set")
        return self

    def to_ek_recurrence(self) -> EKRecurrenceRule:
        # Create the end rule if specified
        end = None
        if self.end_date:
            end = EKRecurrenceEnd.recurrenceEndWithEndDate_(self.end_date)
        elif self.occurrence_count:
            end = EKRecurrenceEnd.recurrenceEndWithOccurrenceCount_(
                self.occurrence_count,
            )

        # Convert weekdays if specified
        ek_days = None
        if self.days_of_week:
            ek_days = [
                EKRecurrenceDayOfWeek.alloc().initWithDayOfTheWeek_weekNumber_(
                    day.value,
                    0,  # weekNumber 0 means "any week"
                )
                for day in self.days_of_week
            ]

        return EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_daysOfTheWeek_daysOfTheMonth_monthsOfTheYear_weeksOfTheYear_daysOfTheYear_setPositions_end_(
            self.frequency.value,
            self.interval,
            ek_days,
            None,  # daysOfTheMonth
            None,  # monthsOfTheYear
            None,  # weeksOfTheYear
            None,  # daysOfTheYear
            None,  # setPositions
            end,
        )


@dataclass
class Event:
    title: str
    start_time: FlexibleDateTime
    end_time: FlexibleDateTime
    identifier: str
    calendar_name: str | None = None
    location: str | None = None
    notes: str | None = None
    alarms_minutes_offsets: list[int] | None = None
    url: str | None = None
    all_day: bool = False
    has_alarms: bool = False
    availability: int | None = None
    status: int | None = None
    organizer: str | None = None
    attendees: list[str] | None = None
    last_modified: FlexibleDateTime | None = None
    recurrence_rule: RecurrenceRule | None = None
    _raw_event: EKEvent | None = None  # Store the original EKEvent object

    @classmethod
    def from_ekevent(cls, ekevent: EKEvent) -> "Event":
        """Create an Event instance from an EKEvent."""
        attendees = [str(attendee.name()) for attendee in ekevent.attendees()] if ekevent.attendees() else []

        # Convert EKAlarms to our Alarm objects
        alarms = []
        if ekevent.alarms():
            for alarm in ekevent.alarms():
                offset_seconds = alarm.relativeOffset()
                minutes = int(-offset_seconds / 60)  # Convert to minutes
                alarms.append(minutes)

        # Convert EKRecurrenceRule to our Recurrence object
        recurrence = None
        if ekevent.recurrenceRule():
            rule = ekevent.recurrenceRule()
            days = None
            if rule.daysOfTheWeek():
                days = [Weekday(day.dayOfTheWeek()) for day in rule.daysOfTheWeek()]

            recurrence = RecurrenceRule(
                frequency=Frequency(rule.frequency()),
                interval=rule.interval(),
                days_of_week=days,
                # Only set one of end_date or occurrence_count
                end_date=rule.recurrenceEnd().endDate()
                if rule.recurrenceEnd() and not rule.recurrenceEnd().occurrenceCount()
                else None,
                occurrence_count=rule.recurrenceEnd().occurrenceCount()
                if rule.recurrenceEnd() and rule.recurrenceEnd().occurrenceCount()
                else None,
            )

        return cls(
            title=ekevent.title(),
            start_time=ekevent.startDate(),
            end_time=ekevent.endDate(),
            calendar_name=ekevent.calendar().title(),
            location=ekevent.location(),
            notes=ekevent.notes(),
            url=str(ekevent.URL()) if ekevent.URL() else None,
            all_day=ekevent.isAllDay(),
            alarms_minutes_offsets=alarms,
            recurrence_rule=recurrence,
            availability=ekevent.availability(),
            status=ekevent.status(),
            organizer=str(ekevent.organizer().name()) if ekevent.organizer() else None,
            attendees=attendees,
            last_modified=ekevent.lastModifiedDate(),
            identifier=ekevent.eventIdentifier(),
            _raw_event=ekevent,
        )

    def __str__(self) -> str:
        """Return a human-readable string representation of the Event."""
        attendees_list = ", ".join(self.attendees) if self.attendees else "None"
        alarms_list = ", ".join(map(str, self.alarms_minutes_offsets)) if self.alarms_minutes_offsets else "None"

        recurrence_info = "No recurrence"
        if self.recurrence_rule:
            recurrence_info = (
                f"Recurrence: {self.recurrence_rule.frequency.name}, "
                f"Interval: {self.recurrence_rule.interval}, "
                f"End Date: {self.recurrence_rule.end_date or 'N/A'}, "
                f"Occurrences: {self.recurrence_rule.occurrence_count or 'N/A'}"
            )

        return (
            f"Event: {self.title},\n"
            f" - Identifier: {self.identifier},\n"
            f" - Start Time: {self.start_time},\n"
            f" - End Time: {self.end_time},\n"
            f" - Calendar: {self.calendar_name or 'N/A'},\n"
            f" - Location: {self.location or 'N/A'},\n"
            f" - Notes: {self.notes or 'N/A'},\n"
            f" - Alarms (minutes before): {alarms_list},\n"
            f" - URL: {self.url or 'N/A'},\n"
            f" - All Day Event?: {self.all_day},\n"
            f" - Status: {self.status or 'N/A'},\n"
            f" - Organizer: {self.organizer or 'N/A'},\n"
            f" - Attendees: {attendees_list},\n"
            f" - {recurrence_info}\n"
        )


class CreateEventRequest(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    calendar_name: str | None = None
    location: str | None = None
    notes: str | None = None
    alarms_minutes_offsets: list[int] | None = None
    url: str | None = None
    all_day: bool = False
    recurrence_rule: RecurrenceRule | None = None


class UpdateEventRequest(BaseModel):
    title: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    calendar_name: str | None = None
    location: str | None = None
    notes: str | None = None
    alarms_minutes_offsets: list[int] | None = None
    url: str | None = None
    all_day: bool | None = None
    recurrence_rule: RecurrenceRule | None = None


@dataclass
class Reminder:
    title: str
    identifier: str
    list_name: str | None = None
    due_date: FlexibleDateTime | None = None
    completion_date: FlexibleDateTime | None = None
    notes: str | None = None
    priority: Priority = Priority.NONE
    url: str | None = None
    is_completed: bool = False
    alarms_minutes_offsets: list[int] | None = None
    recurrence_rule: RecurrenceRule | None = None
    creation_date: FlexibleDateTime | None = None
    last_modified: FlexibleDateTime | None = None
    _raw_reminder: EKReminder | None = None  # Store the original EKReminder object

    @classmethod
    def from_ekreminder(cls, ekreminder: EKReminder) -> "Reminder":
        """Create a Reminder instance from an EKReminder."""
        # Convert EKAlarms to our Alarm objects
        alarms = []
        if ekreminder.alarms():
            for alarm in ekreminder.alarms():
                offset_seconds = alarm.relativeOffset()
                minutes = int(-offset_seconds / 60)  # Convert to minutes
                alarms.append(minutes)

        # Convert EKRecurrenceRule to our Recurrence object
        # Note: EKReminder uses recurrenceRules (plural) which returns an array
        recurrence = None
        if hasattr(ekreminder, 'recurrenceRules') and ekreminder.recurrenceRules() and len(ekreminder.recurrenceRules()) > 0:
            rule = ekreminder.recurrenceRules()[0]  # Take the first recurrence rule
            days = None
            if rule.daysOfTheWeek():
                days = [Weekday(day.dayOfTheWeek()) for day in rule.daysOfTheWeek()]

            recurrence = RecurrenceRule(
                frequency=Frequency(rule.frequency()),
                interval=rule.interval(),
                days_of_week=days,
                # Only set one of end_date or occurrence_count
                end_date=rule.recurrenceEnd().endDate()
                if rule.recurrenceEnd() and not rule.recurrenceEnd().occurrenceCount()
                else None,
                occurrence_count=rule.recurrenceEnd().occurrenceCount()
                if rule.recurrenceEnd() and rule.recurrenceEnd().occurrenceCount()
                else None,
            )

        # Convert due date components to datetime if present
        due_date = None
        if ekreminder.dueDateComponents():
            from Foundation import NSCalendar
            calendar = NSCalendar.currentCalendar()
            due_date = calendar.dateFromComponents_(ekreminder.dueDateComponents())

        return cls(
            title=ekreminder.title(),
            identifier=ekreminder.calendarItemIdentifier(),
            list_name=ekreminder.calendar().title() if ekreminder.calendar() else None,
            due_date=due_date,
            completion_date=ekreminder.completionDate() if ekreminder.completionDate() else None,
            notes=ekreminder.notes() if ekreminder.notes() else None,
            priority=Priority(ekreminder.priority()) if ekreminder.priority() else Priority.NONE,
            url=str(ekreminder.URL()) if ekreminder.URL() else None,
            is_completed=ekreminder.isCompleted(),
            alarms_minutes_offsets=alarms,
            recurrence_rule=recurrence,
            creation_date=ekreminder.creationDate() if ekreminder.creationDate() else None,
            last_modified=ekreminder.lastModifiedDate() if ekreminder.lastModifiedDate() else None,
            _raw_reminder=ekreminder,
        )

    def __str__(self) -> str:
        """Return a human-readable string representation of the Reminder."""
        alarms_list = ", ".join(map(str, self.alarms_minutes_offsets)) if self.alarms_minutes_offsets else "None"
        
        recurrence_info = "No recurrence"
        if self.recurrence_rule:
            recurrence_info = (
                f"Recurrence: {self.recurrence_rule.frequency.name}, "
                f"Interval: {self.recurrence_rule.interval}, "
                f"End Date: {self.recurrence_rule.end_date or 'N/A'}, "
                f"Occurrences: {self.recurrence_rule.occurrence_count or 'N/A'}"
            )

        status = "✅ Completed" if self.is_completed else "⏸️ Pending"
        if self.completion_date and self.is_completed:
            status += f" on {self.completion_date}"

        return (
            f"Reminder: {self.title},\n"
            f" - Identifier: {self.identifier},\n"
            f" - List: {self.list_name or 'N/A'},\n"
            f" - Status: {status},\n"
            f" - Due Date: {self.due_date or 'N/A'},\n"
            f" - Priority: {self.priority.name},\n"
            f" - Notes: {self.notes or 'N/A'},\n"
            f" - Alarms (minutes before): {alarms_list},\n"
            f" - URL: {self.url or 'N/A'},\n"
            f" - Created: {self.creation_date or 'N/A'},\n"
            f" - {recurrence_info}\n"
        )


class CreateReminderRequest(BaseModel):
    title: str
    list_name: str | None = None
    due_date: datetime | None = None
    notes: str | None = None
    priority: Priority = Priority.NONE
    url: str | None = None
    alarms_minutes_offsets: list[int] | None = None
    recurrence_rule: RecurrenceRule | None = None


class UpdateReminderRequest(BaseModel):
    title: str | None = None
    list_name: str | None = None
    due_date: datetime | None = None
    notes: str | None = None
    priority: Priority | None = None
    url: str | None = None
    is_completed: bool | None = None
    alarms_minutes_offsets: list[int] | None = None
    recurrence_rule: RecurrenceRule | None = None

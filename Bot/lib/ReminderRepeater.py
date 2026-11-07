from datetime import datetime
import lib.timeutil as timeutil
from dateutil import tz
import dateutil.rrule as rr

from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder


#====================
# Time frames
#====================

# Interval rules (DTSTART, first_at, rdates, exdates) are naive datetimes in
# the local time of the server (of the user, in DMs).
# Reminder.at is always naive UTC. Convert at every boundary between the two.

def instance_id_of(reminder):
    return reminder.g_id if reminder.g_id else reminder.author


def utc_to_rule_frame(utc_dt: datetime, instance_id) -> datetime:
    """convert a naive UTC datetime into the frame used by interval rules"""
    if utc_dt is None:
        return utc_dt
    local_tz = tz.gettz(Connector.get_timezone(instance_id))
    return utc_dt.replace(tzinfo=tz.UTC).astimezone(local_tz).replace(tzinfo=None)


def rule_frame_to_utc(rule_dt: datetime, instance_id) -> datetime:
    """convert a naive datetime of the interval rule frame back to naive UTC"""
    if rule_dt is None:
        return rule_dt
    local_tz = tz.gettz(Connector.get_timezone(instance_id))
    return rule_dt.replace(tzinfo=local_tz).astimezone(tz.UTC).replace(tzinfo=None)


#====================
# Transformation Ops
#====================

def _reminder_to_interval(reminder: Reminder):
    """convert the Reminder into an IntervalReminder
       push transaction onto db
       return new IntervalReminder Object
       WARN: reminder might be orphaned and requires rules to be added

    Args:
        reminder (Reminder): old reminder       

    Returns:
        IntervalReminder: new reminder object
    """

    # create new IntervalReminder
    old_reminder = reminder
    reminder = IntervalReminder(old_reminder._to_json())

    # update the occurrence to optimise database fetches
    # first_at lives in the rule frame (local time), at stays UTC
    reminder.first_at = timeutil.to_minute(utc_to_rule_frame(old_reminder.at, instance_id_of(old_reminder)))
    # keep reminder 'at' at old val for now

    new_id = Connector.add_interval(reminder)
    Connector.delete_reminder(old_reminder._id)


    reminder._id = new_id
    return reminder



def _interval_to_reminder(reminder: IntervalReminder):

    old_reminder = reminder
    reminder = Reminder(reminder._to_json())
    reminder.at = rule_frame_to_utc(old_reminder.first_at, instance_id_of(old_reminder))

    new_id = Connector.add_reminder(reminder)
    Connector.delete_interval(old_reminder._id)
    

    reminder._id = new_id
    return reminder



def add_rules(reminder, rrule=None, exrule=None, rdate=None, exdate=None) -> IntervalReminder:
    """add the given rules to the given reminder
       converts the reminder to Intevral if not done yet

    Args:
        reminder (_type_): _description_
        rrule (_type_, optional): _description_. Defaults to None.
        exrule (_type_, optional): _description_. Defaults to None.
        rdate (_type_, optional): _description_. Defaults to None.
        exdate (_type_, optional): _description_. Defaults to None.

    Returns:
        IntervalReminder: the converted  reminder
    """

    if type(reminder) == Reminder:
        reminder = _reminder_to_interval(reminder)

    if rrule:
        reminder.rrules.append(rrule)
    
    if exrule:
        reminder.exrules.append(exrule)

    # dates to the minute, like the occurrences of the rules
    if rdate:
        reminder.rdates.append(timeutil.to_minute(rdate))

    if exdate:
        reminder.exdates.append(timeutil.to_minute(exdate))


    reminder.at = reminder.next_trigger(timeutil.utcnow())
    Connector.update_interval_rules(reminder)
    Connector.update_interval_at(reminder)


    return reminder


def rm_rules(reminder: IntervalReminder, rule_idx=None):

    utcnow = timeutil.utcnow()

    if rule_idx is None:
        return reminder

    reminder.delete_rule_idx(rule_idx)
    reminder.at = reminder.next_trigger(timeutil.utcnow())

    rules_cnt = reminder.get_rule_cnt()

    # if reminder has no further rules left over
    # and .at is in the future, set it as default Reminder
    if rules_cnt == 0 and reminder.at and reminder.at > utcnow:
        reminder = _interval_to_reminder(reminder)
        return reminder

    # if reminder has no further occurrence
    # it is kept as orphaned reminder
    # it may or may not have some rules set
    # it's deleted in both cases within the next 24h

    # if at is None
    # the reminder is orphaned, a warning can be displayed by a higher layer
    Connector.update_interval_rules(reminder)
    Connector.update_interval_at(reminder)

    return reminder


def _rule_normalize(rule_str, dtstart):
    """generate the rrule of the given rrule string
       if the string contains timezone based offsets (iso dates)
       they are converted into the non-timezone aware utc equivalent

    Args:
        rule_str ([type]): [description]
        dtstart ([type]): [description]

    Returns:
        [type]: [description]
    """

    try:
        rule = rr.rrulestr(rule_str)
    except Exception as e:
        return None, str(e)

    until = rule._until
    until_utc = None

    if until:
        # convert the until date to non-tz aware
        until_utc = until.astimezone(tz.UTC)
        until_utc = until_utc.replace(tzinfo=None)

    try:
        rule = rr.rrulestr(rule_str, dtstart=dtstart, ignoretz=True)
    except Exception as e:
        return None, str(e)

    if until_utc:
        rule = rule.replace(until=until_utc)

    return rule, None




def reschedule_instance(instance_id, tz_str: str = None) -> int:
    """compute again the next date of every interval of a server (or of a
       user's private intervals), e.g. after a change of its timezone

    The rules keep their local times (07:00 stays 07:00 in the new timezone),
    the stored next date (UTC) moves accordingly.

    Returns:
        int: number of intervals updated
    """
    tz_str = tz_str or Connector.get_timezone(instance_id)
    utcnow = timeutil.utcnow()
    count = 0
    for interval in Connector.get_instance_intervals(instance_id):
        if not interval.at:
            continue  # orphaned, deleted soon
        interval.at = interval.next_trigger(utcnow, tz_str=tz_str)
        Connector.update_interval_at(interval)
        count += 1
    return count

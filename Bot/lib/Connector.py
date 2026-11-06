import os
from enum import Enum

from pymongo import MongoClient

from lib.Reminder import Reminder, IntervalReminder


import logging



log = logging.getLogger('Remindme.Connector')



class Connector:

    client = None
    db = None
    class Scope():
        def __init__(self, is_private=False, guild_id=None, user_id=None):
            self.is_private = is_private
            self.guild_id = guild_id
            self.user_id = user_id
            self.instance_id = self.guild_id or self.user_id

    class ReminderType(Enum):
        TEXT_ONLY = 1
        HYBRID = 2
        EMBED_ONLY = 3
        BAREBONE = 4

    class AutoDelete(Enum):
        TIMEOUT = 1
        NEVER = 2
        HIDE = 3
        
    @staticmethod
    def init():
        host = os.getenv('MONGO_CONN')
        port = int(os.getenv('MONGO_PORT'))

        uname = os.getenv('MONGO_ROOT_USER')
        pw = os.getenv('MONGO_ROOT_PASS')

        # pymongo calls block the event loop (and every Discord interaction) while they wait.
        # The defaults wait up to 30 s for an unreachable server; fail fast instead,
        # the task loops retry on their next iteration
        Connector.client = MongoClient(host=host, username=uname, password=pw, port=port,
                                       serverSelectionTimeoutMS=5000,
                                       connectTimeoutMS=5000,
                                       socketTimeoutMS=15000)
        Connector.db = Connector.client.reminderBot


    @staticmethod
    def delete_guild(guild_id: int):
        Connector.db.settings.delete_one({'g_id': str(guild_id)})
        rem_cursor = Connector.db.reminders.delete_many({'g_id': str(guild_id)})
        intvl_cursor = Connector.db.intervals.delete_many({'g_id': str(guild_id)})
        
        return (rem_cursor.deleted_count, intvl_cursor.deleted_count)


    @staticmethod
    def get_timezone(instance_id: int):
        
        # the settings key is 'g_id'
        # however guilds aswell as user ids are supported as key
        # for backwards compatibility with the database, the key name wasn't changed to instance_id
        tz_json = Connector.db.settings.find_one({'g_id': str(instance_id)}, {'timezone': 1})

        if not tz_json:
            return 'UTC'
        else:
            return tz_json.get('timezone', 'UTC')


    @staticmethod
    def set_timezone(instance_id: int, timezone_str):
        
        # the settings key is 'g_id'
        # however guilds aswell as user ids are supported as key
        # for backwards compatibility with the database, the key name wasn't changed to instance_id
        Connector.db.settings.find_one_and_update({'g_id': str(instance_id)}, {'$set': {'timezone': timezone_str}}, new=False, upsert=True)
        
        
    @staticmethod
    def  get_reminder_type(instance_id: int) -> ReminderType:
        
        # keep g_id as key for backwards compatibility
        rem_json = Connector.db.settings.find_one({'g_id': str(instance_id)}, {'reminder_type': 1})
        
        if not rem_json:
            return Connector.ReminderType.HYBRID
        else:
            return Connector.ReminderType[rem_json.get('reminder_type', Connector.ReminderType.HYBRID.name)]
    
        
    @staticmethod
    def set_auto_delete(instance_id: int, delete_type: AutoDelete):
        
        # keep g_id as key for backwards compatibility
        Connector.db.settings.find_one_and_update({'g_id': str(instance_id)}, {'$set': {'auto_delete': delete_type.name}}, new=False, upsert=True)
        
    @staticmethod
    def  get_auto_delete(instance_id: int):
        
        # keep g_id as key for backwards compatibility
        rem_json = Connector.db.settings.find_one({'g_id': str(instance_id)}, {'auto_delete': 1})
        
        if not rem_json:
            return Connector.AutoDelete.TIMEOUT
        else:
            return Connector.AutoDelete[rem_json.get('auto_delete', Connector.AutoDelete.TIMEOUT.name)]
        
    @staticmethod
    def set_reminder_type(instance_id: int, reminder_type: ReminderType):
        
        # keep g_id as key for backwards compatibility
        Connector.db.settings.find_one_and_update({'g_id': str(instance_id)}, {'$set': {'reminder_type': reminder_type.name}}, new=False, upsert=True)


    @staticmethod
    def add_reminder(reminder: Reminder):
        """save the reminder into the database

        Args:
            reminder (Reminder): reminder object to be saved

        Returns:
            ObjectId: id of the database entry
        """
        insert_obj = Connector.db.reminders.insert_one(reminder._to_json())
        return insert_obj.inserted_id

    @staticmethod
    def add_interval(interval: IntervalReminder):
        
        insert_obj = Connector.db.intervals.insert_one(interval._to_json())
        return insert_obj.inserted_id


    @staticmethod
    def update_interval_rules(interval: IntervalReminder):

        intvl_js = interval._to_json()
        Connector.db.intervals.find_one_and_update({'_id': interval._id}, {'$set': {'rdates': intvl_js['rdates'],
                                                                                    'exdates': intvl_js['exdates'],
                                                                                    'rrules': intvl_js['rrules'],
                                                                                    'exrules': intvl_js['exrules']}}, new=False, upsert=False)

    @staticmethod
    def update_reminder_at(reminder: Reminder):

        at_ts = reminder._to_json()['at']
        Connector.db.reminders.find_one_and_update({'_id': reminder._id}, {'$set': {'at': at_ts}}, new=False, upsert=False)


    @staticmethod
    def update_interval_at(interval: IntervalReminder):
        
        if not interval.at:
            log.warning(f'Orphaned interval reminder {interval._id}.')
            at_ts = None
        else:
            at_ts = interval._to_json()['at']

        Connector.db.intervals.find_one_and_update({'_id': interval._id}, {'$set': {'at': at_ts}}, new=False, upsert=False)


    @staticmethod
    def delete_orphaned_intervals():

        op = Connector.db.intervals.delete_many({'at': {'$eq': None}})
        return op.deleted_count


    @staticmethod
    def get_elapsed_reminders(timestamp):
        """get the reminders due before timestamp, without deleting them
           the caller deletes each one once it was handled
        """
        rems =  list(Connector.db.reminders.find({'at': {'$lt': timestamp}}))
        rems = list(map(Reminder, rems))

        return rems

    @staticmethod
    def get_pending_intervals(timestamp):

        intvl =  list(Connector.db.intervals.find({'at': {'$lt': timestamp}}))
        intvl = list(map(IntervalReminder, intvl))

        return intvl


    @staticmethod
    def get_reminder_by_id(reminder_id):

        reminder = Connector.db.reminders.find_one({'_id': reminder_id})

        if reminder:
            return Reminder(reminder)
        else:
            return None
        
    @staticmethod
    def get_interval_by_id(interval_id):

        interval = Connector.db.intervals.find_one({'_id': interval_id})

        if interval:
            return IntervalReminder(interval)
        else:
            return None


    @staticmethod
    def get_author_of_id(reminder_id):
        """return the author id of the given reminder id
           can be a plain reminder or an interval
           
           None if id not found
        """

        reminder = Connector.db.reminders.find_one({'_id': reminder_id}, {'author': 1})
        
        if not reminder:
            reminder = Connector.db.intervals.find_one({'_id': reminder_id}, {'author': 1})

        if reminder:
            return int(reminder['author'])
        else:
            return None



    @staticmethod
    def delete_reminder(reminder_id):
        """delete the reminder with the given id

        Returns:
            bool: True if reminder deleted successfully
        """
        action = Connector.db.reminders.delete_one({'_id': reminder_id})
        return (action.deleted_count > 0)


    @staticmethod
    def delete_interval(reminder_id):
        """delete the reminder with the given id

        Returns:
            bool: True if reminder deleted successfully
        """
        action = Connector.db.intervals.delete_one({'_id': reminder_id})
        return (action.deleted_count > 0)



    @staticmethod
    def _set_fields(reminder_id, fields: dict) -> bool:
        """update fields of a stored reminder, which can be a Reminder or an Interval

        Returns:
            bool: True if the reminder was found
        """
        result = Connector.db.reminders.find_one_and_update({'_id': reminder_id}, {'$set': fields})
        if not result:
            result = Connector.db.intervals.find_one_and_update({'_id': reminder_id}, {'$set': fields})
        return result is not None


    @staticmethod
    def set_reminder_message(reminder_id, message: str) -> bool:
        return Connector._set_fields(reminder_id, {'msg': message})


    @staticmethod
    def set_reminder_title(reminder_id, title: str) -> bool:
        return Connector._set_fields(reminder_id, {'title': title})


    @staticmethod
    def set_reminder_img_url(reminder_id, img_url: str) -> bool:
        return Connector._set_fields(reminder_id, {'img_url': img_url})


    @staticmethod
    def set_reminder_channel(reminder_id, channel_id: int, channel_name: str = None) -> bool:
        fields = {'ch_id': str(channel_id)}
        if channel_name:
            fields['ch_name'] = str(channel_name)
        return Connector._set_fields(reminder_id, fields)


    @staticmethod
    def get_scoped_reminders(scope: Scope, sort_return=True):
        """request all reminders from the db
           which match the required scope

        Args:
            scope (Scope): request scope (guild or private, always user bound)
            sort_return (bool): sort the reminders by elapsed time

        Returns:
            list: list of reminders
        """

        rems = []

        if scope.is_private and scope.user_id:
            rems =  Connector._get_user_private_reminders(scope.user_id)
        elif scope.user_id and scope.guild_id:
            rems =  Connector._get_user_reminders(scope.guild_id, scope.user_id)
        else:
            rems = []

        if sort_return:
            #rems = sorted(rems, key=lambda r: r.at or datetime.utcnow())
            rems = sorted(rems)
        
        return rems


    @staticmethod
    def _get_user_reminders(guild_id: int, user_id: int):

        rems = list(Connector.db.reminders.find({'g_id': str(guild_id), 'author': str(user_id)}))
        rems = list(map(Reminder, rems))

        intvl = list(Connector.db.intervals.find({'g_id': str(guild_id), 'author': str(user_id)}))
        intvl = list(map(IntervalReminder, intvl))

        return rems + intvl

    @staticmethod
    def _get_user_private_reminders(user_id: int):

        rems = list(Connector.db.reminders.find({'g_id': None, 'author': str(user_id)}))
        rems = list(map(Reminder, rems))

        intvl = list(Connector.db.intervals.find({'g_id': None, 'author': str(user_id)}))
        intvl = list(map(IntervalReminder, intvl))

        return rems + intvl

    

    
   

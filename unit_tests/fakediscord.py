"""A small stand-in for Discord, to test the menus end to end

Clicks go through py-cord's own view code (View._dispatch_item, which replaces
view.message, then interaction_check, the callback and on_error), and popups
through py-cord's modal code (_refresh, callback, on_error).

Like on Discord:
- the message py-cord gives with a click is a plain Message: it has no
  edit_original_* methods, and editing it through the channel fails when it is
  ephemeral (all menus are)
- an interaction is answered once; edit_original_response needs an answer
  that showed or edited a message (not a popup)
- a click that is not answered shows "This interaction failed"
- an interaction must be answered within 3 seconds, and its token (to edit
  the answer or send followups) dies after 15 minutes
- single-line popup fields can't hold line breaks: they arrive as spaces
- popups go through py-cord's own ModalStore (lookup, callback, removal)
"""
import asyncio
import itertools
from types import SimpleNamespace

import discord
from discord.ui.modal import ModalStore
from discord.utils import MISSING

OWNER = 111
STRANGER = 222

# seconds (patch them to test expiry)
ANSWER_WINDOW = 3
TOKEN_LIFETIME = 15*60

_ids = itertools.count(1000)


class _NotFoundResponse:
    status = 404
    reason = 'Not Found'


def _not_found():
    return discord.NotFound(_NotFoundResponse(), 'Unknown Message')


class ChatMessage:
    """a message as Discord shows it"""
    def __init__(self, world, ephemeral=True):
        self.world = world
        self.id = next(_ids)
        self.ephemeral = ephemeral
        self.content = None
        self.embed = None
        self.view = None

    def apply(self, content=MISSING, embed=MISSING, view=MISSING, **_):
        if content is not MISSING:
            self.content = content
        if embed is not MISSING:
            self.embed = embed
        if view is not MISSING:
            self.view = view
            if view is not None and not view.is_finished():
                # py-cord stores the view, which (re)starts its timeout
                view._start_listening_from_store(self.world.store)

    @property
    def title(self):
        return self.embed.title if self.embed else None

    def button(self, label=None, emoji=None):
        for item in self.view.children:
            if isinstance(item, discord.ui.Button):
                if label is not None and item.label == label:
                    return item
                if emoji is not None and str(item.emoji) == emoji:
                    return item
        raise AssertionError(f'no button {label or emoji} on "{self.title}": '
                             f'{[getattr(i, "label", None) for i in self.view.children]}')

    def select(self, placeholder):
        for item in self.view.children:
            if isinstance(item, discord.ui.Select) and item.placeholder == placeholder:
                return item
        raise AssertionError(f'no dropdown "{placeholder}" on "{self.title}"')


class PlainMessage:
    """interaction.message as py-cord builds it"""
    def __init__(self, chat: ChatMessage):
        self._chat = chat
        self.id = chat.id
        self.flags = SimpleNamespace(ephemeral=chat.ephemeral)

    async def edit(self, **kwargs):
        if self._chat.ephemeral:
            # ephemeral messages can only be edited through an interaction
            raise _not_found()
        self._chat.apply(**kwargs)
        return self


class FakeResponse:
    def __init__(self, interaction):
        self._inter = interaction
        self.kind = None

    def is_done(self):
        return self.kind is not None

    def _answer(self, kind):
        if self.kind is not None:
            raise discord.InteractionResponded(self._inter)
        if self._inter.age() > ANSWER_WINDOW:
            raise _not_found()  # Unknown interaction
        self.kind = kind

    async def edit_message(self, **kwargs):
        if self._inter._target is None:
            raise AssertionError('edit_message without a message')
        self._answer('update')
        self._inter._target.apply(**kwargs)

    async def defer(self, *args, **kwargs):
        self._answer('update' if self._inter._target else 'message')

    async def send_message(self, content=None, embed=None, view=None, ephemeral=False, **_):
        self._answer('message')
        msg = self._inter.world.new_message(ephemeral)
        msg.apply(content=content, embed=embed, view=view)
        self._inter._sent = msg
        return self._inter

    async def send_modal(self, modal):
        self._answer('popup')
        # as py-cord: the popup waits in the ModalStore for its submit
        self._inter.world.modal_store.add_modal(modal, self._inter.user.id)
        self._inter.world.popups.append((modal, self._inter._target))


class FakeFollowup:
    def __init__(self, interaction):
        self._inter = interaction

    async def send(self, content=None, embed=None, view=None, ephemeral=False, **_):
        if not self._inter.response.is_done():
            raise AssertionError('followup before the answer')
        if self._inter.age() > TOKEN_LIFETIME:
            raise _not_found()  # Unknown Webhook
        msg = self._inter.world.new_message(ephemeral)
        msg.apply(content=content, embed=embed, view=view)
        return msg


class FakeUser:
    """a Discord user the bot can DM"""
    def __init__(self, world, user_id):
        self.world = world
        self.id = user_id

    async def send(self, content=None, embed=None, **_):
        if self.id in self.world.closed_dms:
            raise discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'),
                                    {'code': 50007, 'message': 'Cannot send messages to this user'})
        self.world.dms.append(SimpleNamespace(user_id=self.id, content=content, embed=embed))


class FakeClient:
    def __init__(self, world):
        self.world = world

    def dispatch(self, *args):
        pass

    def get_user(self, user_id):
        return None  # not cached: fetched

    async def fetch_user(self, user_id):
        return FakeUser(self.world, user_id)

    def get_guild(self, guild_id):
        return SimpleNamespace(id=guild_id, name='Test')


class FakeInteraction:
    def __init__(self, world, user_id, target: ChatMessage = None, data=None,
                 type=discord.InteractionType.component):
        self.world = world
        self.user = SimpleNamespace(id=user_id, mention=f'<@{user_id}>')
        self.type = type
        self._target = target
        self.message = PlainMessage(target) if target else None
        self.data = data or {}
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self._sent = None
        self.guild = None
        self.guild_id = None
        self._state = SimpleNamespace(_modal_store=world.modal_store)
        self.client = world.client
        self.locale = world.locale  # the language of the user's Discord
        self.created = asyncio.get_running_loop().time()

    def age(self) -> float:
        return asyncio.get_running_loop().time() - self.created

    async def edit_original_response(self, **kwargs):
        if self.age() > TOKEN_LIFETIME:
            raise _not_found()  # Unknown Webhook
        kind = self.response.kind
        if kind == 'update':
            self._target.apply(**kwargs)
        elif kind == 'message':
            self._sent.apply(**kwargs)
        else:
            # not answered yet, or answered with a popup: no message
            raise _not_found()


class FakeStore:
    def remove_view(self, view):
        pass


class FakeWebhookMessage:
    """what ctx.respond returns after ctx.defer(): a followup message"""
    def __init__(self, interaction: 'FakeInteraction', chat: ChatMessage):
        self._inter = interaction
        self._chat = chat
        self.id = chat.id

    async def edit(self, **kwargs):
        if self._inter.age() > TOKEN_LIFETIME:
            raise _not_found()  # Unknown Webhook
        self._chat.apply(**kwargs)
        return self


class FakeDiscord:
    def __init__(self):
        self.store = FakeStore()
        self.modal_store = ModalStore(state=None)
        self.messages: list[ChatMessage] = []
        self.popups = []
        self.client = FakeClient(self)
        self.dms = []             # DMs the bot sent
        self.closed_dms = set()   # users who don't accept DMs
        self.locale = 'en-US'     # the language of the users' Discord

    def new_message(self, ephemeral=True) -> ChatMessage:
        msg = ChatMessage(self, ephemeral)
        self.messages.append(msg)
        return msg

    @staticmethod
    async def settle():
        """let the clicked callbacks run until they wait for the user"""
        for _ in range(200):
            await asyncio.sleep(0)

    async def respond(self, view, embed=None, ephemeral=True, user_id=OWNER, deferred=False):
        """a slash command answering with a menu (ctx.respond)

        deferred: the command called ctx.defer() first, ctx.respond then sends a
        followup and returns a WebhookMessage
        """
        inter = FakeInteraction(self, user_id, type=discord.InteractionType.application_command)
        await inter.response.send_message(embed=embed, view=view, ephemeral=ephemeral)
        view.origin = FakeWebhookMessage(inter, inter._sent) if deferred else inter
        return inter._sent

    def last_message(self) -> ChatMessage:
        return self.messages[-1]

    async def _dispatch(self, msg: ChatMessage, item, inter, must_answer):
        # py-cord drops clicks on finished views: Discord shows "interaction failed"
        msg.view._dispatch_item(item, inter)
        await self.settle()
        if must_answer and not inter.response.is_done():
            raise AssertionError(f'"This interaction failed" on "{msg.title}"')
        return inter

    async def click(self, msg: ChatMessage, label=None, emoji=None, user_id=OWNER, must_answer=True):
        item = msg.button(label, emoji)
        if item.disabled:
            raise AssertionError(f'button {label or emoji} is disabled')
        inter = FakeInteraction(self, user_id, target=msg, data={'custom_id': item.custom_id})
        return await self._dispatch(msg, item, inter, must_answer)

    async def press(self, msg: ChatMessage, label=None, emoji=None, user_id=OWNER, must_answer=True, member=None):
        """click a button whose view py-cord doesn't keep (store=False): the
           click reaches the bot through its on_interaction listener only

        member: who clicks, as a server member (with permissions), instead of user_id
        """
        import util.reminderButtons
        item = msg.button(label, emoji)
        if item.disabled:
            raise AssertionError(f'button {label or emoji} is disabled')
        inter = FakeInteraction(self, member.id if member else user_id, target=msg,
                                data={'custom_id': item.custom_id, 'component_type': 2})
        if member is not None:
            inter.user = member
        asyncio.get_running_loop().create_task(util.reminderButtons.handle_click(inter))
        await self.settle()
        if must_answer and not inter.response.is_done():
            raise AssertionError(f'"This interaction failed" on "{msg.title}"')
        return inter

    async def choose(self, msg: ChatMessage, placeholder, value, user_id=OWNER, must_answer=True):
        item = msg.select(placeholder)
        inter = FakeInteraction(self, user_id, target=msg,
                                data={'custom_id': item.custom_id, 'values': [value]})
        item._selected_values = [value]
        item._interaction = inter
        return await self._dispatch(msg, item, inter, must_answer)

    @staticmethod
    def _typed(field: discord.ui.InputText, value: str) -> str:
        # a single-line field can't hold line breaks: pasted ones become spaces
        if field.style == discord.InputTextStyle.singleline:
            return value.replace('\n', ' ')
        return value

    async def submit(self, *values, user_id=OWNER):
        """fill the text fields of the open popup in order, then submit it"""
        modal, target = self.popups.pop()
        components = []
        it = iter(values)
        for child in modal.children:
            if isinstance(child, discord.ui.TextDisplay):
                components.append({'type': 10, 'id': next(_ids)})
            elif isinstance(child, discord.ui.Label):
                components.append({'type': 18, 'id': next(_ids), 'component': {
                    'type': 4, 'id': next(_ids), 'custom_id': child.item.custom_id,
                    'value': self._typed(child.item, next(it, ''))}})
            elif isinstance(child, discord.ui.InputText):
                components.append({'type': 1, 'components': [{
                    'type': 4, 'custom_id': child.custom_id, 'value': self._typed(child, next(it, ''))}]})
        inter = FakeInteraction(self, user_id, target=target, data={'components': components},
                                type=discord.InteractionType.modal_submit)

        # py-cord's own dispatch: finds the popup in its store, runs it, removes it
        asyncio.get_running_loop().create_task(self.modal_store.dispatch(user_id, modal.custom_id, inter))
        await self.settle()
        if not inter.response.is_done():
            raise AssertionError('popup submitted: "This interaction failed"')
        return inter

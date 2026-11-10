import asyncio

import discord

import lib.i18n

import logging

log = logging.getLogger('Remindme')


# menus stay usable this long after their last use: a bit less than the 15 minutes
# an interaction token lives, so the timeout can still disable the buttons
MENU_TIMEOUT = 14*60
# a popup left open is dropped after this time: a late submit still saves
# (the menu tells it expired), a much later one gets "interaction failed"
POPUP_TIMEOUT = 30*60
# a menu is closed this long after its last edit at the latest: later, the token
# it is edited with is dead (clicks that only open a popup bring no new one)
TOKEN_LIFETIME = 15*60 - 30


async def open_popup(interaction: discord.Interaction, popup: discord.ui.Modal):
    """show a popup (modal) as the answer to interaction"""
    await interaction.response.send_modal(popup)
    # py-cord 2.8 keeps a timed out popup in its store forever (and the menu it
    # calls back): remember where it is, forget_popup() drops it
    store = getattr(getattr(interaction, '_state', None), '_modal_store', None)
    popup.store_key = (store, interaction.user.id)


def forget_popup(popup: discord.ui.Modal):
    """drop a popup opened with open_popup() from py-cord's store"""
    store, user_id = getattr(popup, 'store_key', (None, None))
    popups = getattr(store, '_modals', None)
    if popups is not None:
        popups.pop((user_id, popup.custom_id), None)


async def edit_menu(target, **kwargs):
    """edit the message of a menu

    target is an interaction on the menu message (a click, or a popup opened
    from it), or the first response of the menu (the Interaction returned by
    ctx.respond, a WebhookMessage, a Message)

    py-cord replaces view.message by the plain Message of every click, and a
    plain Message can't be edited when it is ephemeral: menus are edited
    through their interactions instead
    """
    response = getattr(target, 'response', None)
    if response is None:
        return await target.edit(**kwargs)
    if response.is_done():
        return await target.edit_original_response(**kwargs)
    return await response.edit_message(**kwargs)


async def report_error(error: Exception, interaction: discord.Interaction, where: str):
    """log an error of a button or popup (with its traceback) and tell the user"""
    log.error(f'error in {where}', exc_info=error)
    text = lib.i18n.tr(lib.i18n.lang_of(interaction), 'Something went wrong, sorry. The error was logged.')
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except Exception:
        log.debug('could not tell the user about the error', exc_info=True)


class CustomView(discord.ui.View):
    """base of all menus and buttons

    The message is edited with show(), through the latest interaction on it.
    A sub-menu is shown on the same message with open_child(), which returns
    once the sub-menu stops.
    """
    def __init__(self, *args, timeout=discord.utils.MISSING, **kwargs):
        if timeout is discord.utils.MISSING:
            timeout = MENU_TIMEOUT
        super().__init__(*args, timeout=timeout, **kwargs)

        self.value = None
        # first response of the menu (ctx.respond, channel.send),
        # for a timeout before anyone used it
        self.origin = None
        # latest click on this view, possibly not answered yet
        self.last_interaction: discord.Interaction = None
        # latest interaction that edited the message
        self._handle: discord.Interaction = None
        self._token_guard: asyncio.TimerHandle = None
        # True once this menu, or one of its sub-menus, timed out
        self.expired = False
        # when set, only this user can use the components
        # (needed for views attached to public messages)
        self.owner_id = None
        # the language of the user ('en', 'fr'), set_lang(); None: English
        self.lang = None

    def set_lang(self, lang):
        """show the buttons and dropdowns in that language: their English text is the key

        Texts set later (a button changing from Pause to Resume) are translated where they are set.
        """
        self.lang = lang
        for item in self.children:
            originals = getattr(item, '_english', None)
            if originals is None:
                originals = {attr: getattr(item, attr, None) for attr in ('label', 'placeholder')}
                item._english = originals
            for attr, text in originals.items():
                if isinstance(text, str):
                    setattr(item, attr, lib.i18n.tr(lang, text))
            options = getattr(item, 'options', None) or []
            if options:
                # new options: py-cord shares the ones of a decorated dropdown between all the menus,
                # changing them would show this language to everyone
                if getattr(item, '_english_options', None) is None:
                    item._english_options = [option.label for option in options]
                item.options = [discord.SelectOption(label=lib.i18n.tr(lang, english), value=option.value,
                                                     description=option.description, emoji=option.emoji,
                                                     default=option.default)
                                for option, english in zip(options, item._english_options)]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                lib.i18n.tr(lib.i18n.lang_of(interaction), 'Only the person who opened this menu can use it.'), ephemeral=True)
            return False
        self.last_interaction = interaction
        return True

    async def on_error(self, error: Exception, item, interaction: discord.Interaction):
        name = getattr(item, 'label', None) or getattr(item, 'placeholder', None) or type(item).__name__
        await report_error(error, interaction, f'{type(self).__name__} ({name})')

    def disable_all(self):
        """disable all components in this view
        """
        for child in self.children:
           # make all button childs gray
           if isinstance(child, discord.ui.Button):
               child.style = discord.ButtonStyle.secondary
           child.disabled = True


    def _edit_target(self):
        """what to edit the message with: the latest click while it is
           unanswered, else the latest interaction that edited the message
        """
        click = self.last_interaction
        if click is not None and not click.response.is_done():
            return click
        return self._handle or self.origin or click


    async def show(self, interaction: discord.Interaction = None, **kwargs):
        """edit the menu message (embed=..., view=...)

        through interaction when given (a click on this menu, or a popup opened
        from it), else through the latest interaction known
        """
        target = interaction or self._edit_target()
        if target is None:
            log.warning(f'{type(self).__name__}: no message to edit')
            return
        await edit_menu(target, **kwargs)
        if getattr(target, 'response', None) is not None:
            self._handle = target
            self._arm_token_guard()


    def _arm_token_guard(self):
        """close this menu before the token of _handle dies

        py-cord's timeout restarts with every click, also with clicks that only
        open a popup: those bring no new token to edit the message with
        """
        if self._token_guard is not None:
            self._token_guard.cancel()
        loop = asyncio.get_running_loop()
        self._token_guard = loop.call_later(TOKEN_LIFETIME, lambda: loop.create_task(self._token_expiring()))


    async def _token_expiring(self):
        if self.is_finished() or self.timeout is None:
            # over, or paused while one of its sub-menus shows (it has its own guard)
            return
        self.expired = True
        self.stop()
        await self.on_timeout()


    async def close(self, text: str):
        """end this menu and the ones it was opened from, with a message"""
        self.expired = True
        self.stop()
        await self.show(embed=discord.Embed(title=lib.i18n.tr(self.lang, 'Menu closed'),
                                            description=lib.i18n.tr(self.lang, text), color=0xff0000), view=None)


    async def open_child(self, interaction: discord.Interaction, child: 'CustomView', **kwargs) -> bool:
        """show the sub-menu child on this message and wait until it stops

        This menu doesn't time out meanwhile. Afterwards it continues through
        the latest clicks on the sub-menu: call show() to come back.

        Returns:
            bool: True if the sub-menu timed out. The whole menu is over then,
                  this one stops as well
        """
        if child.owner_id is None:
            child.owner_id = self.owner_id
        if child.lang is None and self.lang:
            child.set_lang(self.lang)

        own_timeout, self.timeout = self.timeout, None  # py-cord's timer ends on None
        try:
            await child.show(interaction or self._edit_target(), view=child, **kwargs)
            timed_out = await child.wait() or child.expired
        finally:
            # restarted when this menu is shown again
            self.timeout = own_timeout

        self.last_interaction = child.last_interaction or self.last_interaction
        self._handle = child._handle or self._handle
        if timed_out:
            self.expired = True
            self.stop()
        return timed_out


    async def on_timeout(self):
        self.expired = True
        self.disable_all()

        # self.message is set by py-cord: fine for public messages only
        for target in (self._handle, self.origin, self.message):
            if target is None:
                continue
            try:
                await edit_menu(target, view=self)
                return
            except Exception:
                continue
        log.debug(f'{type(self).__name__} timed out, could not disable its buttons')


    async def answer_expired(self, interaction: discord.Interaction, saved=False, info='') -> bool:
        """tell the user this menu is over (for popups submitted after the timeout)

        info: what the popup couldn't save

        Returns:
            bool: True if the menu is over
        """
        if not self.is_finished():
            return False
        lang = lib.i18n.lang_of(interaction)
        text = lib.i18n.tr(lang, 'Saved. ') if saved else ''
        text += lib.i18n.tr(lang, 'This menu has expired, open it again with `/reminder_list`.')
        if info:
            text += f'\n{info}'
        await interaction.response.send_message(text, ephemeral=True)
        return True




class AckView(CustomView):
    def __init__(self, dangerous_action=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.danger = dangerous_action
        if dangerous_action:
            self.ack.style = discord.ButtonStyle.danger

    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.success)
    async def ack(self, button:  discord.ui.Button, interaction: discord.Interaction):

        # but remove the other button this time
        self.disable_all()
        button.label = lib.i18n.tr(self.lang, 'Confirmed')
        button.style = discord.ButtonStyle.red if self.danger else discord.ButtonStyle.green
        self.children = [button]

        await self.show(interaction, view=self)

        self.value = True
        self.stop()



class ConfirmDenyView(AckView):
    def __init__(self, dangerous_action=False, *args, **kwargs):
        super().__init__(dangerous_action, *args , **kwargs)

    # This one is similar to the confirmation button except sets the inner value to `False`
    @discord.ui.button(label="Abort", style=discord.ButtonStyle.grey)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):

        # modify button colors
        self.disable_all()
        button.label = lib.i18n.tr(self.lang, 'Aborted')
        button.style = discord.ButtonStyle.danger

        await self.show(interaction, view=self)

        self.value = False
        self.stop()




class MulitDropdownView(CustomView):
    def __init__(self, dropdowns: list[discord.ui.Select], *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Adds the dropdown to our view object.
        for drop in dropdowns:
            drop.callback = self.callback
            self.add_item(drop)


    async def callback(self, interaction: discord.Interaction):

        values = interaction.data.get('values') or []
        if not values:
            # nothing selected, keep waiting for a choice
            await interaction.response.defer()
            return
        self.value = values[0]

        # find selected item and make it default
        # this is a workaround as disabling the item
        # resets the user selection
        self.disable_all()
        child = [x for x in self.children if x.custom_id == interaction.data['custom_id']][0]
        opt = [x for x in child.options if x.value==self.value][0]

        await self.show(interaction, view=self)
        # go ahead and disable the view
        opt.default = True
        self.stop()


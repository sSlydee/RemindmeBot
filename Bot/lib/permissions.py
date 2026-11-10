import discord

from util.consts import Consts


# commands usable everywhere once a user installed the app on their account:
# DMs, group DMs and servers the bot is not a member of
EVERYWHERE = {
    'integration_types': {discord.IntegrationType.guild_install, discord.IntegrationType.user_install},
    'contexts': {discord.InteractionContextType.guild,
                 discord.InteractionContextType.bot_dm,
                 discord.InteractionContextType.private_channel},
}


def is_personal_context(ctx) -> bool:
    """True where the bot cannot post later: DMs, group DMs, and servers in
       which only the user installed the app (the bot is not a member there)

    In those places reminders are private: delivered by DM, with the user's
    own timezone and settings.
    """
    interaction = getattr(ctx, 'interaction', ctx)
    if not interaction.guild_id:
        return True
    owners = interaction.authorizing_integration_owners
    if owners is None or (owners.guild_id is None and owners.user_id is None):
        # no install data: assume the bot is in the server (previous behaviour)
        return False
    return owners.guild_id != interaction.guild_id


def can_change_settings(user) -> bool:
    """server settings need the 'Manage Server' permission (administrators have it)

    Outside a server (DMs) the settings belong to the user.
    """
    if isinstance(user, discord.Member):
        return user.guild_permissions.manage_guild
    return True


def can_moderate(user, guild_id: int) -> bool:
    """moderators ('Manage Messages') see and delete all the reminders of their server"""
    return (isinstance(user, discord.Member) and user.guild.id == guild_id
            and user.guild_permissions.manage_messages)


def can_delete_reminder(rem, user) -> bool:
    """a reminder can be deleted by its author, by the member it is for
       (not a role) or mentions, and by the moderators of its server
    """
    if user.id in (rem.author, rem.target) or user.id in rem.mentioned_ids():
        return True
    return bool(rem.g_id) and can_moderate(user, rem.g_id)


def missing_settings_permission_embed() -> discord.Embed:
    return discord.Embed(title='Missing Permissions',
                         description='You need the `Manage Server` permission to change the settings of this server.',
                         color=Consts.col_err)

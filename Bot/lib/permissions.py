import discord

from util.consts import Consts


def can_change_settings(user) -> bool:
    """server settings need the 'Manage Server' permission (administrators have it)

    Outside a server (DMs) the settings belong to the user.
    """
    if isinstance(user, discord.Member):
        return user.guild_permissions.manage_guild
    return True


def missing_settings_permission_embed() -> discord.Embed:
    return discord.Embed(title='Missing Permissions',
                         description='You need the `Manage Server` permission to change the settings of this server.',
                         color=Consts.col_err)

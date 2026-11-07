import discord


class VerboseErrors:

    @staticmethod
    def _get_effective_permission(granted_perms: discord.Permissions, channel: discord.TextChannel, channel_overwrite, me_override = None):
        # check for overrides by 'channel'
        if channel_overwrite:
            # the list holds lowest permission at first index
            # apply channel-role from low-high onto the granted permissions
            # result after iteration is effective permissions for that channel
            if me_override:
                me = me_override
            else:
                me = channel.guild.me
            granted_perms = channel.permissions_for(me)

        return granted_perms


    @staticmethod
    def get_send_messages_perms():
        """get Permissions obj for send_messages

        Returns:
            [discord.Permissions]: has enough Perms for send_messages
        """
        return discord.Permissions(send_messages=True, read_messages=True)

    @staticmethod
    def can_send_messages(channel: discord.TextChannel, channel_overwrite = True, granted_perms: discord.Permissions = None, user_override = None):
        """shortcut for has_permissions with send_messages

        Args:
            channel (discord.TextChannel): channel for overwrite, supplies guild and channel permissions
            channel_overwrite (bool, optional): apply channel overwrite (for bot user). Defaults to True.
            granted_perms (discord.Permissions): override guild permissions of 'channel' of not None. Defaults to None
            user_override (discord.Member): evaluate permissions for the given user, not for the bot. Defaults to None (=Bot)

        Returns:
            [type]: true, if requested permissions are granted
        """
        return VerboseErrors.has_permission(VerboseErrors.get_send_messages_perms(), 
                    channel = channel, 
                    channel_overwrite= channel_overwrite, 
                    granted_perms = granted_perms,
                    user_override=user_override)

    @staticmethod
    def get_embed_perms():
        """get Permissions obj for embed_links

        Returns:
            [discord.Permissions]: has enough Perms for embed_links
        """
        return discord.Permissions(embed_links=True, send_messages=True, read_messages=True)

    @staticmethod
    def can_embed(channel: discord.TextChannel, channel_overwrite = True, granted_perms: discord.Permissions = None, user_override = None):
        """shortcut for has_permissions with embed_links

        Args:
            channel (discord.TextChannel): channel for overwrite, supplies guild and channel permissions
            channel_overwrite (bool, optional): apply channel overwrite (for bot user). Defaults to True.
            granted_perms (discord.Permissions): override guild permissions of 'channel' of not None. Defaults to None
            user_override (discord.Member): evaluate permissions for the given user, not for the bot. Defaults to None (=Bot)

        Returns:
            [type]: true, if requested permissions are granted
        """

        return VerboseErrors.has_permission(VerboseErrors.get_embed_perms(), 
                    channel = channel, 
                    channel_overwrite= channel_overwrite, 
                    granted_perms = granted_perms,
                    user_override=user_override)


    @staticmethod
    def has_permission(wanted_perms: discord.Permissions, channel: discord.TextChannel, channel_overwrite = True, granted_perms: discord.Permissions = None, user_override = None):
        """determin if bot has requested permissions (in a specific channel)

        Args:
            wanted_perms (discord.Permissions): requested permission
            channel (discord.TextChannel): channel for overwrite, supplies guild and channel permissions
            channel_overwrite (bool, optional): apply channel overwrite (for bot user). Defaults to True.
            granted_perms (discord.Permissions): override guild permissions of 'channel' of not None. Defaults to None
            user_override (discord.Member): evaluate permissions for the given user, not for the bot. Defaults to None (=Bot)

        Returns:
            [type]: true, if requested permissions are granted
        """

        if not granted_perms:
            granted_perms = channel.guild.me.guild_permissions

        effective = VerboseErrors._get_effective_permission(granted_perms, channel, channel_overwrite, me_override=user_override)

        return (wanted_perms <= effective) or effective.administrator


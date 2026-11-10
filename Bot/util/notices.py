"""Messages the bot sends on its own, outside of an interaction"""
import logging

import discord

import lib.text

log = logging.getLogger('Remindme.Notices')


async def tell_author_deleted(client, rem, by) -> bool:
    """DM the author of a reminder that someone else deleted (best effort)

    by: who deleted it (the member it was for or mentions, or a moderator)

    Returns:
        bool: True if the author got the message
    """
    if by.id == rem.author:
        return False

    name = discord.utils.escape_markdown(lib.text.shorten(rem.title or rem.msg or '', 100))
    guild = client.get_guild(rem.g_id) if rem.g_id else None
    where = f'#{rem.ch_name}' if rem.ch_name else 'by DM'
    if guild:
        where += f' on {discord.utils.escape_markdown(guild.name)}'
    by_name = getattr(by, 'display_name', None)
    who = f'{by.mention} ({discord.utils.escape_markdown(by_name)})' if isinstance(by_name, str) else by.mention
    eb = discord.Embed(title='Your reminder was deleted',
                       description=f'**{name}** ({where})\nDeleted by {who}.',
                       color=0x409fe2)
    try:
        author = client.get_user(rem.author) or await client.fetch_user(rem.author)
        await author.send(embed=eb)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
        # DMs closed, or the author left Discord: the log keeps who deleted it
        log.info(f'could not tell {rem.author} that reminder {rem._id} was deleted: {e!r}')
        return False
    except Exception:
        # the reminder is deleted already: never report this as a failed delete
        log.exception(f'could not tell {rem.author} that reminder {rem._id} was deleted')
        return False
    return True

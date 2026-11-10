from datetime import timedelta


class Consts:
    col_crit = 0xff0000
    col_err = 0xde4b55
    col_warn = 0xebb666
    col_good = 0x69eb67

    col_identity_blue = 0x409fe2

    # where users report bugs (this fork, not the public bot of the original author)
    github_url = 'https://github.com/sSlydee/RemindmeBot'

    # Discord error code: the user is not a member of the server
    unknown_member = 10007

    # a server that removed the bot: its data is kept that long, in case it comes back
    left_guild_keep = timedelta(days=7)
    col_identity_lime = 0xe4ff1e
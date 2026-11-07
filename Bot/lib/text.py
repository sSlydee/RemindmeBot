"""Discord message size limits"""

MAX_CONTENT = 2000      # characters of a message text
MAX_DESCRIPTION = 4096  # characters of an embed description


def shorten(text: str, limit: int) -> str:
    """text cut to at most limit characters, with … when cut"""
    if text is None or len(text) <= limit:
        return text
    return text[:limit - 1] + '…'


def split_message(text: str, limit: int = MAX_CONTENT) -> list[str]:
    """text in parts of at most limit characters, cut at a line break or a
       space when possible (Discord refuses longer messages)
    """
    parts = []
    text = text or ''
    while len(text) > limit:
        cut = text.rfind('\n', 0, limit + 1)
        if cut <= 0:
            cut = text.rfind(' ', 0, limit + 1)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip('\n ') if cut < len(text) else ''
    if text or not parts:
        parts.append(text)
    return parts

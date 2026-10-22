"""Post messages to Slack with a bot token (chat:write). No dependencies; one HTTPS call per message.

Settings (from .env): SLACK_BOT_TOKEN (xoxb-...) and SLACK_CHANNEL_ID (a channel ID like C0123ABCD,
which the bot must be a member of: /invite @PEAshooter).
"""

import json
import os
import urllib.request

API = "https://slack.com/api/chat.postMessage"
MAX_CHARS = 3500  # Slack truncates long messages; split on blank lines below this


class SlackError(Exception):
    pass


class Thread(str):
    """A message plus replies to post in its thread. Behaves as the full text when printed.

    `blocks`, if given, holds Block Kit for the main message and each reply in turn (None to send one as text);
    the text then becomes the notification fallback.
    """

    def __new__(cls, main: str, replies: tuple = (), blocks: tuple = ()):
        text = main + "".join(f"\n🧵 (in thread)\n{r}" for r in replies)
        obj = super().__new__(cls, text)
        obj.main, obj.replies, obj.blocks = main, tuple(replies), tuple(blocks)
        return obj


def post_thread(message, channel: str = "", token: str = "") -> list:
    """Post a Thread (main message, then each reply in its thread) or plain text."""
    if not isinstance(message, Thread):
        return post(message, channel, token)
    blocks = message.blocks + (None,) * (1 + len(message.replies) - len(message.blocks))
    stamps = post(message.main, channel, token, blocks=blocks[0])
    for reply, reply_blocks in zip(message.replies, blocks[1:]):
        stamps += post(reply, channel, token, thread_ts=stamps[0], blocks=reply_blocks)
    return stamps


def split_message(text: str, limit: int = MAX_CHARS) -> list:
    """Chunks under `limit`, split between paragraphs (then lines) so formatting stays intact."""
    chunks, current = [], ""
    for para in text.strip().split("\n\n"):
        pieces = [para] if len(para) <= limit else para.split("\n")
        for piece in pieces:
            sep = "\n\n" if piece is para else "\n"
            if current and len(current) + len(sep) + len(piece) > limit:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}{sep}{piece}" if current else piece
    return chunks + ([current] if current else [])


def post(text: str, channel: str = "", token: str = "", thread_ts: str = "", blocks: list = None) -> list:
    """Post `text` (Slack mrkdwn) as one or more messages, optionally as replies in a thread; returns timestamps.

    With `blocks`, it's one message: the blocks are what shows, and `text` is the notification fallback.
    """
    token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    channel = channel or os.environ.get("SLACK_CHANNEL_ID", "")
    if not token or not channel:
        raise SlackError("set SLACK_BOT_TOKEN and SLACK_CHANNEL_ID in .env")
    stamps = []
    for chunk in [text] if blocks else split_message(text):
        message = {"channel": channel, "text": chunk, "unfurl_links": False, "unfurl_media": False}
        if blocks:
            message["blocks"] = blocks
        if thread_ts:
            message["thread_ts"] = thread_ts
        body = json.dumps(message)
        request = urllib.request.Request(API, data=body.encode(), headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(request, timeout=30) as response:
            reply = json.load(response)
        if not reply.get("ok"):
            details = "; ".join(reply.get("response_metadata", {}).get("messages", []))
            raise SlackError(f"chat.postMessage failed: {reply.get('error')}" + (f" ({details})" if details else ""))
        stamps.append(reply["ts"])
    return stamps

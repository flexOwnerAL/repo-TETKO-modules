"""DonniAdmin — TETKO port of the original DonniAdmin module."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from telethon.errors import (
    ChatAdminRequiredError,
    UserAdminInvalidError,
    UserIdInvalidError,
)
from telethon.tl.functions.channels import EditBannedRequest, GetParticipantRequest
from telethon.tl.types import ChatBannedRights, ChannelParticipantCreator

from core.tetko import Module, command, db_get, db_set


__version__ = (1, 0, 0)

_TIME_RE = re.compile(
    r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?(?:(\d+)sec?)?",
    re.IGNORECASE,
)


def parse_duration(value: str) -> int | None:
    value = value.strip()
    match = _TIME_RE.fullmatch(value)
    if not match or not any(match.groups()):
        return None
    d, h, minutes, sec = (int(v) if v else 0 for v in match.groups())
    total = d * 86400 + h * 3600 + minutes * 60 + sec
    return total if total > 0 else None


def fmt_duration(seconds: int) -> str:
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if s:
        parts.append(f"{s}с")
    return " ".join(parts) if parts else f"{seconds}с"


def parse_time_and_reason(args: list[str]) -> tuple[int | None, str]:
    if not args:
        return None, ""

    duration = parse_duration(args[0])
    if duration is not None:
        return duration, " ".join(args[1:]).strip()

    return None, " ".join(args).strip()


def until_timestamp(duration: int | None) -> int | None:
    if duration is None:
        return None
    return int((datetime.now(timezone.utc) + timedelta(seconds=duration)).timestamp())


def warn_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


class DonniAdmin(Module):
    name = "DonniAdmin"
    __compat__ = "0.0.9.0"
    version = "1.0.0"
    author = "@anhedonuya; porting by @flexOwnerAL"
    description = {
        "ru": "Инструменты администратора: mute, ban, warn, kick.",
        "en": "Admin tools: mute, ban, warn, kick.",
    }

    config = {
        "max_warns": 3,
        "warn_ban_duration": 0,
        "notify_on_action": True,
        "delete_command": True,
    }

    def __init__(self, kernel=None):
        super().__init__(kernel)
        self._warns: dict[str, int] = {}

    async def on_load(self):
        self._warns = db_get(self.name, "warns", {}) or {}
        self.log.info("DonniAdmin загружен (TETKO port by @flexOwnerAL)")

    async def on_unload(self):
        db_set(self.name, "warns", self._warns)

    def _user_mention(self, user) -> str:
        name = getattr(user, "first_name", None) or getattr(user, "title", None) or str(user.id)
        return f'<a href="tg://user?id={user.id}">{name}</a>'

    def _reason(self, reason: str) -> str:
        return f"\n📝 <b>Причина:</b> {reason}" if reason else ""

    def _args(self, args: list[str]) -> list[str]:
        return args or []

    async def _get_reply_user(self, event):
        reply = await event.get_reply_message()
        if not reply:
            return None, None
        try:
            user = await self.client.get_entity(reply.sender_id)
            return reply, user
        except Exception:
            return reply, None

    async def _check_can_act(self, event, user) -> bool:
        try:
            me = await self.client.get_me()
            if user.id == me.id:
                return False

            part = await self.client(GetParticipantRequest(event.chat_id, user.id))
            if isinstance(part.participant, ChannelParticipantCreator):
                return False
        except Exception:
            pass
        return True

    async def _notify(self, event, text: str):
        if self.cfg.get("notify_on_action", True):
            await self.client.send_message(event.chat_id, text, parse_mode="html")

        if self.cfg.get("delete_command", True):
            try:
                await event.delete()
            except Exception:
                pass

    async def _error(self, event, exc: Exception):
        if isinstance(exc, ChatAdminRequiredError):
            text = "❌ <b>У меня нет прав администратора или недостаточно полномочий.</b>"
        elif isinstance(exc, UserAdminInvalidError):
            text = "❌ <b>Нельзя применить действие к этому пользователю.</b>"
        elif isinstance(exc, UserIdInvalidError):
            text = "❌ <b>Пользователь не найден в чате.</b>"
        else:
            text = f"❌ <b>{type(exc).__name__}:</b> <code>{exc}</code>"
        await event.edit(text, parse_mode="html")

    @staticmethod
    def _is_group(event) -> bool:
        return bool(event.is_group or event.is_channel)

    @command(
        name="mute",
        description="[время] [причина] — заглушить пользователя (ответ на сообщение)",
    )
    async def mute_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return

        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return
        if not await self._check_can_act(event, user):
            await event.edit("❌ <b>Нельзя применить действие к этому пользователю.</b>", parse_mode="html")
            return

        duration, reason = parse_time_and_reason(self._args(args))
        rights = ChatBannedRights(
            until_date=until_timestamp(duration),
            send_messages=True,
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True,
            embed_links=True,
        )

        try:
            await self.client(EditBannedRequest(event.chat_id, user.id, rights))
            mention = self._user_mention(user)
            reason_text = self._reason(reason)
            if duration:
                text = f"🔇 <b>Пользователь {mention} заглушён на {fmt_duration(duration)}.</b>{reason_text}"
            else:
                text = f"🔇 <b>Пользователь {mention} заглушён навсегда.</b>{reason_text}"
            await self._notify(event, text)
        except Exception as exc:
            await self._error(event, exc)

    @command(name="unmute", description="снять мут (ответ на сообщение)")
    async def unmute_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return

        try:
            await self.client(EditBannedRequest(event.chat_id, user.id, ChatBannedRights(until_date=None)))
            await self._notify(event, f"🔊 <b>Пользователь {self._user_mention(user)} размучен.</b>")
        except Exception as exc:
            await self._error(event, exc)

    @command(name="ban", description="[время] [причина] — заблокировать пользователя (ответ на сообщение)")
    async def ban_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return
        if not await self._check_can_act(event, user):
            await event.edit("❌ <b>Нельзя применить действие к этому пользователю.</b>", parse_mode="html")
            return

        duration, reason = parse_time_and_reason(self._args(args))
        rights = ChatBannedRights(until_date=until_timestamp(duration), view_messages=True)

        try:
            await self.client(EditBannedRequest(event.chat_id, user.id, rights))
            mention = self._user_mention(user)
            reason_text = self._reason(reason)
            if duration:
                text = f"🔨 <b>Пользователь {mention} заблокирован на {fmt_duration(duration)}.</b>{reason_text}"
            else:
                text = f"🔨 <b>Пользователь {mention} заблокирован навсегда.</b>{reason_text}"
            await self._notify(event, text)
        except Exception as exc:
            await self._error(event, exc)

    @command(name="unban", description="разблокировать пользователя (ответ на сообщение)")
    async def unban_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return

        try:
            await self.client(EditBannedRequest(event.chat_id, user.id, ChatBannedRights(until_date=None)))
            await self._notify(event, f"✅ <b>Пользователь {self._user_mention(user)} разблокирован.</b>")
        except Exception as exc:
            await self._error(event, exc)

    @command(name="kick", description="[причина] — кикнуть пользователя из чата (ответ на сообщение)")
    async def kick_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return
        if not await self._check_can_act(event, user):
            await event.edit("❌ <b>Нельзя применить действие к этому пользователю.</b>", parse_mode="html")
            return

        reason = " ".join(self._args(args)).strip()
        try:
            await self.client.kick_participant(event.chat_id, user.id)
            await self._notify(
                event,
                f"👟 <b>Пользователь {self._user_mention(user)} кикнут из чата.</b>{self._reason(reason)}",
            )
        except Exception as exc:
            await self._error(event, exc)

    @command(name="warn", description="[время_бана] [причина] — выдать предупреждение (ответ на сообщение)")
    async def warn_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return
        if not await self._check_can_act(event, user):
            await event.edit("❌ <b>Нельзя применить действие к этому пользователю.</b>", parse_mode="html")
            return

        duration, reason = parse_time_and_reason(self._args(args))
        key = warn_key(event.chat_id, user.id)
        self._warns[key] = int(self._warns.get(key, 0)) + 1
        count = self._warns[key]
        max_warns = int(self.cfg.get("max_warns", 3))
        db_set(self.name, "warns", self._warns)

        mention = self._user_mention(user)
        reason_text = self._reason(reason)

        if count >= max_warns:
            ban_duration = duration or int(self.cfg.get("warn_ban_duration", 0)) or None
            try:
                await self.client(
                    EditBannedRequest(
                        event.chat_id,
                        user.id,
                        ChatBannedRights(until_date=until_timestamp(ban_duration), view_messages=True),
                    )
                )
            except Exception as exc:
                await self._error(event, exc)
                return

            self._warns[key] = 0
            db_set(self.name, "warns", self._warns)
            await self._notify(event, f"🔨 <b>Пользователь {mention} превысил лимит предупреждений и заблокирован.</b>")
            return

        await self._notify(
            event,
            f"⚠️ <b>Пользователь {mention} получил предупреждение {count}/{max_warns}.</b>{reason_text}",
        )

    @command(name="unwarn", description="сбросить предупреждения пользователя (ответ на сообщение)")
    async def unwarn_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return

        key = warn_key(event.chat_id, user.id)
        self._warns.pop(key, None)
        db_set(self.name, "warns", self._warns)
        await self._notify(event, f"✅ <b>Предупреждения пользователя {self._user_mention(user)} сброшены.</b>")

    @command(name="warns", description="посмотреть предупреждения пользователя (ответ на сообщение)")
    async def warns_cmd(self, event, args):
        if not self._is_group(event):
            await event.edit("❌ <b>Команда работает только в группах.</b>", parse_mode="html")
            return
        _, user = await self._get_reply_user(event)
        if not user:
            await event.edit("❌ <b>Ответь на сообщение пользователя.</b>", parse_mode="html")
            return

        key = warn_key(event.chat_id, user.id)
        count = int(self._warns.get(key, 0))
        mention = self._user_mention(user)
        if count == 0:
            await event.edit(f"✅ <b>У пользователя {mention} нет предупреждений.</b>", parse_mode="html")
        else:
            await event.edit(
                f"⚠️ <b>Предупреждения {mention}: {count}/{int(self.cfg.get('max_warns', 3))}</b>",
                parse_mode="html",
            )
from __future__ import annotations

import asyncio
import html
import random

from telethon import events
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    RPCError,
)

from core.tetko import Module, command


class RandomEdits(Module):
    name = "RandomEdits"
    __compat__ = "0.0.9.0"
    version = "1.0.5"
    author = "@modulesanhedonuya && @flexOwnerAL"
    description = "Отправляет случайный эдит"

    async def on_load(self) -> None:
        self.cfg.set("channel", self.cfg.get("channel", "randomeditsforme"))
        self.cfg.set("sample_limit", self.cfg.get("sample_limit", 500))

    def _text(self, key: str, **kwargs) -> str:
        strings = {
            "pick": "Ищу случайный эдит...",
            "done": "Готово.",
            "no_posts": "Не удалось найти подходящий эдит.",
            "bad_channel": "Не удалось получить доступ к каналу с эдитами.",
            "protected": "Этот пост защищён от копирования.",
            "flood": "Telegram попросил подождать {seconds} сек.",
            "rpc_error": "Ошибка Telegram: {error}",
            "unknown_error": "Неизвестная ошибка: {error}",
        }

        return strings.get(key, key).format(**kwargs)

    async def _edit_status(self, message, text: str):
        try:
            return await message.edit(text)
        except Exception:
            return message

    async def _send_random_post(
        self,
        chat_id,
        reply_to=None,
    ) -> tuple[bool, str | None]:
        channel = self.cfg.get("channel", "randomeditsforme")
        sample_limit = int(self.cfg.get("sample_limit", 500))

        if not channel:
            return False, self._text("bad_channel")

        try:
            entity = await self.client.get_entity(channel)

            messages = []

            async for message in self.client.iter_messages(
                entity,
                limit=sample_limit,
            ):
                # Берём только сообщения, которые можно переслать.
                if message and not getattr(message, "noforwards", False):
                    messages.append(message)

            if not messages:
                return False, self._text("no_posts")

            selected = random.choice(messages)

            await self.client.send_message(
                chat_id,
                file=selected.media if selected.media else None,
                message=selected.message or "",
                reply_to=reply_to,
            )

            return True, None

        except (ChannelPrivateError, ChannelInvalidError):
            raise

        except ValueError:
            raise

    @command(
        "randomedit",
        description="Отправить случайный эдит",
        only_for="owner",
    )
    async def cmd_randomedit(
        self,
        event: events.NewMessage.Event,
    ) -> None:
        status = await event.reply(self._text("pick"))

        try:
            ok, error_text = await self._send_random_post(
                event.chat_id,
                reply_to=getattr(event, "reply_to_msg_id", None),
            )

            if not ok:
                await self._edit_status(
                    status,
                    error_text or self._text("no_posts"),
                )
                return

            await self._edit_status(status, self._text("done"))

            await asyncio.sleep(3)

            try:
                await status.delete()
            except Exception:
                pass

        except (
            ChannelPrivateError,
            ChannelInvalidError,
            ValueError,
        ) as exc:
            self.log.warning(
                "RandomEdits source channel is unavailable: %s",
                exc,
            )

            await self._edit_status(
                status,
                self._text("bad_channel"),
            )

        except FloodWaitError as exc:
            seconds = getattr(exc, "seconds", 0)

            self.log.warning(
                "RandomEdits hit Telegram flood wait: %s",
                seconds,
            )

            await self._edit_status(
                status,
                self._text(
                    "flood",
                    seconds=seconds,
                ),
            )

        except RPCError as exc:
            self.log.warning(
                "RandomEdits Telegram RPC error: %s",
                exc,
            )

            error_text = str(exc)
            lowered = error_text.lower()

            if (
                "protected" in lowered
                or "forbidden" in lowered
                or "copy" in lowered
            ):
                await self._edit_status(
                    status,
                    self._text("protected"),
                )
                return

            await self._edit_status(
                status,
                self._text(
                    "rpc_error",
                    error=html.escape(error_text),
                ),
            )

        except Exception as exc:
            self.log.exception(
                "Unexpected RandomEdits error"
            )

            await self._edit_status(
                status,
                self._text(
                    "unknown_error",
                    error=html.escape(str(exc)),
                ),
            )

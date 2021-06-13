# This is part of Requiem
# Copyright (C) 2020  God Empress Verin

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


from core import config, models, constants
from discord.ext import commands
from aiocache import Cache

import contextlib
import traceback
import tortoise
import logging
import discord
import random
import sys
import os
import io


_LOGGER = logging.getLogger("requiem.client")


class Requiem(commands.AutoShardedBot):
    """
    Custom Requiem client based on <discord.ext.commands.AutoShardedBot>.
    """

    def __init__(self, credentials: config.Config) -> None:
        """
        Inits Requiem. Sets up required intents.
        """

        intents = discord.Intents.all()
        intents.members = True

        super().__init__(command_prefix=credentials.default_prefix, intents=intents)

        self.credentials = credentials

        self.cache = Cache(Cache.MEMORY)

    async def start(self, *args, **kwargs) -> None:
        """
        Inserts plugin loading into start coroutine.
        """
        plugins = (
            plugin.replace(".py", "")
            for plugin in os.listdir("plugins")
            if plugin not in ("__init__.py", "__pycache__")
        )

        for plugin in plugins:
            try:
                self.load_extension(f"plugins.{plugin}")
                _LOGGER.info("requiem has successfully loaded the plugin <%s>!", plugin)

            except Exception as exc:
                await self.report_error(exc)

        await super().start(*args, **kwargs)

    async def close(self) -> None:
        """
        Shuts the bot down and closes connection to tortoise.
        """
        _LOGGER.info("requiem is shutting down!")
        await super().close()
        await tortoise.Tortoise.close_connections()

    async def get_context(self, message: discord.Message, *, cls=commands.Context) -> commands.Context:
        """
        Overwrites default get_context method to insert context colour.
        """
        ctx = await super().get_context(message)
        ctx.colour = await self.get_colour(message)
        return ctx

    async def get_prefix(self, message: discord.Message) -> str:
        """
        Fetches string prefix and determines if a string or mention prefix will be used for command invocation.
        """
        string_prefix = await self.get_string_prefix(message)
        return commands.when_mentioned_or(string_prefix)(self, message)

    async def get_string_prefix(self, message: discord.Message) -> str:
        """
        Fetches string prefix using message context.
        """
        if message.guild:
            data = await self.cache.get(message.guild.id, default={"prefix": self.command_prefix})
            prefix = data["prefix"]
        else:
            prefix = self.command_prefix

        return prefix

    async def get_colour(self, message: discord.Message) -> discord.Colour:
        """
        Fetches embed colour using message context.
        """
        if message.guild:
            data = await self.cache.get(message.guild.id, default={"colour": "purple"})
            colour = data["colour"]
        else:
            colour = "purple"

        return constants.colours[colour]()

    async def state_prefix(self, message: discord.Message) -> None:
        """
        States the given prefix using a random satire string.
        """
        prefix = await self.get_string_prefix(message)
        colour = await self.get_colour(message)
        response = random.choice(constants.prefix_responses)(prefix)
        embed = discord.Embed(description=response, colour=colour)
        await message.channel.send(embed=embed)

    async def report_error(self, exc: Exception) -> None:
        """
        Reports error occurrences to owners and console.
        """
        _LOGGER.error("requiem has encountered an exception!", exc_info=exc)

        if not self.credentials.report_errors:
            return

        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        string_io = io.StringIO("".join(tb))
        file = discord.File(fp=string_io, filename="error_report.txt")

        for owner_id in self.owner_ids:
            if owner := self.get_user(owner_id):
                with contextlib.suppress(discord.Forbidden, discord.NotFound):
                    await owner.send(file=file)

    async def on_command_completion(self, ctx: commands.Context) -> None:
        """
        Logs successful command execution to console.
        """
        _LOGGER.info("command <%s> executed successfully!", ctx.command)

    async def on_command_error(self, ctx: commands.Context, exc: Exception) -> None:
        """
        Catches and reports or handles unhandled command exceptions.
        """
        exc_name = exc.__class__.__name__

        if isinstance(exc, commands.CommandNotFound):
            return

        elif isinstance(exc, commands.CheckFailure):
            return

        elif isinstance(exc, commands.CommandInvokeError):
            await self.report_error(exc)
            response = random.choice(constants.unhandled_errors)

        elif exc_name in constants.handled_errors:
            response = constants.handled_errors.get(exc_name)(ctx, exc)

        else:
            return

        embed = discord.Embed(description=response, colour=discord.Colour.red())
        await ctx.send(embed=embed)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """
        Catches and reports unhandled exceptions raised by event methods.
        """
        _, exc, _ = sys.exc_info()
        await self.report_error(exc)

    async def on_ready(self) -> None:
        """
        Logs ready state to console.
        """
        _LOGGER.info("requiem is logged in as <%s:%s>!", self.user.name, self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        """
        Responds to prefix requests or calls process commands.
        """
        bot_mentions = (self.user.mention, '<@!%s>' % self.user.id)

        if message.content in bot_mentions:
            if self.credentials.prefix_on_mention:
                await self.state_prefix(message)

        else:
            await self.process_commands(message)

    async def on_message_edit(self, message: discord.Message, message_edit: discord.Message) -> None:
        """
        Calls on_message on message edit.
        """
        await self.on_message(message_edit)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """
        Handles guild config creation on guild join.
        """
        saved, created = await models.Guilds.get_or_create(
            defaults={"prefix": self.credentials.default_prefix}, snowflake=guild.id
        )
        data = await self.cache.get(guild.id)

        if created:
            _LOGGER.info("requiem has created a config entry for guild <%s>!", guild.id)

        if not data:
            data = {"prefix": saved.prefix, "colour": saved.colour}
            await self.cache.add(guild.id, data)

    async def on_guild_available(self, guild: discord.Guild) -> None:
        """
        Handles guild config creation for missed guilds on bot start.
        """
        await self.on_guild_join(guild)
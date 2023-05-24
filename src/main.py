import discord
from discord import Message as DiscordMessage
from discord.ext import tasks
import logging
import subprocess
from src.base import Message, Conversation
from src.constants import (
    BOT_INVITE_URL,
    DISCORD_BOT_TOKEN,
    # EXAMPLE_CONVOS,
    ACTIVATE_THREAD_PREFX,
    MAX_THREAD_MESSAGES,
    SECONDS_DELAY_RECEIVING_MSG,
    OPENAI_API_KEY,
    ALLOWED_SERVER_IDS
)
import asyncio
from src.utils import (
    logger,
    should_block,
    close_thread,
    is_last_message_stale,
    discord_message_to_message,
)
from src import completion
from src.completion import generate_completion_response, process_response
from src.moderation import (
    moderate_message,
    send_moderation_blocked_message,
    send_moderation_flagged_message,
)
token_usage = 0
logging.basicConfig(
    format="[%(asctime)s] [%(filename)s:%(lineno)d] %(message)s", level=logging.INFO
)
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


from src.arxiv2discord.interface import ArxivInterface 
arxiv_interface = ArxivInterface()

from google.cloud import datastore
data_client = datastore.Client()
query = data_client.query()
query.keys_only()

async def access_datastore(timestamp):
    with data_client.transaction():
        key = data_client.key(
            "message", timestamp.isoformat()
        )
        try:
            entity = data_client.get(key)
        except Exception as e:
            logger.exception(e)
            return False
        if not entity:
            entity = datastore.Entity(key)
            # task.update({"description": "Example task"})
            data_client.put(entity)
            return True
        else:
            return False
    return False
# commands =["gunicorn","-b",":$PORT","src.dummy_server:app"]
# subprocess.Popen(commands,shell=False)

@client.event
async def on_ready():
    logger.info(f"We have logged in as {client.user}. Invite URL: {BOT_INVITE_URL}")
    completion.MY_BOT_NAME = client.user.name
    # client.loop.create_task(get_token_count())
    await tree.sync()

# /chat message:
@tree.command(name="chat", description="Create a new thread for conversation")
@discord.app_commands.checks.has_permissions(send_messages=True)
@discord.app_commands.checks.has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(send_messages=True)
@discord.app_commands.checks.bot_has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(manage_threads=True)
async def chat_command(int: discord.Interaction, message: str):

    try:
        # only support creating thread in text channel
        if not isinstance(int.channel, discord.TextChannel):
            return

        # block servers not in allow list
        if should_block(guild=int.guild):
            return
        # int.response.defer()
        user = int.user
        logger.info(f"Chat command by {user} {message[:20]}")
        try:
            embed = discord.Embed(
                description=f"<@{user.id}> wants to chat! 🤖💬",
                color=discord.Color.green(),
            )
            embed.add_field(name=user.global_name, value=message)

            await int.response.send_message(embed=embed)
            response = await int.original_response()

        except Exception as e:
            logger.exception(e)
            await int.response.send_message(
                f"Failed to start chat {str(e)},{int.is_expired()}", ephemeral=True
            )
            return
        # create the thread
        thread = await response.create_thread(
            name=f"{ACTIVATE_THREAD_PREFX} {user.global_name[:20]} - {message[:30]}",
            slowmode_delay=1,
            reason="gpt-bot",
            auto_archive_duration=60,
        )
        async with thread.typing():
            # fetch completion
            messages = [Message(user=user.global_name, text=message)]
            response_data = await generate_completion_response(
                messages=messages, user=user
            )
            print(response_data)
            if response_data.tokens != None:
                await token_usage_changed(response_data.tokens)
            else:
                print("response_data.tokens!= None")
            # send the result
            await process_response(
                user=user, thread=thread, response_data=response_data
            )
    except Exception as e:
        logger.exception(e)
        await int.response.send_message(
            f"Failed to start chat {str(e)}", ephemeral=True
        )


# calls for each message
@client.event
async def on_message(message: DiscordMessage):
    if not await access_datastore(message.created_at):
        print("return: instance conflicted")
        return
    try:
        # block servers not in allow list
        if should_block(guild=message.guild):
            return

        # ignore messages from the bot
        if message.author == client.user:
            return

        # ignore messages not in a thread
        channel = message.channel
        if not isinstance(channel, discord.Thread):
            return

        # ignore threads not created by the bot
        thread = channel
        if thread.owner_id != client.user.id:
            return

        # ignore threads that are archived locked or title is not what we want
        if (
            thread.archived
            or thread.locked
            or not thread.name.startswith(ACTIVATE_THREAD_PREFX)
        ):
            # ignore this thread
            return

        if thread.message_count > MAX_THREAD_MESSAGES:
            # too many messages, no longer going to reply
            await close_thread(thread=thread)
            return

        # wait a bit in case user has more messages
        if SECONDS_DELAY_RECEIVING_MSG > 0:
            await asyncio.sleep(SECONDS_DELAY_RECEIVING_MSG)
            if is_last_message_stale(
                interaction_message=message,
                last_message=thread.last_message,
                bot_id=client.user.id,
            ):
                # there is another message, so ignore this one
                return

        logger.info(
            f"Thread message to process - {message.author}: {message.content[:50]} - {thread.name} {thread.jump_url}"
        )

        channel_messages = [
            discord_message_to_message(message)
            async for message in thread.history(limit=MAX_THREAD_MESSAGES)
        ]
        channel_messages = [x for x in channel_messages if x is not None]
        channel_messages.reverse()

        # generate the response
        async with thread.typing():
            response_data = await generate_completion_response(
                messages=channel_messages, user=message.author
            )
            print(response_data)
            if response_data.tokens != None:
                await token_usage_changed(response_data.tokens)
            else:
                print("response_data.tokens!= Nones")

        if is_last_message_stale(
            interaction_message=message,
            last_message=thread.last_message,
            bot_id=client.user.id,
        ):
            # there is another message and its not from us, so ignore this response
            return

        # send response
        await process_response(
            user=message.author, thread=thread, response_data=response_data
        )
    except Exception as e:
        logger.exception(e)


@tasks.loop(hours=2)
async def send_paper_summary():
    token_used = await arxiv_interface.run()
    await token_usage_changed(token_used)

@tree.command(name="startpaper", description=" Start sending summary of latest papers in this channel")
async def startpaper_command(int: discord.Interaction):
    arxiv_interface.set_channel(int.channel)
    send_paper_summary.start()

async def token_usage_changed(token_used):
    global token_usage
    token_usage += token_used
    cost = token_usage/1000*0.002
    name = "GPT-chan [%.3f$/10.00$]" %(cost)
    guild = client.get_guild(ALLOWED_SERVER_IDS[0])
    await guild.me.edit(nick=name)

client.run(DISCORD_BOT_TOKEN)
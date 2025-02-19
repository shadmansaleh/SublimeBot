import logging
import os
import time

import discord as ds
from discord.ext import commands
from dotenv import load_dotenv

from keep_alive import keep_alive
from services.api import cf
from services.db import duels_db, handles_db
from utils import get_duel_prob, get_prob

bot = commands.Bot(command_prefix=".", intents=ds.Intents.all(), help_command=None)

logger = logging.getLogger("discord")
logger.name = "SublimeBot"

load_dotenv(".env")

DESCRIPTIONS = {
    "handle_set": "Set or update handle",
    "handle_list": "Lists all registered handles in this server (incognito)",
    "duel": "Challenge someone for a duel (mentions opponent)",
    "accept": "Accept a duel",
    "drop": "Drop a duel",
    "complete": "Complete a duel",
    "gimme": "Chanllage yourself with a problem",
    "help": "Shows all commands (incognito)",
}

HELP = {
    "handle_set `handlle`": "Set or update your own handle",
    "handle_list": "Lists all registered handles in this server, in alphabetic order (incognito)",
    "duel `opponent` `rating`": "Challenge `opponent` with a duel (mentions opponent)",
    # "duel_list": "List all duels (ongoing and challenged)",
    "accept": "Accept a duel",
    "drop": "Drop a duel",
    "complete": "Complete a duel",
    "gimme `rating`": "Challange yourself with a problem",
    "help": "Shows this message",
}


@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    logger.info(f"Number of slash commands synced: {len(synced)}")


@bot.tree.command(description=DESCRIPTIONS["handle_set"])
async def handle_set(itr: ds.Interaction, handle: str):
    """
    :param handle: Codeforces handle of the member
    """
    embed = ds.Embed()

    # show error if handle does not exist
    if not cf.handle_exists(handle):
        embed.description = f"Could not find handle, {handle} in CF"
        embed.color = ds.Color.red()
    else:
        handles_db.set_or_update_handle(handle, itr.user.id)
        embed.description = f"Handle of {itr.user.mention} set to {handle}"
        embed.color = ds.Color.green()

    await itr.response.send_message(embed=embed)


@bot.tree.command(description=DESCRIPTIONS["handle_list"])
async def handle_list(itr: ds.Interaction):
    uids, handles = handles_db.get_all_uid_handle()
    rows = []

    # only show hanldes of users who are present in the server
    for uid, handle in zip(uids, handles):
        user = itr.guild.get_member(uid)
        if user != None:
            rows.append((user.display_name.lower(), user.mention, handle))
    rows.sort(key=lambda x: x[0])
    embed = ds.Embed()
    # if no users found, show error
    if not rows:
        embed.description = (
            "No handle found.\n:point_right: Type `/handleset` to set handle"
        )
        embed.color = ds.Color.red()
    else:
        embed.title = "List of all handles (sorted)"
        embed.description = "\n".join([f"{row[1]} — {row[2]}" for row in rows])
    await itr.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(description=DESCRIPTIONS["duel"])
async def duel(itr: ds.Interaction, opponent: ds.Member, rating: int):
    """
    :param opponent: Member of the server you want to challenge
    :param rating: Rating of the problem
    """
    uid1 = itr.user.id
    uid2 = opponent.id
    embed = ds.Embed(description="Proposing a duel ...")
    await itr.response.send_message(embed=embed, ephemeral=True)
    embed.color = ds.Color.red()
    embed.description = None
    message_content = None
    ephemeral = False
    if uid1 == uid2:
        embed.description = "You cannot challenge yourself for a duel"
        ephemeral = True
    elif not handles_db.uid_exists(uid1):
        embed.description = (
            "Could not find your handle in the database\n"
            ":point_right:  Type `/handle_set` to set your handle"
        )
        ephemeral = True
    elif not handles_db.uid_exists(uid2):
        embed.description = (
            f"Could not find {opponent.mention}'s handle in the database\n"
            ":point_right:  Type `/handle_set` to set your handle"
        )
    elif rating not in range(800, 3600, 100):
        embed.description = f"Rating must be a multiple of 100 between 800 and 3500"
        ephemeral = True
    elif duels_db.duel_exists(itr.guild_id, itr.channel_id, uid1):
        embed.description = (
            "You are already in a duel\n"
            ":point_right:  Type `/drop` to drop the duel"
            # ":point_right:  Type `/duel_list` to list all duels"
        )
        ephemeral = True
    elif duels_db.duel_exists(itr.guild_id, itr.channel_id, uid2):
        embed.description = (
            f"{opponent.mention} is already in a duel\n"
            ":point_right:  Type `/drop` to drop the duel"
            # ":point_right:  Type `/duel_list` to list all duels"
        )
    else:
        duels_db.new(itr.guild_id, itr.channel_id, uid1, uid2, rating)
        message_content = opponent.mention
        embed.title = f"{opponent.display_name}, are you up for a duel?\n"
        embed.add_field(name="Opponent", value=itr.user.mention)
        embed.add_field(name="rating", value=rating)
        embed.color = None
        embed.set_footer(text="Type /accept to accept the duel")
    await itr.followup.send(
        content=message_content,
        embed=embed,
        ephemeral=ephemeral,
    )


@bot.tree.command(description=DESCRIPTIONS["accept"])
async def accept(itr: ds.Interaction):
    embed = ds.Embed(color=ds.Color.red())
    ephemeral = False
    message_content = None
    uid2 = itr.user.id

    if not duels_db.duel_exists(itr.guild_id, itr.channel_id, uid2=uid2):
        embed.description = "No one challenged you for a duel"
        ephemeral = True
        await itr.response.send_message(
            content=message_content, embed=embed, ephemeral=ephemeral
        )
    elif duels_db.duel_is_ongoing(itr.guild_id, itr.channel_id, uid2=uid2):
        embed.description = "You are already in a duel"
        ephemeral = True
        await itr.response.send_message(
            content=message_content, embed=embed, ephemeral=ephemeral
        )
    else:
        embed.description = "Searching a good problems for you ..."
        embed.color = None
        await itr.response.send_message(embed=embed, ephemeral=True)
        duel_details = duels_db.get_duel_details(
            itr.guild_id, itr.channel_id, uid2=uid2
        )
        uid1 = duel_details["uid1"]
        rating = duel_details["rating"]

        contestId, index, prob_name = get_duel_prob(uid1, uid2, rating)
        duels_db.add_problem_and_time(
            itr.guild_id, itr.channel_id, uid1, contestId, index, int(time.time())
        )
        u1_mention = itr.guild.get_member(uid1).mention
        u2_mention = itr.user.mention
        problem_url = f"https://codeforces.com/problemset/problem/{contestId}/{index}"

        message_content = u1_mention
        embed.title = "Duel started!"
        embed.description = f"{u1_mention} :crossed_swords: {u2_mention}"
        embed.add_field(name="Rating", value=rating)
        embed.add_field(name="Problem URL", value=problem_url, inline=False)
        embed.set_footer(text="Type /complete after completing the challenge")
        await itr.followup.send(
            content=message_content,
            embed=embed,
            ephemeral=ephemeral,
        )
        cf.set_problemset_json()


@bot.tree.command(description=DESCRIPTIONS["drop"])
async def drop(itr: ds.Interaction):
    embed = ds.Embed()
    ephemeral = False
    if duels_db.duel_exists(itr.guild_id, itr.channel_id, uid=itr.user.id):
        duel_details = duels_db.get_duel_details(
            itr.guild_id, itr.channel_id, uid=itr.user.id
        )
        u1 = itr.guild.get_member(duel_details["uid1"])
        u2 = itr.guild.get_member(duel_details["uid2"])
        duels_db.drop(itr.guild_id, itr.channel_id, itr.user.id)
        embed.title = "Duel dropped"
        embed.add_field(
            name="Duel",
            value=f"{u1.mention} :crossed_swords: {u2.mention}",
            inline=False,
        )
        embed.add_field(name="Dropped by", value=itr.user.mention)
    else:
        embed.description = "No duel to drop"
        embed.color = ds.Color.red()
        ephemeral = True
    await itr.response.send_message(embed=embed, ephemeral=ephemeral)


@bot.tree.command(description=DESCRIPTIONS["complete"])
async def complete(itr: ds.Interaction):
    embed = ds.Embed(color=ds.Color.red())
    ephemeral = True
    if not duels_db.duel_is_ongoing(itr.guild_id, itr.channel_id, uid=itr.user.id):
        embed.description = "You are not in an ongoing duel"
        await itr.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        embed.description = "This might take a while ..."
        await itr.response.send_message(embed=embed, ephemeral=ephemeral)
        duel_details = duels_db.get_duel_details(
            itr.guild_id, itr.channel_id, uid=itr.user.id
        )
        contestId = duel_details["contestId"]
        index = duel_details["index"]
        prob = (contestId, index)
        uid1 = duel_details["uid1"]
        uid2 = duel_details["uid2"]
        u1 = itr.guild.get_member(uid1)
        u2 = itr.guild.get_member(uid2)
        handle1 = handles_db.uid2handle(uid1)
        handle2 = handles_db.uid2handle(uid2)
        creationTime1 = cf.get_all_accepted_probs(handle1).get(prob, float("inf"))
        creationTime2 = cf.get_all_accepted_probs(handle2).get(prob, float("inf"))
        if creationTime1 == float("inf") and creationTime2 == float("inf"):
            embed.description = (
                "None of you have completed the challenge yet\n"
                ":point_right: Type `/drop` if you want to give up"
            )
        else:
            ephemeral = False
            embed.title = "Duel completed"
            embed.color = None
            duels_db.drop(itr.guild_id, itr.channel_id, uid1)
            if creationTime2 < creationTime1:
                embed.description = f"{u2.mention} won against {u1.mention}!"
            else:
                embed.description = f"{u1.mention} won against {u2.mention}!"
        await itr.followup.send(embed=embed, ephemeral=ephemeral)


@bot.tree.command(description=DESCRIPTIONS["gimme"])
async def gimme(itr: ds.Interaction, rating: int):
    """
    :param rating: Rating of the problem
    """
    uid = itr.user.id
    embed = ds.Embed(description="Setting up problem search ...")
    await itr.response.send_message(embed=embed, ephemeral=True)
    embed.color = ds.Color.teal()
    embed.description = None
    messaged_content = None
    ephemeral = False
    if not handles_db.uid_exists(uid):
        embed.description = (
            "Could not find your handle in the database\n"
            ":point_right:  Type `/handle_set` to set your handle"
        )
        ephemeral = True
    elif rating not in range(800, 3600, 100):
        embed.description = "Rating must be in a multiple of 100 between 800 to 3500"
        ephemeral = True
    else:
        contestId, index, name = get_prob(uid, rating)
        usr_mention = itr.guild.get_member(uid).mention
        problem_url = f"https://codeforces.com/problemset/problem/{contestId}/{index}"

        message_content = usr_mention
        embed.title = name
        embed.description = f"{usr_mention} an interesting problem for you"
        embed.add_field(name="Rating", value=rating)
        embed.add_field(name="Problem URL", value=problem_url, inline=False)
        embed.url = problem_url

    await itr.followup.send(
        content=message_content,
        embed=embed,
        ephemeral=ephemeral,
    )
    cf.set_problemset_json()


@bot.tree.command(description=DESCRIPTIONS["help"])
async def help(itr: ds.Interaction):
    embed = ds.Embed(title="List of all commands")
    for name, value in HELP.items():
        embed.add_field(name="/" + name, value=value, inline=False)
    await itr.response.send_message(embed=embed, ephemeral=True)


keep_alive()
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
try:
    bot.run(DISCORD_TOKEN)
except ds.errors.HTTPException:
    os.system("kill 1")
    os.system("python restarter.py")

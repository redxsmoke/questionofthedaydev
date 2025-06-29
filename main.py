import discord
import json
import datetime
from discord.ext import tasks
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, Select
import logging
from datetime import time
import os
import asyncio

# --- Add VotingView and VoteButton classes here ---

# Update VotingView and VoteButton to accept display_name:

class VotingView(View):
    def __init__(self, answers):  # answers: list of (uid, display_name, answer)
        super().__init__(timeout=None)
        self.answers = answers
        self.vote_counts = {uid: 0 for uid, _, _ in answers}
        self.user_votes = {}

        for idx, (uid, display_name, _) in enumerate(answers):
            label = f"Vote for answer #{idx+1} ({display_name})"
            self.add_item(VoteButton(label=label, uid=uid, parent=self))

class VoteButton(Button):
    def __init__(self, label, uid, parent):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.uid = uid
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        parent = self.parent

        if user_id == str(self.uid):
            await interaction.response.send_message("❌ You cannot vote for your own answer.", ephemeral=True)
            return

        if user_id in parent.user_votes:
            previous_vote = parent.user_votes[user_id]
            if previous_vote == self.uid:
                await interaction.response.send_message("You already voted for this answer.", ephemeral=True)
                return
            else:
                parent.vote_counts[previous_vote] -= 1

        parent.user_votes[user_id] = self.uid
        parent.vote_counts[self.uid] += 1

        desc_lines = []
        for idx, (uid, display_name, answer) in enumerate(parent.answers, start=1):
            count = parent.vote_counts.get(uid, 0)
            desc_lines.append(f"Answer #{idx} ({display_name}): {answer} — {count} vote{'s' if count != 1 else ''}")

        vote_summary = "\n".join(desc_lines)
        await interaction.response.edit_message(content=f"Current votes:\n{vote_summary}", view=parent)


logging.basicConfig(level=logging.INFO)
print("💡 main.py is running")

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("❌ DISCORD_BOT_TOKEN not set!")
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
ADMIN_CHANNEL_ID = int(os.getenv('DISCORD_ADMIN_CHANNEL_ID', CHANNEL_ID))
GUILD_ID = int(os.getenv('GUILD_ID'))

QUESTIONS_FILE = 'questions.json'
SCORES_FILE = 'user_scores.json'
START_DATE = datetime.date(2025, 6, 25)
# --- Voting and submission tracking ---
submission_open = True
voting_message = None
voting_view = None
current_votes = {}
answer_log = {}  # Stores answers by user: {user_id: {"answer": ..., "user": ..., "anonymous": bool}}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def load_questions():
    try:
        with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_questions(questions):
    with open(QUESTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(questions, f, indent=2)

def load_scores():
    try:
        with open(SCORES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_scores(scores):
    with open(SCORES_FILE, 'w', encoding='utf-8') as f:
        json.dump(scores, f, indent=2)

def get_rank(total):
    if total <= 10:
        return "🍚 Rice Rookie"
    elif total <= 25:
        return "🥢 Miso Mind"
    elif total <= 40:
        return "🍣 Sashimi Scholar"
    elif total <= 75:
        return "🌶️ Wasabi Wizard"
    elif total <= 99:
        return "🍱 Sushi Sensei"
    else:
        return "🍣 Master Sushi Chef"

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_messages

async def post_question():
    questions = load_questions()
    idx = (datetime.date.today() - START_DATE).days
    if idx < 0 or idx >= len(questions):
        return
    q = questions[idx]
    question = q["question"]
    submitter = q.get("submitter")
    submitter_text = (
        f"🧠 Question submitted by <@{submitter}>"
        if submitter else "🤖 Question by the Bot"
    )

    ch = client.get_channel(CHANNEL_ID)
    await ch.send(f"@everyone {question}\n\n{submitter_text}", view=QuestionView(idx))
    
class QuestionView(View):
    def __init__(self, qid):
        super().__init__(timeout=None)
        self.qid = qid

    @discord.ui.button(label="Answer Freely ⭐ (+1 Insight Point)", style=discord.ButtonStyle.primary)
    async def freely(self, interaction, button):
        await interaction.response.send_modal(AnswerModal(self.qid, interaction.user))

    @discord.ui.button(label="Answer Anonymously 🔒 (0 Insight Points)", style=discord.ButtonStyle.secondary)
    async def anon(self, interaction, button):
        await interaction.response.send_modal(AnonModal(self.qid, interaction.user))


class AnswerModal(Modal, title="Answer the Question"):
    answer = TextInput(label="Your answer", style=discord.TextStyle.paragraph)

    def __init__(self, qid, user):
        super().__init__()
        self.qid = qid
        self.user = user

    async def on_submit(self, inter):
        if not submission_open:
            await inter.response.send_message("❌ Submissions are closed for today.", ephemeral=True)
            return

        scores = load_scores()
        uid = str(self.user.id)
        scores.setdefault(uid, {"insight_points": 0, "contribution_points": 0, "answered": []})
        if self.qid not in scores[uid]["answered"]:
            scores[uid]["insight_points"] += 1
            scores[uid]["answered"].append(self.qid)
            save_scores(scores)
        total = scores[uid]["insight_points"] + scores[uid]["contribution_points"]
        msg = (
            f"📝 <@{uid}>: {self.answer.value}\n"
            f"⭐ {scores[uid]['insight_points']} | 💡 {scores[uid]['contribution_points']} | 🏆 {get_rank(total)}"
        )
        await inter.response.send_message(msg)

        answer_log[str(self.user.id)] = {
            "answer": self.answer.value,
            "user": self.user,
            "anonymous": False
        }

class AnonModal(Modal, title="Answer Anonymously"):
    answer = TextInput(label="Anonymous answer", style=discord.TextStyle.paragraph)

    def __init__(self, qid, user):
        super().__init__()
        self.qid = qid
        self.user = user

    async def on_submit(self, inter):
        if not submission_open:
            await inter.response.send_message("❌ Submissions are closed for today.", ephemeral=True)
            return

        admin_ch = client.get_channel(ADMIN_CHANNEL_ID)
        await admin_ch.send(f"📩 Anonymous (QID {self.qid}): {self.answer.value}")
        await inter.response.send_message("✅ Received anonymously.", ephemeral=True)

        answer_log[str(self.user.id)] = {
            "answer": self.answer.value,
            "user": self.user,
            "anonymous": True
        }
@client.event
async def on_ready():
    print("✅ Discord bot connected")
    await tree.sync()
    purge_channel_before_post.start()
    notify_upcoming_question.start()
    post_daily_message.start()
    submission_warning.start() 
    close_submissions.start()
    start_voting.start()
    end_voting.start()
    

@tasks.loop(time=time(hour=11, minute=50))
async def purge_channel_before_post():
    ch = client.get_channel(CHANNEL_ID)
    await ch.purge(limit=1000)

@tasks.loop(time=time(hour=11, minute=55))
async def notify_upcoming_question():
    ch_id = int(os.getenv("DISCORD_CHANNEL_ID") or 0)
    channel = client.get_channel(ch_id)
    if channel:
        await channel.send("⏳ The next question will be posted soon! Submit your own question by using the /submitquestion command and earn 💡 Contribution Points ")

@tasks.loop(time=time(hour=12, minute=0))
async def post_daily_message():
    await post_question()

@tasks.loop(time=time(hour=16, minute=50))
async def submission_warning():
    channel = client.get_channel(CHANNEL_ID)
    await channel.send("⏳ Submissions will close in 10 minutes! Get your answers in quickly!.")

@tasks.loop(time=time(hour=17, minute=0))
async def close_submissions():
    global submission_open
    submission_open = False
    channel = client.get_channel(CHANNEL_ID)
    await channel.send("🔒 Submissions are now closed for today's question. Voting will begin in 5 minutes Thank you!")
@tasks.loop(time=time(hour=17, minute=5))
async def start_voting():
    global voting_message, submission_open

    if submission_open:
        return  # Don’t start voting if submissions are still open

    channel = client.get_channel(CHANNEL_ID)
    guild = client.get_guild(GUILD_ID)

    # Prepare answers for voting: include display name with user ID and answer
    answers = []
    for uid, data in answer_log.items():
        if not data["anonymous"]:
            member = guild.get_member(int(uid))
            display_name = member.display_name if member else f"User {uid}"
            answers.append((uid, display_name, data["answer"]))

    if not answers:
        await channel.send("⚠️ No answers were submitted for voting today. Anonymous answers can't be voted on.")
        return

    view = VotingView(answers)
    content_lines = ["Vote for the best answer!"]
    for idx, (uid, display_name, ans) in enumerate(answers, start=1):
        content_lines.append(f"**Answer #{idx} ({display_name}):** {ans}")

    content = "\n".join(content_lines)
    voting_message = await channel.send(content, view=view)

@tasks.loop(time=time(hour=18, minute=10))
async def end_voting():
    global voting_message

    if not voting_message:
        return  # No voting message found

    channel = client.get_channel(CHANNEL_ID)

    # Disable voting buttons so no more votes can be cast
    view = voting_message.view
    if view:
        for child in view.children:
            child.disabled = True
        await voting_message.edit(view=view)

    # Tally votes
    vote_counts = voting_message.view.vote_counts if voting_message.view else None
    if not vote_counts:
        await channel.send("⚠️ No votes were cast today.")
        voting_message = None
        return

    # Your "after voting ends" code goes here:
    max_votes = max(vote_counts.values())
    winners = [uid for uid, count in vote_counts.items() if count == max_votes]

    if max_votes == 0:
        await channel.send("No votes received today.")
        voting_message = None
        return

    # Award points to winners and send congrats message
    scores = load_scores()
    for winner_uid in winners:
        uid = str(winner_uid)
        scores.setdefault(uid, {"insight_points": 0, "contribution_points": 0, "answered": []})
        scores[uid]["insight_points"] += 1
    save_scores(scores)

    winner_mentions = [f"<@{uid}>" for uid in winners]
    if len(winner_mentions) == 1:
        msg = (
            f"🏆 Congratulations {winner_mentions[0]} - you had the most liked answer for today's Question of the Day! "
            f"As a reward, an ⭐ Insight point has been added to your score."
        )
    else:
        winners_str = " & ".join(winner_mentions)
        msg = (
            f"🏆 Congratulations {winners_str} - you had the most liked answers for today's Question of the Day! "
            f"As a reward, an ⭐ Insight point has been added to your scores."
        )

    await channel.send(msg)

    # Reset voting state
    voting_message = None


@client.event
async def on_message(msg):
    if msg.author == client.user:
        return
    if msg.guild is None:
        admin_ch = client.get_channel(ADMIN_CHANNEL_ID)
        await admin_ch.send(f"📩 DM: {msg.content}")
        await msg.channel.send("✅ Received anonymously.")

@tree.command(name="questionofthedaycommands", description="List available question commands")
async def question_commands(interaction):
    await interaction.response.send_message(
        "Commands:\n"
        "/submitquestion\n/score\n/leaderboard\n/ranks\n\n"
        "ADMIN ONLY COMMANDS:\n"
        "/removequestion\n/questionlist\n"
        "/addinsightpoints\n/addcontributorpoints\n/removeinsightpoints\n/removecontributorpoints",
        ephemeral=True
    )

@tree.command(name="ranks", description="View sushi ranks and point ranges")
async def ranks(interaction: discord.Interaction):
    ranks_description = """
**Sushi Rank Tiers — Based on Total Points (⭐ + 💡):**

🍚 **Rice Rookie**  
For scores between 0 and 10 points.

🥢 **Miso Mind**  
For scores between 11 and 25 points.

🍣 **Sashimi Scholar**  
For scores between 26 and 40 points.

🌶️ **Wasabi Wizard**  
For scores between 41 and 75 points.

🍱 **Sushi Sensei**  
For scores between 76 and 99 points.

🍣 **Master Sushi Chef**  
For scores of 100 points and above.
"""
    await interaction.response.send_message(ranks_description, ephemeral=False)

class SubmitModal(Modal, title="Submit a Question"):
    q = TextInput(label="Your question", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, user):
        super().__init__()
        self.user = user

    async def on_submit(self, inter):
        qs = load_questions()
        ids = [int(x["id"]) for x in qs if "id" in x]
        nid = str(max(ids) + 1 if ids else 1)
        qs.append({"id": nid, "question": self.q.value, "submitter": str(self.user.id)})
        save_questions(qs)

        sc = load_scores()
        uid = str(self.user.id)
        today = str(datetime.date.today())
        sc.setdefault(uid, {"insight_points": 0, "contribution_points": 0, "answered": [], "last_contrib": None})
        if sc[uid]["last_contrib"] != today:
            sc[uid]["contribution_points"] += 1
            sc[uid]["last_contrib"] = today
            save_scores(sc)
            await inter.response.send_message(f"✅ Submitted! ID `{nid}` +1 contribution point", ephemeral=True)
        else:
            await inter.response.send_message(f"✅ Submitted! ID `{nid}` (already got today's point)", ephemeral=True)

        # --- Notify admins/mods here ---
        # Fetch guild from interaction
        guild = inter.guild
        member = guild.get_member(self.user.id) if guild else None
        display_name = member.display_name if member else f"{self.user.name}#{self.user.discriminator}"

        notify_msg = f"🧠 @{display_name} has submitted a new question. Use /listquestions to view the question and use /removequestion if moderation is needed."

        # Then send to admins/mods DMs
        for member in guild.members:
            if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
                try:
                    await member.send(notify_msg)
                except Exception as e:
                    print(f"Could not DM {member}: {e}")

@tree.command(name="submitquestion", description="Submit a question")
async def submit_question(interaction):
    await interaction.response.send_modal(SubmitModal(interaction.user))

from discord.ui import View, Button
import discord

class QuestionListView(View):
    def __init__(self, questions, page=0):
        super().__init__(timeout=180)
        self.questions = questions
        self.page = page
        self.per_page = 10
        self.max_page = (len(self.questions) - 1) // self.per_page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        prev = Button(label="Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        next = Button(label="Next", style=discord.ButtonStyle.secondary, disabled=self.page == self.max_page)

        async def prev_callback(interaction):
            self.page -= 1
            await self.update_message(interaction)

        async def next_callback(interaction):
            self.page += 1
            await self.update_message(interaction)

        prev.callback = prev_callback
        next.callback = next_callback

        self.add_item(prev)
        self.add_item(next)

    async def update_message(self, interaction):
        start = self.page * self.per_page
        end = start + self.per_page
        current = self.questions[start:end]

        embed = discord.Embed(
            title="📋 Question List",
            description="\n".join(
                f"`{q['id']}`: {q['question']} — submitted by <@{q['submitter']}>" if q.get("submitter") else f"`{q['id']}`: {q['question']}"
                for q in current
            ),
            color=discord.Color.blue()
        )

        embed.set_footer(text=f"Page {self.page + 1} of {self.max_page + 1}")

        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

@tree.command(name="questionlist", description="Admin-only: list questions")
async def question_list(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)

    questions = load_questions()
    if not questions:
        return await interaction.response.send_message("⚠️ No questions found.", ephemeral=True)

    view = QuestionListView(questions)
    embed = discord.Embed(
        title="📋 Question List",
        description="\n".join(f"`{q['id']}`: {q['question']}" for q in questions[:10]),
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Page 1 of {(len(questions) - 1) // 10 + 1}")
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="removequestion", description="Admin-only: remove question")
@app_commands.describe(question_id="ID to remove")
async def remove_question(interaction, question_id: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    qs = load_questions()
    new = [q for q in qs if q["id"] != question_id]
    if len(new)==len(qs):
        return await interaction.response.send_message("⚠️ Not found.", ephemeral=True)
    save_questions(new)
    await interaction.response.send_message(f"✅ Removed `{question_id}`.", ephemeral=True)

@tree.command(name="score", description="Show your score")
async def score(interaction):
    sc = load_scores().get(str(interaction.user.id),{"insight_points":0,"contribution_points":0})
    tot = sc["insight_points"]+sc["contribution_points"]
    await interaction.response.send_message(
        f"⭐ {sc['insight_points']} | 💡 {sc['contribution_points']} | 🏆 {get_rank(tot)}",
        ephemeral=False
    )

# ------- LEADERBOARD with category select and pagination -------

class CategorySelect(Select):
    def __init__(self, inter, scores, page=0):
        opts = [
            discord.SelectOption(label="All", description="Insight + Contribution"),
            discord.SelectOption(label="Insight", description="Insight only"),
            discord.SelectOption(label="Contributor", description="Contribution only"),
        ]
        super().__init__(placeholder="Pick a category…", min_values=1, max_values=1, options=opts)
        self.inter = inter
        self.scores = scores
        self.page = page

    async def callback(self, interaction):
        cat = self.values[0]
        lb = []
        if cat=="All":
            for uid, s in self.scores.items():
                ins,con = s.get("insight_points",0),s.get("contribution_points",0)
                tot=ins+con
                if tot>0: lb.append((uid,ins,con,tot))
            lb.sort(key=lambda x:x[3],reverse=True)
        elif cat=="Insight":
            for uid,s in self.scores.items():
                ins=s.get("insight_points",0)
                if ins>0: lb.append((uid,ins))
            lb.sort(key=lambda x:x[1],reverse=True)
        else:
            for uid,s in self.scores.items():
                con=s.get("contribution_points",0)
                if con>0: lb.append((uid,con))
            lb.sort(key=lambda x:x[1],reverse=True)

        per=10
        maxp=(len(lb)-1)//per if lb else 0
        self.page=max(0,min(self.page,maxp))
        start,end=self.page*per,(self.page+1)*per
        slice=lb[start:end]

        if not lb:
            desc="No entries."
        else:
            lines=[]
            for i,e in enumerate(slice,start+1):
                if cat=="All":
                    uid,ins,con,tot=e
                    lines.append(f"{i}. <@{uid}> — {ins} ⭐ / {con} 💡 — {get_rank(tot)}")
                else:
                    uid,pt=e
                    em="⭐" if cat=="Insight" else "💡"
                    lines.append(f"{i}. <@{uid}> — {pt} {em} — {get_rank(pt)}")
            desc="\n".join(lines)

        embed=discord.Embed(title=f"Leaderboard — {cat}",description=desc,color=discord.Color.green())
        embed.set_footer(text=f"Page {self.page+1}/{maxp+1}")

        view=View(timeout=120)
        view.add_item(self)
        prev=Button(label="Previous",style=discord.ButtonStyle.secondary,disabled=self.page==0)
        nxt=Button(label="Next",style=discord.ButtonStyle.secondary,disabled=self.page==maxp)
        async def p(i): self.page-=1; await self.callback(i)
        async def n(i): self.page+=1; await self.callback(i)
        prev.callback, nxt.callback = p,n
        view.add_item(prev); view.add_item(nxt)

        await interaction.response.edit_message(embed=embed,view=view)

@tree.command(name="leaderboard", description="View the leaderboard")
async def leaderboard(interaction):
    scores = load_scores()
    view = View(timeout=120)
    view.add_item(CategorySelect(interaction, scores))
    await interaction.response.send_message("Select a category:", view=view, ephemeral=False)

# ------- ADMIN POINT COMMANDS -------

@tree.command(name="addinsightpoints", description="Admin: add insight points")
@app_commands.describe(user="Mention user", amount="Points to add")
async def add_insight(interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.",ephemeral=True)
    sc=load_scores();uid=str(user.id)
    sc.setdefault(uid,{"insight_points":0,"contribution_points":0,"answered":[]})
    sc[uid]["insight_points"]+=amount; save_scores(sc)
    await interaction.response.send_message(f"✅ +{amount} insight to {user.mention}",ephemeral=False)

@tree.command(name="addcontributorpoints", description="Admin: add contribution points")
@app_commands.describe(user="Mention user", amount="Points to add")
async def add_contrib(interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.",ephemeral=True)
    sc=load_scores();uid=str(user.id)
    sc.setdefault(uid,{"insight_points":0,"contribution_points":0,"answered":[]})
    sc[uid]["contribution_points"]+=amount; save_scores(sc)
    await interaction.response.send_message(f"✅ +{amount} contribution to {user.mention}",ephemeral=False)

@tree.command(name="removeinsightpoints", description="Admin: remove insight points")
@app_commands.describe(user="Mention user", amount="Points to remove")
async def remove_insight(interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.",ephemeral=True)
    sc=load_scores();uid=str(user.id)
    sc.setdefault(uid,{"insight_points":0,"contribution_points":0,"answered":[]})
    sc[uid]["insight_points"]=max(0,sc[uid]["insight_points"]-amount); save_scores(sc)
    await interaction.response.send_message(f"✅ -{amount} insight from {user.mention}",ephemeral=False)

@tree.command(name="removecontributorpoints", description="Admin: remove contribution points")
@app_commands.describe(user="Mention user", amount="Points to remove")
async def remove_contrib(interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.",ephemeral=True)
    sc=load_scores();uid=str(user.id)
    sc.setdefault(uid,{"insight_points":0,"contribution_points":0,"answered":[]})
    sc[uid]["contribution_points"]=max(0,sc[uid]["contribution_points"]-amount); save_scores(sc)
    await interaction.response.send_message(f"✅ -{amount} contribution from {user.mention}",ephemeral=False)
@tree.command(name="start_test_sequence", description="Admin only: Run full test sequence for question flow")
async def start_test_sequence(interaction: discord.Interaction):
    global submission_open, voting_message, voting_view, answer_log
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)

    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        return await interaction.response.send_message("❌ Channel not found.", ephemeral=True)

    submission_open = True
    voting_message = None
    voting_view = None
    answer_log = {}

    await interaction.response.send_message("🚦 Starting full test sequence...", ephemeral=False)

    await channel.purge(limit=1000)
    await channel.send("🧹 Channel purged for test.")
    await asyncio.sleep(2)

    await channel.send("⏳ The next question will be posted soon!")
    await asyncio.sleep(5)

    await post_question()
    await asyncio.sleep(3)

    await channel.send("You can now answer freely or anonymously using the buttons.")
    await asyncio.sleep(15)

    await channel.send("⏳ Submissions will close in 10 minutes! Get your answers in quickly!")
    await asyncio.sleep(10)

    submission_open = False
    await channel.send("🔒 Submissions are now closed for today's question. Voting will begin in 5 minutes Thank you!")
    await asyncio.sleep(10)

    # Prepare answers for voting
    guild = client.get_guild(GUILD_ID)
    answers = []
    for uid, data in answer_log.items():
        if not data["anonymous"]:
            member = guild.get_member(int(uid))
            display_name = member.display_name if member else f"User {uid}"
            answers.append((uid, display_name, data["answer"]))

    if not answers:
        await channel.send("⚠️ No answers submitted to vote on. Note - anonymous answers are not eligible for voting")
        return

    voting_view = VotingView(answers)  # Save VotingView instance to global
    voting_message = await channel.send(
        "\n".join(
            [
                "Vote for the best answer!",
                *[
                    f"Answer #{idx} - submitted by <@{uid}>: \"{ans}\""
                    for idx, (uid, display_name, ans) in enumerate(answers, start=1)
                ],
            ]
        ),
        view=voting_view,
    )
    await channel.send("🗳️ Voting started! Click buttons to vote.")

    await asyncio.sleep(15)

    if voting_message and voting_view:
        for child in voting_view.children:
            child.disabled = True
        await voting_message.edit(view=voting_view)

        vote_counts = voting_view.vote_counts
        if not vote_counts:
            await channel.send("⚠️ No votes were cast today.")
            return

        max_votes = max(vote_counts.values())
        winners = [uid for uid, count in vote_counts.items() if count == max_votes]

        if max_votes == 0:
            await channel.send("No votes received today.")
            return

        scores = load_scores()
        for winner_uid in winners:
            uid = str(winner_uid)
            scores.setdefault(uid, {"insight_points": 0, "contribution_points": 0, "answered": []})
            scores[uid]["insight_points"] += 1
        save_scores(scores)

        winner_names = []
        for uid in winners:
            member = guild.get_member(int(uid))
            winner_names.append(f"@{member.display_name}" if member else f"User {uid}")

        if len(winner_names) == 1:
            msg = (
                f"🏆 Congratulations {winner_names[0]} - you had the most liked answer for today's Question of the Day! "
                f"As a reward, an ⭐ Insight point has been added to your score."
            )
        else:
            winners_str = " & ".join(winner_names)
            msg = (
                f"🏆 Congratulations {winners_str} - you had the most liked answers for today's Question of the Day! "
                f"As a reward, an ⭐ Insight point has been added to your scores."
            )

        await channel.send(msg)
    else:
        await channel.send("⚠️ Voting message missing or no votes to tally.")


client.run(TOKEN)

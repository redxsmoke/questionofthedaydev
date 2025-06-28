import discord
import json
import datetime
from discord.ext import tasks
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, Select
import logging
from datetime import time
import os

logging.basicConfig(level=logging.INFO)
print("💡 main.py is running")

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("❌ DISCORD_BOT_TOKEN not set!")
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
ADMIN_CHANNEL_ID = int(os.getenv('DISCORD_ADMIN_CHANNEL_ID', CHANNEL_ID))

QUESTIONS_FILE = 'questions.json'
SCORES_FILE = 'user_scores.json'
START_DATE = datetime.date(2025, 6, 25)

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
    else:
        return "🍱 Sushi Sensei"

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

    class QuestionView(View):
        def __init__(self, qid):
            super().__init__(timeout=None)
            self.qid = qid

        @discord.ui.button(label="Answer Freely ⭐", style=discord.ButtonStyle.primary)
        async def freely(self, interaction, button):
            await interaction.response.send_modal(AnswerModal(self.qid, interaction.user))

        @discord.ui.button(label="Answer Anonymously 🔒", style=discord.ButtonStyle.secondary)
        async def anon(self, interaction, button):
            await interaction.response.send_modal(AnonModal(self.qid, interaction.user))

    class AnswerModal(Modal, title="Answer the Question"):
        answer = TextInput(label="Your answer", style=discord.TextStyle.paragraph)

        def __init__(self, qid, user):
            super().__init__()
            self.qid = qid
            self.user = user

        async def on_submit(self, inter):
            scores = load_scores()
            uid = str(self.user.id)
            scores.setdefault(uid, {"insight_points": 0, "contribution_points": 0, "answered": []})
            if self.qid not in scores[uid]["answered"]:
                scores[uid]["insight_points"] += 1
                scores[uid]["answered"].append(self.qid)
                save_scores(scores)
            total = scores[uid]["insight_points"] + scores[uid]["contribution_points"]
            msg = (
                f"📝 <@{uid}>: {self.answer}\n"
                f"⭐ {scores[uid]['insight_points']} | 💡 {scores[uid]['contribution_points']} | 🏆 {get_rank(total)}"
            )
            await inter.response.send_message(msg)

    class AnonModal(Modal, title="Answer Anonymously"):
        answer = TextInput(label="Anonymous answer", style=discord.TextStyle.paragraph)

        def __init__(self, qid, user):
            super().__init__()
            self.qid = qid
            self.user = user

        async def on_submit(self, inter):
            admin_ch = client.get_channel(ADMIN_CHANNEL_ID)
            await admin_ch.send(f"📩 Anonymous (QID {self.qid}): {self.answer}")
            await inter.response.send_message("✅ Received anonymously.", ephemeral=True)

    ch = client.get_channel(CHANNEL_ID)
    await ch.send(f"@everyone {question}\n\n{submitter_text}", view=QuestionView(idx))

@client.event
async def on_ready():
    print("✅ Discord bot connected")
    await tree.sync()
    purge_channel_before_post.start()
    post_daily_message.start()

@tasks.loop(time=time(hour=11, minute=59))
async def purge_channel_before_post():
    ch = client.get_channel(CHANNEL_ID)
    await ch.purge(limit=1000)

@tasks.loop(time=time(hour=12, minute=0))
async def post_daily_message():
    await post_question()

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
        "/submitquestion\n/removequestion\n/questionlist\n/score\n/leaderboard\n/ranks\n\n"
        "Admin-only:\n"
        "/addinsightpoints\n/addcontributorpoints\n/removeinsightpoints\n/removecontributorpoints",
        ephemeral=True
    )

@tree.command(name="ranks", description="View sushi ranks")
async def ranks(interaction):
    await interaction.response.send_message(
        "🏆 Ranks:\n"
        "🍚 0–10 Rice Rookie\n"
        "🥢 11–25 Miso Mind\n"
        "🍣 26–40 Sashimi Scholar\n"
        "🌶️ 41–75 Wasabi Wizard\n"
        "🍱 76+ Sushi Sensei",
        ephemeral=True
    )

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
        sc.setdefault(uid, {"insight_points":0,"contribution_points":0,"answered":[], "last_contrib":None})
        if sc[uid]["last_contrib"] != today:
            sc[uid]["contribution_points"] += 1
            sc[uid]["last_contrib"] = today
            save_scores(sc)
            await inter.response.send_message(f"✅ Submitted! ID `{nid}` +1 contribution point", ephemeral=True)
        else:
            await inter.response.send_message(f"✅ Submitted! ID `{nid}` (already got today's point)", ephemeral=True)

@tree.command(name="submitquestion", description="Submit a question")
async def submit_question(interaction):
    await interaction.response.send_modal(SubmitModal(interaction.user))

@tree.command(name="questionlist", description="Admin-only: list questions")
async def question_list(interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    qs = load_questions()
    if not qs:
        return await interaction.response.send_message("⚠️ No questions.", ephemeral=True)
    lines = [f"`{q['id']}`: {q['question']}" for q in qs]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

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
        ephemeral=True
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
                    lines.append(f"{i}. <@{uid}> — {ins} 🧠 / {con} 💡 — {get_rank(tot)}")
                else:
                    uid,pt=e
                    em="🧠" if cat=="Insight" else "💡"
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

client.run(TOKEN)

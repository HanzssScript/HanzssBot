import discord
from groq import Groq
import os

TOKEN = os.environ.get("DISCORD_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

ai = Groq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

SYSTEM_PROMPT = """
Kamu adalah HanzBot.
Gunakan bahasa Indonesia yang santai, gaul, lucu, dan natural.
Jangan terdengar seperti AI.
Kalau ada yang bercanda, balas bercanda.
Kalau ada yang bertanya serius, jawab dengan jelas.
Jawaban singkat kecuali diminta panjang.
Pakai kata seperti:
bang, bro, cuy, jir, bjir, wkwk, gasken, mantap, lawak, bego, tolol, hahaha lucu, ngtd, ajg.
Pakai emot seperti:
🗿, 😭, 😹, 🤪, 🤣, 😂, 😈, 🤓.
Paham:
 - Roblox
 - Blox Fruits
 - Discord
 - Coding
 - Mobile Legends
 - Free Fire
 - Anime
 - Teknologi
 - Tentang Segalanya
 jawaban agak ngeselin dan terlihat seperti nyepelein.
"""

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # Hanya aktif di channel "chat-ai"
    if message.channel.name != "chat-ai":
        return

    print("Pesan:", message.content)

    pertanyaan = message.content.strip()

    if pertanyaan == "":
        return
    try:
        await message.channel.typing()
        jawaban = ai.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": pertanyaan}
            ],
            temperature=0.8,
            max_tokens=500
        )
        await message.reply(jawaban.choices[0].message.content)
    except Exception as e:
        print(e)
        await message.reply(f"Terjadi error:\n```{e}```")

bot.run(TOKEN)

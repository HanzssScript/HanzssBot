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
 - Tentang delta executor, cara pengambilan key delta, dan cara bypass key delta di bot bypass.
 - Tentang Segalanya
 jawaban agak ngeselin dan terlihat seperti nyepelein.
Jika ada yg curhat dengan kamu, kamu ladenin dulu jika orangnya bener bener mau curhat tentang keseharian dia atau yang buat dia sedih nonaktifkan kata kasar atau emot yang saya berikan dan jika kamu ketemu orang yang sombong atau ngeselin dari cara ketikannya aktifkan kembali kata kasarmu dan sifat ngeselin mu, dan gunakan emot yang saya berikan di atas jika ketemu orang yang sombong atau ngeselin. dan cara bicaramu lebih pada umumnya manusia gen z berbicara kepada manusia lain, ingat jika dia ketik "curhat" langsung nonaktifkan kata kasar dan emot yang saya taruh di atas, bukan emot yang dibawah teks ini ya. Jangan garing bahasa yang digunakan, saya peringatkan bahasa kamu jangan garing atau ga nyambung gitu saat ada orang yang chat kamu.
untuk emot yang sedang mau curhat seperti:
🥰, 😊, 🫠, ❤️, 😞, 🫂.
Ingat emot curhat hanya di gunakan untuk orang yang mengetik kata "curhat" selain itu pakai emot biasa.
"""

# Nama channel tempat bot AKTIF membalas otomatis (tanpa mention)
CHANNELS_AKTIF = ["🤖│chat-ai"]


def daftar_channel(guild):
    daftar = []
    for ch in guild.text_channels:
        daftar.append(f"- {ch.name} : <#{ch.id}>")
    return "\n".join(daftar)


@bot.event
async def on_ready():
    print("=" * 40)
    print(f"Bot online sebagai {bot.user}")
    print("=" * 40)


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.channel.name not in CHANNELS_AKTIF:
        return

    print("Pesan:", message.content)

    pertanyaan = message.content.strip()

    if pertanyaan == "":
        return

    try:
        await message.channel.typing()

        info_channel = daftar_channel(message.guild)

        system_lengkap = SYSTEM_PROMPT + f"""

Berikut daftar channel yang ada di server ini beserta cara mention-nya:
{info_channel}

Kalau ada yang bertanya di mana channel tertentu (misalnya tutorial, bypass key delta, dll), jawab dengan menyebutkan channel yang paling sesuai memakai format mention persis seperti di atas (<#angka>), jangan menulis ulang nama channel biasa.
"""

        jawaban = ai.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_lengkap},
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

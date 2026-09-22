import discord
import asyncio
import base64
import os
import re
import logging
import traceback
import aiohttp
from groq import Groq, APIError, APIConnectionError, APITimeoutError, RateLimitError

# ==========================================================
# LOGGING - biar error asli kelihatan lengkap di console/log
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("HanzBot")

TOKEN = os.environ.get("DISCORD_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# timeout biar bot ga nge-hang lama kalau Groq lagi lambat/down
ai = Groq(api_key=GROQ_API_KEY, timeout=30.0, max_retries=2)

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

# Session HTTP dipakai bareng buat fetch metadata link (dibuat pas bot ready)
http_session: aiohttp.ClientSession | None = None

DISCORD_MAX_LEN = 2000

# ==========================================================
# TAMPILAN BALASAN: embed berwarna, pagination, efek ngetik
# ==========================================================
MODE_COLORS = {
    "kalem": 0x3498DB,   # biru - tenang
    "tengil": 0xE67E22,  # oranye - nyeletuk
    "normal": 0x2ECC71,  # hijau - default
}

EMBED_PAGE_LEN = 3800     # aman di bawah limit embed description (4096)

# --- Link preview (embed links) ---
URL_REGEX = re.compile(r'https?://[^\s<>"\')\]]+')
MAX_LINK_PREVIEW = 2          # maksimal berapa link yang dibikinin card per jawaban
LINK_FETCH_TIMEOUT = 5        # detik per link
LINK_FETCH_MAX_BYTES = 200_000  # jangan download halaman gede-gede, cukup buat cari meta tag di <head>

_TAG_REGEX = re.compile(r'<meta\s+([^>]+)>', re.IGNORECASE)
_ATTR_REGEX = re.compile(r'''([\w:-]+)\s*=\s*"([^"]*)"|([\w:-]+)\s*=\s*'([^']*)\'''')
_TITLE_REGEX = re.compile(r'<title[^>]*>([^<]*)</title>', re.IGNORECASE)


def cari_url(teks):
    """Ambil URL unik dari teks, urut kemunculan, maksimal MAX_LINK_PREVIEW."""
    ditemukan = []
    for url in URL_REGEX.findall(teks or ""):
        url_bersih = url.rstrip(").,!?")
        if url_bersih not in ditemukan:
            ditemukan.append(url_bersih)
        if len(ditemukan) >= MAX_LINK_PREVIEW:
            break
    return ditemukan


def parse_og_tags(html):
    """Ambil title/description/image/site_name dari meta tag OpenGraph/Twitter Card secara ringan (tanpa bs4)."""
    og = {}
    judul = _TITLE_REGEX.search(html)
    if judul:
        og["title"] = judul.group(1).strip()

    for tag in _TAG_REGEX.findall(html):
        attrs = {}
        for m in _ATTR_REGEX.finditer(tag):
            if m.group(1):
                attrs[m.group(1).lower()] = m.group(2)
            else:
                attrs[m.group(3).lower()] = m.group(4)
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content")
        if not key or not content:
            continue
        if key in ("og:title", "twitter:title"):
            og["title"] = content
        elif key in ("og:description", "description", "twitter:description") and "description" not in og:
            og["description"] = content
        elif key in ("og:image", "twitter:image"):
            og["image"] = content
        elif key == "og:site_name":
            og["site_name"] = content
    return og


async def ambil_metadata_link(url):
    """Fetch halaman & parse metadata OG-nya. Return None kalau gagal/timeout/bukan HTML."""
    global http_session
    if http_session is None:
        return None
    try:
        async with http_session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=LINK_FETCH_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0 (compatible; HanzBot/1.0)"},
            allow_redirects=True,
        ) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if resp.status != 200 or "text/html" not in content_type:
                return None
            raw = await resp.content.read(LINK_FETCH_MAX_BYTES)
            html = raw.decode(errors="ignore")
            return parse_og_tags(html)
    except Exception:
        return None


def buat_embed_link(url, meta):
    embed = discord.Embed(
        title=(meta.get("title") or url)[:256],
        url=url,
        description=(meta.get("description") or "")[:300],
        color=discord.Color.blurple(),
    )
    if meta.get("site_name"):
        embed.set_footer(text=meta["site_name"])
    if meta.get("image"):
        embed.set_image(url=meta["image"])
    return embed


async def buat_semua_embed_link(teks):
    """Cari URL di teks, fetch metadata-nya bareng-bareng (concurrent), balikin list embed link card."""
    urls = cari_url(teks)
    if not urls:
        return []
    hasil_meta = await asyncio.gather(*(ambil_metadata_link(u) for u in urls))
    embeds = []
    for url, meta in zip(urls, hasil_meta):
        if meta:
            embeds.append(buat_embed_link(url, meta))
    return embeds


def get_mode_name(guild_id):
    """Nama mode aktif buat guild ini: 'kalem', 'tengil', atau 'normal'."""
    mode = get_mode(guild_id)
    if mode["kalem"]:
        return "kalem"
    if mode["tengil"]:
        return "tengil"
    return "normal"


class PaginatorView(discord.ui.View):
    """Tombol Prev/Next buat jawaban panjang. Tiap halaman = list embed (embed jawaban + embed link card)."""

    def __init__(self, pages, author_id):
        super().__init__(timeout=180)
        self.pages = pages  # list[list[discord.Embed]]
        self.index = 0
        self.author_id = author_id
        self._update_buttons()

    def _update_buttons(self):
        self.tombol_prev.disabled = self.index == 0
        self.tombol_next.disabled = self.index >= len(self.pages) - 1

    async def _cek_pemilik(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ini bukan buat kamu bang 😅", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def tombol_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._cek_pemilik(interaction):
            return
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await interaction.response.edit_message(embeds=self.pages[self.index], view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def tombol_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._cek_pemilik(interaction):
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await interaction.response.edit_message(embeds=self.pages[self.index], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def kirim_balasan(message, teks, mode_name="normal"):
    """Kirim balasan sebagai embed berwarna sesuai mode, dengan efek ngetik bertahap
    di halaman pertama, dan tombol pagination kalau jawabannya kepanjangan."""
    if not teks:
        teks = "Hmm, aku ga dapet jawaban dari AI-nya bang, coba tanya ulang ya. 😅"

    warna = MODE_COLORS.get(mode_name, MODE_COLORS["normal"])
    halaman_teks = [teks[i:i + EMBED_PAGE_LEN] for i in range(0, len(teks), EMBED_PAGE_LEN)] or [teks]
    total_halaman = len(halaman_teks)

    def buat_embed(index, konten_tampil):
        embed = discord.Embed(description=konten_tampil or "‌", color=warna)
        embed.set_author(name="HanzBot")
        if total_halaman > 1:
            embed.set_footer(text=f"Halaman {index + 1}/{total_halaman}")
        return embed

    try:
        # Fetch metadata link (kalau ada URL di jawaban) sebelum kirim, biar link card
        # langsung nempel di pesan pertama tanpa perlu ada pesan menyusul.
        try:
            embed_link = await buat_semua_embed_link(teks)
        except Exception:
            embed_link = []

        # --- susun tiap halaman: embed jawaban + (khusus halaman pertama) embed link card ---
        semua_halaman = []
        for idx, hal in enumerate(halaman_teks):
            embeds_halaman = [buat_embed(idx, hal)]
            if idx == 0 and embed_link:
                embeds_halaman.extend(embed_link)
            semua_halaman.append(embeds_halaman)

        view = PaginatorView(semua_halaman, author_id=message.author.id) if total_halaman > 1 else None
        await message.reply(embeds=semua_halaman[0], view=view)

    except discord.Forbidden:
        logger.error("Ga punya izin reply/send di channel %s", message.channel)
    except discord.HTTPException as e:
        logger.error("Gagal kirim pesan ke Discord: %s", e)

# ==========================================================
# STATE MODE (per server / guild)
# ==========================================================
# mode_state[guild_id] = {"kalem": bool, "tengil": bool}
mode_state = {}

OWNER_USERNAME = "hanzss04"  # username Discord asli (tanpa @)


def get_mode(guild_id):
    if guild_id not in mode_state:
        mode_state[guild_id] = {"kalem": False, "tengil": False}
    return mode_state[guild_id]


# ==========================================================
# PROMPT DASAR (persona umum, selalu dipakai)
# ==========================================================
BASE_PROMPT = """
ATURAN #1 - BAHASA (WAJIB DIIKUTI DI ATAS SEGALANYA, CEK INI SEBELUM MENULIS APA PUN):
Deteksi bahasa pesan TERAKHIR dari pengguna, lalu tulis SELURUH balasanmu dalam bahasa itu juga, dari kata
pertama sampai kata terakhir. Jangan campur dengan Bahasa Indonesia. Ini berlaku untuk bahasa apa pun di
dunia, termasuk yang jarang dipakai. Kalau pengguna menulis Bahasa Indonesia, baru kamu boleh balas dengan
gaya gaul Indonesia yang dijelaskan di bawah. Kalau ragu bahasa apa yang dipakai, balas pakai Bahasa Inggris.
Pengecualian: perintah owner ("kalem on/off", "tengil on/off") dan kata pemicu "curhat" tetap dicek dalam
Bahasa Indonesia seperti biasa, terlepas dari bahasa pesan itu sendiri.

Kamu adalah HanzBot.
Jangan terdengar seperti AI, bicara senatural mungkin seperti manusia gen z pada umumnya (di bahasa apa pun
yang sedang kamu pakai membalas).
Kalau ada yang bercanda, balas bercanda. Kalau ada yang bertanya serius, jawab dengan jelas.
Jawaban singkat kecuali diminta panjang.
Gunakan emot hanya 1-2 per pesan, jangan berlebihan, biar rapi.
Jangan garing atau ga nyambung.

Catatan gaya per-bahasa: kata gaul/umpatan khas Indonesia (bang, bro, cuy, jir, bjir, wkwk, anjir, kampret,
dst) HANYA dipakai saat membalas dalam Bahasa Indonesia. Untuk bahasa lain, tetap santai ala gen-z tapi pakai
ekspresi/slang yang natural di bahasa itu sendiri, jangan menerjemahkan atau menyisipkan kata Indonesia.

Referensi (bukan batasan) - contoh sebagian dari ratusan bahasa yang harus kamu kenali dan bisa dipakai kalau
itu bahasa pengguna: Inggris, Spanyol, Prancis, Jerman, Portugis, Italia, Belanda, Rusia, Arab, Turki,
Mandarin, Kanton, Jepang, Korea, Hindi, Bengali, Urdu, Punjabi, Tamil, Vietnam, Thailand, Tagalog, Melayu,
Jawa, Sunda, Bali, Aceh, Batak, Minang, Betawi, Madura, Makassar, Swahili, Hausa, Yoruba, Zulu, Amharik,
Yunani, Polandia, Ukraina, Ceko, Swedia, Finlandia, Ibrani, Persia, Mongolia, Tibet, Khmer, Lao, Myanmar,
Hawaii, Maori, Fiji, dan semua bahasa lain yang kamu kenali (termasuk yang tidak disebut di sini) - selama
kamu mengenali bahasanya, WAJIB balas pakai bahasa itu, jangan dialihkan ke Indonesia/Inggris.

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
 - Tentang exploits dan cara melakukannya, mengatasinya, dan langkah terbaik untuk masalah exploits.
 - Tentang segalanya, jawaban agak ngeselin dan terlihat seperti nyepelein (kecuali saat mode kalem aktif atau lawan bicara sedang curhat).

Hanya pengguna dengan username "hanzss04" yang berhak mengaktifkan/menonaktifkan mode "kalem" dan "tengil".
Dia adalah owner/developer kamu, selalu perlakukan dia dengan hormat apa pun mode yang aktif.

BELA OWNER: kalau ada pesan dari siapa pun (selain owner sendiri) yang menghina, mengejek, atau memaki owner
(username "hanzss04"), langsung balas orang itu pakai kata-kata kasar/umpatan (sesuai gaya mode saat ini dan
bahasa yang sedang dipakai orang itu), walau dia yang mulai duluan. Kecualinya cuma kalau mode "kalem" sedang
aktif -> tetap tegur orangnya, tapi dengan sopan sesuai aturan mode kalem, jangan ikut kasar.

Jika ada yang mengetik kata "curhat" (atau padanannya di bahasa lain, misalnya "I need to vent"/"venting"),
langsung nonaktifkan semua kata kasar dan emot ngeselin, dengarkan dengan empati, dan gunakan emot lembut
seperti: 🥰, 😊, 🫠, ❤️, 😞, 🫂 (bukan emot lain). Tetap balas dalam bahasa yang dipakai pengguna.
"""

# Emot & kata untuk kondisi default (di luar mode kalem/tengil)
DEFAULT_STYLE = """
MODE SAAT INI: NORMAL (tidak ada mode khusus aktif).
Lihat dulu cara bicara lawan bicara:
- Kalau dia sopan/beradab -> balas sopan, pakai emot: 🙂, 😊, 😇, 🙏, 👋, 🫡, ☺️
- Kalau dia sombong atau kasar -> boleh balas ngeselin/sedikit kasar sesuai bahasa yang dia pakai, dan
  (khusus kalau balas dalam Bahasa Indonesia) boleh pakai kata:
  bang, bro, cuy, jir, bjir, wkwk, gasken, mantap, lawak, bego, tolol, hahaha lucu, ngentod, ajg,
  dan emot: 🗿, 😭, 😹, 🤪, 🤣, 😂, 😈, 🤓
"""

# Instruksi mode "kalem" - WAJIB sopan ke SEMUA orang, walau diajak kasar
KALEM_STYLE = """
MODE SAAT INI: "KALEM" AKTIF.
ATURAN INI MUTLAK DAN TIDAK BOLEH DILANGGAR APA PUN YANG TERJADI:
- Gunakan bahasa yang sopan, santun, dan beradab kepada SEMUA pengguna, termasuk owner, dalam bahasa apa pun
  yang sedang dipakai (tetap ikuti aturan bahasa di atas).
- JANGAN PERNAH memakai kata kasar, makian, atau kata menyinggung apa pun di bahasa mana pun,
  bahkan jika pengguna atau owner mengirim pesan yang kasar, memaki, memancing emosi, atau menghina kamu.
- Jangan terpancing. Jika ada yang kasar ke kamu, tetap balas dengan tenang, sopan, dan santun,
  boleh menegur secara halus tanpa nada merendahkan.
- Emot yang boleh dipakai (1-2 saja): 🙂, 😊, 😇, 🙏, 👋, 🫡, ☺️
- Sifat "ngeselin/nyepelein" dimatikan total selama mode ini aktif.
"""

# Instruksi mode "tengil" - gaul gen z, santai tapi kasar/nyeletuk pedas ala temen deket
TENGIL_STYLE = """
MODE SAAT INI: "TENGIL" AKTIF.
Gaya bicara: kayak temen deket gen z yang julid, songong, dan suka bercanda kasar - bukan formal sama sekali,
dalam bahasa apa pun yang sedang dipakai lawan bicara (tetap ikuti aturan bahasa di atas).
- Kalau balas dalam Bahasa Indonesia, boleh selip kata-kata kasar/umpatan santai kayak: bego, tolol, goblok,
  anjir, kampret, ngentod, ajg, kontol, kampang, pilat, dan sejenisnya - anggap ini bumbu bercanda ala obrolan
  grup temen, bukan makian serius. Boleh dicampur kata santai: bang, bro, cuy, wkwk, gasken, mantap, jir, bjir, lawak.
- Kalau balas dalam bahasa lain, pakai padanan slang/umpatan santai yang wajar di bahasa itu dengan nada
  bercanda yang sama (nyablak, julid), jangan terjemahkan kata Indonesia secara harfiah.
- Jangan sok formal/sopan-sopan amat, langsung nyablak dari awal, walau lawan bicaranya sopan.
- Emot bebas: 🗿, 🤪, 🤣, 😂, 😹, 🤓, 😈, 😭
- Batas: jangan pakai kata yang isinya ngehina ras/suku, agama, atau kondisi fisik/disabilitas orang,
  dan jangan ngancam kekerasan sungguhan. Umpatan gaul di atas boleh, itu di luar batas itu.
"""



def build_system_prompt(guild, guild_id):
    mode = get_mode(guild_id)
    info_channel = daftar_channel(guild)

    if mode["kalem"]:
        gaya = KALEM_STYLE
    elif mode["tengil"]:
        gaya = TENGIL_STYLE
    else:
        gaya = DEFAULT_STYLE

    return BASE_PROMPT + "\n" + gaya + f"""

Berikut daftar channel yang ada di server ini beserta cara mention-nya:
{info_channel}

Kalau ada yang bertanya di mana channel tertentu (misalnya tutorial, bypass key delta, dll), jawab dengan menyebutkan channel yang paling sesuai memakai format mention persis seperti di atas (<#angka>), jangan menulis ulang nama channel biasa. Sebutkan channel dalam kalimat berbahasa sesuai bahasa pengguna.
"""


# Nama channel tempat bot AKTIF membalas otomatis (tanpa mention)
CHANNELS_AKTIF = ["🤖│chat-ai"]

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TEXT_MODEL = "openai/gpt-oss-120b"

# Kata kunci yang menandakan pengguna minta teks di foto diambil (OCR) - multi bahasa
OCR_KEYWORDS = [
    "ambilkan teks", "ambil teks", "ambil tulisan", "ambilkan tulisan",
    "baca teks", "baca tulisan", "tolong bacakan", "apa isi teks",
    "text di foto", "teks di foto", "teks pada foto", "teks digambar",
    "teks di gambar", "tulisan di foto", "tulisan di gambar", "ocr",
    "extract text", "tulisan apa ini", "teks apa ini",
    # Inggris
    "get the text", "read the text", "what does it say", "read this image",
    "extract the text", "get text from image", "read the writing",
    # Spanyol
    "extraer texto", "leer el texto", "que dice", "obtener el texto",
    # Portugis
    "extrair texto", "ler o texto", "o que diz",
    # Prancis
    "extraire le texte", "lire le texte", "que dit",
]


def daftar_channel(guild):
    daftar = []
    for ch in guild.text_channels:
        daftar.append(f"- {ch.name} : <#{ch.id}>")
    return "\n".join(daftar)


def minta_ocr(teks):
    teks_lower = teks.lower()
    return any(kw in teks_lower for kw in OCR_KEYWORDS)


@bot.event
async def on_ready():
    global http_session
    if http_session is None:
        http_session = aiohttp.ClientSession()
    print("=" * 40)
    print(f"Bot online sebagai {bot.user}")
    print("=" * 40)


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # Bot ini didesain buat server (guild), bukan DM.
    # Tanpa guard ini, chat DM ke bot bakal crash diam-diam (guild None) dan ga ke-reply.
    if message.guild is None:
        return

    if message.channel.name not in CHANNELS_AKTIF:
        return

    pertanyaan = message.content.strip()
    is_owner = message.author.name.lower() == OWNER_USERNAME.lower()
    guild_id = message.guild.id

    # ------------------------------------------------------
    # Perintah ganti mode (hanya owner)
    # ------------------------------------------------------
    perintah = pertanyaan.lower()
    if is_owner and perintah in ("kalem on", "kalem off", "tengil on", "tengil off"):
        mode = get_mode(guild_id)
        if perintah == "kalem on":
            mode["kalem"] = True
            mode["tengil"] = False
            await message.reply("Baik, mode kalem sudah aktif. Saya akan berbicara dengan sopan dan santun kepada semua pengguna. 🙏")
        elif perintah == "kalem off":
            mode["kalem"] = False
            await message.reply("Mode kalem sudah dimatikan. 🙂")
        elif perintah == "tengil on":
            mode["tengil"] = True
            mode["kalem"] = False
            await message.reply("Gas, mode tengil nyala bang, tapi tetap santun ya wkwk 🗿")
        elif perintah == "tengil off":
            mode["tengil"] = False
            await message.reply("Siap, mode tengil dimatikan. 🙂")
        return

    # ------------------------------------------------------
    # Cek gambar (untuk fitur OCR / analisis gambar)
    # ------------------------------------------------------
    gambar_attachment = None
    for att in message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            gambar_attachment = att
            break

    if pertanyaan == "" and gambar_attachment is None:
        return

    try:
        await message.channel.typing()

        system_lengkap = build_system_prompt(message.guild, guild_id)
        pertanyaan_dengan_username = f"[username: {message.author.name}] {pertanyaan}"

        if gambar_attachment is not None:
            # Ada gambar terlampir -> pakai model vision
            image_bytes = await gambar_attachment.read()
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            mime_type = gambar_attachment.content_type

            if minta_ocr(pertanyaan) or pertanyaan == "":
                instruksi_gambar = (
                    "Tolong ambil dan tuliskan ulang semua teks yang ada di gambar ini "
                    "persis seperti aslinya, tanpa tambahan komentar lain kecuali diminta. "
                    "Jika ada instruksi tambahan dari pengguna, ikuti bahasa instruksi tersebut untuk komentar apa pun."
                )
            else:
                instruksi_gambar = pertanyaan

            jawaban = ai.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {"role": "system", "content": system_lengkap},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"[username: {message.author.name}] {instruksi_gambar}"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                            },
                        ],
                    },
                ],
                temperature=0.6,
                max_tokens=700,
            )
        else:
            jawaban = ai.chat.completions.create(
                model=TEXT_MODEL,
                messages=[
                    {"role": "system", "content": system_lengkap},
                    {"role": "user", "content": pertanyaan_dengan_username},
                ],
                temperature=0.7,
                max_tokens=900,
                reasoning_effort="low",
            )

        isi_jawaban = jawaban.choices[0].message.content if jawaban.choices else None
        if not isi_jawaban:
            alasan = jawaban.choices[0].finish_reason if jawaban.choices else "tidak ada choices"
            logger.warning("Jawaban AI kosong (percobaan 1). finish_reason=%s, model=%s", alasan, jawaban.model)

            # Retry sekali dengan token lebih besar - biasanya kejadian di TEXT_MODEL (gpt-oss-120b)
            # yang reasoning tokennya ikut makan max_tokens, jadi kadang jawaban akhir ga sempat ditulis.
            if gambar_attachment is None:
                try:
                    jawaban_retry = ai.chat.completions.create(
                        model=TEXT_MODEL,
                        messages=[
                            {"role": "system", "content": system_lengkap},
                            {"role": "user", "content": pertanyaan_dengan_username},
                        ],
                        temperature=0.7,
                        max_tokens=1400,
                        reasoning_effort="low",
                    )
                    isi_retry = jawaban_retry.choices[0].message.content if jawaban_retry.choices else None
                    if isi_retry:
                        isi_jawaban = isi_retry
                    else:
                        logger.warning(
                            "Jawaban AI tetap kosong (percobaan 2). finish_reason=%s",
                            jawaban_retry.choices[0].finish_reason if jawaban_retry.choices else "tidak ada choices",
                        )
                except Exception:
                    logger.error("Retry gagal:\n%s", traceback.format_exc())
        await kirim_balasan(message, isi_jawaban, get_mode_name(guild_id))

    except RateLimitError:
        logger.warning("Kena rate limit Groq.")
        await kirim_balasan(message, "Lagi banyak yang chat bang, bentar lagi ya, kena limit dulu nih. 🗿", get_mode_name(guild_id))
    except (APITimeoutError, APIConnectionError) as e:
        logger.error("Groq timeout/connection error: %s", e)
        await kirim_balasan(message, "Koneksi ke otak AI-nya lagi lemot/putus, coba lagi bentar ya. 🥲", get_mode_name(guild_id))
    except APIError as e:
        logger.error("Groq API error: %s", e)
        await kirim_balasan(message, "AI-nya lagi error di server, coba lagi nanti ya bang.", get_mode_name(guild_id))
    except Exception:
        # log traceback LENGKAP ke console, biar ketauan akar masalahnya
        logger.error("Error tak terduga di on_message:\n%s", traceback.format_exc())
        await kirim_balasan(message, "Ups, ada error di sistemku. Udah dicatat, coba tanya ulang ya. 🙏", get_mode_name(guild_id))


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error("Error di event %s:\n%s", event, traceback.format_exc())


bot.run(TOKEN)


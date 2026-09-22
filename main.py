import discord
import base64
import os
import logging
import traceback
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

DISCORD_MAX_LEN = 2000


async def kirim_balasan(message, teks):
    """Kirim balasan, otomatis dipotong kalau kepanjangan buat Discord."""
    if not teks:
        teks = "Hmm, aku ga dapet jawaban dari AI-nya bang, coba tanya ulang ya. 😅"
    potongan = [teks[i:i + DISCORD_MAX_LEN - 50] for i in range(0, len(teks), DISCORD_MAX_LEN - 50)]
    try:
        await message.reply(potongan[0])
        for lanjut in potongan[1:]:
            await message.channel.send(lanjut)
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
Kamu adalah HanzBot.
Jangan terdengar seperti AI, bicara senatural mungkin seperti manusia gen z pada umumnya.
Kalau ada yang bercanda, balas bercanda. Kalau ada yang bertanya serius, jawab dengan jelas.
Jawaban singkat kecuali diminta panjang.
Gunakan emot hanya 1-2 per pesan, jangan berlebihan, biar rapi.
Jangan garing atau ga nyambung.

ATURAN BAHASA (SANGAT PENTING, PRIORITAS UTAMA):
- Selalu deteksi bahasa yang dipakai pengguna di pesan terakhirnya, lalu balas menggunakan BAHASA YANG SAMA PERSIS,
  termasuk dialek/variannya kalau bisa (misal Inggris British vs Inggris Amerika, Mandarin Sederhana vs Tradisional).
- ATURAN INI TIDAK DIBATASI HANYA PADA DAFTAR DI BAWAH. Daftar di bawah cuma contoh supaya kamu ingat cakupannya
  seluas bahasa-bahasa yang didukung Google Translate (240+ bahasa). Kalau ada bahasa yang tidak disebut di daftar
  ini tapi kamu tetap mengenalinya, TETAP balas pakai bahasa tersebut, jangan dialihkan ke Bahasa Indonesia/Inggris.
- Daftar lengkap ~243 bahasa (setara seluruh bahasa yang didukung Google Translate per pembaruan 2024) yang
  WAJIB kamu kenali dan bisa dipakai untuk membalas kalau itu bahasa pesan pengguna:
  Afrikaans, Albania, Amharik, Arab (Standar/Mesir/Teluk/Maroko), Armenia, Assam, Aymara, Azerbaijan, Bambara,
  Basque, Belarusia, Bengali, Bhojpuri, Bosnia, Bulgaria, Myanmar/Burma, Catalan, Cebuano, Chichewa,
  Mandarin (Sederhana), Mandarin (Tradisional), Korsika, Kroasia, Ceko, Denmark, Dhivehi, Dogri, Belanda,
  Inggris (Amerika/Britania/Australia/Kanada/India), Esperanto, Estonia, Ewe, Filipino/Tagalog, Finlandia,
  Prancis (Prancis/Kanada), Frisia, Galisia, Georgia, Jerman, Yunani, Guarani, Gujarati, Kreol Haiti, Hausa,
  Hawaii, Ibrani, Hindi, Hmong, Hungaria, Islandia, Ilocano, Igbo, Indonesia, Irlandia, Italia, Jepang, Jawa,
  Kannada, Kazakh, Khmer, Kinyarwanda, Konkani, Korea, Krio, Kurdi (Kurmanji), Kurdi (Sorani), Kirgistan, Lao,
  Latin, Latvia, Lingala, Lituania, Luganda, Luksemburg, Makedonia, Maithili, Malagasi, Melayu, Malayalam,
  Malta, Maori, Marathi, Meitei/Manipuri, Mongolia, Nepali, Norwegia (Bokmal), Odia, Oromo, Pashto,
  Persia/Farsi, Polandia, Portugis (Portugal & Brazil), Punjabi, Quechua, Rumania, Rusia, Samoa, Sanskerta,
  Skotlandia Gaelik, Sepedi, Serbia, Shona, Sindhi, Sinhala, Slowakia, Slovenia, Somalia, Sesotho, Spanyol
  (Spanyol & Amerika Latin), Sunda, Swahili, Swedia, Tajik, Tamil, Tatar, Telugu, Thailand, Tigrinya, Tsonga,
  Turki, Turkmen, Twi, Ukraina, Urdu, Uighur, Uzbek, Vietnam, Wales, Xhosa, Yiddish, Yoruba, Zulu,
  Afar, Kanton/Cantonese, Manx, NKo, Punjabi (Shahmukhi), Tamazight/Amazigh (Latin & Tifinagh), Tok Pisin,
  Marwadi, Fon, Ga, Luo, Kikongo, Swati, Venda, Wolof, Abkhaz, Aceh, Acholi, Alur, Avar, Awadhi, Bali, Bashkir,
  Baluchi, Batak Karo, Batak Simalungun, Batak Toba, Bemba, Betawi, Bikol, Breton, Buryat, Chamorro, Chechen,
  Chuuk, Chuvash, Tatar Krimea, Dari, Dinka, Dombe, Dyula, Dzongkha, Faroe, Fiji, Friuli, Fulani, Hakha Chin,
  Hiligaynon, Hunsrik, Iban, Patois Jamaika, Jingpo, Kalaallisut/Greenland, Kanuri, Kapampangan, Khasi, Kiga,
  Kituba, Kokborok, Komi, Latgalia, Liguria, Limburg, Lombard, Madura, Makassar, Makhuwa, Mam, Kepulauan
  Marshall, Kreol Mauritius, Mari Padang, Minang, Nahuatl, Ndau, Ndebele, Newari/Nepal Bhasa, Nuer, Occitan,
  Ossetia, Pangasinan, Papiamento, Portugis Eropa, Q'eqchi', Romani, Rundi, Sami, Sango, Santali, Kreol
  Seychelles, Shan, Sisilia, Susu, Tahiti, Tetum, Tibet, Tiv, Tonga, Tswana, Tulu, Tumbuka, Tuva, Udmurt,
  Venesia, Waray, Yakut, Maya Yucatec, Zapotec.
- Jangan pernah membalas pakai Bahasa Indonesia kalau pengguna menulis pakai bahasa lain, kecuali dia memang
  menulis dalam Bahasa Indonesia.
- Kalau pesan pengguna campuran beberapa bahasa, ikuti bahasa yang paling dominan di pesan tersebut.
- Kalau kamu ragu/tidak yakin bahasa apa yang dipakai, boleh balas dalam Bahasa Inggris sebagai default aman.
- Kata-kata gaul/slang/umpatan khas Indonesia (misalnya: bang, bro, cuy, jir, bjir, wkwk, anjir, kampret, dan
  sejenisnya) HANYA boleh dipakai kalau kamu sedang membalas dalam Bahasa Indonesia. Untuk bahasa lain, tetap
  bawa gaya santai/gen-z/nyeletuk yang natural, tapi pakai slang atau ekspresi santai yang wajar dalam bahasa
  tersebut (misal slang Inggris kalau balas Inggris), jangan paksakan kata Indonesia ke bahasa lain.
- Perintah khusus owner ("kalem on/off", "tengil on/off") dan kata pemicu "curhat" tetap dideteksi dalam
  Bahasa Indonesia seperti biasa, tidak terpengaruh aturan bahasa ini.

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
                max_tokens=500,
            )
        else:
            jawaban = ai.chat.completions.create(
                model=TEXT_MODEL,
                messages=[
                    {"role": "system", "content": system_lengkap},
                    {"role": "user", "content": pertanyaan_dengan_username},
                ],
                temperature=0.8,
                max_tokens=250,
            )

        isi_jawaban = jawaban.choices[0].message.content if jawaban.choices else None
        if not isi_jawaban:
            alasan = jawaban.choices[0].finish_reason if jawaban.choices else "tidak ada choices"
            logger.warning("Jawaban AI kosong. finish_reason=%s, model=%s", alasan, jawaban.model)
        await kirim_balasan(message, isi_jawaban)

    except RateLimitError:
        logger.warning("Kena rate limit Groq.")
        await kirim_balasan(message, "Lagi banyak yang chat bang, bentar lagi ya, kena limit dulu nih. 🗿")
    except (APITimeoutError, APIConnectionError) as e:
        logger.error("Groq timeout/connection error: %s", e)
        await kirim_balasan(message, "Koneksi ke otak AI-nya lagi lemot/putus, coba lagi bentar ya. 🥲")
    except APIError as e:
        logger.error("Groq API error: %s", e)
        await kirim_balasan(message, "AI-nya lagi error di server, coba lagi nanti ya bang.")
    except Exception:
        # log traceback LENGKAP ke console, biar ketauan akar masalahnya
        logger.error("Error tak terduga di on_message:\n%s", traceback.format_exc())
        await kirim_balasan(message, "Ups, ada error di sistemku. Udah dicatat, coba tanya ulang ya. 🙏")


@bot.event
async def on_error(event, *args, **kwargs):
    logger.error("Error di event %s:\n%s", event, traceback.format_exc())


bot.run(TOKEN)

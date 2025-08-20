import os
import shutil
import requests
from bs4 import BeautifulSoup
import telebot
from telebot import types
from downloader import download_chapter, create_pdf, download_chapter_big
from keep_alive import keep_alive
import time
import threading
import gc

TOKEN = os.getenv("BOT_TOKEN")
OUTPUT_DIR = "downloads"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Clean up downloads folder on startup
def cleanup_downloads():
    try:
        if os.path.exists(OUTPUT_DIR):
            for item in os.listdir(OUTPUT_DIR):
                item_path = os.path.join(OUTPUT_DIR, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                elif os.path.isfile(item_path):
                    os.remove(item_path)
        print("🗑️ Cleaned downloads folder on startup")
    except Exception as e:
        print(f"❌ Startup cleanup error: {e}")

cleanup_downloads()

bot = telebot.TeleBot(TOKEN)
user_state = {}
user_cancel = {}
autodemo_active = {}  # Track autodemo status for each user
autodemo_thread = {}  # Track autodemo threads

def cleanup_resources():
    """Clean up resources to prevent memory issues"""
    try:
        # Clear old user states (older than 1 hour)
        current_time = time.time()
        expired_users = []
        for chat_id, state in user_state.items():
            if current_time - state.get('timestamp', current_time) > 3600:  # 1 hour
                expired_users.append(chat_id)
        
        for chat_id in expired_users:
            user_state.pop(chat_id, None)
            user_cancel.pop(chat_id, None)
        
        # Force garbage collection
        gc.collect()
        print(f"🧹 Cleaned up {len(expired_users)} expired user sessions")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")

# Run cleanup every 30 minutes
def start_cleanup_scheduler():
    def cleanup_loop():
        while True:
            time.sleep(1800)  # 30 minutes
            cleanup_resources()
    
    cleanup_thread = threading.Thread(target=cleanup_loop)
    cleanup_thread.daemon = True
    cleanup_thread.start()

# Auto ping to keep bot alive
def start_auto_ping():
    def ping_loop():
        while True:
            try:
                time.sleep(240)  # 4 minutes - more frequent
                
                # Simple API call to keep bot active
                bot.get_me()
                print("🏓 Auto ping sent to keep bot alive")
                
                # Keep alive server ping
                try:
                    requests.get("http://0.0.0.0:8080", timeout=10)
                    print("🌐 Keep alive server pinged")
                except Exception as ke:
                    print(f"⚠️ Keep alive server ping failed: {ke}")
                
                # Health check - ensure bot is responsive
                try:
                    # Send a test message to a test chat (will fail gracefully if no chat)
                    pass
                except Exception as he:
                    print(f"⚠️ Health check failed: {he}")
                    
            except Exception as e:
                print(f"❌ Auto ping error: {e}")
                # If ping fails, try to restart bot connection
                try:
                    print("🔄 Attempting to restart bot connection...")
                    time.sleep(10)
                    bot.get_me()  # Test if bot is back online
                    print("✅ Bot connection restored")
                except:
                    print("❌ Bot connection still failed")
    
    ping_thread = threading.Thread(target=ping_loop)
    ping_thread.daemon = True
    ping_thread.start()

# Enhanced error handling and auto-restart
def start_bot_monitor():
    def monitor_loop():
        last_activity = time.time()
        while True:
            try:
                time.sleep(600)  # Check every 10 minutes
                
                # Check if bot has been inactive too long
                current_time = time.time()
                if current_time - last_activity > 1800:  # 30 minutes of inactivity
                    print("⚠️ Bot inactive for 30+ minutes, sending keep-alive signal")
                    try:
                        bot.get_me()
                        last_activity = current_time
                        print("✅ Bot keep-alive successful")
                    except Exception as e:
                        print(f"❌ Bot keep-alive failed: {e}")
                
                # Memory cleanup for long-running instances
                if len(user_state) > 100:  # If too many user states
                    cleanup_resources()
                    
            except Exception as e:
                print(f"❌ Bot monitor error: {e}")
    
    monitor_thread = threading.Thread(target=monitor_loop)
    monitor_thread.daemon = True
    monitor_thread.start()

# -------------------- Fungsi Ambil Data Manga --------------------
def get_manga_info(manga_url):
    resp = requests.get(manga_url, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        return None, None, None

    soup = BeautifulSoup(resp.text, "html.parser")
    chapter_links = soup.select("a[href*='chapter']")
    if not chapter_links:
        return None, None, None

    first_chapter = chapter_links[0]["href"]
    if not first_chapter.startswith("http"):
        first_chapter = "https://komiku.org" + first_chapter

    slug = first_chapter.split("-chapter-")[0].replace("https://komiku.org/", "").strip("/")
    base_url = f"https://komiku.org/{slug}-chapter-{{}}/"
    manga_name = slug.split("/")[-1]

    chapter_numbers = set()
    for link in chapter_links:
        href = link["href"]
        if "-chapter-" in href:
            try:
                num = int(href.split("-chapter-")[-1].replace("/", "").split("?")[0])
                chapter_numbers.add(num)
            except:
                pass
    total_chapters = max(chapter_numbers) if chapter_numbers else None

    return base_url, manga_name, total_chapters

# -------------------- Handler /start --------------------
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    welcome_msg = (
        "👋 Selamat datang di Bot Manga Downloader! 📚\n\n"
        "Pilih mode download yang kamu inginkan:"
    )
    
    markup = types.InlineKeyboardMarkup()
    btn_normal = types.InlineKeyboardButton("📖 Mode Normal (/manga)", callback_data="mode_normal")
    btn_big = types.InlineKeyboardButton("🔥 Mode Komik (/komik)", callback_data="mode_big")
    markup.add(btn_normal)
    markup.add(btn_big)
    
    bot.send_message(chat_id, welcome_msg, reply_markup=markup)

# -------------------- Handler /manga --------------------
@bot.message_handler(commands=['manga'])
def manga_mode(message):
    chat_id = message.chat.id
    user_state[chat_id] = {"step": "link", "mode": "normal", "timestamp": time.time()}
    tutorial = (
        "📖 Mode Normal aktif! Download manga dari Komiku 📚\n\n"
        "Cara pakai:\n"
        "1️⃣ Kirim link halaman manga (bukan link chapter)\n"
        "   Contoh: https://komiku.org/manga/mairimashita-iruma-kun/\n"
        "2️⃣ Masukkan nomor chapter awal\n"
        "3️⃣ Masukkan nomor chapter akhir\n"
        "4️⃣ Pilih mau di-GABUNG jadi 1 PDF atau di-PISAH per chapter\n\n"
        "📌 Bot akan download dan kirim sesuai pilihan kamu.\n\n"
        "⚠️ Bisa hentikan download kapan saja dengan /cancel"
    )
    bot.reply_to(message, tutorial)

# -------------------- Handler Mode Selection from /start --------------------
@bot.callback_query_handler(func=lambda call: call.data in ["mode_normal", "mode_big"])
def handle_mode_selection(call):
    chat_id = call.message.chat.id
    
    # Remove the inline keyboard buttons
    try:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    except:
        pass
    
    if call.data == "mode_normal":
        manga_mode(call.message)
    elif call.data == "mode_big":
        komik_mode(call.message)

# -------------------- Handler /cancel --------------------
@bot.message_handler(commands=['cancel'])
def cancel_download(message):
    chat_id = message.chat.id
    user_cancel[chat_id] = True
    
    # Clean up any existing downloads immediately
    cleanup_user_downloads(chat_id)
    
    bot.reply_to(message, "⛔ Download dihentikan! Semua file telah dihapus.")

def cleanup_user_downloads(chat_id):
    """Clean up all download files and folders for a specific user"""
    try:
        if chat_id in user_state:
            manga_name = user_state[chat_id].get("manga_name", "")
            awal = user_state[chat_id].get("awal", 0)
            akhir = user_state[chat_id].get("akhir", 0)
            download_mode = user_state[chat_id].get("mode", "normal")
            
            # Remove chapter folders
            for ch in range(awal, akhir + 1):
                if download_mode == "big":
                    folder_ch = os.path.join(OUTPUT_DIR, f"chapter-{ch}-big")
                else:
                    folder_ch = os.path.join(OUTPUT_DIR, f"chapter-{ch}")
                    
                if os.path.exists(folder_ch):
                    shutil.rmtree(folder_ch)
                    print(f"🗑️ Deleted folder: {folder_ch}")
            
            # Only remove temporary chapter folders, keep PDF files for user
            # PDF files will be cleaned up during startup cleanup only
        
        print(f"🧹 Cleanup completed for user {chat_id}")
    except Exception as e:
        print(f"❌ Cleanup error for user {chat_id}: {e}")

# -------------------- Handler /komik --------------------
@bot.message_handler(commands=['komik'])
def komik_mode(message):
    chat_id = message.chat.id
    user_state[chat_id] = {"step": "link", "mode": "big", "timestamp": time.time()}
    tutorial = (
        "🔥 Mode Komik aktif! Download gambar yang lebih panjang\n\n"
        "Cara pakai:\n"
        "1️⃣ Kirim link halaman manga (bukan link chapter)\n"
        "   Contoh: https://komiku.org/manga/mairimashita-iruma-kun/\n"
        "2️⃣ Masukkan nomor chapter awal\n"
        "3️⃣ Masukkan nomor chapter akhir\n"
        "4️⃣ Pilih mau di-GABUNG jadi 1 PDF atau di-PISAH per chapter\n\n"
        "📌 Mode ini akan download gambar dengan resolusi lebih tinggi.\n"
        "⚠️ BATASAN: Maksimal 3 chapter per download\n"
        "⚠️ Bisa hentikan download kapan saja dengan /cancel"
    )
    bot.reply_to(message, tutorial)

# -------------------- Handler /autodemo --------------------
@bot.message_handler(commands=['autodemo'])
def start_autodemo(message):
    chat_id = message.chat.id
    
    if chat_id in autodemo_active and autodemo_active[chat_id]:
        bot.reply_to(message, "🤖 Auto demo sudah aktif! Gunakan /offautodemo untuk menghentikan.")
        return
    
    autodemo_active[chat_id] = True
    bot.reply_to(message, "🚀 Auto demo dimulai! Bot akan otomatis download manga setiap selesai.")
    
    # Start autodemo thread
    def autodemo_loop():
        demo_urls = [
            "https://komiku.org/manga/mairimashita-iruma-kun/",
            "https://komiku.org/manga/one-piece/",
            "https://komiku.org/manga/naruto/",
            "https://komiku.org/manga/attack-on-titan/"
        ]
        current_url = 0
        chapter_start = 1
        
        while autodemo_active.get(chat_id, False):
            try:
                # Wait a bit before starting next demo
                time.sleep(5)
                
                if not autodemo_active.get(chat_id, False):
                    break
                
                # Send /manga command
                bot.send_message(chat_id, "🤖 Auto Demo: Memulai mode /manga")
                user_state[chat_id] = {"step": "link", "mode": "normal", "timestamp": time.time()}
                
                time.sleep(2)
                
                # Send manga URL
                manga_url = demo_urls[current_url % len(demo_urls)]
                bot.send_message(chat_id, f"🤖 Auto Demo: Mengirim link\n{manga_url}")
                
                # Process the manga URL
                base_url, manga_name, total_chapters = get_manga_info(manga_url)
                if base_url:
                    user_state[chat_id].update({
                        "base_url": base_url,
                        "manga_name": manga_name,
                        "total_chapters": total_chapters,
                        "step": "awal"
                    })
                    
                    time.sleep(2)
                    
                    # Send chapter start
                    bot.send_message(chat_id, f"🤖 Auto Demo: Chapter awal: {chapter_start}")
                    user_state[chat_id]["awal"] = chapter_start
                    user_state[chat_id]["step"] = "akhir"
                    
                    time.sleep(2)
                    
                    # Send chapter end (max 5 chapters ahead)
                    chapter_end = min(chapter_start + 4, total_chapters, chapter_start + 2)  # Limit to 3 chapters max
                    bot.send_message(chat_id, f"🤖 Auto Demo: Chapter akhir: {chapter_end}")
                    user_state[chat_id]["akhir"] = chapter_end
                    user_state[chat_id]["step"] = "mode"
                    
                    time.sleep(2)
                    
                    # Auto select "pisah" mode
                    bot.send_message(chat_id, "🤖 Auto Demo: Memilih mode PISAH per chapter")
                    
                    # Start download process
                    try:
                        user_cancel[chat_id] = False
                        base_url_format = user_state[chat_id]["base_url"]
                        manga_name_demo = user_state[chat_id]["manga_name"]
                        awal = user_state[chat_id]["awal"]
                        akhir = user_state[chat_id]["akhir"]
                        
                        bot.send_message(chat_id, f"🤖 Auto Demo: Memulai download chapter {awal} s/d {akhir}...")
                        
                        # Download in pisah mode
                        for ch in range(awal, akhir + 1):
                            if not autodemo_active.get(chat_id, False) or user_cancel.get(chat_id):
                                break
                                
                            bot.send_message(chat_id, f"🤖 Auto Demo: Download chapter {ch}...")
                            
                            imgs = download_chapter(base_url_format.format(ch), ch, OUTPUT_DIR, chat_id, user_cancel)
                            
                            if imgs and not user_cancel.get(chat_id):
                                pdf_name = f"{manga_name_demo} chapter {ch}.pdf"
                                pdf_path = os.path.join(OUTPUT_DIR, pdf_name)
                                create_pdf(imgs, pdf_path)
                                
                                try:
                                    with open(pdf_path, "rb") as pdf_file:
                                        bot.send_document(chat_id, pdf_file, caption=f"🤖 Auto Demo: {pdf_name}")
                                    print(f"✅ Auto Demo PDF sent: {pdf_name}")
                                    # Auto-delete PDF after 10 seconds
                                    auto_delete_pdf(pdf_path, 10)
                                except Exception as upload_error:
                                    print(f"❌ Auto Demo upload error: {upload_error}")
                                    bot.send_message(chat_id, f"🤖 Auto Demo: Gagal upload {pdf_name}")
                                    # Still delete even if upload failed
                                    auto_delete_pdf(pdf_path, 10)
                                
                                folder_ch = os.path.join(OUTPUT_DIR, f"chapter-{ch}")
                                if os.path.exists(folder_ch):
                                    shutil.rmtree(folder_ch)
                        
                        if autodemo_active.get(chat_id, False):
                            bot.send_message(chat_id, "🤖 Auto Demo: Selesai! Menunggu demo berikutnya...")
                        
                    except Exception as e:
                        bot.send_message(chat_id, f"🤖 Auto Demo Error: {e}")
                
                # Prepare for next demo
                current_url += 1
                chapter_start = chapter_end + 1 if chapter_end < total_chapters - 2 else 1
                
                # Wait before next demo (2 minutes)
                if autodemo_active.get(chat_id, False):
                    bot.send_message(chat_id, "🤖 Auto Demo: Menunggu 2 menit untuk demo berikutnya...")
                    for _ in range(120):  # 2 minutes = 120 seconds
                        if not autodemo_active.get(chat_id, False):
                            break
                        time.sleep(1)
                
            except Exception as e:
                print(f"❌ Autodemo error: {e}")
                time.sleep(30)
        
        # Cleanup when autodemo stops
        user_state.pop(chat_id, None)
        user_cancel.pop(chat_id, None)
        print(f"🤖 Autodemo stopped for user {chat_id}")
    
    autodemo_thread[chat_id] = threading.Thread(target=autodemo_loop)
    autodemo_thread[chat_id].daemon = True
    autodemo_thread[chat_id].start()

# -------------------- Handler /offautodemo --------------------
@bot.message_handler(commands=['offautodemo'])
def stop_autodemo(message):
    chat_id = message.chat.id
    
    if chat_id not in autodemo_active or not autodemo_active[chat_id]:
        bot.reply_to(message, "🤖 Auto demo tidak aktif.")
        return
    
    # Stop autodemo
    autodemo_active[chat_id] = False
    user_cancel[chat_id] = True
    
    # Clean up user state
    user_state.pop(chat_id, None)
    user_cancel.pop(chat_id, None)
    
    # Clean up any ongoing downloads
    cleanup_user_downloads(chat_id)
    
    bot.reply_to(message, "🛑 Auto demo dihentikan! Semua download dibatalkan dan file dihapus.")

# -------------------- Handler Pesan --------------------
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id not in user_state:
        bot.reply_to(message, "Ketik /start dulu ya.")
        return

    step = user_state[chat_id]["step"]

    if step == "link":
        if not text.startswith("https://komiku.org/manga/"):
            bot.reply_to(message, "❌ Link tidak valid! Contoh:\nhttps://komiku.org/manga/mairimashita-iruma-kun/")
            return

        base_url, manga_name, total_chapters = get_manga_info(text)
        if not base_url:
            bot.reply_to(message, "❌ Gagal mengambil data manga. Pastikan link benar.")
            return

        user_state[chat_id].update({
            "base_url": base_url,
            "manga_name": manga_name,
            "total_chapters": total_chapters
        })

        user_state[chat_id]["step"] = "awal"
        bot.reply_to(message, f"📌 Masukkan chapter awal (1 - {total_chapters}):")

    elif step == "awal":
        if not text.isdigit():
            bot.reply_to(message, "❌ Harap masukkan angka untuk chapter awal.")
            return
        user_state[chat_id]["awal"] = int(text)
        user_state[chat_id]["step"] = "akhir"
        bot.reply_to(message, f"📌 Masukkan chapter akhir (maks {user_state[chat_id]['total_chapters']}):")

    elif step == "akhir":
        if not text.isdigit():
            bot.reply_to(message, "❌ Harap masukkan angka untuk chapter akhir.")
            return
        awal = user_state[chat_id]["awal"]
        akhir = int(text)
        total = user_state[chat_id]['total_chapters']
        download_mode = user_state[chat_id].get("mode", "normal")
        
        if ak
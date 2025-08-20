# downloader.py
import os
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

def download_chapter(chapter_url, chapter_num, OUTPUT_DIR, chat_id=None, user_cancel=None):
    print(f"[*] Mengambil gambar dari {chapter_url}")
    resp = requests.get(chapter_url, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        print(f"[!] Gagal mengakses {chapter_url}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    img_tags = soup.select("img")
    img_urls = []

    for img in img_tags:
        src = img.get("src") or img.get("data-src")
        if src and (src.endswith(".jpg") or src.endswith(".png")):
            # Skip advertisement and non-content images
            if "komikuplus" in src or "asset/img" in src:
                continue
            if not src.startswith("http"):
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = "https://komiku.org" + src
                else:
                    src = "https://" + src
            img_urls.append(src)

    if not img_urls:
        print(f"[!] Tidak ada gambar ditemukan di {chapter_url}")
        return []

    chapter_folder = os.path.join(OUTPUT_DIR, f"chapter-{chapter_num}")
    os.makedirs(chapter_folder, exist_ok=True)

    images = []
    for i, img_url in enumerate(img_urls, start=1):
        # Check for cancellation
        if user_cancel and chat_id and user_cancel.get(chat_id):
            print(f"[!] Download cancelled for chapter {chapter_num}")
            return []
            
        try:
            img_resp = requests.get(img_url, stream=True)
            img = Image.open(BytesIO(img_resp.content)).convert("RGB")
            img_path = os.path.join(chapter_folder, f"{i:03}.jpg")
            img.save(img_path, "JPEG")
            images.append(img_path)
            print(f"    > Download gambar {i}/{len(img_urls)}")
        except Exception as e:
            print(f"    [!] Gagal download {img_url}: {e}")

    return images

def download_chapter_big(chapter_url, chapter_num, OUTPUT_DIR, chat_id=None, user_cancel=None):
    """Download chapter with larger dimensions and higher quality images for /big mode"""
    print(f"[*] BIG MODE: Mengambil gambar dari {chapter_url}")
    resp = requests.get(chapter_url, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        print(f"[!] Gagal mengakses {chapter_url}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    img_tags = soup.select("img")
    img_urls = []

    for img in img_tags:
        src = img.get("src") or img.get("data-src")
        if src and (src.endswith(".jpg") or src.endswith(".png")):
            # Skip advertisement and non-content images
            if "komikuplus" in src or "asset/img" in src:
                continue
            if not src.startswith("http"):
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = "https://komiku.org" + src
                else:
                    src = "https://" + src
            
            # Try to get higher resolution image for BIG mode
            # Replace common size indicators with larger versions
            if "?resize=" in src:
                src = src.split("?resize=")[0]  # Remove resize parameter
            elif "thumb" in src:
                src = src.replace("thumb", "full")  # Replace thumb with full
            elif "_small" in src:
                src = src.replace("_small", "_large")  # Replace small with large
            elif "_medium" in src:
                src = src.replace("_medium", "_large")  # Replace medium with large
                
            img_urls.append(src)

    if not img_urls:
        print(f"[!] Tidak ada gambar ditemukan di {chapter_url}")
        return []

    chapter_folder = os.path.join(OUTPUT_DIR, f"chapter-{chapter_num}-big")
    os.makedirs(chapter_folder, exist_ok=True)

    images = []
    for i, img_url in enumerate(img_urls, start=1):
        # Check for cancellation
        if user_cancel and chat_id and user_cancel.get(chat_id):
            print(f"[!] BIG MODE download cancelled for chapter {chapter_num}")
            return []
            
        try:
            img_resp = requests.get(img_url, stream=True)
            img = Image.open(BytesIO(img_resp.content))
            
            # Get original dimensions
            original_width, original_height = img.size
            
            # Upscale image for BIG mode (increase by 150%)
            new_width = int(original_width * 1.5)
            new_height = int(original_height * 1.5)
            
            # Resize using high-quality resampling
            img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert to RGB if necessary
            if img_resized.mode != "RGB":
                img_resized = img_resized.convert("RGB")
            
            img_path = os.path.join(chapter_folder, f"{i:03}.jpg")
            # Save with maximum quality for BIG mode
            img_resized.save(img_path, "JPEG", quality=100, optimize=False)
            images.append(img_path)
            print(f"    > BIG MODE: Download gambar {i}/{len(img_urls)} - Ukuran: {original_width}x{original_height} → {new_width}x{new_height}")
        except Exception as e:
            print(f"    [!] Gagal download {img_url}: {e}")

    return images

def create_pdf(all_images, output_pdf):
    if not all_images:
        print("[!] Tidak ada gambar untuk dibuat PDF.")
        return
    pil_images = [Image.open(img_path).convert("RGB") for img_path in all_images]
    pil_images[0].save(output_pdf, save_all=True, append_images=pil_images[1:])
    print(f"[+] PDF dibuat: {output_pdf}")
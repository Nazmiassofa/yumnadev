import re
import asyncio
import hashlib

from utils.time import get_current_date, get_current_time, get_day_name_from_date, get_today_formatted

async def compute_file_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def get_server_time():
    jakarta_time = get_current_date()
    hari = get_day_name_from_date(jakarta_time)  # Nama hari (dalam Inggris)
    tanggal = get_today_formatted()  # Format tanggal dd/mm/yyyy
    jam = get_current_time()
    return f"{hari}, {tanggal} {jam}"

def load_prompt_blocks(filename):
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    # Cari semua blok
    blocks = dict(re.findall(r"###\s*(\w+)\s*\n(.*?)(?=\n###|\Z)", content, re.DOTALL))
    
    result = {}
    for k, v in blocks.items():
        v = v.strip()

        # Cari dan ganti {{timeserver}} kalau ada
        if "{{timeserver}}" in v:
            current_time = get_server_time()
            v = v.replace("{{timeserver}}", current_time)

        result[k.lower()] = v

    return result

def validate_input(text: str, max_length: int = 360) -> str:
    if not text or not text.strip():
        raise ValueError("Pertanyaan tidak boleh kosong")
    
    text = text.strip()
    if len(text) > max_length:
        raise ValueError(f"Pertanyaan terlalu panjang. Maksimal {max_length} karakter")
    
    return text

def bersihkan_think(response):
    response = re.sub(r"<think>.*?</think>", "", response, flags=re.IGNORECASE | re.DOTALL)
    response = re.sub(r"<think>.*?<think>", "", response, flags=re.IGNORECASE | re.DOTALL)
    response = re.sub(r"</?think>", "", response, flags=re.IGNORECASE)
    return response.strip()

async def animate_thinking(message, stop_event: asyncio.Event):
    dots = 0
    while not stop_event.is_set():
        dots = (dots + 1) % 4
        await message.edit(content=f"_Processing_{'...'[:dots]}")
        await asyncio.sleep(0.5)
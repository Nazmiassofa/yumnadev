import instructor
import logging
from aiohttp import ClientTimeout

from pydantic import BaseModel
from discord.ext import commands
from utils.time import (get_current_date,
                        get_formatted_date,
                        get_today_formatted)

from typing import Optional, Dict, Any
from openai import AsyncOpenAI
from config import API

today = get_current_date()
logger = logging.getLogger(__name__)

class JadwalRequest(BaseModel):
    kota: str
    tanggal: Optional[str] = None  

class GetJadwalShalat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = instructor.patch(AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=API.GROQ_KEY
        ))
    
    async def extract_jadwal_request(self, user_message: str) -> JadwalRequest:
        
        response = await self.client.chat.completions.create(
            model="meta-llama/llama-4-maverick-17b-128e-instruct",
            response_model=JadwalRequest,
            messages=[
                {"role": "system", "content": f"""
                    Anda adalah asisten jadwal shalat profesional.
                    curren_server_date: {today}.

                    Tugas Anda:
                    - Ekstrak kota dan tanggal dari pesan pengguna.
                    - Jika tanggal tidak disebutkan, gunakan hari ini.
                    - Tanggal harus dalam format YYYY-MM-DD.

                    Jawaban Anda HARUS berupa objek JSON valid sesuai format berikut:
                    {{
                    "kota": "nama kota",
                    "tanggal": "YYYY-MM-DD"
                    }}

                    Contoh:
                    User: Jadwal shalat Jakarta besok
                    Output:
                    {{
                    "kota": "Jakarta",
                    "tanggal": "Gunakan acuan current_server_time"
                    }}
                    """}, 
                {"role": "user", "content": user_message}
            ],
            temperature=0.3,
            max_tokens=512,
        )

        return response

    async def get_jadwal_shalat(self, kota: str, tanggal: Optional[str] = None) -> Dict[str, Any]:
        timeout = ClientTimeout(30)
        session = self.bot.http_session
        async with session.get('https://api.myquran.com/v2/sholat/kota/semua', timeout=timeout) as resp:
            if resp.status != 200:
                raise Exception("Gagal mengambil data kota.")
            kota_data = await resp.json()

        kota_info = next((k for k in kota_data['data'] if kota.lower() in k['lokasi'].lower()), None)
        if not kota_info:
            raise ValueError(f"Kota '{kota}' tidak ditemukan.")

        id_kota = kota_info['id']

        if not tanggal:
            tanggal = get_formatted_date()
        else:
            tanggal = get_today_formatted()

        url = f"https://api.myquran.com/v2/sholat/jadwal/{id_kota}/{tanggal}"

        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                raise Exception("Gagal mengambil jadwal shalat.")
            jadwal_data = await resp.json()

        if not jadwal_data.get('status'):
            raise Exception("Jadwal tidak tersedia.")

        return { 
            "lokasi": jadwal_data['data']['lokasi'],
            "tanggal": jadwal_data['data']['jadwal']['tanggal'],
            "jadwal": {
                "imsak": jadwal_data['data']['jadwal']['imsak'],
                "subuh": jadwal_data['data']['jadwal']['subuh'],
                "terbit": jadwal_data['data']['jadwal']['terbit'],
                "dhuha": jadwal_data['data']['jadwal']['dhuha'],
                "dzuhur": jadwal_data['data']['jadwal']['dzuhur'],
                "ashar": jadwal_data['data']['jadwal']['ashar'],
                "maghrib": jadwal_data['data']['jadwal']['maghrib'],
                "isya": jadwal_data['data']['jadwal']['isya'],
            }
        }

async def setup(bot):
    await bot.add_cog(GetJadwalShalat(bot))
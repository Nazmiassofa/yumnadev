import logging

from core.db import db_connection

logger = logging.getLogger(__name__)

class DataBaseManager:
    @staticmethod
    async def getter_word():
        async with db_connection() as conn:
            if not conn:
                logger.error("Gagal terhubung ke database.")
                raise Exception("Gagal terhubung ke database.")
            try:
                row = await conn.fetchrow(
                    """SELECT word, arti FROM public.dictionary 
                    WHERE type = $1 
                    AND word NOT LIKE '% %' 
                    ORDER BY RANDOM() LIMIT 1""",
                    2
                )
                if not row:
                    logger.warning("Tidak ditemukan kata dengan tipe=2 di dictionary.")
                    return None, None

                word = (row['word'] or "").strip().lower()
                arti = (row['arti'] or "").strip()

                logger.info(f"Original arti: {arti} | kata : {word}")  # Log debugging


                # Case 1: Jika ada format "suku.kata\nDefinisi"
                if '.' in arti and '\n' in arti:
                    # Ambil bagian setelah line break
                    definition_part = arti.split('\n')[1].strip()
                    if definition_part:
                        return word, definition_part.split('|')[0].strip()  # Ambil sebelum pipe (|) jika ada

                # Case 2: Jika mengandung titik (suku kata) tapi tidak ada +
                if '+' in arti:
                    # Ambil teks sebelum titik pertama
                    return word, arti.split('.')[0].strip()

                # Case 3: Default - ambil seluruh arti (tanpa suku kata)
                return word, arti.split('.')[0].strip() if '.' in arti else arti

            except Exception as e:
                logger.exception(f"Error saat mengambil kata: {str(e)}")
                return None, None
import os
from dotenv import load_dotenv

load_dotenv()

class BotSetting:
    #------------- BOT SETTINGS
    #----------------------------------------------------------------------------------
    PREFIX = ["v!","V!","yum ","Yum "]  
    # COGS_FOLDER = ['economy', 'channel', 'chatbot','autodc','fun','game']
    # COGS_FOLDER = ['moderator','chatbot', 'autodc', 'economy', 'message']
    COGS_FOLDER = ['voice', 'autodc', 'moderator', 'tempvoice', 'chatbot','fun','game','spygame','hangman','randomvoice','sambungkata','economy', 'channel']
    
    # TOKEN
    TOKEN = os.getenv("TOKEN")


class API:
    #------------- API
    #----------------------------------------------------------------------------------
    #API GEMINI & GROQ
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    GROQ_KEY = os.getenv("GROQ_KEY")

    # API QDRANT VECTOR
    QDRANT_URL = os.getenv("QDRANT_URL")
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

    # LUPA API APA
    API_KEY = "AIzaSyD0UbzzYjk52L47gFd0-Q-Wglu3k9nYJIQ"
    RESI_KEY = "a46c63663db6a49ced960395e319b67d8d11191f5c6a81b1fef06d03ddce10c2"

    # API GENERATE IMAGE
    PIXABAY_KEY = "50066578-8b832bab595d1f908fdbf41c6"
    STARRYAI_KEY = "tYBTNoKT_tvRIxFOQO_o1IekVwnTEg"

    # API ELEVENLABS 
    ELEVENLABS_API_KEY = "sk_e9e88667aebd988a35f1a24b523cf0163424dcd1c4ca1def"
    # ELEVENLABS_VOICE_ID = "iWydkXKoiVtvdn4vLKp9" ## cahaya
    ELEVENLABS_VOICE_ID = "fUesUKVrbYRcEnWoLXet" ## nesah

class DBconf:
    #------------- DATABASE CREDENTIAL
    #----------------------------------------------------------------------------------
    DATABASE_URL = os.getenv("DATABASE_URL")
    DB_NAME = 'postgres'
    DB_USER = 'postgres.kleshmjkvovkhmziwgvl'
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")

    #------------- REDIS CREDENTIAL
    #----------------------------------------------------------------------------------
    REDIS_HOST = 'awake-gnat-29070.upstash.io'
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    REDIS_URL = os.getenv("REDIS_URL")

class LavaConf:
    #------------- LAVALINK CREDENTIAL
    #----------------------------------------------------------------------------------
    LAVA_HOST = os.getenv("LAVALINK_HOST", "127.0.0.1")
    LAVA_PORT = int(os.getenv("LAVALINK_PORT", 2333))
    LAVA_PSWD = os.getenv("LAVALINK_SERVER_PASSWORD", "")
    LAVA_REGION = os.getenv("LAVALINK_REGION", "local")
    LAVA_NAME = os.getenv("LAVALINK_NODE_NAME", "default-node")
    
class RabbitMQ:
    RABBIT_HOST = os.getenv("RABBIT_HOST", "127.0.0.1")
    RABBIT_PORT = int(os.getenv("RABBIT_PORT", "5672"))
    RABBIT_USER = os.getenv("RABBIT_USER", "voisaapp")
    RABBIT_PASS = os.getenv("RABBIT_PASS", "Nazmiassofa133##")
    RABBIT_VHOST = os.getenv("RABBIT_VHOST", "/")
    
    @property
    def RABBIT_URL(self):
        from urllib.parse import quote_plus
        user = quote_plus(self.RABBIT_USER)
        password = quote_plus(self.RABBIT_PASS)
        return f"amqp://{user}:{password}@{self.RABBIT_HOST}:{self.RABBIT_PORT}{self.RABBIT_VHOST}"
    
    # Exchange dan Queue configs
    AUTODC_EXCHANGE = "autodc_exchange"
    ROUTING_KEY = "autodc"
    AUTODC_QUEUE = "autodc_queue"
    AUTODC_CANCEL_QUEUE = "autodc_cancel"

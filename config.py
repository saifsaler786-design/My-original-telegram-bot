import os

class Config:
    # ======================================
    # 1. BOT AUR TELEGRAM KE CREDENTIALS
    # ======================================
    # @BotFather se mila hua token yahan dalna hoga Koyeb dashboard mein
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    # my.telegram.org se API ID aur Hash (Koyeb dashboard mein dalna hoga)
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    
    # Private channel ka ID (Example: -1002123456789)
    # Koyeb dashboard mein ise bhi as string daalna hoga
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 0))
    
    # ======================================
    # 2. APNA KOYEB APP URL (MOST IMPORTANT)
    # ======================================
    # Jaise: https://curly-harriet-saifmovies-1cca6f58.koyeb.app
    # Koyeb deploy karne ke baad jo URL milega, woh yahan dalna hoga
    FQDN = os.environ.get("FQDN", "").rstrip("/")
    
    # ======================================
    # 3. SECURITY AUR SERVER SETTINGS
    # ======================================
    # Koi bhi strong random string banayein
    # Example: my-super-secret-key-2024-for-bot
    SECRET_KEY = os.environ.get("SECRET_KEY", "default-secret-change-this")
    
    # Koyeb automatically PORT set karta hai
    PORT = int(os.environ.get("PORT", 8000))

# Config class ka instance banayein
config = Config()

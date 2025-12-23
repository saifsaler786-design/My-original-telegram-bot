# Telegram File Stream Bot

Free Telegram bot that generates direct stream/download links.

## Deploy on Koyeb (Free)

1. Fork this repository to your GitHub.
2. Login to [Koyeb](https://koyeb.com).
3. Create a new App -> Select "GitHub" -> Select your repository.
4. Go to **Settings** -> **Environment Variables** and add:
   - `API_ID`: Your Telegram API ID
   - `API_HASH`: Your Telegram API Hash
   - `BOT_TOKEN`: Your Bot Token
   - `CHANNEL_ID`: Channel ID (e.g. -100xxxxxxx)
   - `BASE_URL`: Your Koyeb Public URL (e.g. https://my-app.koyeb.app) - *Wait for deployment to get this*
   - `PORT`: 8080
5. Click **Deploy**.

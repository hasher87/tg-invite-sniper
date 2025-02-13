# Telegram Invite Sniper Bot

A high-performance Telegram bot that monitors channels for private invite links and attempts to join them instantly.

## Features

- Ultra-fast invite link detection (< 0.5ms)
- Optimized joining mechanism
- Multiple user support
- Session management
- Status monitoring
- Easy to use command interface

## Setup

1. Get your Telegram API credentials:
   - Go to https://my.telegram.org/apps
   - Create a new application
   - Note down your `API_ID` and `API_HASH`

2. Create a new bot:
   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Use `/newbot` command to create a new bot
   - Note down the bot token

3. Set up environment variables:
   Create a `.env` file with the following:
   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   BOT_TOKEN=your_bot_token
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Run the bot:
   ```bash
   python bot.py
   ```

## Usage

1. Start the bot:
   - Send `/start` to your bot
   - Enter your phone number when prompted
   - Enter the verification code
   - Specify the target channel to monitor

2. Monitor status:
   - Use `/status <id>` to check your sniper status
   - The status ID is provided when you start the sniper

3. Stop the sniper:
   - Use `/stop` to stop the sniper

## Commands

- `/start` - Start the bot and set up a new sniper
- `/status <id>` - Check sniper status
- `/stop` - Stop the active sniper

## Notes

- The bot requires a valid Telegram user account to join private groups
- Each user can run one sniper at a time
- The bot uses optimized connection settings for maximum performance
- Join attempts timeout after 100ms to maintain responsiveness
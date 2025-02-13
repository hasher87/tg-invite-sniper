import os
import re
import asyncio
import uuid
import json
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.sessions import StringSession
from colorama import Fore, Style
import subprocess
import time
from collections import OrderedDict

# Load environment variables
load_dotenv()

# Bot credentials (only needs bot token)
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Store user states and sessions
user_states = {}
user_processes = {}

ACCESS_CODE = "hilmiisawesome"  # Required access code

# FAQ Content
FAQ_TEXT = """❓ Frequently Asked Questions

Q: How fast is the sniper?
A: Our sniper is optimized for maximum speed, typically joining within 100-300ms of detecting an invite link.

Q: Why am I not joining some groups?
A: Several factors can affect success:
• Invite link already expired
• Group already full
• You're rate limited by Telegram
• Network latency issues

Q: Is this safe to use?
A: Yes, we use official Telegram APIs. However:
• Use at your own risk
• Don't share your session/access code
• Avoid running multiple instances

Q: What's the success rate?
A: Success rates vary based on:
• Your internet connection
• Server location
• Competition
• Group settings

Need more help? Contact @0xDeepSeek on Twitter"""

# Disclaimer
DISCLAIMER = """⚠️ DISCLAIMER

By using this bot, you acknowledge and agree:

1. This is an experimental tool with no guarantees of success
2. Results may vary based on network conditions and competition
3. We're not responsible for any account limitations or bans
4. Use at your own risk and discretion
5. No refunds for access codes

Stay safe and happy sniping! 🎯"""

class UserState:
    def __init__(self):
        self.phone = None
        self.waiting_for_access_code = True
        self.waiting_for_phone = False
        self.waiting_for_code = False
        self.waiting_for_2fa = False
        self.waiting_for_channel = False
        self.client = None
        self.session_string = None
        self.code_request_time = None  # Track when code was requested
        self.code_attempts = 0  # Track number of attempts

async def start_sniper_process(phone, session_string, channel):
    """Start a new sniper process for a user"""
    process = subprocess.Popen(
        ['python', 'invite_sniper.py'],
        env={
            'API_ID': str(API_ID),
            'API_HASH': API_HASH,
            'SESSION_STRING': session_string,
            'TARGET_CHANNEL': channel,
            'PATH': os.environ['PATH']
        }
    )
    return process

async def main():
    try:
        print("🚀 Starting bot...")
        
        # Initialize bot client
        bot = TelegramClient(
            StringSession(),
            API_ID,
            API_HASH
        )
        await bot.start(bot_token=BOT_TOKEN)
        
        # Upload bot profile picture if not already set
        try:
            await bot(UpdateProfilePhotoRequest(
                await bot.upload_file('logo.png')
            ))
        except Exception as e:
            print(f"Could not update profile picture: {e}")
        
        print("✅ Bot started successfully!")
        
        @bot.on(events.NewMessage(pattern='/start'))
        async def start_command(event):
            user_id = event.sender_id
            
            # Reset user state
            user_states[user_id] = UserState()
            
            # Create welcome buttons
            buttons = [
                [Button.inline("📖 FAQ", b"faq")],
                [Button.inline("⚠️ Disclaimer", b"disclaimer")]
            ]
            
            # Send banner image with welcome message
            await bot.send_file(
                event.chat_id,
                'sniper.png',
                caption=(
                    "🎯 Welcome to Telegram Invite Sniper Pro! 🚀\n\n"
                    "🔥 Features:\n"
                    "• Ultra-fast invite detection\n"
                    "• Optimized joining algorithm\n"
                    "• Multi-channel monitoring\n"
                    "• Real-time performance stats\n\n"
                    "⚡️ Average Join Speed: 100-300ms\n\n"
                    "🔒 This is a private bot. Please enter your access code to continue.\n\n"
                    "❓ Need an access code?\n"
                    "Contact @0xDeepSeek on Twitter (x.com/0xDeepSeek)"
                ),
                buttons=buttons
            )

        @bot.on(events.CallbackQuery(pattern=b"faq"))
        async def faq_callback(event):
            await event.answer()
            await event.respond(FAQ_TEXT)

        @bot.on(events.CallbackQuery(pattern=b"disclaimer"))
        async def disclaimer_callback(event):
            await event.answer()
            await event.respond(DISCLAIMER)

        @bot.on(events.NewMessage(pattern='/stop'))
        async def stop_command(event):
            user_id = event.sender_id
            if user_id in user_processes:
                process = user_processes[user_id]
                process.terminate()
                del user_processes[user_id]
                await event.respond(
                    "✅ Sniper has been stopped.\n\n"
                    "Use /start to begin a new session!"
                )
            else:
                await event.respond("❌ No active sniper found.")

        @bot.on(events.NewMessage(pattern='/resend'))
        async def resend_code(event):
            user_id = event.sender_id
            if user_id not in user_states or not user_states[user_id].waiting_for_code:
                await event.respond("⚠️ You can only use this command while waiting for a verification code.")
                return
                
            state = user_states[user_id]
            try:
                # Reset code request time and attempts
                state.code_request_time = time.time()
                state.code_attempts = 0
                
                # Request new code
                await state.client.send_code_request(state.phone)
                await event.respond(
                    "📱 New verification code sent!\n\n"
                    "Please enter the new code you received.\n"
                    "⚠️ Note: Previous codes are now invalid."
                )
            except Exception as e:
                await event.respond(f"❌ Error sending new code: {str(e)}\nPlease start over with /start")
                del user_states[user_id]

        @bot.on(events.NewMessage)
        async def message_handler(event):
            if event.raw_text.startswith('/'):
                return
                
            user_id = event.sender_id
            if user_id not in user_states:
                return
                
            state = user_states[user_id]
            
            if state.waiting_for_access_code:
                access_code = event.raw_text.strip()
                if access_code == ACCESS_CODE:
                    state.waiting_for_access_code = False
                    state.waiting_for_phone = True
                    await event.respond(
                        "✅ Access code verified!\n\n"
                        "🔐 Let's set up your secure session.\n"
                        "Please send your phone number in international format (e.g., +1234567890)\n\n"
                        "ℹ️ Your session will be used only on your dedicated sniper instance."
                    )
                else:
                    await event.respond(
                        "❌ Invalid access code!\n\n"
                        "🔑 Please try again or contact @0xDeepSeek on Twitter (x.com/0xDeepSeek) to get a valid code.\n\n"
                        "⚠️ Note: Access codes are case-sensitive."
                    )
                return
            
            elif state.waiting_for_phone:
                phone = event.raw_text.strip()
                state.phone = phone
                state.waiting_for_phone = False
                state.waiting_for_code = True
                
                # Initialize client for authentication
                client = TelegramClient(
                    StringSession(),
                    API_ID,
                    API_HASH
                )
                await client.connect()
                
                try:
                    await client.send_code_request(phone)
                    state.client = client
                    state.code_request_time = time.time()  # Record the time code was requested
                    state.code_attempts = 0
                    await event.respond(
                        "📱 Verification code sent!\n\n"
                        "Please enter the code you received.\n"
                        "(If you have 2FA enabled, you'll be asked for your password next)\n\n"
                        "⚠️ Notes:\n"
                        "• Code expires in 2 minutes\n"
                        "• Use /resend if you need a new code\n"
                        "• Never share this code with anyone!"
                    )
                except Exception as e:
                    await event.respond(f"❌ Error: {str(e)}\nPlease try again with a valid phone number.")
                    state.waiting_for_phone = True
                    
            elif state.waiting_for_code:
                try:
                    code = event.raw_text.strip()
                    
                    # Check if code has expired (2 minutes)
                    if time.time() - state.code_request_time > 120:
                        await event.respond(
                            "⚠️ This code has expired!\n\n"
                            "Use /resend to get a new verification code, or\n"
                            "Use /start to start over."
                        )
                        return
                    
                    # Track attempts
                    state.code_attempts += 1
                    if state.code_attempts >= 3:
                        await event.respond(
                            "❌ Too many invalid attempts!\n\n"
                            "Use /resend to get a new code, or\n"
                            "Use /start to start over."
                        )
                        return
                    
                    await state.client.sign_in(state.phone, code)
                    
                    # Save session string
                    state.session_string = state.client.session.save()
                    state.waiting_for_code = False
                    state.waiting_for_channel = True
                    
                    await event.respond(
                        "✅ Successfully authenticated!\n\n"
                        "🎯 Almost there! Now, please enter the target channel username (e.g., @channel)\n\n"
                        "ℹ️ Make sure you've already joined the channel you want to monitor."
                    )
                    
                except SessionPasswordNeededError:
                    state.waiting_for_code = False
                    state.waiting_for_2fa = True
                    await event.respond(
                        "🔐 2FA Detected!\n\n"
                        "Please enter your 2FA password:\n\n"
                        "⚠️ Note: This is your account's 2FA password, not the bot access code."
                    )
                except PhoneCodeInvalidError:
                    remaining_attempts = 3 - state.code_attempts
                    await event.respond(
                        f"❌ Invalid code! {remaining_attempts} attempts remaining.\n\n"
                        "Please try again, or:\n"
                        "• Use /resend to get a new code\n"
                        "• Use /start to start over"
                    )
                except Exception as e:
                    await event.respond(
                        f"❌ Error: {str(e)}\n\n"
                        "Please:\n"
                        "• Use /resend to get a new code\n"
                        "• Use /start to start over"
                    )
                    
            elif state.waiting_for_2fa:
                try:
                    password = event.raw_text.strip()
                    await state.client.sign_in(password=password)
                    
                    # Save session string
                    state.session_string = state.client.session.save()
                    state.waiting_for_2fa = False
                    state.waiting_for_channel = True
                    
                    await event.respond(
                        "✅ 2FA Verified!\n\n"
                        "🎯 Almost there! Now, please enter the target channel username (e.g., @channel)\n\n"
                        "ℹ️ Make sure you've already joined the channel you want to monitor."
                    )
                    
                except Exception as e:
                    await event.respond(f"❌ Error: {str(e)}\nPlease start over with /start")
                    del user_states[user_id]
                    
            elif state.waiting_for_channel:
                channel = event.raw_text.strip()
                
                if not channel.startswith('@'):
                    await event.respond("❌ Please provide a valid channel username starting with @")
                    return
                
                try:
                    # Stop existing process if any
                    if user_id in user_processes:
                        user_processes[user_id].terminate()
                    
                    # Start new sniper process
                    process = await start_sniper_process(
                        state.phone,
                        state.session_string,
                        channel
                    )
                    user_processes[user_id] = process
                    
                    await event.respond(
                        "🎯 Sniper deployed successfully!\n\n"
                        "✅ Your dedicated sniper is now monitoring the channel.\n"
                        "⚡️ Average response time: 100-300ms\n\n"
                        "📊 Performance Tips:\n"
                        "• Keep your internet connection stable\n"
                        "• Avoid running multiple instances\n"
                        "• Monitor CPU and memory usage\n\n"
                        "⚠️ Remember: Success rates may vary based on:\n"
                        "• Network conditions\n"
                        "• Server location\n"
                        "• Competition\n"
                        "• Group settings\n\n"
                        "Use /stop to stop the sniper when you're done."
                    )
                    
                except Exception as e:
                    await event.respond(f"❌ Error starting sniper: {str(e)}")
                
                del user_states[user_id]
        
        print("🤖 Bot is ready! Press Ctrl+C to stop.")
        await bot.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
if __name__ == '__main__':
    # Clean up any existing processes on restart
    asyncio.run(main())

import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
import sqlite3
from telethon.errors import InviteHashExpiredError

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = '+6737187174'

# Target channel to monitor
TARGET_CHAT = -1002067695602  # Your channel ID without -100 prefix

# Invite link pattern
INVITE_PATTERN = re.compile(
    r'(https?://)?(t\.me/|telegram\.me/joinchat/)\S+',
    re.IGNORECASE
)

async def main():
    client = TelegramClient('sniper_session', API_ID, API_HASH)
    await client.start(PHONE_NUMBER)
    
    # Connect to monitoring channel
    entity = await client.get_input_entity(TARGET_CHAT)
    
    # Create database for tracking invites
    conn = sqlite3.connect('invite_links.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS invites
                 (link TEXT PRIMARY KEY,
                  date TEXT,
                  status TEXT)''')
    conn.commit()

    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        try:
            text = event.message.text
            if matches := INVITE_PATTERN.findall(text):
                for match in matches:
                    link = ''.join(match).strip()
                    
                    # Check if link is new
                    c.execute('SELECT * FROM invites WHERE link = ?', (link,))
                    if not c.fetchone():
                        print(f"New invite detected: {link}")
                        
                        # Attempt to join
                        try:
                            await client.join_chat(link)
                            status = 'joined'
                        except InviteHashExpiredError:
                            status = 'expired'
                            print(f"Expired link: {link}")
                        except Exception as e:
                            status = f'error: {str(e)}'
                            print(f"Failed to join {link}: {str(e)}")
                            
                        # Store in database
                        c.execute('''INSERT INTO invites 
                                   VALUES (?, ?, ?)''',
                                (link, 
                                 datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                 status))
                        conn.commit()
        
        except Exception as e:
            print(f"Error processing message: {str(e)}")

    print("Invite sniper is actively monitoring...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main()) 
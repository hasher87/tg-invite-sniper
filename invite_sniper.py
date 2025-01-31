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

# Invite link pattern
INVITE_PATTERN = re.compile(
    r'(https?://)?(t\.me/|telegram\.me/joinchat/)\S+',
    re.IGNORECASE
)

async def main():
    # Get user input
    phone = input("Enter your phone number (international format): ")
    target_chat = input("Enter target channel ID (with or without -100 prefix): ")
    
    # Remove the ID conversion logic and use string directly
    target_chat = target_chat.strip()  # Keep as string
    
    client = TelegramClient('sniper_session', API_ID, API_HASH)
    await client.start(phone)
    
    try:
        # Get full entity details
        input_entity = await client.get_input_entity(target_chat)
        full_entity = await client.get_entity(input_entity)
        
        print(f"\nSuccessfully connected to channel:")
        print(f"Title: {full_entity.title}")
        print(f"ID: {full_entity.id}")
        print(f"Username: @{full_entity.username}" if full_entity.username else "Private channel")
        
    except Exception as e:
        print(f"Error connecting to channel: {str(e)}")
        print("Make sure:")
        print("1. You're using the correct channel ID/username")
        print("2. You have joined the channel")
        print("3. The channel exists and is accessible")
        await client.disconnect()
        return
    
    # Create database for tracking invites
    conn = sqlite3.connect('invite_links.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS invites
                 (link TEXT PRIMARY KEY,
                  date TEXT,
                  status TEXT)''')
    conn.commit()

    @client.on(events.NewMessage(chats=input_entity))
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
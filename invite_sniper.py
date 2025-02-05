import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
import aiosqlite
from telethon.errors import InviteHashExpiredError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from colorama import Fore, Style
from telethon.network.connection import ConnectionTcpAbridged, ConnectionTcpFull
import time

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Regex pattern to detect Telegram invite links in messages
# Matches both http and non-http URLs with any capitalization
# Captures the unique hash after the + symbol
INVITE_PATTERN = re.compile(
    r'(?:https?://)?t\.me/\+([\w-]+)',  # Include hyphen in matching
    re.IGNORECASE
)

async def main():
    """Main entry point for the invite sniper bot.
    Handles user authentication, channel verification, and event monitoring.
    Implements batched database writes for performance optimization."""
    
    # Get user input
    phone = input("Enter your phone number (international format): ").strip().replace(' ', '')
    target_chat = input("Enter target channel ID (with or without -100 prefix): ").strip()
    
    # Configure client with optimized Telegram connection settings:
    # - TCP Abridged for faster packet encoding
    # - 3 connection retries for reliability
    # - Reduced flood sleep threshold for responsiveness
    client = TelegramClient(
        'sniper_session', 
        API_ID, 
        API_HASH,
        connection=ConnectionTcpFull,  # Switch to full encryption for faster packet processing
        use_ipv6=False,  # Disable IPv6 lookup
        connection_retries=1,  # Fail fast
        request_retries=1,
        flood_sleep_threshold=0,  # No flood wait
        auto_reconnect=False,
        workers=16,  # Increase worker threads
        device_model="SniperX",
        app_version="4.0.0"
    )
    
    try:
        # Start client with proper parameters
        await client.start(
            phone,
            max_attempts=3
        )
    except Exception as e:
        print(f"{Fore.RED}🚨 Connection failed: {str(e)}{Style.RESET_ALL}")
        print("Please verify:")
        print("1. Your phone number format (+CountryCodeNumber)")
        print("2. API_ID/API_HASH in .env file")
        print("3. Internet connection")
        return
    
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
    
    # Database setup using async SQLite:
    # - Stores invite links with timestamp and status
    # - Uses memory cache to avoid duplicate processing
    conn = await aiosqlite.connect('invite_links.db')
    c = await conn.cursor()
    await c.execute('''CREATE TABLE IF NOT EXISTS invites
             (link TEXT PRIMARY KEY,
              date TEXT,
              status TEXT)''')
    await conn.commit()

    # Preload existing links to memory
    await c.execute('SELECT link FROM invites')
    existing_links = {row[0] async for row in c}
    
    @client.on(events.NewMessage(chats=input_entity))
    async def handler(event):
        """Message handler that scans for invite links in real-time.
        Uses perf_counter for high-precision timing measurements.
        Processes multiple matches concurrently using asyncio.gather."""
        try:
            detection_time = time.perf_counter()  # More precise timing
            text = event.message.text
            
            if matches := INVITE_PATTERN.finditer(text):
                # Process matches concurrently
                await asyncio.gather(*[
                    process_invite(match, detection_time, existing_links)
                    for match in matches
                ])
    
        except Exception as e:
            print(f"{Fore.RED}🚨 Critical error: {str(e)}{Style.RESET_ALL}")

    async def process_invite(match, detection_time, cache):
        """Processes a single invite link match.
        Args:
            match: re.Match object containing the invite hash
            detection_time: Timestamp of initial message detection
            cache: Set of already processed links for deduplication"""
        invite_hash = match.group(1)
        link = f"https://t.me/+{invite_hash}"
        
        if link in cache:
            return  # Skip already processed links
            
        detect_latency = (time.perf_counter() - detection_time) * 1000
        print(f"{Fore.CYAN}⌛ Detection: {detect_latency:.2f}ms{Style.RESET_ALL}")
        
        join_start = time.perf_counter()
        try:
            # Bypass normal request handling
            await asyncio.wait_for(
                client._sender.send(
                    ImportChatInviteRequest(invite_hash),
                    retries=0  # No retries
                ),
                timeout=0.3  # 300ms hard timeout
            )
            
            join_time = (time.perf_counter() - join_start) * 1000
            print(f"{Fore.GREEN}✅ Joined in {join_time:.2f}ms{Style.RESET_ALL} | {link}")
            cache.add(link)
            
            # Queue write operation instead of immediate commit
            asyncio.create_task(queue_write(link, 'joined'))
            
        except asyncio.TimeoutError:
            print(f"{Fore.RED}⌛ Timeout after 300ms{Style.RESET_ALL}")
        except InviteHashExpiredError:
            # Handle links that are no longer valid
            status = 'expired'
            print(f"{Fore.RED}❌ Expired link: {link}{Style.RESET_ALL}")
            asyncio.create_task(queue_write(link, status))
        except ValueError as ve:
            if "A wait of" in str(ve):
                # Handle flood wait errors and existing membership
                status = 'already member'
                print(f"{Fore.YELLOW}ℹ️ Already in group: {link}{Style.RESET_ALL}")
                asyncio.create_task(queue_write(link, status))
            else:
                # General value errors (malformed requests)
                status = f'error: {str(ve)}'
                print(f"{Fore.RED}⚠️ Error joining {link}: {str(ve)}{Style.RESET_ALL}")
                asyncio.create_task(queue_write(link, status))
        except Exception as e:
            # Catch-all for unexpected errors
            join_time = (time.perf_counter() - join_start) * 1000
            print(f"{Fore.RED}⚠️ Failed in {join_time:.2f}ms{Style.RESET_ALL} | {str(e)}")
            asyncio.create_task(queue_write(link, status))

    # Batch writing system reduces database I/O operations
    write_queue = []
    async def queue_write(link, status):
        """Queues write operations for batched database commits.
        Reduces disk I/O by grouping up to 5 operations before writing."""
        write_queue.append((
            link,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status
        ))
        
        if len(write_queue) >= 5:  # Batch every 5 entries
            await bulk_write()
    
    async def bulk_write():
        """Executes batched database writes and maintains queue state."""
        nonlocal write_queue
        try:
            await c.executemany(
                '''INSERT OR IGNORE INTO invites VALUES (?, ?, ?)''',
                write_queue
            )
            await conn.commit()
        finally:
            write_queue = []  # Reset queue even if commit fails

    # Add connection pre-warming
    async def maintain_connection():
        while True:
            if not client.is_connected():
                await client.connect()
            await asyncio.sleep(0.1)

    asyncio.create_task(maintain_connection())

    print("Invite sniper is actively monitoring...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main()) 
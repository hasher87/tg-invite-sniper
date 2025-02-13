import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import InviteHashExpiredError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from colorama import Fore, Style
from telethon.network.connection import ConnectionTcpAbridged
import time
from collections import OrderedDict

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Regex pattern optimization: Simplified pattern for faster matching
INVITE_PATTERN = re.compile(r't\.me/\+([\w-]+)', re.IGNORECASE)

# Connection pool for request management
class ConnectionPool:
    def __init__(self, size=5):
        self.size = size
        self.available = asyncio.Queue()
        self.connections = []

    async def init_pool(self, client):
        for _ in range(self.size):
            conn = await client.connect()
            self.connections.append(conn)
            await self.available.put(conn)

    async def get_connection(self):
        return await self.available.get()

    async def release_connection(self, conn):
        await self.available.put(conn)

class InviteCache:
    def __init__(self, max_size=10000):
        self.cache = OrderedDict()
        self.max_size = max_size
    
    def add(self, link: str, status: str):
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)  # Remove oldest item
        self.cache[link] = {
            'status': status,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def exists(self, link: str) -> bool:
        return link in self.cache
    
    def get_status(self, link: str) -> dict:
        return self.cache.get(link)

async def main():
    """Main entry point for the invite sniper bot.
    Implements optimized connection handling and request processing."""
    
    # Get user input
    phone = input("Enter your phone number (international format): ").strip().replace(' ', '')
    target_chat = input("Enter target channel ID (with or without -100 prefix): ").strip()
    
    # Optimized client configuration
    client = TelegramClient(
        'sniper_session',
        API_ID,
        API_HASH,
        connection=ConnectionTcpAbridged,  # Faster packet processing
        use_ipv6=False,
        connection_retries=1,
        request_retries=1,
        flood_sleep_threshold=0,
        auto_reconnect=True,  # Enable auto-reconnect
        retry_delay=0,
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
    
    # Initialize connection pool
    pool = ConnectionPool(size=5)
    await pool.init_pool(client)

    # Initialize in-memory cache
    invite_cache = InviteCache()

    @client.on(events.NewMessage(chats=input_entity))
    async def handler(event):
        """Optimized message handler with in-memory caching"""
        try:
            detection_time = time.perf_counter()
            text = event.message.text
            
            if matches := INVITE_PATTERN.finditer(text):
                conn = await pool.get_connection()
                try:
                    await asyncio.gather(*[
                        process_invite(match, detection_time, invite_cache, conn)
                        for match in matches
                    ])
                finally:
                    await pool.release_connection(conn)
    
        except Exception as e:
            print(f"{Fore.RED}🚨 Critical error: {str(e)}{Style.RESET_ALL}")

    async def process_invite(match, detection_time, cache, conn):
        """Optimized invite processing with in-memory caching"""
        invite_hash = match.group(1)
        link = f"https://t.me/+{invite_hash}"
        
        if cache.exists(link):
            return
            
        detect_latency = (time.perf_counter() - detection_time) * 1000
        print(f"{Fore.CYAN}⌛ Detection: {detect_latency:.2f}ms{Style.RESET_ALL}")
        
        join_start = time.perf_counter()
        try:
            await asyncio.wait_for(
                client._sender.send(
                    ImportChatInviteRequest(invite_hash),
                    retries=0
                ),
                timeout=0.1
            )
            
            join_time = (time.perf_counter() - join_start) * 1000
            print(f"{Fore.GREEN}✅ Joined in {join_time:.2f}ms{Style.RESET_ALL} | {link}")
            cache.add(link, 'joined')
            
        except asyncio.TimeoutError:
            print(f"{Fore.RED}⌛ Timeout after 100ms{Style.RESET_ALL}")
            cache.add(link, 'timeout')
        except InviteHashExpiredError:
            status = 'expired'
            print(f"{Fore.RED}❌ Expired link: {link}{Style.RESET_ALL}")
            cache.add(link, status)
        except ValueError as ve:
            if "A wait of" in str(ve):
                status = 'already member'
                print(f"{Fore.YELLOW}ℹ️ Already in group: {link}{Style.RESET_ALL}")
                cache.add(link, status)
            else:
                status = f'error: {str(ve)}'
                print(f"{Fore.RED}⚠️ Error joining {link}: {str(ve)}{Style.RESET_ALL}")
                cache.add(link, status)
        except Exception as e:
            join_time = (time.perf_counter() - join_start) * 1000
            print(f"{Fore.RED}⚠️ Failed in {join_time:.2f}ms{Style.RESET_ALL} | {str(e)}")
            cache.add(link, f'error: {str(e)}')

    print("Invite sniper is actively monitoring...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main()) 
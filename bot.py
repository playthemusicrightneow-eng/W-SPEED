import sys, types
try:
    import audioop
except ImportError:
    sys.modules['audioop'] = types.ModuleType('audioop')
import discord
from discord.ext import commands
import json
import aiosqlite
import os
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

OWNER_ID = 728201873366056992
DEFAULT_ALERT_USERS = {728201873366056992, 1063630678106853436}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

configs = {}

class Config:
    def __init__(self, guild_id):
        self.guild_id = guild_id
        self.log_channel_id = None
        self.lockdown_active = False
        self.whitelist_users = set()
        self.whitelist_bots = set()
        self.alert_users = set()
        self.thresholds = {
            'channel_delete': {'count': 3, 'window': 60, 'enabled': True},
            'role_delete': {'count': 3, 'window': 60, 'enabled': True},
            'member_kick': {'count': 5, 'window': 60, 'enabled': True},
            'member_ban': {'count': 5, 'window': 60, 'enabled': True},
            'bot_join': {'enabled': True},
        }
    
    @classmethod
    async def load(cls, guild_id):
        config = cls(guild_id)
        async with aiosqlite.connect('guardian.db') as db:
            async with db.execute('SELECT * FROM configs WHERE guild_id = ?', (guild_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    config.log_channel_id = row[1]
                    config.lockdown_active = bool(row[2])
                    if row[3]:
                        config.whitelist_users = set(json.loads(row[3]))
                    if row[4]:
                        config.whitelist_bots = set(json.loads(row[4]))
                    if row[5]:
                        config.thresholds = json.loads(row[5])
                    if row[6]:
                        config.alert_users = set(json.loads(row[6]))
                    else:
                        config.alert_users = DEFAULT_ALERT_USERS.copy()
                else:
                    config.alert_users = DEFAULT_ALERT_USERS.copy()
        
        if not config.alert_users:
            config.alert_users = DEFAULT_ALERT_USERS.copy()
        
        return config
    
    async def save(self):
        async with aiosqlite.connect('guardian.db') as db:
            await db.execute('''
                INSERT OR REPLACE INTO configs 
                (guild_id, log_channel_id, lockdown_active, whitelist_users, whitelist_bots, thresholds, alert_users)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.guild_id,
                self.log_channel_id,
                int(self.lockdown_active),
                json.dumps(list(self.whitelist_users)),
                json.dumps(list(self.whitelist_bots)),
                json.dumps(self.thresholds),
                json.dumps(list(self.alert_users))
            ))
            await db.commit()

action_tracker = defaultdict(lambda: defaultdict(list))

async def init_db():
    async with aiosqlite.connect('guardian.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS configs (
                guild_id INTEGER PRIMARY KEY,
                log_channel_id INTEGER,
                lockdown_active INTEGER DEFAULT 0,
                whitelist_users TEXT,
                whitelist_bots TEXT,
                thresholds TEXT,
                alert_users TEXT
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                action_type TEXT,
                timestamp TEXT,
                data TEXT
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                timestamp TEXT,
                data TEXT
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                action_type TEXT,
                target TEXT,
                timestamp TEXT,
                bot_action TEXT,
                details TEXT
            )
        ''')
        
        await db.commit()

def has_control_perms(guild, member):
    return member.guild_permissions.administrator or member.guild_permissions.ban_members

async def log_evidence(guild_id, user_id, action_type, data):
    async with aiosqlite.connect('guardian.db') as db:
        await db.execute('''
            INSERT INTO evidence (guild_id, user_id, action_type, timestamp, data)
            VALUES (?, ?, ?, ?, ?)
        ''', (guild_id, user_id, action_type, datetime.utcnow().isoformat(), json.dumps(data)))
        await db.commit()

async def log_action(guild_id, user_id, action_type, target, bot_action, details):
    async with aiosqlite.connect('guardian.db') as db:
        await db.execute('''
            INSERT INTO action_log (guild_id, user_id, action_type, target, timestamp, bot_action, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (guild_id, user_id, action_type, target, datetime.utcnow().isoformat(), bot_action, details))
        await db.commit()

async def send_log(guild, embed):
    if guild.id not in configs:
        configs[guild.id] = await Config.load(guild.id)
    
    config = configs[guild.id]
    
    if config.log_channel_id:
        channel = guild.get_channel(config.log_channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except:
                pass

async def send_alert_dm(guild, embed, action_type):
    if guild.id not in configs:
        configs[guild.id] = await Config.load(guild.id)
    
    config = configs[guild.id]
    
    if config.alert_users:
        for user_id in config.alert_users:
            try:
                user = await bot.fetch_user(user_id)
                for i in range(5):
                    await user.send(f"RAID ALERT in {guild.name}", embed=embed)
                    await asyncio.sleep(0.5)
            except:
                pass

async def check_mass_action(guild_id, user_id, action_type):
    now = datetime.utcnow()
    if guild_id not in configs:
        configs[guild_id] = await Config.load(guild_id)
    
    config = configs[guild_id]
    
    if action_type not in config.thresholds:
        return False
    
    threshold = config.thresholds[action_type]
    
    if not threshold.get('enabled', True):
        return False
    
    window = threshold['window']
    max_count = threshold['count']
    
    cutoff = now - timedelta(seconds=window)
    action_tracker[guild_id][user_id] = [
        t for t in action_tracker[guild_id][user_id] if t > cutoff
    ]
    
    action_tracker[guild_id][user_id].append(now)
    
    return len(action_tracker[guild_id][user_id]) >= max_count

async def create_backup(guild):
    backup_data = {
        'roles': [{'id': r.id, 'name': r.name, 'permissions': r.permissions.value, 'color': r.color.value, 'position': r.position} for r in guild.roles],
        'channels': [{'id': c.id, 'name': c.name, 'type': str(c.type), 'position': c.position} for c in guild.channels],
        'timestamp': datetime.utcnow().isoformat()
    }
    
    async with aiosqlite.connect('guardian.db') as db:
        cursor = await db.execute('''
            INSERT INTO backups (guild_id, timestamp, data)
            VALUES (?, ?, ?)
        ''', (guild.id, datetime.utcnow().isoformat(), json.dumps(backup_data)))
        await db.commit()
        return cursor.lastrowid

async def ban_user(guild, user, reason):
    try:
        await guild.ban(user, reason=reason, delete_message_days=0)
        return True
    except:
        return False

@bot.event
async def on_ready():
    await init_db()
    print(f'Guardian Bot is ready! Logged in as {bot.user.name} ({bot.user.id})')
    print(f'Protecting {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for raids and nukes"))

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    
    if guild.id not in configs:
        configs[guild.id] = await Config.load(guild.id)
    
    config = configs[guild.id]
    
    if not config.thresholds.get('channel_delete', {}).get('enabled', True):
        return
    
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        if entry.target.id == channel.id:
            user = entry.user
            
            if user.bot or user.id in config.whitelist_users or user.id == bot.user.id:
                return
            
            is_mass = await check_mass_action(guild.id, user.id, 'channel_delete')
            
            await log_evidence(guild.id, user.id, 'channel_delete', {
                'channel_name': channel.name,
                'channel_id': channel.id,
                'is_mass': is_mass
            })
            
            embed = discord.Embed(
                title="CHANNEL DELETED - RAID DETECTED" if is_mass else "Channel Deleted",
                description=f"**Channel:** {channel.name}\n**Deleted by:** {user.mention} ({user.id})",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            
            bot_action = "None"
            if is_mass:
                banned = await ban_user(guild, user, "Anti-Raid: Mass channel deletion detected")
                if banned:
                    bot_action = "BANNED USER"
                    embed.add_field(name="Action Taken", value=f"User {user.mention} has been BANNED immediately", inline=False)
                    await send_alert_dm(guild, embed, 'channel_delete')
                else:
                    bot_action = "Ban failed - insufficient permissions"
                    embed.add_field(name="Action Failed", value="Bot lacks permission to ban this user", inline=False)
            
            await log_action(guild.id, user.id, 'channel_delete', channel.name, bot_action, f"Mass: {is_mass}")
            await send_log(guild, embed)
            break

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    
    if guild.id not in configs:
        configs[guild.id] = await Config.load(guild.id)
    
    config = configs[guild.id]
    
    if not config.thresholds.get('role_delete', {}).get('enabled', True):
        return
    
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        if entry.target.id == role.id:
            user = entry.user
            
            if user.bot or user.id in config.whitelist_users or user.id == bot.user.id:
                return
            
            is_mass = await check_mass_action(guild.id, user.id, 'role_delete')
            
            await log_evidence(guild.id, user.id, 'role_delete', {
                'role_name': role.name,
                'role_id': role.id,
                'is_mass': is_mass
            })
            
            embed = discord.Embed(
                title="ROLE DELETED - RAID DETECTED" if is_mass else "Role Deleted",
                description=f"**Role:** {role.name}\n**Deleted by:** {user.mention} ({user.id})",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            
            bot_action = "None"
            if is_mass:
                banned = await ban_user(guild, user, "Anti-Raid: Mass role deletion detected")
                if banned:
                    bot_action = "BANNED USER"
                    embed.add_field(name="Action Taken", value=f"User {user.mention} has been BANNED immediately", inline=False)
                    await send_alert_dm(guild, embed, 'role_delete')
                else:
                    bot_action = "Ban failed - insufficient permissions"
                    embed.add_field(name="Action Failed", value="Bot lacks permission to ban this user", inline=False)
            
            await log_action(guild.id, user.id, 'role_delete', role.name, bot_action, f"Mass: {is_mass}")
            await send_log(guild, embed)
            break

@bot.event
async def on_member_remove(member):
    guild = member.guild
    
    if guild.id not in configs:
        configs[guild.id] = await Config.load(guild.id)
    
    config = configs[guild.id]
    
    async for entry in guild.audit_logs(limit=1):
        if entry.action in [discord.AuditLogAction.kick, discord.AuditLogAction.ban]:
            if entry.target.id == member.id:
                user = entry.user
                
                if user.bot or user.id in config.whitelist_users or user.id == bot.user.id:
                    return
                
                action_type = 'member_kick' if entry.action == discord.AuditLogAction.kick else 'member_ban'
                
                if not config.thresholds.get(action_type, {}).get('enabled', True):
                    return
                
                is_mass = await check_mass_action(guild.id, user.id, action_type)
                
                await log_evidence(guild.id, user.id, action_type, {
                    'target_name': str(member),
                    'target_id': member.id,
                    'is_mass': is_mass
                })
                
                action_name = "Kicked" if entry.action == discord.AuditLogAction.kick else "Banned"
                embed = discord.Embed(
                    title=f"MEMBER {action_name.upper()} - RAID DETECTED" if is_mass else f"Member {action_name}",
                    description=f"**Member:** {member.mention} ({member.id})\n**{action_name} by:** {user.mention} ({user.id})",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                
                bot_action = "None"
                if is_mass:
                    banned = await ban_user(guild, user, f"Anti-Raid: Mass {action_name.lower()} detected")
                    if banned:
                        bot_action = "BANNED USER"
                        embed.add_field(name="Action Taken", value=f"User {user.mention} has been BANNED immediately", inline=False)
                        await send_alert_dm(guild, embed, action_type)
                    else:
                        bot_action = "Ban failed - insufficient permissions"
                        embed.add_field(name="Action Failed", value="Bot lacks permission to ban this user", inline=False)
                
                await log_action(guild.id, user.id, action_type, str(member), bot_action, f"Mass: {is_mass}")
                await send_log(guild, embed)
                break

@bot.event
async def on_member_join(member):
    guild = member.guild
    
    if guild.id not in configs:
        configs[guild.id] = await Config.load(guild.id)
    
    config = configs[guild.id]
    
    if not config.thresholds.get('bot_join', {}).get('enabled', True):
        return
    
    if member.bot and member.id not in config.whitelist_bots:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
            if entry.target.id == member.id:
                inviter = entry.user
                
                if inviter.bot or inviter.id in config.whitelist_users:
                    return
                
                embed = discord.Embed(
                    title="UNVERIFIED BOT ADDED - POTENTIAL RAID",
                    description=f"**Bot:** {member.mention} ({member.id})\n**Added by:** {inviter.mention} ({inviter.id})\n**Verified:** {'Yes' if member.public_flags.verified_bot else 'No'}",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                
                bot_action = "Alert sent"
                if not member.public_flags.verified_bot:
                    try:
                        await member.kick(reason="Anti-Raid: Unverified bot added")
                        bot_action = "KICKED BOT"
                        embed.add_field(name="Action Taken", value=f"Bot {member.mention} has been KICKED", inline=False)
                    except:
                        bot_action = "Kick failed"
                        embed.add_field(name="Action Failed", value="Bot lacks permission to kick", inline=False)
                
                await log_evidence(guild.id, inviter.id, 'bot_join', {
                    'bot_name': str(member),
                    'bot_id': member.id,
                    'verified': member.public_flags.verified_bot
                })
                
                await log_action(guild.id, inviter.id, 'bot_join', str(member), bot_action, f"Verified: {member.public_flags.verified_bot}")
                await send_log(guild, embed)
                await send_alert_dm(guild, embed, 'bot_join')
                break

async def load_extensions():
    
import traceback

try:
    await bot.load_extension('commands')
except Exception as e:
    # print full inner traceback so Render logs show exactly what failed inside commands.py
    traceback.print_exc()
    raise

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required argument: {error.param.name}")
    else:
        print(f"Error: {error}")

if __name__ == '__main__':
    import asyncio
    
    async def main():
        async with bot:
            await load_extensions()
            token = os.getenv('DISCORD_BOT_TOKEN')
            if not token:
                print("Error: DISCORD_BOT_TOKEN environment variable not set!")
                print("Please add your Discord bot token using the Secrets tab")
                return
            await bot.start(token)
    
    asyncio.run(main())

import discord
from discord.ext import commands
from flask import Flask
import json
import aiosqlite
import os
import threading
from datetime import datetime

# --- Fake web server for Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.start()

class GuardianCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def get_config(self, guild_id):
        from bot import configs, Config
        if guild_id not in configs:
            configs[guild_id] = await Config.load(guild_id)
        return configs[guild_id]
    
    @commands.group(name='guard', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def guard(self, ctx):
        """Main guardian command group"""
        embed = discord.Embed(
            title="Anti-Raid Guardian Bot",
            description="Protect your server from raids, nukes, and mass deletions",
            color=discord.Color.blue()
        )
        embed.add_field(name="Setup", value="`!guard logs <#channel>` - Set log channel\n`!guard config` - View configuration\n`!guard alerts` - Manage alert users", inline=False)
        embed.add_field(name="Protection", value="`!guard lockdown` - Lock server\n`!guard unlock` - Unlock server\n`!guard toggle <feature>` - Enable/disable features", inline=False)
        embed.add_field(name="Backups", value="`!backup now` - Create backup\n`!backup list` - List backups", inline=False)
        embed.add_field(name="Whitelist", value="`!whitelist user <add/remove> <@user>` - Manage user whitelist\n`!whitelist bot <add/remove> <bot_id>` - Manage bot whitelist", inline=False)
        embed.add_field(name="Evidence", value="`!guard evidence <@user>` - View user's actions\n`!guard evidence list` - Recent events\n`!guard actionlog` - View bot actions", inline=False)
        embed.add_field(name="Tools", value="`!guard scan` - Security scan\n`!guard info` - Bot status\n`!guard healthcheck` - System check", inline=False)
        await ctx.send(embed=embed)
    
    @guard.command(name='logs')
    @commands.has_permissions(administrator=True)
    async def set_logs(self, ctx, channel: discord.TextChannel):
        """Set the log channel"""
        config = await self.get_config(ctx.guild.id)
        config.log_channel_id = channel.id
        await config.save()
        await ctx.send(f"Log channel set to {channel.mention}")
    
    @guard.command(name='config')
    @commands.has_permissions(administrator=True)
    async def show_config(self, ctx):
        """Show current configuration"""
        config = await self.get_config(ctx.guild.id)
        
        embed = discord.Embed(title="Guardian Configuration", color=discord.Color.blue())
        embed.add_field(name="Log Channel", value=f"<#{config.log_channel_id}>" if config.log_channel_id else "Not set", inline=False)
        embed.add_field(name="Lockdown", value="Active" if config.lockdown_active else "Inactive", inline=True)
        embed.add_field(name="Whitelisted Users", value=str(len(config.whitelist_users)), inline=True)
        embed.add_field(name="Whitelisted Bots", value=str(len(config.whitelist_bots)), inline=True)
        embed.add_field(name="Alert Users", value=str(len(config.alert_users)), inline=True)
        
        features = []
        for feature, settings in config.thresholds.items():
            if 'enabled' in settings:
                status = "ON" if settings['enabled'] else "OFF"
            else:
                status = "ON"
            
            if 'window' in settings:
                features.append(f"{feature}: {status} ({settings['count']} in {settings['window']}s)")
            else:
                features.append(f"{feature}: {status}")
        
        embed.add_field(name="Features", value="\n".join(features), inline=False)
        
        await ctx.send(embed=embed)
    
    @guard.command(name='toggle')
    @commands.has_permissions(administrator=True)
    async def toggle_feature(self, ctx, feature: str, state: str = None):
        """Toggle detection features on/off
        Usage: !guard toggle <channel_delete|role_delete|member_kick|member_ban|bot_join> <on|off>
        """
        config = await self.get_config(ctx.guild.id)
        
        valid_features = ['channel_delete', 'role_delete', 'member_kick', 'member_ban', 'bot_join']
        
        if feature not in valid_features:
            await ctx.send(f"Invalid feature. Valid features: {', '.join(valid_features)}")
            return
        
        if state is None:
            current = config.thresholds.get(feature, {}).get('enabled', True)
            await ctx.send(f"{feature} is currently: {'ON' if current else 'OFF'}")
            return
        
        if state.lower() == 'on':
            if feature not in config.thresholds:
                config.thresholds[feature] = {'enabled': True}
            else:
                config.thresholds[feature]['enabled'] = True
            await config.save()
            await ctx.send(f"{feature} detection enabled")
        elif state.lower() == 'off':
            if feature not in config.thresholds:
                config.thresholds[feature] = {'enabled': False}
            else:
                config.thresholds[feature]['enabled'] = False
            await config.save()
            await ctx.send(f"{feature} detection disabled")
        else:
            await ctx.send("Use 'on' or 'off'")
    
    @guard.command(name='lockdown')
    @commands.has_permissions(administrator=True)
    async def lockdown(self, ctx):
        """Lock down the server"""
        config = await self.get_config(ctx.guild.id)
        
        if config.lockdown_active:
            await ctx.send("Server is already in lockdown")
            return
        
        locked_count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(ctx.guild.default_role, send_messages=False)
                locked_count += 1
            except:
                pass
        
        config.lockdown_active = True
        await config.save()
        
        embed = discord.Embed(
            title="SERVER LOCKDOWN ACTIVATED",
            description=f"All text channels have been locked.\n**Locked channels:** {locked_count}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Reason", value="Anti-raid protection triggered", inline=False)
        embed.add_field(name="Unlock", value="Use `!guard unlock` to restore access", inline=False)
        
        await ctx.send(embed=embed)
    
    @guard.command(name='unlock')
    @commands.has_permissions(administrator=True)
    async def unlock(self, ctx):
        """Unlock the server"""
        config = await self.get_config(ctx.guild.id)
        
        if not config.lockdown_active:
            await ctx.send("Server is not in lockdown")
            return
        
        unlocked_count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(ctx.guild.default_role, send_messages=None)
                unlocked_count += 1
            except:
                pass
        
        config.lockdown_active = False
        await config.save()
        
        embed = discord.Embed(
            title="SERVER UNLOCKED",
            description=f"All text channels have been unlocked.\n**Unlocked channels:** {unlocked_count}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        await ctx.send(embed=embed)
    
    @guard.command(name='scan')
    @commands.has_permissions(administrator=True)
    async def scan(self, ctx):
        """Run security scan"""
        config = await self.get_config(ctx.guild.id)
        
        embed = discord.Embed(title="Security Scan Results", color=discord.Color.blue())
        
        admin_users = [m for m in ctx.guild.members if m.guild_permissions.administrator and not m.bot]
        embed.add_field(name="Admin Users", value=str(len(admin_users)), inline=True)
        
        bots = [m for m in ctx.guild.members if m.bot]
        unverified_bots = [b for b in bots if not b.public_flags.verified_bot and b.id not in config.whitelist_bots]
        embed.add_field(name="Total Bots", value=str(len(bots)), inline=True)
        embed.add_field(name="Unverified Bots", value=str(len(unverified_bots)), inline=True)
        
        async with aiosqlite.connect('guardian.db') as db:
            async with db.execute('SELECT COUNT(*) FROM backups WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                result = await cursor.fetchone()
                backup_count = result[0] if result else 0
        embed.add_field(name="Backups", value=str(backup_count), inline=True)
        
        bot_member = ctx.guild.get_member(self.bot.user.id)
        has_admin = bot_member.guild_permissions.administrator
        embed.add_field(name="Bot Admin Perms", value="Yes" if has_admin else "No", inline=True)
        
        if admin_users:
            admin_list = "\n".join([f"{u.mention}" for u in admin_users[:10]])
            if len(admin_users) > 10:
                admin_list += f"\n... and {len(admin_users) - 10} more"
            embed.add_field(name="Admin Users List", value=admin_list, inline=False)
        
        if unverified_bots:
            bot_list = "\n".join([f"{b.mention} (ID: {b.id})" for b in unverified_bots[:5]])
            if len(unverified_bots) > 5:
                bot_list += f"\n... and {len(unverified_bots) - 5} more"
            embed.add_field(name="Unverified Bots", value=bot_list, inline=False)
        
        await ctx.send(embed=embed)
    
    @guard.command(name='info')
    async def info(self, ctx):
        """Show bot status"""
        config = await self.get_config(ctx.guild.id)
        bot_member = ctx.guild.get_member(self.bot.user.id)
        
        from bot import has_control_perms
        mode = "Full Control" if has_control_perms(ctx.guild, bot_member) else "Monitor Only"
        
        embed = discord.Embed(title="Guardian Bot Status", color=discord.Color.blue())
        embed.add_field(name="Mode", value=f"**{mode}**", inline=True)
        embed.add_field(name="Lockdown", value="Active" if config.lockdown_active else "Inactive", inline=True)
        embed.add_field(name="Servers Protected", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Version", value="2.0.0", inline=True)
        
        await ctx.send(embed=embed)
    
    @guard.command(name='alerts')
    @commands.has_permissions(administrator=True)
    async def manage_alerts(self, ctx, action: str = None, user: discord.User = None):
        """Manage users who receive DM alerts
        Usage: 
        !guard alerts - Show current alert users
        !guard alerts add @user - Add user to alert list
        !guard alerts remove @user - Remove user from alert list
        """
        config = await self.get_config(ctx.guild.id)
        
        if action is None:
            if config.alert_users:
                users_list = "\n".join([f"<@{uid}>" for uid in config.alert_users])
                await ctx.send(f"**Alert Users (receive DMs on raids):**\n{users_list}")
            else:
                await ctx.send("No alert users configured")
            return
        
        if user is None:
            await ctx.send("Please mention a user")
            return
        
        if action.lower() == 'add':
            config.alert_users.add(user.id)
            await config.save()
            await ctx.send(f"Added {user.mention} to alert list - they will receive DMs on raid detection")
        elif action.lower() == 'remove':
            config.alert_users.discard(user.id)
            await config.save()
            await ctx.send(f"Removed {user.mention} from alert list")
        else:
            await ctx.send("Use 'add' or 'remove'")
    
    @guard.command(name='exempt')
    async def exempt_user(self, ctx, action: str = None, user: discord.User = None):
        """[OWNER ONLY] Exempt a user from all detections
        Usage: 
        !guard exempt add @user - Add user to exemption list
        !guard exempt remove @user - Remove user from exemption list
        !guard exempt list - Show all exempted users
        """
        from bot import OWNER_ID
        
        if ctx.author.id != OWNER_ID:
            await ctx.send("This command can only be used by the bot owner")
            return
        
        config = await self.get_config(ctx.guild.id)
        
        if action is None or action.lower() == 'list':
            if config.whitelist_users:
                users_list = "\n".join([f"<@{uid}>" for uid in config.whitelist_users])
                await ctx.send(f"**Exempted Users:**\n{users_list}")
            else:
                await ctx.send("No exempted users")
            return
        
        if user is None:
            await ctx.send("Please mention a user")
            return
        
        if action.lower() == 'add':
            config.whitelist_users.add(user.id)
            await config.save()
            await ctx.send(f"Exempted {user.mention} - they will not trigger any detections")
        elif action.lower() == 'remove':
            config.whitelist_users.discard(user.id)
            await config.save()
            await ctx.send(f"Removed exemption for {user.mention}")
        else:
            await ctx.send("Use 'add', 'remove', or 'list'")
    
    @guard.command(name='healthcheck')
    @commands.has_permissions(administrator=True)
    async def healthcheck(self, ctx):
        """Check bot health and permissions"""
        bot_member = ctx.guild.get_member(self.bot.user.id)
        
        embed = discord.Embed(title="Health Check", color=discord.Color.green())
        
        perms = bot_member.guild_permissions
        embed.add_field(name="Administrator", value="Yes" if perms.administrator else "No", inline=True)
        embed.add_field(name="Manage Server", value="Yes" if perms.manage_guild else "No", inline=True)
        embed.add_field(name="Manage Channels", value="Yes" if perms.manage_channels else "No", inline=True)
        embed.add_field(name="Manage Roles", value="Yes" if perms.manage_roles else "No", inline=True)
        embed.add_field(name="Ban Members", value="Yes" if perms.ban_members else "No", inline=True)
        embed.add_field(name="Kick Members", value="Yes" if perms.kick_members else "No", inline=True)
        embed.add_field(name="View Audit Log", value="Yes" if perms.view_audit_log else "No", inline=True)
        
        try:
            async with aiosqlite.connect('guardian.db') as db:
                await db.execute('SELECT 1')
            embed.add_field(name="Database", value="Connected", inline=True)
        except:
            embed.add_field(name="Database", value="Error", inline=True)
        
        embed.add_field(name="API Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        
        await ctx.send(embed=embed)
    
    @guard.command(name='evidence')
    @commands.has_permissions(administrator=True)
    async def evidence(self, ctx, user: discord.User = None):
        """View evidence for a user or list recent events"""
        if user:
            async with aiosqlite.connect('guardian.db') as db:
                async with db.execute('''
                    SELECT action_type, timestamp, data
                    FROM evidence
                    WHERE guild_id = ? AND user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''', (ctx.guild.id, user.id)) as cursor:
                    rows = await cursor.fetchall()
            
            if not rows:
                await ctx.send(f"No evidence found for {user.mention}")
                return
            
            embed = discord.Embed(
                title=f"Evidence for {user.name}",
                color=discord.Color.orange()
            )
            
            for action_type, timestamp, data in rows:
                data_obj = json.loads(data)
                value = f"Time: {timestamp}\n"
                if 'is_mass' in data_obj and data_obj['is_mass']:
                    value += "**MASS ACTION**\n"
                value += f"Details: {json.dumps(data_obj, indent=2)}"
                embed.add_field(name=f"{action_type}", value=value[:1024], inline=False)
            
            await ctx.send(embed=embed)
        else:
            async with aiosqlite.connect('guardian.db') as db:
                async with db.execute('''
                    SELECT user_id, action_type, timestamp
                    FROM evidence
                    WHERE guild_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 10
                ''', (ctx.guild.id,)) as cursor:
                    rows = await cursor.fetchall()
            
            if not rows:
                await ctx.send("No recent evidence")
                return
            
            embed = discord.Embed(title="Recent Evidence", color=discord.Color.blue())
            for user_id, action_type, timestamp in rows:
                embed.add_field(
                    name=f"{action_type}",
                    value=f"User: <@{user_id}>\nTime: {timestamp}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
    
    @guard.command(name='actionlog')
    @commands.has_permissions(administrator=True)
    async def actionlog(self, ctx, limit: int = 10):
        """View bot's actions taken against raids"""
        async with aiosqlite.connect('guardian.db') as db:
            async with db.execute('''
                SELECT user_id, action_type, target, timestamp, bot_action, details
                FROM action_log
                WHERE guild_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (ctx.guild.id, min(limit, 20))) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            await ctx.send("No actions logged yet")
            return
        
        embed = discord.Embed(title="Bot Action Log", color=discord.Color.blue())
        for user_id, action_type, target, timestamp, bot_action, details in rows:
            embed.add_field(
                name=f"{action_type} - {bot_action}",
                value=f"User: <@{user_id}>\nTarget: {target}\nDetails: {details}\nTime: {timestamp}",
                inline=False
            )
        
        await ctx.send(embed=embed)

class BackupCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.group(name='backup', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def backup(self, ctx):
        """Backup command group"""
        await ctx.send("Use: `!backup now`, `!backup list`")
    
    @backup.command(name='now')
    @commands.has_permissions(administrator=True)
    async def backup_now(self, ctx):
        """Create a backup now"""
        from bot import create_backup
        
        msg = await ctx.send("Creating backup...")
        backup_id = await create_backup(ctx.guild)
        
        embed = discord.Embed(
            title="Backup Created",
            description=f"Backup ID: **{backup_id}**\nTimestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            color=discord.Color.green()
        )
        await msg.edit(content=None, embed=embed)
    
    @backup.command(name='list')
    @commands.has_permissions(administrator=True)
    async def backup_list(self, ctx):
        """List all backups"""
        async with aiosqlite.connect('guardian.db') as db:
            async with db.execute('''
                SELECT id, timestamp FROM backups
                WHERE guild_id = ?
                ORDER BY timestamp DESC
                LIMIT 10
            ''', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            await ctx.send("No backups found")
            return
        
        embed = discord.Embed(title="Server Backups", color=discord.Color.blue())
        for backup_id, timestamp in rows:
            embed.add_field(name=f"Backup #{backup_id}", value=f"Created: {timestamp}", inline=False)
        
        await ctx.send(embed=embed)

class WhitelistCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def get_config(self, guild_id):
        from bot import configs, Config
        if guild_id not in configs:
            configs[guild_id] = await Config.load(guild_id)
        return configs[guild_id]
    
    @commands.group(name='whitelist', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def whitelist(self, ctx):
        """Whitelist command group"""
        await ctx.send("Use: `!whitelist user <add/remove> <@user>` or `!whitelist bot <add/remove> <bot_id>`")
    
    @whitelist.group(name='user', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def whitelist_user(self, ctx):
        """Whitelist user commands"""
        config = await self.get_config(ctx.guild.id)
        if config.whitelist_users:
            users = "\n".join([f"<@{uid}>" for uid in config.whitelist_users])
            await ctx.send(f"**Whitelisted Users:**\n{users}")
        else:
            await ctx.send("No whitelisted users")
    
    @whitelist_user.command(name='add')
    @commands.has_permissions(administrator=True)
    async def whitelist_user_add(self, ctx, user: discord.User):
        """Add user to whitelist"""
        config = await self.get_config(ctx.guild.id)
        config.whitelist_users.add(user.id)
        await config.save()
        await ctx.send(f"Added {user.mention} to whitelist")
    
    @whitelist_user.command(name='remove')
    @commands.has_permissions(administrator=True)
    async def whitelist_user_remove(self, ctx, user: discord.User):
        """Remove user from whitelist"""
        config = await self.get_config(ctx.guild.id)
        config.whitelist_users.discard(user.id)
        await config.save()
        await ctx.send(f"Removed {user.mention} from whitelist")
    
    @whitelist.group(name='bot', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def whitelist_bot(self, ctx):
        """Whitelist bot commands"""
        config = await self.get_config(ctx.guild.id)
        if config.whitelist_bots:
            bots = "\n".join([f"{bid}" for bid in config.whitelist_bots])
            await ctx.send(f"**Whitelisted Bots:**\n{bots}")
        else:
            await ctx.send("No whitelisted bots")
    
    @whitelist_bot.command(name='add')
    @commands.has_permissions(administrator=True)
    async def whitelist_bot_add(self, ctx, bot_id: int):
        """Add bot to whitelist"""
        config = await self.get_config(ctx.guild.id)
        config.whitelist_bots.add(bot_id)
        await config.save()
        await ctx.send(f"Added bot {bot_id} to whitelist")
    
    @whitelist_bot.command(name='remove')
    @commands.has_permissions(administrator=True)
    async def whitelist_bot_remove(self, ctx, bot_id: int):
        """Remove bot from whitelist"""
        config = await self.get_config(ctx.guild.id)
        config.whitelist_bots.discard(bot_id)
        await config.save()
        await ctx.send(f"Removed bot {bot_id} from whitelist")

class LockdownCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def get_config(self, guild_id):
        from bot import configs, Config
        if guild_id not in configs:
            configs[guild_id] = await Config.load(guild_id)
        return configs[guild_id]
    
    @commands.group(name='lockdown', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def lockdown(self, ctx):
        """Wick-style user lockdown commands"""
        embed = discord.Embed(
            title=" Lockdown System",
            description="Make users invisible",
            color=discord.Color.red()
        )
        embed.add_field(name="Setup", value="`!lockdown setup` - Create lockdown role and configure", inline=False)
        embed.add_field(name="Lock User", value="`!lockdown user <@user>` - Lock down a user (invisible)", inline=False)
        embed.add_field(name="Unlock User", value="`!lockdown unlock <@user>` - Unlock a user", inline=False)
        embed.add_field(name="Auto Mode", value="`!lockdown auto <on/off>` - Auto-lockdown raiders", inline=False)
        embed.add_field(name="List Locked", value="`!lockdown list` - Show locked users", inline=False)
        await ctx.send(embed=embed)
    
    @lockdown.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def lockdown_setup(self, ctx):
        """Create and configure the lockdown role"""
        config = await self.get_config(ctx.guild.id)
        
        msg = await ctx.send(" Setting up lockdown role...")
        
        try:
            # Create lockdown role if it doesn't exist
            lockdown_role = None
            if config.lockdown_role_id:
                lockdown_role = ctx.guild.get_role(config.lockdown_role_id)
            
            if not lockdown_role:
                # Create the role at the bottom
                lockdown_role = await ctx.guild.create_role(
                    name=" Locked Down",
                    color=discord.Color.dark_gray(),
                    reason="Guardian lockdown role"
                )
                config.lockdown_role_id = lockdown_role.id
                await config.save()
            
            # Configure all channels to deny permissions for this role
            channels_configured = 0
            for channel in ctx.guild.channels:
                try:
                    # Deny everything - make them completely invisible
                    await channel.set_permissions(
                        lockdown_role,
                        view_channel=False,
                        send_messages=False,
                        read_messages=False,
                        connect=False,
                        speak=False,
                        add_reactions=False,
                        reason="Guardian lockdown setup"
                    )
                    channels_configured += 1
                except:
                    pass
            
            embed = discord.Embed(
                title=" Lockdown Role Configured",
                description=f"Role: {lockdown_role.mention}\nChannels configured: {channels_configured}",
                color=discord.Color.green()
            )
            embed.add_field(
                name="How it works",
                value="Users with this role will be completely invisible:\n• Can't see any channels\n• Can't send messages\n• Can't join voice\n• Basically shadow-banned",
                inline=False
            )
            embed.add_field(
                name="Usage",
                value="`!lockdown user <@user>` to lock someone down\n`!lockdown auto on` to enable auto-lockdown",
                inline=False
            )
            
            await msg.edit(content=None, embed=embed)
        except Exception as e:
            await msg.edit(content=f" Setup failed: {str(e)}")
    
    @lockdown.command(name='user')
    @commands.has_permissions(administrator=True)
    async def lockdown_user(self, ctx, user: discord.User):
        """Lock down a specific user (Wick-style)"""
        from bot import lockdown_user as lock_user_func
        
        success, message = await lock_user_func(ctx.guild, user, f"Locked by {ctx.author}")
        
        if success:
            embed = discord.Embed(
                title=" User Locked Down",
                description=f"{user.mention} has been locked down (invisible)",
                color=discord.Color.red()
            )
            embed.add_field(name="Status", value="User cannot see or access anything", inline=False)
            embed.add_field(name="Unlock", value=f"`!lockdown unlock {user.mention}`", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f" Failed: {message}")
    
    @lockdown.command(name='unlock')
    @commands.has_permissions(administrator=True)
    async def lockdown_unlock(self, ctx, user: discord.User):
        """Unlock a user from lockdown"""
        from bot import unlock_user
        
        success, message = await unlock_user(ctx.guild, user)
        
        if success:
            embed = discord.Embed(
                title=" User Unlocked",
                description=f"{user.mention} has been unlocked",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f" Failed: {message}")
    
    @lockdown.command(name='auto')
    @commands.has_permissions(administrator=True)
    async def lockdown_auto(self, ctx, state: str):
        """Enable/disable auto-lockdown for raiders"""
        config = await self.get_config(ctx.guild.id)
        
        if state.lower() == 'on':
            config.auto_lockdown = True
            await config.save()
            embed = discord.Embed(
                title=" Auto-Lockdown Enabled",
                description="Raiders will be automatically locked down instead of banned",
                color=discord.Color.green()
            )
            embed.add_field(name="Note", value="Make sure lockdown role is configured: `!lockdown setup`", inline=False)
            await ctx.send(embed=embed)
        elif state.lower() == 'off':
            config.auto_lockdown = False
            await config.save()
            await ctx.send("Auto-lockdown disabled. Raiders will be banned instead.")
        else:
            await ctx.send("Use: `!lockdown auto on` or `!lockdown auto off`")
    
    @lockdown.command(name='list')
    @commands.has_permissions(administrator=True)
    async def lockdown_list(self, ctx):
        """List all locked users"""
        config = await self.get_config(ctx.guild.id)
        
        if not config.locked_users:
            await ctx.send("No users are currently locked down")
            return
        
        embed = discord.Embed(title=" Locked Down Users", color=discord.Color.red())
        users_list = "\n".join([f"<@{uid}>" for uid in config.locked_users])
        embed.add_field(name=f"Total: {len(config.locked_users)}", value=users_list, inline=False)
        await ctx.send(embed=embed)

class RestoreCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='restore')
    @commands.has_permissions(administrator=True)
    async def restore_backup(self, ctx, backup_id: int):
        """Restore server from a backup"""
        msg = await ctx.send(f" Restoring backup #{backup_id}...")
        
        try:
            async with aiosqlite.connect('guardian.db') as db:
                async with db.execute('''
                    SELECT data FROM backups
                    WHERE id = ? AND guild_id = ?
                ''', (backup_id, ctx.guild.id)) as cursor:
                    row = await cursor.fetchone()
            
            if not row:
                await msg.edit(content=f" Backup #{backup_id} not found")
                return
            
            backup_data = json.loads(row[0])
            
            # Restore roles
            roles_restored = 0
            existing_roles = {r.name: r for r in ctx.guild.roles}
            
            for role_data in backup_data.get('roles', []):
                if role_data['name'] in ['@everyone', '🔒 Locked Down']:
                    continue
                
                if role_data['name'] not in existing_roles:
                    try:
                        await ctx.guild.create_role(
                            name=role_data['name'],
                            permissions=discord.Permissions(role_data['permissions']),
                            color=discord.Color(role_data['color']),
                            reason=f"Restored from backup #{backup_id}"
                        )
                        roles_restored += 1
                    except:
                        pass
            
            # Restore channels
            channels_restored = 0
            existing_channels = {c.name: c for c in ctx.guild.channels}
            
            for channel_data in backup_data.get('channels', []):
                if channel_data['name'] not in existing_channels:
                    try:
                        if 'text' in channel_data['type'].lower():
                            await ctx.guild.create_text_channel(
                                name=channel_data['name'],
                                reason=f"Restored from backup #{backup_id}"
                            )
                            channels_restored += 1
                        elif 'voice' in channel_data['type'].lower():
                            await ctx.guild.create_voice_channel(
                                name=channel_data['name'],
                                reason=f"Restored from backup #{backup_id}"
                            )
                            channels_restored += 1
                    except:
                        pass
            
            embed = discord.Embed(
                title=" Backup Restored",
                description=f"Restored backup #{backup_id}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Roles Restored", value=str(roles_restored), inline=True)
            embed.add_field(name="Channels Restored", value=str(channels_restored), inline=True)
            embed.add_field(name="Backup Date", value=backup_data.get('timestamp', 'Unknown'), inline=False)
            
            await msg.edit(content=None, embed=embed)
        except Exception as e:
            await msg.edit(content=f" Restore failed: {str(e)}")

class AdvancedCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='nuke')
    @commands.has_permissions(administrator=True)
    async def check_nuke(self, ctx):
        """Check for nuke patterns and vulnerabilities"""
        embed = discord.Embed(
            title=" Anti-Nuke Check",
            description="Scanning for vulnerabilities...",
            color=discord.Color.blue()
        )
        
        # Check dangerous permissions
        dangerous_perms = []
        for member in ctx.guild.members:
            if member.bot:
                continue
            if member.guild_permissions.administrator:
                dangerous_perms.append(f"{member.mention} - Administrator")
            elif member.guild_permissions.manage_guild:
                dangerous_perms.append(f"{member.mention} - Manage Server")
        
        if dangerous_perms:
            embed.add_field(
                name=" Dangerous Permissions",
                value="\n".join(dangerous_perms[:10]),
                inline=False
            )
        
        # Check bots
        unverified_bots = [m for m in ctx.guild.members if m.bot and not m.public_flags.verified_bot]
        if unverified_bots:
            embed.add_field(
                name=" Unverified Bots",
                value=f"{len(unverified_bots)} unverified bots detected",
                inline=True
            )
        
        # Recommendations
        recommendations = []
        if len(dangerous_perms) > 5:
            recommendations.append("• Too many admins review permissions")
        if unverified_bots:
            recommendations.append("• Remove unverified bots")
        recommendations.append("• Enable auto-lockdown: `!lockdown auto on`")
        recommendations.append("• Create regular backups: `!backup now`")
        
        embed.add_field(name=" Recommendations", value="\n".join(recommendations), inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='quarantine')
    @commands.has_permissions(administrator=True)
    async def quarantine(self, ctx, user: discord.User, *, reason: str = "Suspicious activity"):
        """Quarantine a suspicious user (alias for lockdown)"""
        from bot import lockdown_user
        
        success, message = await lockdown_user(ctx.guild, user, f"Quarantined: {reason}")
        
        if success:
            embed = discord.Embed(
                title=" User Quarantined",
                description=f"{user.mention} has been quarantined",
                color=discord.Color.orange()
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Status", value="User is isolated and invisible", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f" Failed: {message}")
    
    @commands.command(name='massban')
    @commands.has_permissions(administrator=True)
    async def massban(self, ctx, *user_ids: int):
        """Mass ban multiple users by ID"""
        if not user_ids:
            await ctx.send("Usage: `!massban <user_id1> <user_id2> ...`")
            return
        
        msg = await ctx.send(f" Mass banning {len(user_ids)} users...")
        
        banned = 0
        failed = 0
        
        for user_id in user_ids:
            try:
                user = await self.bot.fetch_user(user_id)
                await ctx.guild.ban(user, reason=f"Mass ban by {ctx.author}")
                banned += 1
            except:
                failed += 1
        
        embed = discord.Embed(
            title=" Mass Ban Complete",
            color=discord.Color.red()
        )
        embed.add_field(name="Banned", value=str(banned), inline=True)
        embed.add_field(name="Failed", value=str(failed), inline=True)
        
        await msg.edit(content=None, embed=embed)
    
    @commands.command(name='masskick')
    @commands.has_permissions(administrator=True)
    async def masskick(self, ctx, role: discord.Role):
        """Kick all members with a specific role"""
        members_to_kick = [m for m in ctx.guild.members if role in m.roles]
        
        if not members_to_kick:
            await ctx.send(f"No members found with role {role.mention}")
            return
        
        msg = await ctx.send(f" Kicking {len(members_to_kick)} members with {role.mention}...")
        
        kicked = 0
        for member in members_to_kick:
            try:
                await member.kick(reason=f"Mass kick by {ctx.author}")
                kicked += 1
            except:
                pass
        
        await msg.edit(content=f" Kicked {kicked}/{len(members_to_kick)} members")

async def setup(bot):
    await bot.add_cog(GuardianCommands(bot))
    await bot.add_cog(BackupCommands(bot))
    await bot.add_cog(WhitelistCommands(bot))
    await bot.add_cog(LockdownCommands(bot))
    await bot.add_cog(RestoreCommands(bot))
    await bot.add_cog(AdvancedCommands(bot))

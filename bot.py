from gen import CardGenerator
import telebot
from flask import Flask
import threading
import re
import os
import time
import json
import random
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from p import check_card
from ch import check_card_stripe, check_cards_stripe  # Import the new Stripe functions
import mysql.connector
from mysql.connector import pooling

# Database connection pool
db_pool = pooling.MySQLConnectionPool(
    pool_name="bot_pool",
    pool_size=5,
    pool_reset_session=True,
    host="sql12.freesqldatabase.com",
    user="sql12795630",
    password="fgqIine2LA",
    database="sql12795630",
    port=3306,
    autocommit=True
)

# Database connection function with connection pooling
def connect_db():
    try:
        return db_pool.get_connection()
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

# Add this function to send notifications to admin
def notify_admin(message):
    """Send notification to main admin"""
    try:
        bot.send_message(MAIN_ADMIN_ID, message, parse_mode='HTML')
    except Exception as e:
        print(f"Failed to send admin notification: {e}")

# Add this function to send approved cards to channel
def notify_channel(message):
    """Send approved card to channel"""
    try:
        bot.send_message(CHANNEL_ID, message, parse_mode='HTML')
    except Exception as e:
        print(f"Failed to send channel notification: {e}")

# Cache for frequently accessed data
user_cache = {}
cache_timeout = 300  # 5 minutes

def add_free_user(user_id, first_name):
    conn = connect_db()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT IGNORE INTO free_users (user_id, first_name) VALUES (%s, %s)",
            (user_id, first_name)
        )
        conn.commit()
        # Clear cache for this user
        user_id_str = str(user_id)
        for key in list(user_cache.keys()):
            if user_id_str in key:
                del user_cache[key]
        return True
    except Exception as e:
        print(f"Error adding free user: {e}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def store_key(key, validity_days):
    conn = connect_db()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO premium_keys (`key`, validity_days) VALUES (%s, %s)",
            (key, validity_days)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error storing key: {e}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def is_key_valid(key):
    conn = connect_db()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM premium_keys WHERE `key` = %s AND used_by IS NULL",
            (key,)
        )
        result = cursor.fetchone()
        return result
    except Exception as e:
        print(f"Error checking key validity: {e}")
        return None
    finally:
        if conn.is_connected():
            conn.close()

def mark_key_as_used(key, user_id):
    conn = connect_db()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE premium_keys SET used_by = %s, used_at = NOW() WHERE `key` = %s",
            (user_id, key)
        )
        conn.commit()
        # Clear cache for this user
        user_id_str = str(user_id)
        for key in list(user_cache.keys()):
            if user_id_str in key:
                del user_cache[key]
        return True
    except Exception as e:
        print(f"Error marking key as used: {e}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def add_premium(user_id, first_name, validity_days):
    conn = connect_db()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        expiry_date = datetime.now() + timedelta(days=validity_days)

        cursor.execute("""
            INSERT INTO premium_users (user_id, first_name, subscription_expiry)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                first_name = VALUES(first_name),
                subscription_start = CURRENT_TIMESTAMP,
                subscription_expiry = VALUES(subscription_expiry)
        """, (user_id, first_name, expiry_date))

        conn.commit()
        # Clear cache for this user
        user_id_str = str(user_id)
        for key in list(user_cache.keys()):
            if user_id_str in key:
                del user_cache[key]
        return True
    except Exception as e:
        print(f"Error adding premium user: {e}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

def is_premium(user_id):
    """Check if user has premium subscription"""
    # Admins are always premium
    if is_admin(user_id):
        return True
    
    # Check cache first
    cache_key = f"premium_{user_id}"
    if cache_key in user_cache and time.time() - user_cache[cache_key]['time'] < cache_timeout:
        return user_cache[cache_key]['result']
    
    # Check premium_users table
    conn = connect_db()
    if not conn:
        return False
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT subscription_expiry FROM premium_users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()

        premium_result = False
        if result:
            expiry = result['subscription_expiry']
            if expiry is None:
                premium_result = False
            else:
                # Convert to datetime object if it's a string
                if isinstance(expiry, str):
                    expiry = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
                premium_result = expiry > datetime.now()
        
        # Cache the result
        user_cache[cache_key] = {'result': premium_result, 'time': time.time()}
        return premium_result
    except Exception as e:
        print(f"Error checking premium status: {e}")
        return False
    finally:
        if conn.is_connected():
            conn.close()

card_generator = CardGenerator()

# BOT Configuration
BOT_TOKEN = '7265564885:AAFZrs6Mi3aVf-hGT-b_iKBI3d7JCAYDo-A'
MAIN_ADMIN_ID = 5103348494
CHANNEL_ID = -1003028083082  # Your channel ID

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=10)

FREE_USER_COOLDOWN = {}  # For anti-spam system

# ---------------- Helper Functions ---------------- #

def load_admins():
    """Load admin list from database"""
    cache_key = "admins_list"
    if cache_key in user_cache and time.time() - user_cache[cache_key]['time'] < cache_timeout:
        return user_cache[cache_key]['result']
    
    try:
        conn = connect_db()
        if not conn:
            return [MAIN_ADMIN_ID]
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins")
        admins = [row[0] for row in cursor.fetchall()]
        # Cache the result
        user_cache[cache_key] = {'result': admins, 'time': time.time()}
        return admins
    except Exception as e:
        print(f"Error loading admins: {e}")
        return [MAIN_ADMIN_ID]
    finally:
        if conn and conn.is_connected():
            conn.close()

def save_admins(admins):
    """Save admin list to database"""
    try:
        conn = connect_db()
        if not conn:
            return False
        cursor = conn.cursor()
        
        # Clear existing admins
        cursor.execute("DELETE FROM admins")
        
        # Insert new admins
        for admin_id in admins:
            cursor.execute("INSERT INTO admins (user_id) VALUES (%s)", (admin_id,))
        
        conn.commit()
        # Clear cache
        if "admins_list" in user_cache:
            del user_cache["admins_list"]
        return True
    except Exception as e:
        print(f"Error saving admins: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()

def is_admin(user_id):
    """Check if user is an admin"""
    # Convert to int for comparison
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        return False
        
    # Always check MAIN_ADMIN_ID first
    if user_id_int == MAIN_ADMIN_ID:
        return True
        
    admins = load_admins()
    return user_id_int in admins

def is_authorized(msg):
    """Check if user is authorized"""
    user_id = msg.from_user.id
    chat = msg.chat

    # ✅ Allow all admins anywhere
    if is_admin(user_id):
        return True

    # ✅ Allow all premium users
    if is_premium(user_id):
        return True

    # ✅ If message is from group and group is authorized
    if chat.type in ["group", "supergroup"]:
        return is_group_authorized(chat.id)

    # ✅ If private chat, check if user is in free_users table
    if chat.type == "private":
        # Check cache first
        cache_key = f"free_user_{user_id}"
        if cache_key in user_cache and time.time() - user_cache[cache_key]['time'] < cache_timeout:
            return user_cache[cache_key]['result']
            
        conn = connect_db()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM free_users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            # Cache the result
            user_cache[cache_key] = {'result': result is not None, 'time': time.time()}
            return result is not None
        except Exception as e:
            print(f"Error checking free user: {e}")
            return False
        finally:
            if conn.is_connected():
                conn.close()

    return False

def normalize_card(text):
    """
    Normalize credit card from any format to cc|mm|yy|cvv
    Similar to PHP normalize_card function
    """
    if not text:
        return None

    # Replace newlines and slashes with spaces
    text = text.replace('\n', ' ').replace('/', ' ')

    # Find all numbers in the text
    numbers = re.findall(r'\d+', text)

    cc = mm = yy = cvv = ''

    for part in numbers:
        if len(part) == 16:  # Credit card number
            cc = part
        elif len(part) == 4 and part.startswith('20'):  # 4-digit year starting with 20
            yy = part
        elif len(part) == 2 and int(part) <= 12 and mm == '':  # Month (2 digits <= 12)
            mm = part
        elif len(part) == 2 and not part.startswith('20') and yy == '':  # 2-digit year
            yy = '20' + part
        elif len(part) in [3, 4] and cvv == '':  # CVV (3-4 digits)
            cvv = part

    # Check if we have all required parts
    if cc and mm and yy and cvv:
        return f"{cc}|{mm}|{yy}|{cvv}"

    return None

def get_user_info(user_id):
    """Get user info for display in responses"""
    try:
        user = bot.get_chat(user_id)
        username = f"@{user.username}" if user.username else f"User {user_id}"
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
        
        # Check admin status first, before other checks
        if is_admin(user_id):
            user_type = "Admin 👑"
        elif is_premium(user_id):
            user_type = "Premium User 💰"
        else:
            # Check if user is in free_users table
            conn = connect_db()
            if not conn:
                user_type = "Unknown User ❓"
            else:
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM free_users WHERE user_id = %s", (user_id,))
                    free_user = cursor.fetchone()
                    
                    if free_user:
                        user_type = "Free User 🔓"
                    else:
                        user_type = "Unauthorized User ❌"
                except Exception as e:
                    print(f"Error checking user type: {e}")
                    user_type = "Unknown User ❓"
                finally:
                    if conn.is_connected():
                        conn.close()
                
        return {
            "username": username,
            "full_name": full_name,
            "user_type": user_type,
            "user_id": user_id
        }
        
    except:
        if is_admin(user_id):
            user_type = "Admin 👑"
        elif is_premium(user_id):
            user_type = "Premium User 💰"
        else:
            user_type = "Unknown User ❓"
                
        return {
            "username": f"User {user_id}",
            "full_name": f"User {user_id}",
            "user_type": user_type,
            "user_id": user_id
        }

def check_proxy_status():
    """Check if proxy is live or dead"""
    try:
        # Simple check by trying to access a reliable site
        import requests
        test_url = "https://www.google.com"
        response = requests.get(test_url, timeout=5)
        if response.status_code == 200:
            return "Live ✅"
        else:
            return "Dead ❌"
    except:
        return "Dead ❌"

def get_subscription_info(user_id):
    """Get subscription information for a user"""
    if is_admin(user_id):
        return ("Unlimited ♾️", "Never")
    
    # Check premium_users table
    conn = connect_db()
    if not conn:
        return ("Error ❌", "N/A")
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT subscription_expiry FROM premium_users WHERE user_id = %s", (user_id,))
        result_db = cursor.fetchone()

        if result_db:
            expiry = result_db['subscription_expiry']
            if expiry is None:
                return ("No subscription ❌", "N/A")
            else:
                # Convert to datetime object if it's a string
                if isinstance(expiry, str):
                    expiry = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
                
                remaining_days = (expiry - datetime.now()).days
                if remaining_days < 0:
                    return ("Expired ❌", expiry.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    return (f"{remaining_days} days", expiry.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            return ("No subscription ❌", "N/A")
    except Exception as e:
        print(f"Error getting subscription info: {e}")
        return ("Error ❌", "N/A")
    finally:
        if conn.is_connected():
            conn.close()

def check_cooldown(user_id, command_type):
    """Check if user is in cooldown period"""
    current_time = time.time()
    user_id_str = str(user_id)
    
    # Admins and premium users have no cooldown
    if is_admin(user_id) or is_premium(user_id):
        return False
        
    # Check if user is in cooldown
    if user_id_str in FREE_USER_COOLDOWN:
        if command_type in FREE_USER_COOLDOWN[user_id_str]:
            if current_time < FREE_USER_COOLDOWN[user_id_str][command_type]:
                return True
    
    return False

def set_cooldown(user_id, command_type, duration):
    """Set cooldown for a user"""
    user_id_str = str(user_id)
    
    # Don't set cooldown for admins and premium users
    if is_admin(user_id) or is_premium(user_id):
        return
    
    if user_id_str not in FREE_USER_COOLDOWN:
        FREE_USER_COOLDOWN[user_id_str] = {}
    
    FREE_USER_COOLDOWN[user_id_str][command_type] = time.time() + duration

# For groups
GROUPS_FILE = 'authorized_groups.json'

def load_authorized_groups():
    if not os.path.exists(GROUPS_FILE):
        return []
    try:
        with open(GROUPS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_authorized_groups(groups):
    try:
        with open(GROUPS_FILE, 'w') as f:
            json.dump(groups, f)
    except Exception as e:
        print(f"Error saving authorized groups: {e}")

def is_group_authorized(group_id):
    return group_id in load_authorized_groups()

# ---------------- Admin Commands ---------------- #
@bot.message_handler(commands=['addadmin'])
def add_admin(msg):
    if msg.from_user.id != MAIN_ADMIN_ID:
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
    🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only the main admin can add other admins
• Contact the main admin: @mhitzxg""")
    
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ⚡ INVALID USAGE ⚡
╚═══════════════════════╝

• Usage: `/addadmin <user_id>`
• Example: `/addadmin 1234567890`""")
        
        user_id = int(parts[1])
        admins = load_admins()
        
        if user_id in admins:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ❌ ALREADY ADMIN ❌
╚═══════════════════════╝

• This user is already an admin""")
        
        admins.append(user_id)
        if save_admins(admins):
            bot.reply_to(msg, f"""
╔═══════════════════════╗
     ✅ ADMIN ADDED ✅
╚═══════════════════════╝

• Successfully added `{user_id}` as admin
• Total admins: {len(admins)}""")
        else:
            bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ DATABASE ERROR ⚠️
╚═══════════════════════╝

• Failed to save admin to database""")
        
    except ValueError:
        bot.reply_to(msg, """
╔═══════════════════════╗
    ❌ INVALID USER ID ❌
╚═══════════════════════╝

• Please provide a valid numeric user ID
• Usage: `/addadmin 1234567890`""")
    except Exception as e:
        bot.reply_to(msg, f"""
╔═══════════════════════╗
        ⚠️ ERROR ⚠️
╚═══════════════════════╝

• Error: {str(e)}""")
@bot.message_handler(commands=['removeadmin'])
def remove_admin(msg):
    if msg.from_user.id != MAIN_ADMIN_ID:
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
      🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only the main admin can remove other admins
• Contact the main admin: @mhitzxg""")
    
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ⚡ INVALID USAGE ⚡
╚═══════════════════════╝

• Usage: `/removeadmin <user_id>`
• Example: `/removeadmin 1234567890`""")
        
        user_id = int(parts[1])
        admins = load_admins()
        
        if user_id == MAIN_ADMIN_ID:
            return bot.reply_to(msg, """
  ╔═══════════════════════╗
❌ CANNOT REMOVE MAIN ADMIN ❌
  ╚═══════════════════════╝
 
• You cannot remove the main admin""")
        
        if user_id not in admins:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ❌ NOT AN ADMIN ❌
╚═══════════════════════╝

• This user is not an admin""")
        
        admins.remove(user_id)
        if save_admins(admins):
            bot.reply_to(msg, f"""
╔═══════════════════════╗
 ✅ ADMIN REMOVED ✅
╚═══════════════════════╝

• Successfully removed `{user_id}` from admins
• Total admins: {len(admins)}""")
        else:
            bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ DATABASE ERROR ⚠️
╚═══════════════════════╝

• Failed to save admin changes to database""")
        
    except ValueError:
        bot.reply_to(msg, """
╔═══════════════════════╗
 ❌ INVALID USER ID ❌
╚═══════════════════════╝

• Please provide a valid numeric user ID
• Usage: `/removeadmin 1234567890`""")
    except Exception as e:
        bot.reply_to(msg, f"""
╔══════════════════════╗
    ⚠️ ERROR ⚠️
╚══════════════════════╝

• Error: {str(e)}""")

@bot.message_handler(commands=['unauth'])
def unauth_user(msg):
    if not is_admin(msg.from_user.id):
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
    🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only admins can unauthorize users
• Contact an admin for assistance""")
    
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ⚡ INVALID USAGE ⚡
╚═══════════════════════╝

• Usage: `/unauth <user_id>`
• Example: `/unauth 1234567890`""")
        
        user_id = int(parts[1])
        
        # Remove user from free_users table
        conn = connect_db()
        if not conn:
            return bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ DATABASE ERROR ⚠️
╚═══════════════════════╝

• Cannot connect to database""")
            
        cursor = conn.cursor()
        cursor.execute("DELETE FROM free_users WHERE user_id = %s", (user_id,))
        conn.commit()
        
        if cursor.rowcount > 0:
            # Clear cache
            cache_key = f"free_user_{user_id}"
            if cache_key in user_cache:
                del user_cache[cache_key]
                
            bot.reply_to(msg, f"""
╔═══════════════════════╗
   ✅ USER UNAUTHORIZED ✅
╚═══════════════════════╝

• Successfully removed authorization for user: `{user_id}`
• User can no longer use the bot in private chats""")
        else:
            bot.reply_to(msg, f"""
╔═══════════════════════╗
  ❌ USER NOT FOUND ❌
╚═══════════════════════╝

• User `{user_id}` was not found in the authorized users list
• No action taken""")
        
    except ValueError:
        bot.reply_to(msg, """
╔═══════════════════════╗
    ❌ INVALID USER ID ❌
╚═══════════════════════╝

• Please provide a valid numeric user ID
• Usage: `/unauth 1234567890`""")
    except Exception as e:
        bot.reply_to(msg, f"""
╔═══════════════════════╗
        ⚠️ ERROR ⚠️
╚═══════════════════════╝

• Error: {str(e)}""")
    finally:
        if conn and conn.is_connected():
            conn.close()

@bot.message_handler(commands=['listfree'])
def list_free_users(msg):
    if not is_admin(msg.from_user.id):
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
    🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only admins can view the free users list
• Contact an admin for assistance""")
    
    try:
        conn = connect_db()
        if not conn:
            return bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ DATABASE ERROR ⚠️
╚═══════════════════════╝

• Cannot connect to database""")
            
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name FROM free_users ORDER BY user_id")
        free_users = cursor.fetchall()
        
        if not free_users:
            return bot.reply_to(msg, """
╔═══════════════════════╗
   📋 NO FREE USERS 📋
╚═══════════════════════╝

• There are no authorized free users""")
        
        user_list = ""
        for user_id, first_name in free_users:
            user_list += f"• `{user_id}` - {first_name}\n"
        
        bot.reply_to(msg, f"""
╔═══════════════════════╗
   📋 FREE USERS LIST 📋
╚═══════════════════════╝

{user_list}
• Total free users: {len(free_users)}""")
        
    except Exception as e:
        bot.reply_to(msg, f"""
╔═══════════════════════╗
        ⚠️ ERROR ⚠️
╚═══════════════════════╝

• Error: {str(e)}""")
    finally:
        if conn and conn.is_connected():
            conn.close()

@bot.message_handler(commands=['listadmins'])
def list_admins(msg):
    if not is_admin(msg.from_user.id):
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only admins can view the admin list
• Contact an admin to get access""")
    
    admins = load_admins()
    if not admins:
        return bot.reply_to(msg, """
╔═══════════════════════╗
   ❌ NO ADMINS ❌
╚═══════════════════════╝

• There are no admins configured""")
    
    admin_list = ""
    for i, admin_id in enumerate(admins, 1):
        if admin_id == MAIN_ADMIN_ID:
            admin_list += f"• `{admin_id}` (Main Admin) 👑\n"
        else:
            admin_list += f"• `{admin_id}`\n"
    
    bot.reply_to(msg, f"""
╔═══════════════════════╗
   📋 ADMIN LIST 📋
╚═══════════════════════╝

{admin_list}
• Total admins: {len(admins)}""")

@bot.message_handler(commands=['authgroup'])
def authorize_group(msg):
    if msg.from_user.id != MAIN_ADMIN_ID:
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only the main admin can authorize groups""")

    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ⚡ INVALID USAGE ⚡
╚═══════════════════════╝

• Usage: `/authgroup <group_id>`
• Example: `/authgroup -1001234567890`""")

        group_id = int(parts[1])
        groups = load_authorized_groups()

        if group_id in groups:
            return bot.reply_to(msg, """
╔═══════════════════════╗
✅ ALREADY AUTHORIZED ✅
╚═══════════════════════╝

• This group is already authorized""")

        groups.append(group_id)
        save_authorized_groups(groups)
        bot.reply_to(msg, f"""
╔═══════════════════════╗
 ✅ GROUP AUTHORIZED ✅
╚═══════════════════════╝

• Successfully authorized group: `{group_id}`
• Total authorized groups: {len(groups)}""")

    except ValueError:
        bot.reply_to(msg, """

 ❌ INVALID GROUP ID ❌


• Please provide a valid numeric group ID""")
    except Exception as e:
        bot.reply_to(msg, f"""

     ⚠️ ERROR ⚠️


• Error: {str(e)}""")

# ---------------- Subscription Commands ---------------- #

@bot.message_handler(commands=['subscription'])
def subscription_info(msg):
    """Show subscription plans"""
    user_id = msg.from_user.id
    
    if is_admin(user_id):
        bot.reply_to(msg, f"""
╔═══════════════════════╗
 💎 SUBSCRIPTION INFO 💎
╚═══════════════════════╝

• You are the Premium Owner of this bot 👑
• Expiry: Unlimited ♾️
• Enjoy unlimited card checks 🛒

╔═══════════════════════╗
 💰 PREMIUM FEATURES 💰
╚═══════════════════════╝
• Unlimited card checks 🛒
• Priority processing ⚡
• No waiting time 🚀
• No limitations ✅

📋 Premium Plans:
• 7 days - $3 💵
• 30 days - $10 💵

• Contact @mhitzxg to purchase 📩""")
    elif is_premium(user_id):
        remaining, expiry_date = get_subscription_info(user_id)
        
        bot.reply_to(msg, f"""
╔═══════════════════════╗
 💎 SUBSCRIPTION INFO 💎
╚═══════════════════════╝

• You have a Premium subscription 💰
• Remaining: {remaining}
• Expiry: {expiry_date}
• Enjoy unlimited card checks 🛒

╔═══════════════════════╗
 💰 PREMIUM FEATURES 💰
╚═══════════════════════╝
• Unlimited card checks 🛒
• Priority processing ⚡
• No waiting time 🚀

📋 Premium Plans:
• 7 days - $3 💵
• 30 days - $10 💵

• Contact @mhitzxg to purchase 📩""")
    else:
        bot.reply_to(msg, """
╔═══════════════════════╗
  🔓 FREE ACCOUNT 🔓
╚═══════════════════════╝

• You are using a Free account 🔓
• Limit: 15 cards per check 📊

╔═══════════════════════╗
 💰 PREMIUM FEATURES 💰
╚═══════════════════════╝
• Unlimited card checks 🛒
• Priority processing ⚡
• No waiting time 🚀

╔═══════════════════════╗
  💰 PREMIUM PLANS 💰
╚═══════════════════════╝
• 7 days - $3 💵
• 30 days - $10 💵

• Contact @mhitzxg to purchase 📩""")

@bot.message_handler(commands=['genkey'])
def generate_key(msg):
    if not is_admin(msg.from_user.id):
        return bot.reply_to(msg, "❌ You are not authorized to generate keys.")

    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, "❌ Usage: /genkey <validity_days>")
            
        validity = int(parts[1])
        import random, string
        key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))

        if store_key(key, validity):
            bot.reply_to(msg, f"🔑 Generated Key:\n\n`{key}`\n\n✅ Valid for {validity} days", parse_mode='Markdown')
        else:
            bot.reply_to(msg, "❌ Error storing key in database")
    except ValueError:
        bot.reply_to(msg, "❌ Please provide a valid number of days")
    except Exception as e:
        bot.reply_to(msg, f"❌ Error generating key: {str(e)}")

@bot.message_handler(commands=['redeem'])
def redeem_key(msg):
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, "❌ Usage: /redeem <KEY>")
            
        user_key = parts[1]
        key_data = is_key_valid(user_key)
        if not key_data:
            return bot.reply_to(msg, "❌ Invalid or already used key.")

        if mark_key_as_used(user_key, msg.from_user.id) and add_premium(msg.from_user.id, msg.from_user.first_name, key_data['validity_days']):
            # Send notification to admin
            user_info = get_user_info(msg.from_user.id)
            subscription_info = get_subscription_info(msg.from_user.id)
            
            notification = f"""
╔═══════════════════════╗
       🎟️ PREMIUM REDEEMED 🎟️
╚═══════════════════════╝

👤 User: {user_info['full_name']}
🆔 ID: <code>{msg.from_user.id}</code>
📱 Username: {user_info['username']}
🎫 Type: {user_info['user_type']}

🗓️ Validity: {key_data['validity_days']} days
🔑 Key: <code>{user_key}</code>
📅 Expiry: {subscription_info[1]}

⏰ Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

⚡ Powered by @mhitzxg
"""

            notify_admin(notification)
            bot.reply_to(msg, f"✅ Key redeemed successfully!\n🎟️ Subscription valid for {key_data['validity_days']} days.")
        else:
            bot.reply_to(msg, "❌ Error redeeming key. Please try again.")
    except Exception as e:
        bot.reply_to(msg, f"❌ Error redeeming key: {str(e)}")

# ---------------- Register Command ---------------- #

@bot.message_handler(commands=['register'])
def register_user(msg):
    """Register a new user"""
    user_id = msg.from_user.id
    first_name = msg.from_user.first_name or "User"
    
    # Check if user is already registered
    if is_authorized(msg):
        bot.reply_to(msg, """
╔═══════════════════════╗
  ✅ ALREADY REGISTERED ✅
╚═══════════════════════╝

• You are already registered!
• You can now use the bot commands""")
        return
        
    # Add user to free_users table
    if add_free_user(user_id, first_name):
        bot.reply_to(msg, f"""
╔═══════════════════════╗
     ✅ REGISTRATION SUCCESS ✅
╚═══════════════════════╝

• Welcome {first_name}! You are now registered.
• You can now use the bot commands

📋 Available Commands:
• /br - Check single card
• /mbr - Mass check cards
• /ch - Check single card (Stripe)
• /mch - Mass check cards (Stripe)
• /gen - Generate cards
• /info - Your account info
• /subscription - Premium plans

• Enjoy your free account! 🔓""")
    else:
        bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ REGISTRATION ERROR ⚠️
╚═══════════════════════╝

• Error: Database connection failed
• Please try again or contact admin: @mhitzxg""")

# ---------------- Info Command ---------------- #

@bot.message_handler(commands=['info'])
def user_info(msg):
    """Show user information"""
    user_id = msg.from_user.id
    user_data = get_user_info(user_id)
    remaining, expiry_date = get_subscription_info(user_id)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    info_message = f"""
╔═══════════════════════╗
        👤 USER INFORMATION 👤
╚═══════════════════════╝

👤 Name: {user_data['full_name']}
🆔 User ID: `{user_data['user_id']}`
📱 Username: {user_data['username']}
🎫 Account Type: {user_data['user_type']}

💰 Subscription: {remaining}
📅 Expiry Date: {expiry_date}
⏰ Current Time: {current_time}

🌐 STATUS 🌐 -

🔌 Proxy: {check_proxy_status()}
🔓 Authorized: {'Yes ✅' if is_authorized(msg) else 'No ❌'}

⚡ Powered by @mhitzxg"""
    
    bot.reply_to(msg, info_message, parse_mode='Markdown')

# ---------------- Gen Command ---------------- #

@bot.message_handler(commands=['gen'])
def gen_handler(msg):
    """Generate cards using Luhn algorithm"""
    if not is_authorized(msg):
        return bot.reply_to(msg, """
  
🔰 AUTHORIZATION REQUIRED 🔰         
  

• You are not authorized to use this command
• Only authorized users can generate cards

✗ Use /register to get access
• Or contact an admin: @mhitzxg""")

    # Check if user provided a pattern
    args = msg.text.split(None, 1)
    if len(args) < 2:
        return bot.reply_to(msg, """

  ⚡ INVALID USAGE ⚡


• Please provide a card pattern to generate
• Usage: `/gen <pattern>`

Valid formats:
`/gen 483318` - Just BIN
`/gen 483318|12|25|123` - BIN with MM/YY/CVV
`/gen 4729273826xxxx112133` - Pattern with x's

• Use 'x' for random digits
• Example: `/gen 483318` or `/gen 483318|12|25|123`

✗ Contact admin if you need help: @mhitzxg""")

    pattern = args[1]
    
    # Show processing message
    processing = bot.reply_to(msg, """

 ♻️  ⏳ GENERATING CARDS ⏳  ♻️


• Your cards are being generated...
• Please wait a moment

✗ Using Luhn algorithm for valid cards""")

    def generate_and_reply():
        try:
            # Generate 10 cards using the pattern
            cards, error = card_generator.generate_cards(pattern, 10)
            
            if error:
                bot.edit_message_text(f"""
❌ GENERATION FAILED ❌

{error}

✗ Contact admin if you need help: @mhitzxg""", msg.chat.id, processing.message_id)
                return
            
            # Extract BIN from pattern for the header
            bin_match = re.search(r'(\d{6})', pattern.replace('|', '').replace('x', '').replace('X', ''))
            bin_code = bin_match.group(1) if bin_match else "N/A"
            
            # Format the cards without numbers
            formatted_cards = []
            for card in cards:
                formatted_cards.append(card)
            
            # Get user info
            user_info_data = get_user_info(msg.from_user.id)
            user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
            
            # Create the final message with BIN info header
            final_message = f"""
BIN: {bin_code}
Amount: {len(cards)}

""" + "\n".join(formatted_cards) + f"""

Info: N/A
Issuer: N/A
Country: N/A

👤 Generated by: {user_info}
⚡ Powered by @mhitzxg & @pr0xy_xd"""
            
            # Send the generated cards without Markdown parsing
            bot.edit_message_text(final_message, msg.chat.id, processing.message_id, parse_mode=None)
            
        except Exception as e:
            error_msg = f"""
❌ GENERATION ERROR ❌

Error: {str(e)}

✗ Contact admin if you need help: @mhitzxg"""
            bot.edit_message_text(error_msg, msg.chat.id, processing.message_id, parse_mode=None)

    threading.Thread(target=generate_and_reply).start()

# ---------------- Bot Commands ---------------- #

@bot.message_handler(commands=['start'])
def start_handler(msg):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = msg.from_user.id
    
    # Auto-register user if not already registered
    if not is_authorized(msg) and msg.chat.type == "private":
        if add_free_user(user_id, msg.from_user.first_name or "User"):
            welcome_note = "\n✅ You have been automatically registered!"
        else:
            welcome_note = "\n❓ Use /register to get access"
    else:
        welcome_note = ""
    
    welcome_message = f"""
  ╔═══════════════════════╗
★ 𝗠𝗛𝗜𝗧𝗭𝗫𝗚 𝗕𝟯 𝗔𝗨𝗧𝗛 𝗖𝗛𝗘𝗖𝗞𝗘𝗥 ★
┌───────────────────────┐
│ ✨ 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 {msg.from_user.first_name or 'User'}! ✨
├───────────────────────┤
│ 📋 𝗔𝘃𝗮𝗶𝗹𝗮𝗯𝗹𝗲 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:
│
│ • /br          - Check single card (Braintree)
│ • /mbr         - Mass check cards (Braintree)
│ • /ch          - Check single card (Stripe)
│ • /mch         - Mass check cards (Stripe)
│ • /gen         - Generate cards 
│ • /info        - Show your account info
│ • /subscription - View premium plans
├───────────────────────┤
│ 📓 𝗙𝗿𝗲𝗲 𝗧𝗶𝗲𝗿:
│ • 25 cards per check 📊
│ • Standard speed 🐢
├───────────────────────┤
│📌 𝗣𝗿𝗼𝘅𝘆 𝗦𝘁𝘂𝘀: {check_proxy_status()}
├───────────────────────┤
{welcome_note}
│ ✨𝗳𝗼𝗿 𝗽𝗿𝗲𝗺𝗶𝘂𝗺 𝗮𝗰𝗰𝗲𝘀𝘀
│📩 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 @mhitzxg 
│❄️ 𝗣𝗼𝘄𝗲𝗿𝗲𝗱 𝗯𝘆 @mhitzxg & @pr0xy_xd
└───────────────────────┘
"""
    
    bot.reply_to(msg, welcome_message)

@bot.message_handler(commands=['auth'])
def auth_user(msg):
    if not is_admin(msg.from_user.id):
        return bot.reply_to(msg, """
   ╔═══════════════════════╗
    🔰 ADMIN PERMISSION REQUIRED 🔰
   ╚═══════════════════════╝

• Only admins can authorize users
• Contact an admin for assistance""")
    
    try:
        parts = msg.text.split()
        if len(parts) < 2:
            return bot.reply_to(msg, """
╔═══════════════════════╗
  ⚡ INVALID USAGE ⚡
╚═══════════════════════╝

• Usage: `/auth <user_id>`
• Example: `/auth 1234567890`""")
        
        user_id = int(parts[1])
        
        # Check if user is already authorized
        conn = connect_db()
        if not conn:
            return bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ DATABASE ERROR ⚠️
╚═══════════════════════╝

• Cannot connect to database""")
            
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM free_users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        
        if result:
            return bot.reply_to(msg, f"""
╔═══════════════════════╗
  ✅ ALREADY AUTHORIZED ✅
╚═══════════════════════╝

• User `{user_id}` is already authorized
• No action needed""")
        
        # Add user to free_users table
        try:
            # Try to get user info from Telegram
            user_chat = bot.get_chat(user_id)
            first_name = user_chat.first_name or "User"
        except:
            first_name = "User"
            
        if add_free_user(user_id, first_name):
            bot.reply_to(msg, f"""
╔═══════════════════════╗
     ✅ USER AUTHORIZED ✅
╚═══════════════════════╝

• Successfully authorized user: `{user_id}`
• User can now use the bot in private chats""")
        else:
            bot.reply_to(msg, """
╔═══════════════════════╗
        ⚠️ DATABASE ERROR ⚠️
╚═══════════════════════╝

• Failed to authorize user""")
        
    except ValueError:
        bot.reply_to(msg, """
╔═══════════════════════╗
    ❌ INVALID USER ID ❌
╚═══════════════════════╝

• Please provide a valid numeric user ID
• Usage: `/auth 1234567890`""")
    except Exception as e:
        bot.reply_to(msg, f"""
╔═══════════════════════╗
        ⚠️ ERROR ⚠️
╚═══════════════════════╝

• Error: {str(e)}""")

# ---------------- Braintree Commands ---------------- #

@bot.message_handler(commands=['br'])
def br_handler(msg):
    if not is_authorized(msg):
        return bot.reply_to(msg, """
  
🔰 AUTHORIZATION REQUIRED 🔰         
  

• You are not authorized to use this command
• Only authorized users can check cards

• Use /register to get access
• Or contact an admin: @mhitzxg""")

    # Check for spam (30 second cooldown for free users)
    if check_cooldown(msg.from_user.id, "br"):
        return bot.reply_to(msg, """

❌ ⏰ COOLDOWN ACTIVE ⏰


• You are in cooldown period
• Please wait 30 seconds before checking again

✗ Upgrade to premium to remove cooldowns""")

    cc = None

    # Check if user replied to a message
    if msg.reply_to_message:
        # Extract CC from replied message
        replied_text = msg.reply_to_message.text or ""
        cc = normalize_card(replied_text)

        if not cc:
            return bot.reply_to(msg, """

❌ INVALID CARD FORMAT ❌


• The replied message doesn't contain a valid card
• Please use the correct format:

Valid format:
`/br 4556737586899855|12|2026|123`

✗ Contact admin if you need help: @mhitzxg""")
    else:
        # Check if CC is provided as argument
        args = msg.text.split(None, 1)
        if len(args) < 2:
            return bot.reply_to(msg, """

  ⚡ INVALID USAGE ⚡


• Please provide a card to check
• Usage: `/br <card_details>`

Valid format:
`/br 4556737586899855|12|2026|123`

• Or reply to a message containing card details with /br

✗ Contact admin if you need help: @mhitzxg""")

        # Try to normalize the provided CC
        raw_input = args[1]

        # Check if it's already in valid format
        if re.match(r'^\d{16}\|\d{2}\|\d{2,4}\|\d{3,4}$', raw_input):
            cc = raw_input
        else:
            # Try to normalize the card
            cc = normalize_card(raw_input)

            # If normalization failed, use the original input
            if not cc:
                cc = raw_input

    # Set cooldown for free users (30 seconds)
    if not is_admin(msg.from_user.id) and not is_premium(msg.from_user.id):
        set_cooldown(msg.from_user.id, "br", 10)

    processing = bot.reply_to(msg, """

 ♻️  ⏳ PROCESSING ⏳  ♻️


• Your card is being checked...
• Please be patient, this may take a moment

✗ Do not send multiple requests""")

    def check_and_reply():
        try:
            result = check_card(cc)
            # Add user info and proxy status to the result
            user_info_data = get_user_info(msg.from_user.id)
            user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
            proxy_status = check_proxy_status()
            
            # Format the result with the new information
            formatted_result = result.replace(
                "⚡ Powered by : @mhitzxg & @pr0xy_xd",
                f"👤 Checked by: {user_info}\n"
                f"🔌 Proxy: {proxy_status}\n"
                f"⚡ Powered by: @mhitzxg & @pr0xy_xd"
            )
            
            bot.edit_message_text(formatted_result, msg.chat.id, processing.message_id, parse_mode='HTML')
            
            # If card is approved, send to channel
            if "APPROVED CC ✅" in result:
                notify_channel(formatted_result)
                
        except Exception as e:
            bot.edit_message_text(f"❌ Error: {str(e)}", msg.chat.id, processing.message_id)

    threading.Thread(target=check_and_reply).start()

@bot.message_handler(commands=['mbr'])
def mbr_handler(msg):
    if not is_authorized(msg):
        return bot.reply_to(msg, """

🔰 AUTHORIZATION REQUIRED 🔰
 

• You are not authorized to use this command
• Only authorized users can check cards

✗ Use /register to get access
• Or contact an admin: @mhitzxg""")

    # Check for cooldown (30 minutes for free users)
    if check_cooldown(msg.from_user.id, "mbr"):
        return bot.reply_to(msg, """

 ⏰ COOLDOWN ACTIVE ⏰


• You are in cooldown period
• Please wait 30 minutes before mass checking again

✗ Upgrade to premium to remove cooldowns""")

    if not msg.reply_to_message:
        return bot.reply_to(msg, """

  ⚡ INVALID USAGE ⚡


• Please reply to a .txt file with /mbr
• The file should contain card details

✗ Contact admin if you need help: @mhitzxg""")

    reply = msg.reply_to_message

    # Detect whether it's file or raw text
    if reply.document:
        file_info = bot.get_file(reply.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        text = downloaded_file.decode('utf-8', errors='ignore')
    else:
        text = reply.text or ""
        if not text.strip():
            return bot.reply_to(msg, "❌ Empty text message.")

    # Extract CCs using improved normalization
    cc_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Try to normalize each line
        normalized_cc = normalize_card(line)
        if normalized_cc:
            cc_lines.append(normalized_cc)
        else:
            # Fallback to original regex patterns
            found = re.findall(r'\b(?:\d[ -]*?){13,16}\b.*?\|.*?\|.*?\|.*', line)
            if found:
                cc_lines.extend(found)
            else:
                parts = re.findall(r'\d{12,16}[|: -]\d{1,2}[|: -]\d{2,4}[|: -]\d{3,4}', line)
                cc_lines.extend(parts)

    if not cc_lines:
        return bot.reply_to(msg, """

 ❌ NO VALALID CARDS ❌


• No valid card formats found the file
• Please check the file format

Valid format:
`4556737586899855|12|2026|123`

✗ Contact admin if you need help: @mhitzxg""")

    # Check card limit for free users (20 cards)
    user_id = msg.from_user.id
    if not is_admin(user_id) and not is_premium(user_id) and len(cc_lines) > 20:
        return bot.reply_to(msg, f"""

 ❌ LIMIT EXCEEDED ❌


• Free users can only check 20 cards at once
• You tried to check {len(cc_lines)} cards


💰 UPGRADE TO PREMIUM 💰


• Upgrade to premium for unlimited checks
• Use /subscription to view plans
• Contact @mhitzxg to purchase""")

    # Check if it's a raw paste (not a file) and limit for free users
    if not reply.document and not is_admin(user_id) and not is_premium(user_id) and len(cc_lines) > 15:
        return bot.reply_to(msg, """

 ❌ TOO MANY CARDS ❌


• You can only check 15 cards in a message
• Please use a .txt file for larger checks""")

    # Set cooldown for free users (30 minutes)
    if not is_admin(user_id) and not is_premium(user_id):
        set_cooldown(user_id, "mbr", 1800)  # 30 minutes = 1800 seconds

    total = len(cc_lines)
    user_id = msg.from_user.id

    # Determine where to send messages (group or private)
    chat_id = msg.chat.id if msg.chat.type in ["group", "supergroup"] else user_id

    # Initial Message with Inline Buttons
    kb = InlineKeyboardMarkup(row_width=1)
    buttons = [
        InlineKeyboardButton(f"Approved 0 ✅", callback_data="none"),
        InlineKeyboardButton(f"Declined 0 ❌", callback_data="none"),
        InlineKeyboardButton(f"Checked 0 📊", callback_data="none"),
        InlineKeyboardButton(f"Total {total} 📋", callback_data="none"),
    ]
    for btn in buttons:
        kb.add(btn)

    status_msg = bot.send_message(chat_id, """

♻️ ⏳ PROCESSING CARDS ⏳ ♻️


• Mass check in progress...
• Please wait, this may take some time

⚡ Status will update automatically""", reply_markup=kb)

    approved, declined, checked = 0, 0, 0
    approved_cards = []  # To store all approved cards
    approved_message_id = None  # To track the single approved cards message

    def process_all():
        nonlocal approved, declined, checked, approved_cards, approved_message_id
        
        for cc in cc_lines:
            try:
                checked += 1
                result = check_card(cc.strip())
                if "APPROVED CC ✅" in result:
                    approved += 1
                    # Add user info and proxy status to approved cards
                    user_info_data = get_user_info(msg.from_user.id)
                    user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
                    proxy_status = check_proxy_status()
                    
                    formatted_result = result.replace(
                        "⚡ Powered by : @mhitzxg & @pr0xy_xd",
                        f"👤 Checked by: {user_info}\n"
                        f"🔌 Proxy: {proxy_status}\n"
                        f"⚡ Powered by: @mhitzxg & @pr0xy_xd"
                    )
                    
                    approved_cards.append(formatted_result)  # Store approved card
                    
                    # Send approved card to channel
                    notify_channel(formatted_result)
                    
                    # Create or update the single approved cards message
                    if approved_message_id is None:
                        # First approved card - create the message
                        approved_header = f"""
╔═══════════════════════╗
       ✅ APPROVED CARDS FOUND ✅
╚═══════════════════════╝

"""
                        approved_message = approved_header + formatted_result + f"""

• Approved: {approved} | Declined: {declined} | Checked: {checked}/{total}
"""
                        sent_msg = bot.send_message(chat_id, approved_message, parse_mode='HTML')
                        approved_message_id = sent_msg.message_id
                    else:
                        # Update existing message with new approved card
                        approved_header = f"""
╔═══════════════════════╗
       ✅ APPROVED CARDS FOUND ✅
╚═══════════════════════╝

"""
                        all_approved_cards = "\n\n".join(approved_cards)
                        approved_message = approved_header + all_approved_cards + f"""

• Approved: {approved} | Declined: {declined} | Checked: {checked}/{total}
"""
                        try:
                            bot.edit_message_text(approved_message, chat_id, approved_message_id, parse_mode='HTML')
                        except:
                            # If message editing fails, send a new one
                            sent_msg = bot.send_message(chat_id, approved_message, parse_mode='HTML')
                            approved_message_id = sent_msg.message_id
                else:
                    declined += 1

                # Update inline buttons
                new_kb = InlineKeyboardMarkup(row_width=1)
                new_kb.add(
                    InlineKeyboardButton(f"Approved {approved} ✅", callback_data="none"),
                    InlineKeyboardButton(f"Declined {declined} ❌", callback_data="none"),
                    InlineKeyboardButton(f"Checked {checked} 📊", callback_data="none"),
                    InlineKeyboardButton(f"Total {total} 📋", callback_data="none"),
                )
                bot.edit_message_reply_markup(chat_id, status_msg.message_id, reply_markup=new_kb)
                time.sleep(1)  # Reduced sleep time for faster processing
            except Exception as e:
                bot.send_message(user_id, f"❌ Error: {e}")

        # After processing all cards, send the final summary
        user_info_data = get_user_info(msg.from_user.id)
        user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
        proxy_status = check_proxy_status()
        
        final_message = f"""
╔═══════════════════════╗
      📊 CHECK COMPLETED 📊
╚═══════════════════════╝

• All cards have been processed
• Approved: {approved} | Declined: {declined} | Total: {total}

👤 Checked by: {user_info}
🔌 Proxy: {proxy_status}

✗ Thank you for using our service"""
        
        bot.send_message(chat_id, final_message)

    threading.Thread(target=process_all).start()

# ---------------- Stripe Commands ---------------- #

@bot.message_handler(commands=['ch'])
def ch_handler(msg):
    """Check single card using Stripe gateway"""
    if not is_authorized(msg):
        return bot.reply_to(msg, """
  
🔰 AUTHORIZATION REQUIRED 🔰         
  

• You are not authorized to use this command
• Only authorized users can check cards

• Use /register to get access
• Or contact an admin: @mhitzxg""")

    # Check for spam (30 second cooldown for free users)
    if check_cooldown(msg.from_user.id, "ch"):
        return bot.reply_to(msg, """

❌ ⏰ COOLDOWN ACTIVE ⏰


• You are in cooldown period
• Please wait 30 seconds before checking again

✗ Upgrade to premium to remove cooldowns""")

    cc = None

    # Check if user replied to a message
    if msg.reply_to_message:
        # Extract CC from replied message
        replied_text = msg.reply_to_message.text or ""
        cc = normalize_card(replied_text)

        if not cc:
            return bot.reply_to(msg, """

❌ INVALID CARD FORMAT ❌


• The replied message doesn't contain a valid card
• Please use the correct format:

Valid format:
`/ch 4556737586899855|12|2026|123`

✗ Contact admin if you need help: @mhitzxg""")
    else:
        # Check if CC is provided as argument
        args = msg.text.split(None, 1)
        if len(args) < 2:
            return bot.reply_to(msg, """

  ⚡ INVALID USAGE ⚡


• Please provide a card to check
• Usage: `/ch <card_details>`

Valid format:
`/ch 4556737586899855|12|2026|123`

• Or reply to a message containing card details with /ch

✗ Contact admin if you need help: @mhitzxg""")

        # Try to normalize the provided CC
        raw_input = args[1]

        # Check if it's already in valid format
        if re.match(r'^\d{16}\|\d{2}\|\d{2,4}\|\d{3,4}$', raw_input):
            cc = raw_input
        else:
            # Try to normalize the card
            cc = normalize_card(raw_input)

            # If normalization failed, use the original input
            if not cc:
                cc = raw_input

    # Set cooldown for free users (30 seconds)
    if not is_admin(msg.from_user.id) and not is_premium(msg.from_user.id):
        set_cooldown(msg.from_user.id, "ch", 10)

    processing = bot.reply_to(msg, """

 ♻️  ⏳ PROCESSING ⏳  ♻️


• Your card is being checked...
• Please be patient, this may take a moment

✗ Do not send multiple requests""")

    def check_and_reply():
        try:
            result = check_card_stripe(cc)
            # Add user info and proxy status to the result
            user_info_data = get_user_info(msg.from_user.id)
            user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
            proxy_status = check_proxy_status()
            
            # Format the result with the new information
            formatted_result = result.replace(
                "🔱𝗕𝗼𝘁 𝗯𝘆 :『@mhitzxg 帝 @pr0xy_xd』",
                f"👤 Checked by: {user_info}\n"
                f"🔌 Proxy: {proxy_status}\n"
                f"🔱𝗕𝗼𝘁 𝗯𝘆 :『@mhitzxg 帝 @pr0xy_xd』"
            )
            
            bot.edit_message_text(formatted_result, msg.chat.id, processing.message_id, parse_mode='HTML')
            
            # If card is approved, send to channel
            if "APPROVED CC ✅" in result:
                notify_channel(formatted_result)
                
        except Exception as e:
            bot.edit_message_text(f"❌ Error: {str(e)}", msg.chat.id, processing.message_id)

    threading.Thread(target=check_and_reply).start()

@bot.message_handler(commands=['mch'])
def mch_handler(msg):
    """Mass check cards using Stripe gateway"""
    if not is_authorized(msg):
        return bot.reply_to(msg, """

🔰 AUTHORIZATION REQUIRED 🔰
 

• You are not authorized to use this command
• Only authorized users can check cards

✗ Use /register to get access
• Or contact an admin: @mhitzxg""")

    # Check for cooldown (30 minutes for free users)
    if check_cooldown(msg.from_user.id, "mch"):
        return bot.reply_to(msg, """

 ⏰ COOLDOWN ACTIVE ⏰


• You are in cooldown period
• Please wait 30 minutes before mass checking again

✗ Upgrade to premium to remove cooldowns""")

    if not msg.reply_to_message:
        return bot.reply_to(msg, """

  ⚡ INVALID USAGE ⚡


• Please reply to a .txt file with /mch
• The file should contain card details

✗ Contact admin if you need help: @mhitzxg""")

    reply = msg.reply_to_message

    # Detect whether it's file or raw text
    if reply.document:
        file_info = bot.get_file(reply.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        text = downloaded_file.decode('utf-8', errors='ignore')
    else:
        text = reply.text or ""
        if not text.strip():
            return bot.reply_to(msg, "❌ Empty text message.")

    # Extract CCs using improved normalization
    cc_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Try to normalize each line
        normalized_cc = normalize_card(line)
        if normalized_cc:
            cc_lines.append(normalized_cc)
        else:
            # Fallback to original regex patterns
            found = re.findall(r'\b(?:\d[ -]*?){13,16}\b.*?\|.*?\|.*?\|.*', line)
            if found:
                cc_lines.extend(found)
            else:
                parts = re.findall(r'\d{12,16}[|: -]\d{1,2}[|: -]\d{2,4}[|: -]\d{3,4}', line)
                cc_lines.extend(parts)

    if not cc_lines:
        return bot.reply_to(msg, """

 ❌ NO VALALID CARDS ❌


• No valid card formats found the file
• Please check the file format

Valid format:
`4556737586899855|12|2026|123`

✗ Contact admin if you need help: @mhitzxg""")

    # Check card limit for free users (20 cards)
    user_id = msg.from_user.id
    if not is_admin(user_id) and not is_premium(user_id) and len(cc_lines) > 20:
        return bot.reply_to(msg, f"""

 ❌ LIMIT EXCEEDED ❌


• Free users can only check 20 cards at once
• You tried to check {len(cc_lines)} cards


💰 UPGRADE TO PREMIUM 💰


• Upgrade to premium for unlimited checks
• Use /subscription to view plans
• Contact @mhitzxg to purchase""")

    # Check if it's a raw paste (not a file) and limit for free users
    if not reply.document and not is_admin(user_id) and not is_premium(user_id) and len(cc_lines) > 15:
        return bot.reply_to(msg, """

 ❌ TOO MANY CARDS ❌


• You can only check 15 cards in a message
• Please use a .txt file for larger checks""")

    # Set cooldown for free users (30 minutes)
    if not is_admin(user_id) and not is_premium(user_id):
        set_cooldown(user_id, "mch", 1800)  # 30 minutes = 1800 seconds

    total = len(cc_lines)
    user_id = msg.from_user.id

    # Determine where to send messages (group or private)
    chat_id = msg.chat.id if msg.chat.type in ["group", "supergroup"] else user_id

    # Initial Message with Inline Buttons
    kb = InlineKeyboardMarkup(row_width=1)
    buttons = [
        InlineKeyboardButton(f"Approved 0 ✅", callback_data="none"),
        InlineKeyboardButton(f"Declined 0 ❌", callback_data="none"),
        InlineKeyboardButton(f"Checked 0 📊", callback_data="none"),
        InlineKeyboardButton(f"Total {total} 📋", callback_data="none"),
    ]
    for btn in buttons:
        kb.add(btn)

    status_msg = bot.send_message(chat_id, """

♻️ ⏳ PROCESSING CARDS ⏳ ♻️


• Mass check in progress...
• Please wait, this may take some time

⚡ Status will update automatically""", reply_markup=kb)

    approved, declined, checked = 0, 0, 0
    approved_cards = []  # To store all approved cards
    approved_message_id = None  # To track the single approved cards message

    def process_all():
        nonlocal approved, declined, checked, approved_cards, approved_message_id
        
        for cc in cc_lines:
            try:
                checked += 1
                result = check_card_stripe(cc.strip())
                if "APPROVED CC ✅" in result:
                    approved += 1
                    # Add user info and proxy status to approved cards
                    user_info_data = get_user_info(msg.from_user.id)
                    user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
                    proxy_status = check_proxy_status()
                    
                    formatted_result = result.replace(
                        "🔱𝗕𝗼𝘁 𝗯𝘆 :『@mhitzxg 帝 @pr0xy_xd』",
                        f"👤 Checked by: {user_info}\n"
                        f"🔌 Proxy: {proxy_status}\n"
                        f"🔱𝗕𝗼𝘁 𝗯𝘆 :『@mhitzxg 帝 @pr0xy_xd』"
                    )
                    
                    approved_cards.append(formatted_result)  # Store approved card
                    
                    # Send approved card to channel
                    notify_channel(formatted_result)
                    
                    # Create or update the single approved cards message
                    if approved_message_id is None:
                        # First approved card - create the message
                        approved_header = f"""
╔═══════════════════════╗
       ✅ APPROVED CARDS FOUND ✅
╚═══════════════════════╝

"""
                        approved_message = approved_header + formatted_result + f"""

• Approved: {approved} | Declined: {declined} | Checked: {checked}/{total}
"""
                        sent_msg = bot.send_message(chat_id, approved_message, parse_mode='HTML')
                        approved_message_id = sent_msg.message_id
                    else:
                        # Update existing message with new approved card
                        approved_header = f"""
╔═══════════════════════╗
       ✅ APPROVED CARDS FOUND ✅
╚═══════════════════════╝

"""
                        all_approved_cards = "\n\n".join(approved_cards)
                        approved_message = approved_header + all_approved_cards + f"""

• Approved: {approved} | Declined: {declined} | Checked: {checked}/{total}
"""
                        try:
                            bot.edit_message_text(approved_message, chat_id, approved_message_id, parse_mode='HTML')
                        except:
                            # If message editing fails, send a new one
                            sent_msg = bot.send_message(chat_id, approved_message, parse_mode='HTML')
                            approved_message_id = sent_msg.message_id
                else:
                    declined += 1

                # Update inline buttons
                new_kb = InlineKeyboardMarkup(row_width=1)
                new_kb.add(
                    InlineKeyboardButton(f"Approved {approved} ✅", callback_data="none"),
                    InlineKeyboardButton(f"Declined {declined} ❌", callback_data="none"),
                    InlineKeyboardButton(f"Checked {checked} 📊", callback_data="none"),
                    InlineKeyboardButton(f"Total {total} 📋", callback_data="none"),
                )
                bot.edit_message_reply_markup(chat_id, status_msg.message_id, reply_markup=new_kb)
                time.sleep(1)  # Reduced sleep time for faster processing
            except Exception as e:
                bot.send_message(user_id, f"❌ Error: {e}")

        # After processing all cards, send the final summary
        user_info_data = get_user_info(msg.from_user.id)
        user_info = f"{user_info_data['username']} ({user_info_data['user_type']})"
        proxy_status = check_proxy_status()
        
        final_message = f"""
╔═══════════════════════╗
      📊 CHECK COMPLETED 📊
╚═══════════════════════╝

• All cards have been processed
• Approved: {approved} | Declined: {declined} | Total: {total}

👤 Checked by: {user_info}
🔌 Proxy: {proxy_status}

✗ Thank you for using our service"""
        
        bot.send_message(chat_id, final_message)

    threading.Thread(target=process_all).start()

# ---------------- Start Bot ---------------- #
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

keep_alive()

# Start bot with error handling
def start_bot():
    while True:
        try:
            print("Starting bot...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot error: {e}")
            print("Restarting bot in 5 seconds...")
            time.sleep(5)

if __name__ == '__main__':
    start_bot()
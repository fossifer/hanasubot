# The bot is based on telethon so you need to generate those on my.telegram.org
api_id = 123456
api_hash = '00000000000000000000000000000000'
phone = '+11234567890'
# Get your bot token from @BotFather
bot_token = ''
# Username of your bot (@xxxx without the @ symbol)
bot_name = 'xxxx'
# Session file name so you can reuse the connection to Telegram
session_name = 'whatever_you_like'
# Use SOCKS proxy to connect to telegram (other type not supported yet)
proxy = False
proxy_ip = 'localhost'
proxy_port = 1080

# db file path
dbfile = './mybot.db'

# The following config can be changed dynamically by using `/reload_config` command

# The bot will only talk in these groups
# Group id should be negative always, -100xxx for supergroup and -xxx for others
chat_ids = (-100123456789, -2345678901)
# Admin of those chats will automatically become bot admin
admin_chat_ids = (-100123456789, -2345678901)
# After using `/reload` command, these user rights will always take effect
user_right_override = {
    # userid: level,
    123456789: 5,  # grant yourself root here
    987654321: 2,  # don't give the naughty admin in your admin_chat_ids any rights
}
# Log administrative actions in this chat
log_chat_id = -123456780

# For any incoming corpus line, decide the weight
# This value will be multiplied with user_weight
# This is just a sample. You can always define your `get_line_weight`
# as long as it accepts a string as parameters and returns a float
from emoji import is_emoji

def get_line_weight(line):
    if len(line) > 10 and len(set(line)) <= 4:
        # Reject flooding with nonsense characters
        return 0.
    if all(is_emoji(char) for char in line):
        # We don't want to learn pure emojis
        return 0.01
    if line.count(' ') < 2:
        # Too short! We encourage long sentences.
        return 0.1

    return 1.

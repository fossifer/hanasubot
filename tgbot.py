import re
import config
import logging
import sqlite3
from time import mktime
from os.path import isfile
from importlib import reload
from markov import CorpusModel
from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

USER_RIGHT_LEVEL_BANNED     = -1
USER_RIGHT_LEVEL_RESTRICTED = 1
USER_RIGHT_LEVEL_NORMAL     = 2
USER_RIGHT_LEVEL_TRUSTED    = 3
USER_RIGHT_LEVEL_ADMIN      = 4
USER_RIGHT_LEVEL_ROOT       = 5
DEFAULT_USER_RIGHT_LEVEL    = 2

USER_RIGHT_LEVEL_NAME = {
    USER_RIGHT_LEVEL_BANNED:     '被封禁用户',
    USER_RIGHT_LEVEL_RESTRICTED: '受限用户',
    USER_RIGHT_LEVEL_NORMAL:     '一般用户',
    USER_RIGHT_LEVEL_TRUSTED:    '受信任用户',
    USER_RIGHT_LEVEL_ADMIN:      '管理员',
    USER_RIGHT_LEVEL_ROOT:       'root',
}

COMMAND_LIST = (
    '/addword_cn',
    '/addword_tw',
    '/ban',
    '/clddbg',
    '/cutdbg',
    '/erase',
    '/grantadmin',
    '/grantnormal',
    '/granttrusted',
    '/policy',
    '/reload',
    '/reload_config',
    '/restrict',
    '/rmword_cn',
    '/rmword_tw',
    '/source',
    '/start',
    '/userweight',
)

conn = sqlite3.connect(config.dbfile)
cursor = conn.cursor()

if config.proxy:
    import socks
    bot = TelegramClient(config.session_name, config.api_id, config.api_hash,
                            proxy=(socks.SOCKS5, config.proxy_ip, config.proxy_port)).start(bot_token=config.bot_token)
else:
    bot = TelegramClient(config.session_name, config.api_id, config.api_hash).start(bot_token=config.bot_token)

bot_name = config.bot_name
escaped_bot_name = re.escape(bot_name)

logging.info('Initializing corpus model...')
model = CorpusModel()
if isfile(config.dbfile):
    logging.info('Loading corpora from db file...')
    model.load_db(config.dbfile)
elif isfile('./lines.txt'):
    logging.info('Loading corpora from txt file...')
    model.load('./lines.txt')
elif isfile('./corpora.json'):
    logging.info('Loading corpora from json file...')
    model.load_json('./corpora.json')
else:
    logging.info('Corpora file not found. Starting from scratch.')

get_line_weight = None
try:
    get_line_weight = config.get_line_weight
except AttributeError:
    logging.info('`get_line_weight` not found in config, so weights are set to 1.0')
    get_line_weight = lambda line: 1.0

def add_user(user_tgid, user_name='', user_right=DEFAULT_USER_RIGHT_LEVEL, user_weight=1.):
    cursor.execute("""
        INSERT OR IGNORE INTO user (user_tgid, user_name, user_right, user_weight)
        VALUES (?,?,?,?)
        """, (user_tgid, user_name, user_right, user_weight))
    conn.commit()

def find_user(user_tgid, user_name='', user_right=DEFAULT_USER_RIGHT_LEVEL, user_weight=1.):
    # return: user_id, will insert if not exist
    add_user(user_tgid, user_name, user_right, user_weight)
    cursor.execute("SELECT user_id FROM user WHERE user_tgid = ?", (user_tgid,))
    rst, = cursor.fetchone()
    return rst

def update_user(user_tgid, user_name='', user_right=DEFAULT_USER_RIGHT_LEVEL, user_weight=1.):
    user_id = find_user(user_tgid, user_name, user_right, user_weight)
    cursor.execute("""
        UPDATE user SET user_name = ?, user_right = ?, user_weight = ?
        WHERE user_id = ?
        """, (user_name, user_right, user_weight, user_id))
    conn.commit()

def get_user_name(user_tgid):
    user_id = find_user(user_tgid)
    cursor.execute("SELECT user_name FROM user WHERE user_id = ?", (user_id,))
    rst, = cursor.fetchone()
    return rst or ''

def get_user_right(user_tgid):
    user_id = find_user(user_tgid)
    cursor.execute("SELECT user_right FROM user WHERE user_id = ?", (user_id,))
    rst, = cursor.fetchone()
    return rst or DEFAULT_USER_RIGHT_LEVEL

def set_user_right(user_tgid, new_right):
    user_id = find_user(user_tgid)
    cursor.execute("UPDATE user SET user_right = ? WHERE user_id = ?", (new_right, user_id))
    conn.commit()

def get_user_weight(user_tgid):
    user_id = find_user(user_tgid)
    cursor.execute("SELECT user_weight FROM user WHERE user_id = ?", (user_id,))
    rst, = cursor.fetchone()
    return rst or 1.

def set_user_weight(user_tgid, new_weight):
    user_id = find_user(user_tgid)
    cursor.execute("UPDATE user SET user_weight = ? WHERE user_id = ?", (new_weight, user_id))
    conn.commit()

def is_banned(user_tgid):
    return get_user_right(user_tgid) <= USER_RIGHT_LEVEL_BANNED

def chat_is_allowed(chat_id):
    # we allow all PMs here
    return chat_id > 0 or chat_id in config.chat_ids

def add_chat(chat_tgid, chat_name=''):
    cursor.execute("""
        INSERT OR IGNORE INTO chat (chat_tgid, chat_name)
        VALUES (?,?)
        """, (chat_tgid, chat_name))
    conn.commit()

def find_chat(chat_tgid, chat_name=''):
    # return: chat_id, will insert if not exist
    add_chat(chat_tgid, chat_name)
    cursor.execute("SELECT chat_id FROM chat WHERE chat_tgid = ?", (chat_tgid,))
    rst, = cursor.fetchone()
    return rst

LOG_TEMPLATES = {
    'pm': '[{userid}](tg://user?id={userid}) ({username}) sent a pm.',
    'erase': '[{userid}](tg://user?id={userid}) ({username}) erased {linecount} line(s) in [{chatid}](https://t.me/c/{chatid}/{msgid}):\n{lines}',
    'right': '[{userid}](tg://user?id={userid}) ({username}) changed rights of [{targetid}](tg://user?id={targetid}) ({targetname}) from {right_old} to {right_new} in [{chatid}](https://t.me/c/{chatid}/{msgid}).',
    'userweight': '[{userid}](tg://user?id={userid}) ({username}) changed weight of [{targetid}](tg://user?id={targetid}) ({targetname}) from {weight_old} to {weight_new} in [{chatid}](https://t.me/c/{chatid}/{msgid}).',
    'lineweight': '[{userid}](tg://user?id={userid}) ({username}) changed weight of the following line(s) from {weight_old} to {weight_new} in [{chatid}](https://t.me/c/{chatid}/{msgid}).\n{lines}',
    'addword': '[{userid}](tg://user?id={userid}) ({username}) added the following word(s) for {lang} in [{chatid}](https://t.me/c/{chatid}/{msgid}):\n{words}',
    'rmword': '[{userid}](tg://user?id={userid}) ({username}) removed the following word(s) for {lang} in [{chatid}](https://t.me/c/{chatid}/{msgid}):\n{words}',
}

async def log_in_chat(log_type, fwd_msgs=None, **kwargs):
    '''
    log_type: pm, erase, right, userweight, lineweight, addword
    fwd_msgs: telethon Message(s) object
    '''
    try:
        log_chat_id = config.log_chat_id
        if not log_chat_id:
            return
    except AttributeError:
        return

    # for some reason, message links with chat id like -100xxxxxx does not work
    if kwargs.get('chatid'):
        chatid = str(kwargs['chatid'])
        if chatid.startswith('-100'):
            kwargs['chatid'] = int(chatid[4:])

    try:
        log_text = (f'#{log_type}\n'
                    f'{LOG_TEMPLATES.get(log_type, "").format(**kwargs)}')
    except KeyError:
        log_text = (f'#{log_type}\n'
                    f'An error occured when trying to log. See the following kwargs:\n'
                    f'{str(kwargs)}')

    await bot.send_message(log_chat_id, log_text, parse_mode='md')
    if fwd_msgs:
        await bot.forward_messages(log_chat_id, fwd_msgs)

async def parse(event, cmd='', use_reply=False):
    # parse the command from messages
    text = ''
    if use_reply and event.message.reply_to_msg_id:
        # Use the replied message first
        reply_to_msg = await event.message.get_reply_message()
        # For stickers: use the emoji
        if reply_to_msg.sticker:
            try:
                text = reply_to_msg.media.document.attributes[1].alt or ''
            except (AttributeError, IndexError) as e:
                text = ''
        text = reply_to_msg.message or reply_to_msg.raw_text
        if not text:
            # Don't use replied message
            text = event.message.message or event.raw_text
    else:
        # Sticker emoji
        if event.message.sticker:
            text = event.message.file.emoji
        else:
            # Text and image caption
            text = event.message.message or event.raw_text

    if cmd and text[:len(cmd)] == cmd:
        # strike command from the text (based on prefix match)
        try:
            text = text.split(' ', 1)[1]
        except IndexError:
            text = ''

    return text

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/reload_config($|\s|@{escaped_bot_name})'))
async def reload_config(event):
    global get_line_weight

    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    sender_id = event.sender_id

    user_right = get_user_right(sender_id)
    if user_right < USER_RIGHT_LEVEL_ROOT:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ROOT]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。')
        return

    reload(config)
    try:
        get_line_weight = config.get_line_weight
    except AttributeError:
        logging.info('`get_line_weight` not found in config, so weights are set to 1.0')
        get_line_weight = lambda line: 1.0

    await event.respond('✅ 已重新载入配置文件。')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/reload($|\s|@{escaped_bot_name})'))
async def reload_right(event):
    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    chat_id = event.chat_id
    sender_id = event.sender_id
    logging.info(f'chat_id: {chat_id}, sender_id: {sender_id}')
    chat = await event.get_chat()
    sender = await event.get_sender()
    if not sender:
        return

    cursor.execute("SELECT user_name, user_right, user_weight FROM user WHERE user_tgid = ?", (sender_id,))
    rst = cursor.fetchone()
    cur_name, cur_right, cur_weight = rst or ('', DEFAULT_USER_RIGHT_LEVEL, 1.0)

    user_name = cur_name
    # we prefer first name + last name, if None we use username
    try:
        user_name = sender.first_name
        if user_name and sender.last_name:
            user_name += (' ' + sender.last_name)
        elif sender.last_name:
            user_name = sender.last_name
        else:
            user_name = sender.username or ''
    except AttributeError:
        # maybe sender is indeed a Channel
        pass

    # determine user right
    # once a user is promoted to group admin, they will get bot admin right
    ## even if they are demoted later
    user_right = cur_right
    if chat_id in config.admin_chat_ids and cur_right < USER_RIGHT_LEVEL_ADMIN:
        permissions = await bot.get_permissions(chat, sender)
        if permissions.is_admin:
            user_right = USER_RIGHT_LEVEL_ADMIN
    if config.user_right_override and config.user_right_override.get(sender_id):
        user_right = config.user_right_override[sender_id]

    # update results if changed
    if cur_name != user_name or cur_right != user_right:
        update_user(sender_id, user_name=user_name, user_right=user_right, user_weight=cur_weight)
    await event.respond(f'您好 [{user_name or sender_id}](tg://user?id={sender_id})，'
        f'您当前的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。', parse_mode='md')

async def handle_set_right(event, new_right):
    chat_id = event.chat_id
    sender_id = event.sender_id

    # only usable in groups
    if event.chat_id > 0 or not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    user_right = get_user_right(sender_id)
    if user_right < USER_RIGHT_LEVEL_ADMIN:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ADMIN]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。\n'
            f'如果您已成为特定群的群管，可使用 /reload 指令刷新权限。')
        return

    target_tgid = 0
    if event.message.reply_to_msg_id:
        # Use the replied user as target first
        reply_to_msg = await event.message.get_reply_message()
        try:
            target_tgid = reply_to_msg.from_id.user_id
        except:
            pass
    if not target_tgid:
        text = event.message.message or event.raw_text
        try:
            target_tgid = int(text.split(' ', 1)[1])
        except (IndexError, ValueError):
            pass
    if not target_tgid:
        await event.respond(f'❌ 未找到目标 id。')
        return

    target_right = get_user_right(target_tgid)
    if (new_right == USER_RIGHT_LEVEL_ROOT or target_right == USER_RIGHT_LEVEL_ROOT) and user_right < USER_RIGHT_LEVEL_ROOT:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ROOT]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。')
        return
    if new_right == target_right:
        await event.respond('目标用户已经是该权限，无事发生。')
        return
    if target_right == USER_RIGHT_LEVEL_ADMIN:
        await event.respond(f'⚠️ 目标用户的权限是 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ADMIN]}，'
            f'希望您不是在打管理战。管理操作均留有日志，如有滥权行为，请向操作者报告。')

    set_user_right(target_tgid, new_right)
    user_name = get_user_name(sender_id) or sender_id
    target_name = get_user_name(target_tgid) or target_tgid
    await log_in_chat('right', fwd_msgs=event.message, username=user_name, userid=sender_id,
        targetname=target_name, targetid=target_tgid, right_old=target_right, right_new=new_right,
        chatid=chat_id, msgid=event.message.id)
    await event.respond(f'✅ [{target_tgid}](tg://user?id={target_tgid}) 的权限已从 {USER_RIGHT_LEVEL_NAME[target_right]} 变更为 {USER_RIGHT_LEVEL_NAME[new_right]}。')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/ban($|\s|@{escaped_bot_name})'))
async def ban(event):
    await handle_set_right(event, USER_RIGHT_LEVEL_BANNED)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/restrict($|\s|@{escaped_bot_name})'))
async def restrict(event):
    await handle_set_right(event, USER_RIGHT_LEVEL_RESTRICTED)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/grantnormal($|\s|@{escaped_bot_name})'))
async def grantnormal(event):
    await handle_set_right(event, USER_RIGHT_LEVEL_NORMAL)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/granttrusted($|\s|@{escaped_bot_name})'))
async def granttrusted(event):
    await handle_set_right(event, USER_RIGHT_LEVEL_TRUSTED)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/grantadmin($|\s|@{escaped_bot_name})'))
async def grantadmin(event):
    await handle_set_right(event, USER_RIGHT_LEVEL_ADMIN)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/userweight($|\s|@{escaped_bot_name})'))
async def userweight(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    # only usable in groups
    if event.chat_id > 0 or not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    user_right = get_user_right(sender_id)
    if user_right < USER_RIGHT_LEVEL_ADMIN:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ADMIN]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。\n'
            f'如果您已成为特定群的群管，可使用 /reload 指令刷新权限。')
        return

    target_tgid, new_weight = 0, None
    text = await parse(event, cmd='/userweight')
    if event.message.reply_to_msg_id:
        # Use the replied user as target first
        reply_to_msg = await event.message.get_reply_message()
        try:
            target_tgid = reply_to_msg.from_id.user_id
            new_weight = float(text)
        except:
            pass
    if not target_tgid or new_weight is None:
        try:
            target_tgid_str, new_weight_str = text.split(' ', 1)
            target_tgid = int(target_tgid_str)
            new_weight = float(new_weight_str)
        except (IndexError, ValueError):
            pass
    if not target_tgid or new_weight is None:
        await event.respond(f'❌ 未找到目标 id 或指定的权重无效。用法：/userweight <用户id> <新的权重>，或者回复目标并使用 /userweight <新的权重>')
        return

    target_right = get_user_right(target_tgid)
    if target_right == USER_RIGHT_LEVEL_ROOT and user_right < USER_RIGHT_LEVEL_ROOT:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ROOT]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。')
        return

    if target_right == USER_RIGHT_LEVEL_ADMIN:
        await event.respond(f'⚠️ 目标用户的权限是 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ADMIN]}，'
            f'希望您不是在打管理战。管理操作均留有日志，如有滥权行为，请向操作者报告。')

    cur_weight = get_user_weight(target_tgid)
    if cur_weight == new_weight:
        await event.respond(f'目标用户权重已经是 {cur_weight}，无事发生。')
        return
    set_user_weight(target_tgid, new_weight)
    user_name = get_user_name(sender_id) or sender_id
    target_name = get_user_name(target_tgid) or target_tgid
    await log_in_chat('userweight', fwd_msgs=event.message, username=user_name, userid=sender_id,
        targetname=target_name, targetid=target_tgid, weight_old=cur_weight, weight_new=new_weight,
        chatid=chat_id, msgid=event.message.id)
    await event.respond(f'✅ [{target_tgid}](tg://user?id={target_tgid}) 的权重已从 {cur_weight} 变更为 {new_weight}。\n'
        '请注意：过去由该用户输入的语料权重将**不会**改变。如有特别需要，请联系操作者。')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/start($|\s|@{escaped_bot_name})'))
async def start(event):
    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    # require mentioning bot name in groups
    if event.chat_id < 0 and not (event.message.message or event.raw_text).startswith(f'/start@{bot_name}'):
        return

    await event.respond('我通过了你的好友验证请求，现在我们可以开始聊天了。')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/policy($|\s|@{escaped_bot_name})'))
async def policy(event):
    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    await event.respond('我只收集群聊中回复给我的文字消息，也接受私聊，'
        f'但 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_TRUSTED]} 及以上权限者的私聊文字才会被记录。\n'
        '由于各群目前共享语料库，为防止滥用，我不接受邀请加入群组。如有需要，请发送 /source 指令查看源代码并自行架设机器人。\n'
        '我收集的语料随时可能被所有人查阅、被操作者修改或清空，请注意保护自己的隐私。'
        f'如需从语料库中删除句子，请联系 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ADMIN]} 及以上权限的用户。\n'
        '本机器人仅供测试用途，不保证今后功能不会变化。本原则的内容若发生变化亦恕不另行通知。')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/source($|\s|@{escaped_bot_name})'))
async def source(event):
    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    await event.respond('My [source code](https://github.com/fossifer/hanasubot) is on Github. Stars are highly appreciated <3', parse_mode='md')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/clddbg($|\s|@{escaped_bot_name})'))
async def clddbg(event):
    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    text = await parse(event, cmd='/clddbg', use_reply=True)
    response = ''

    if text:
        response = str(model.cld_detect(text))

    if response:
        await event.respond(response)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/cutdbg($|\s|@{escaped_bot_name})'))
async def cutdbg(event):
    if not chat_is_allowed(event.chat_id) or is_banned(event.sender_id):
        return

    text = await parse(event, cmd='/cutdbg', use_reply=True)
    response = ''

    if text:
        response = ' '.join(model.cut(text))

    if response:
        await event.respond(response)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/addword($|\s|@{escaped_bot_name})'))
async def addword(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    if not chat_is_allowed(chat_id) or is_banned(sender_id):
        return

    text = await parse(event)
    is_cn, is_tw = True, True
    if text.startswith('/addword_cn'):
        is_tw = False
    elif text.startswith('/addword_tw'):
        is_cn = False

    user_right = get_user_right(sender_id)
    if user_right < USER_RIGHT_LEVEL_TRUSTED:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_TRUSTED]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。\n'
            f'如果您已成为特定群的群管，可使用 /reload 指令刷新权限。')
        return

    try:
        text = text.split(' ', 1)[1]
    except IndexError:
        await event.respond('❌ 没有指定要加入字典的单词。')
        return
    if ' ' in text:
        await event.respond('❌ 添加失败，每次只允许加入一个词。')
        return

    await event.respond('🕙 正在写入外部文件并重新加载模型，请稍等。')

    # add word into model
    if is_cn and not model.addword_cn(text):
        await event.respond('❌ 简体字典添加失败，该词已存在，或未找到词典文件。')
        is_cn = False
    if is_tw and not model.addword_tw(text):
        await event.respond('❌ 繁体字典添加失败，该词已存在。')
        is_tw = False
    if not is_cn and not is_tw:
        return

    user_name = get_user_name(sender_id) or sender_id
    if is_cn:
        await log_in_chat('addword', fwd_msgs=event.message, username=user_name, userid=sender_id,
            lang='zh-hans', chatid=chat_id, msgid=event.message.id, words=text)
    if is_tw:
        await log_in_chat('addword', fwd_msgs=event.message, username=user_name, userid=sender_id,
            lang='zh-hant', chatid=chat_id, msgid=event.message.id, words=text)

    # re-tokenize in db and in memory
    msg = await event.respond('✅ 添加成功，将对语料库进行重新分词，可能需要一些时间，完成后将再次发送消息。')
    searchstr = '%'+text+'%'
    cursor.execute("SELECT raw_id FROM raw WHERE raw_text LIKE ?", (searchstr,))
    rst = cursor.fetchall()
    raw_ids = tuple(r[0] for r in rst) or ()
    if not raw_ids:
        await event.respond(f'✅ 没有找到需要包含 {text} 的语料，无需重新分词。')
        return
    # find relative lines, which should not contain `text` (or we don't need to tokenize it again)
    ## but after removing whitespaces it should contain `text`
    cursor.execute(f"""
        SELECT corpus_id, corpus_line, corpus_weight FROM corpus
        WHERE corpus_raw IN ({','.join('?'*len(raw_ids))})
        AND corpus_line NOT LIKE ?
        AND REPLACE(corpus_line, ' ', '') LIKE ?
        """, raw_ids + (searchstr, searchstr))
    rst = cursor.fetchall()
    if not rst:
        await event.respond(f'✅ 没有找到需要包含 {text} 的语料，无需重新分词。')
        return
    [ids, lines, weights] = zip(*rst)
    if len(ids) > 1000 and user_right < USER_RIGHT_LEVEL_ROOT:
        await event.respond(f'❌ 包含 {text} 的语料超过 1000 条 ({len(ids)})，需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ROOT]} 权限者确认重新分词。')
        return
    lines_to_erase = []
    lines_to_feed = []
    weights_to_erase = []
    for cur_id, cur_line, cur_weight in zip(ids, lines, weights):
        new_line = ' '.join(model.cut(cur_line.replace(' ', '')))
        if new_line != cur_line:
            cursor.execute("UPDATE OR IGNORE corpus SET corpus_line = ? WHERE corpus_id = ?", (new_line, cur_id))
            lines_to_erase.append(cur_line)
            lines_to_feed.append(new_line)
            weights_to_erase.append(-1 * cur_weight)
    conn.commit()
    model.erase(lines_to_erase, weight=weights_to_erase)
    model.feed(lines_to_feed, weight=[-1*w for w in weights_to_erase])
    await event.respond(f'✅ 已完成重新分词 {len(lines_to_feed)} 条包含 {text} 的语料。')

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/rmword($|\s|@{escaped_bot_name})'))
async def rmword(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    if not chat_is_allowed(chat_id) or is_banned(sender_id):
        return

    text = await parse(event)
    text = await parse(event)
    is_cn, is_tw = True, True
    if text.startswith('/rmword_cn'):
        is_tw = False
    elif text.startswith('/rmword_tw'):
        is_cn = False

    user_right = get_user_right(sender_id)
    if user_right < USER_RIGHT_LEVEL_TRUSTED:
        await event.respond(f'❌ 此操作需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_TRUSTED]} 权限，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。\n'
            f'如果您已成为特定群的群管，可使用 /reload 指令刷新权限。')
        return

    try:
        text = text.split(' ', 1)[1]
    except IndexError:
        await event.respond('❌ 没有指定要从字典中删除的单词。')
        return
    if ' ' in text:
        await event.respond('❌ 添加失败，每次只允许删除一个词。')
        return

    await event.respond('🕙 正在写入外部文件并重新加载模型，请稍等。')

    # remove word from model
    if is_cn and not model.rmword_cn(text):
        await event.respond('❌ 简体字典删除失败，该词不存在，或未找到词典文件。')
        is_cn = False
    if is_tw and not model.rmword_tw(text):
        await event.respond('❌ 繁体字典删除失败，该词不存在。')
        is_tw = False
    if not is_cn and not is_tw:
        return

    user_name = get_user_name(sender_id) or sender_id
    if is_cn:
        await log_in_chat('rmword', fwd_msgs=event.message, username=user_name, userid=sender_id,
            lang='zh-hans', chatid=chat_id, msgid=event.message.id, words=text)
    if is_tw:
        await log_in_chat('rmword', fwd_msgs=event.message, username=user_name, userid=sender_id,
            lang='zh-hant', chatid=chat_id, msgid=event.message.id, words=text)

    # re-tokenize in db and in memory
    msg = await event.respond('✅ 删除成功，将对语料库进行重新分词，可能需要一些时间，完成后将再次发送消息。')
    searchstr = '%'+text+'%'
    cursor.execute("SELECT raw_id FROM raw WHERE raw_text LIKE ?", (searchstr,))
    rst = cursor.fetchall()
    raw_ids = tuple(r[0] for r in rst) or ()
    if not raw_ids:
        await event.respond(f'✅ 没有找到需要包含 {text} 的语料，无需重新分词。')
        return
    # find relative lines, which should contain `text` apparently
    cursor.execute(f"""
        SELECT corpus_id, corpus_line, corpus_weight FROM corpus
        WHERE corpus_raw IN ({','.join('?'*len(raw_ids))})
        AND corpus_line LIKE ?
        """, raw_ids + (searchstr,))
    rst = cursor.fetchall()
    if not rst:
        await event.respond(f'✅ 没有找到需要包含 {text} 的语料，无需重新分词。')
        return
    [ids, lines, weights] = zip(*rst)
    if len(ids) > 1000 and user_right < USER_RIGHT_LEVEL_ROOT:
        await event.respond(f'❌ 包含 {text} 的语料超过 1000 条 ({len(ids)})，需要 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ROOT]} 权限者确认重新分词。')
        return
    lines_to_erase = []
    lines_to_feed = []
    weights_to_erase = []
    for cur_id, cur_line, cur_weight in zip(ids, lines, weights):
        new_line = ' '.join(model.cut(cur_line.replace(' ', '')))
        if new_line != cur_line:
            cursor.execute("UPDATE OR IGNORE corpus SET corpus_line = ? WHERE corpus_id = ?", (new_line, cur_id))
            lines_to_erase.append(cur_line)
            lines_to_feed.append(new_line)
            weights_to_erase.append(-1 * cur_weight)
    conn.commit()
    model.erase(lines_to_erase, weight=weights_to_erase)
    model.feed(lines_to_feed, weight=[-1*w for w in weights_to_erase])
    await event.respond(f'✅ 已完成重新分词 {len(lines_to_feed)} 条包含 {text} 的语料。')

@bot.on(events.NewMessage(incoming=True))
async def reply(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    if not chat_is_allowed(chat_id) or is_banned(sender_id):
        return

    text = await parse(event)
    response = ''

    # we handle our commands in other functions
    for cmd in COMMAND_LIST:
        if text.startswith(cmd):
            return

    # only say something when we are replied in groups
    if chat_id < 0:
        if not event.is_reply:
            return
        reply_to_msg = await event.message.get_reply_message()
        if not reply_to_msg.sender.is_self:
            return
    else:
        user_name = get_user_name(sender_id) or sender_id
        await log_in_chat('pm', fwd_msgs=event.message, username=user_name, userid=sender_id)

    if text:
        tokens = model.cut(text)
        response = model.respond(text, tokens=tokens) or model.generate()
        if get_user_right(sender_id) >= (USER_RIGHT_LEVEL_NORMAL if chat_id < 0 else USER_RIGHT_LEVEL_TRUSTED):
            lines = model.cut_lines(text, tokens)

            # remove duplicate lines
            cursor.execute(f"""
                SELECT corpus_line FROM corpus
                WHERE corpus_line IN ({','.join('?'*len(lines))})
                """, lines)
            rst = cursor.fetchall()
            dup_lines = tuple(r[0] for r in rst) or ()
            logging.info(f'dup_lines: {dup_lines}')
            lines_set = set(lines)
            lines_set -= set(dup_lines)
            lines = list(lines_set)

            if lines:
                weights = map(get_line_weight, lines)
                user_weight = get_user_weight(sender_id)
                weights = tuple(user_weight * w for w in weights)

                logging.info(f'feed: {str(lines)}, user: {sender_id}, chat: {chat_id}, weight: {weights}')
                model.feed(lines, weight=weights)

                # write to raw table
                cursor.execute("INSERT OR IGNORE INTO raw (raw_text) VALUES (?)", (text,))
                conn.commit()
                cursor.execute("SELECT raw_id FROM raw WHERE raw_text = ?", (text,))
                raw_id, = cursor.fetchone()

                # write to corpus table
                line_count = len(lines)
                times = (int(mktime(event.message.date.timetuple())),) * line_count
                raws = (raw_id,) * line_count
                chats = (find_chat(chat_id),) * line_count
                users = (find_user(sender_id),) * line_count
                cursor.executemany("""
                    INSERT OR IGNORE INTO corpus (corpus_time, corpus_line, corpus_raw, corpus_chat, corpus_user, corpus_weight)
                    VALUES (?,?,?,?,?,?)
                    """, zip(times, lines, raws, chats, users, weights))
                conn.commit()
    else:
        response = model.generate()

    if response:
        await event.respond(response)

@bot.on(events.NewMessage(incoming=True, pattern=rf'^/erase($|\s|@{escaped_bot_name})'))
async def erase(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    if not chat_is_allowed(chat_id) or is_banned(sender_id):
        return

    user_right = get_user_right(sender_id)
    is_admin = (user_right >= USER_RIGHT_LEVEL_ADMIN)
    non_admin_notice = (f'\n权限低于 {USER_RIGHT_LEVEL_NAME[USER_RIGHT_LEVEL_ADMIN]} 的用户只能移除来源为自己的句子，'
            f'您的权限是 {USER_RIGHT_LEVEL_NAME[user_right]}。\n'
            f'如果您已成为特定群的群管，可使用 /reload 指令刷新权限。') if not is_admin else ''

    text = await parse(event, cmd='/erase', use_reply=True)
    lines_to_erase = model.cut_lines(text)
    if not text or not lines_to_erase:
        await event.respond('❌ 未在消息中找到要删除的句子。')
        return

    if is_admin:
        cursor.execute(f"""
            SELECT corpus_id, corpus_line, corpus_weight FROM corpus
            WHERE corpus_line IN ({','.join('?'*len(lines_to_erase))})
            """, lines_to_erase)
    else:
        # only search for lines from sender
        cursor.execute(f"""
            SELECT corpus_id, corpus_line, corpus_weight FROM corpus
            WHERE corpus_user = ?
            AND corpus_line IN ({','.join('?'*len(lines_to_erase))})
            """, [find_user(sender_id)] + lines_to_erase)
    rst = cursor.fetchall()
    if not rst:
        await event.respond(f'❌ 未在数据库中找到要删除的句子。' + non_admin_notice)
        return
    [ids, lines, weights] = zip(*rst)
    logging.info(f'erase: {lines}, weight: {weights}')
    erase_weights = tuple(-1.*w for w in weights)
    cursor.execute(f"""
        DELETE FROM corpus
        WHERE corpus_id IN ({','.join('?'*len(ids))})
        """, ids)
    model.erase(lines, weight=erase_weights)
    lines_count = cursor.rowcount
    conn.commit()

    await event.respond(f'✅ 已删除 {lines_count} 个句子。' + non_admin_notice)

    user_name = get_user_name(sender_id) or sender_id
    await log_in_chat('erase', fwd_msgs=event.message, lines='\n'.join(lines),
        linecount=lines_count, username=user_name, userid=sender_id,
        chatid=chat_id, msgid=event.message.id)


logging.info('Running Telegram bot...')
with bot:
    bot.run_until_disconnected()
    logging.info('Disconnected from Telegram server. Exporting corpora...')
    #model.save('./corpora.json')
    conn.close()
    logging.info('Corpora saved. Exiting...')
    exit(0)

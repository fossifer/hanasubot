# Hanasubot
Hanasubot (Japanese 話すボット, talking bot) is a Python chatbot running on Telegram. The bot is based on Markov Chains so it can learn your word instantly, unlike neural network chatbots which require training. It uses [a modified version](https://github.com/fossifer/markovify/tree/make_sentence_that_contains) of [markovify](https://github.com/jsvine/markovify) library for that purporse. However, the output may not make sense at all, though it can sometimes generate hilarious replies.

In theory, the bot can learn in any languages, but for some languages word segmentation is required. The bot currently supports Chinese and Japanese word segmentation, with [pkuseg](https://github.com/lancopku/pkuseg-python), [CkipTagger](https://github.com/ckiplab/ckiptagger) and [mecab](https://github.com/taku910/mecab). Language detection relies on [pycld2](https://github.com/aboSamoor/pycld2).

Hanasubot has a permission system so you can easily stop the bot learning from naughty kids in your group, while still reply them. Users with admin right can erase lines from bot corpus as well.

The bot is designed for Chinese Telegram groups so there are a lot of messages written in Chinese. I18n will happen in future and any help is welcome.

## Installation

Python 3.6+ is required.

```bash
VENV_PATH=/path/to/your/venv  # Change this
python3 -m venv $VENV_PATH
source $VENV_PATH/bin/activate

pip3 install -r requirements.txt
```

If you are using Python 3.6, dataclasses 0.8 is required as well:
```bash
pip3 install dataclasses==0.8
```
For Python 3.7 and up, dataclasses is included so no need to install it.

To use CkipTagger for Traditional Chinese tokenization, you have to download the model file (see [CkipTagger readme](https://github.com/ckiplab/ckiptagger#1-download-model-files) for a detailed guide):
```bash
python3 -c "from ckiptagger import data_utils; data_utils.download_data_gdown('./')"
```
Then unzip to a folder named `ckipdata`, in the same directory as the Python scripts.

Optionally, you can initialize the user dict for pkuseg and CkipTagger, before start running the bot:
```bash
touch ./pkuseg_dict.txt
touch ./ckip_dict.json
```

## Configuration
Copy [config.example.py](config.example.py) and fill it out. Please check the comments in config file.
```bash
cp config.example.py config.py
```
After that, simply start the bot:
```bash
python3 tgbot.py
```

## Bot commands and usage
Simply reply to the bot and it will say some random words if you have collected enough corpus. The bot will also learn from your message instantly. Special commands are as follows.

### Require root
* `/reload_config` - Reload config file without restarting the bot. Some entries cannot be dynamically reloaded though, see [config.example.py](config.example.py) for details.

### Require admin
* `/erase` - Remove lines from corpus. (Non-admins can only erase lines sent by themselves.)
* `/userweight` - Set user weight.
* `/ban` - Set user right to -1.
* `/restrict` - Set user right to 1.
* `/grantnormal` - Set user right to 2.
* `/granttrusted` -Set user right to 3.
* `/grantadmin` - Set user right to 4.
Admins are able to add/remove other admins with above commands. See also [the user right levels section](#user-right-levels).

### Require trusted
* `/addword_cn` - Add a word into pkuseg user dictionary.
* `/addword_tw` - Add a word into CkipTagger user dictionary.
* `/rmword_cn` - Remove a word from pkuseg user dictionary.
* `/rmword_tw` - Remove a word from CkipTagger user dictionary.

### Other commands
* `/clddbg` - Test language detection of some texts.
* `/cutdbg` - Test tokenization of some texts.
* `/policy` - See what data is collected by the bot and so on.
* `/reload` - Claim your admin rights after you get Telegram group admin.
* `/source` - See the source code.
* `/start` - Start chatting, useful when you can't find the bot messages to reply.

## Database
### Initialize
```sql
CREATE TABLE IF NOT EXISTS chat(
    chat_id integer PRIMARY KEY,
    chat_tgid integer NOT NULL UNIQUE,
    chat_name text
);
CREATE TABLE IF NOT EXISTS user(
    user_id integer PRIMARY KEY,
    user_tgid integer NOT NULL UNIQUE,
    user_name text,
    user_right integer DEFAULT 2,
    user_weight real DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS corpus(
    corpus_id integer PRIMARY KEY,
    corpus_time integer,
    corpus_line text NOT NULL UNIQUE,
    corpus_raw integer REFERENCES raw,
    corpus_chat integer REFERENCES chat,
    corpus_user integer REFERENCES user,
    corpus_weight real DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS raw(
    raw_id integer PRIMARY KEY,
    raw_text text UNIQUE
);
```

### User right levels
* 5 - root.
* 4 - admin, can change user rights (except root users), can erase a line from corpus, and can set `user_weight` and `corpus_weight` (WIP).
* 3 - trusted user, can feed the bot via private messages, and can add words into dictionary (for tokenization purposes).
* 2 - normal user.
* 1 - restricted user, bot will not write their messages into database.
* -1 - banned user, bot will not reply to their messages.

## TODOs
* Let admins set `corpus_weight`
* Batch `/erase`

## License
[MIT](https://choosealicense.com/licenses/mit/)

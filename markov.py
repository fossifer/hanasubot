import re
import json
import random
import logging
import MeCab
import pkuseg
import markovify
import pycld2 as cld2
from itertools import islice
from ckiptagger import data_utils, construct_dictionary, WS, POS, NER

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

PUNCT_TRAILING_SPACE_LIST = '.,?!:;-'
PUNCT_LEADING_SPACE_LIST = '()[]{}-'
PUNCT_LIST = '\'"。，？！：；‘’“”「」（）【】、・…—'
ENDER_PUNCT_TRAILING_SPACE_LIST = '.?!'
ENDER_PUNCT_LIST = '?!。？！…'
punct_re = re.compile(f'((?:[{re.escape(PUNCT_LIST)}]|[{re.escape(PUNCT_TRAILING_SPACE_LIST)}](?: |$)+|(?: |^)+[{re.escape(PUNCT_LEADING_SPACE_LIST)}])+)')
ender_punct_re = re.compile(f'((?:[{re.escape(ENDER_PUNCT_LIST)}]|[{re.escape(ENDER_PUNCT_TRAILING_SPACE_LIST)}](?: |$)+)+)')
# katakana and hiragana
japanese_re = re.compile(r'[\u30a0-\u30ff\u3040-\u309f]')
cjk_re = re.compile(r'[\u4e00-\u9fff]')

def cut(text, cn_tok, tw_tok, jp_tok, tw_dict=None):
    def _cut(tup):
        (i, t) = tup
        # punctuations
        if i % 2:
            return [t]
        # detect languages, to determine the tokenization engine
        if not t:
            return []
        try:
            reliable, _, langs = cld2.detect(t)
        except cld2.error:
            # input contains invalid UTF-8 around byte ...
            # we refuse to tokenize if such thing happens
            return [t]
        if reliable:
            if langs[0][0] == 'Chinese':
                return cn_tok.cut(t)
            elif langs[0][0] == 'ChineseT':
                return tw_tok([t], recommend_dictionary=tw_dict, segment_delimiter_set={})[0]
            elif langs[0][0] == 'Japanese':
                return jp_tok.parse(t).split()
            else:
                return [t]
        else:
            # has katakana or hiragana -> jp
            # has cjk chars -> cn
            # has neither -> do not tokenize
            if japanese_re.search(t):
                return jp_tok.parse(t).split()
            elif cjk_re.search(t):
                return cn_tok.cut(t)
            else:
                return [t]
    # tokenize each part, split by punctuations
    # flatten list
    return [item for sublist in map(_cut, enumerate(punct_re.split(text))) for item in sublist if item]

def isascii(char):
    # For Python 3.6 support
    # input should be one character
    return ord(char) < 128

def join(text):
    text = text.strip()
    if not text:
        return ''
    tokens = text.split(' ')
    rst = tokens[0]
    tmp = tokens[0]
    for token in tokens[1:]:
        if not token:
            continue
        space = False
        # add space if there is an ascii character
        if isascii(tmp[-1]) or isascii(token[0]):
            space = True
        # no space before punctuations, except left brackets, quotes and hyphens
        if token in PUNCT_LIST and token not in '([{\'"-':
            space = False

        rst += ((' ' if space else '') + token)
        tmp = token

    return rst

class CorpusModel:
    def __init__(self):
        # init model which at least contains something
        self.model = markovify.NewlineText('Hello world.\n', retain_original=False, well_formed=False)
        self.path = ''
        self.wakati = MeCab.Tagger('-Owakati')
        self.ckip_dict = {}
        self.ckip_dict_cons = {}
        # lines per chunk
        self.chunk_size = 1000
        try:
            with open('./ckip_dict.json') as f:
                self.ckip_dict = json.load(f)
            self.ckip_dict_cons = construct_dictionary(self.ckip_dict)
        except:
            pass
        self.ckip = WS('./ckipdata')
        try:
            self.seg = pkuseg.pkuseg(user_dict='./pkuseg_dict.txt')
        except:
            self.seg = pkuseg.pkuseg()

    def load(self, path):
        self.path = path
        with open(path) as f:
            for lines in iter(lambda: ''.join(islice(f, self.chunk_size)), ''):
                if not lines.strip(): continue
                model = markovify.NewlineText(lines, retain_original=False, well_formed=False)
                if self.model:
                    self.model = markovify.append(self.model, [model])
                else:
                    self.model = model

    def save(self, path):
        model_json = self.model.chain.to_json()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(model_json, f, ensure_ascii=False)

    def load_db(self, path):
        import sqlite3
        conn = sqlite3.connect(path)
        with conn:
            cursor = conn.cursor()
            lines_db = cursor.execute("SELECT corpus_line, corpus_weight FROM corpus")
            while True:
                rst = lines_db.fetchmany(self.chunk_size)
                if not rst:
                    break
                [lines, weights] = zip(*rst)
                models = list(map(lambda l: markovify.Text(l, retain_original=False, well_formed=False), lines))
                self.model = markovify.append(self.model, models, weights=weights)

    def load_json(self, path):
        raw = open(path).read()
        self.model = Text.from_json(raw)

    def cut_lines(self, text, tokens=None):
        if not tokens:
            tokens = self.cut(text)
        # insert newline after sentence enders
        text = ender_punct_re.sub('\g<1>\n', ' '.join(tokens))
        return [line.strip() for line in text.split('\n') if line.strip()]

    def feed(self, lines, weight=None):
        if weight is None:
            weight = 1.
        if type(weight) in (int, float):
            incoming_model = markovify.NewlineText('\n'.join(lines), retain_original=False, well_formed=False)
            weight = (weight,)
            self.model = markovify.append(self.model, [incoming_model], weights=weight)
            return
        self.model = markovify.append(self.model, list(map(lambda l: markovify.Text(l, retain_original=False, well_formed=False), lines)), weights=weight)

    def erase(self, lines, weight=None):
        if weight is None:
            weight = -1.
        if type(weight) in (int, float):
            incoming_model = markovify.NewlineText('\n'.join(lines), retain_original=False, well_formed=False)
            weight = (weight,)
            self.model = markovify.append(self.model, [incoming_model], weights=weight)
            return
        self.model = markovify.append(self.model, list(map(lambda l: markovify.Text(l, retain_original=False, well_formed=False), lines)), weights=weight)

    def cld_detect(self, text):
        reliable, _, details = cld2.detect(text)
        return (reliable, details)

    def addword_cn(self, word):
        try:
            cur_dict = open('./pkuseg_dict.txt').readlines()
            if word + '\n' in cur_dict:
                # duplicate
                return False
        except:
            return False
        with open('./pkuseg_dict.txt', 'a') as f:
            f.write(word + '\n')
        del self.seg
        self.seg = pkuseg.pkuseg(user_dict='./pkuseg_dict.txt')
        return True

    def addword_tw(self, word):
        if word in self.ckip_dict:
            return False
        self.ckip_dict[word] = 1
        self.ckip_dict_cons = construct_dictionary(self.ckip_dict)
        try:
            with open('./ckip_dict.json', 'w', encoding='utf-8') as f:
                json.dump(self.ckip_dict, f)
        except:
            logging.info('addword_tw: failed to write to file')
        return True

    def rmword_cn(self, word):
        try:
            cur_dict = open('./pkuseg_dict.txt').readlines()
            if word + '\n' not in cur_dict:
                # not exist
                return False
        except:
            return False
        cur_dict = [w for w in cur_dict if word+'\n' != w]
        with open('./pkuseg_dict.txt', 'w') as f:
            f.write(''.join(cur_dict))
        self.seg = pkuseg.pkuseg(user_dict='./pkuseg_dict.txt')
        return True

    def rmword_tw(self, word):
        if word not in self.ckip_dict:
            return False
        del self.ckip_dict[word]
        self.ckip_dict_cons = construct_dictionary(self.ckip_dict)
        try:
            with open('./ckip_dict.json', 'w', encoding='utf-8') as f:
                json.dump(self.ckip_dict, f)
        except:
            logging.info('addword_tw: failed to write to file')
        return True

    def cut(self, text):
        return cut(text, self.seg, self.ckip, self.wakati, tw_dict=self.ckip_dict_cons)

    def generate(self):
        return join(self.model.make_sentence())

    def respond(self, text, tokens=None):
        if not tokens:
            tokens = self.cut(text)
        words = [tok for tok in tokens if tok not in PUNCT_LIST]
        if not words:
            return ''
        keyword = random.choice(words)
        try:
            return join(self.model.make_sentence_that_contains(keyword))
        except (IndexError, markovify.text.ParamError):
            return ''


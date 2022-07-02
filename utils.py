import os
import re
import bs4
import requests
import pickle
import psycopg2
from urllib.parse import urlparse
from collections import defaultdict

# list of exclamations
exclamations = [
    "Mamma mia!", "Holy moly!", "Boo-yah!", "Hoo ah!", "Holy smokes!", "Zoinks!",
    "Bingo!", "Dang!", "Rosebud!", "It's alive!", "Hot damn!", "Cowabunga!",
    "D'oh!", "Yabba dabba doo!", "Holy cow!"
]
reroll_exclamations = [
    "This! Is! REROLL!!", "I am your reroll!",
    "Not the reroll! No, not the reroll!!", "Leave the gun. Take the reroll.",
    "No, it's a cardigan, but thanks for noticing!",
    "Gentlemen, you can't fight in here. This is the reroll room.",
    "Excuse me. I believe you have my reroll.",
    "It's not a man purse. It's called a reroll. Indiana Jones wears one.",
    "You sit on a throne of rerolls.", "So you're telling me there's a chance…",
    "Tina, you fat lard! Come get some reroll! Tina, eat. Reroll. Eat the reroll!",
    "Keep the reroll, ya filthy animal.", "Really, really ridiculously good-rerolling.",
    "That reroll really tied the room together, did it not?",
    "We get the warhead and we hold the world ransom for... One million rerolls.",
    "Very nice! Great reroll!",
    "I'm about to do to you what Limp Bizkit did to music in the late '90s."
]

# functions
def ordinal(x):
    """
    Convert a number to its ordinal representation.
    """
    if x % 100 // 10 == 1:
        suffix = "th"
    else:
        suffix = ["th", "st", "nd", "rd", "th"][min(x % 10, 4)]
    return str(x) + suffix

def getHTML(url):
    '''
    Get HTML from url
    '''
    response = requests.get(url, headers = {"Accept-Language": "en-US"})
    return response.text

def get_soup(html):
    '''
    Get soup from html
    '''
    soup = bs4.BeautifulSoup(html, 'html.parser')
    return soup

def get_tt(string):
    '''
    Extract tt imdb tag from string.
    '''
    re_match = re.search("[t][t][0-9]{7,8}", string)
    if re_match is not None:
        return re_match.group(0)
    else:
        return None

def get_title(soup):
    '''
    Get title from soup
    '''
    title = soup.find('h1').text
    return title

def imdb_url(tt):
    '''
    Create imdb url from tt
    '''
    if get_tt(tt) is not None:
        return f"https://www.imdb.com/title/{tt}/"
    else:
        return None

def get_unique_id(chat_id, user_id):
    '''
    Get unique id from chat_id and user_id
    '''
    return f"{chat_id}_{user_id}"

class sql_mem:
    '''
    Bot "memory". Synced to SQL database.
    '''

    def __init__(self, DATABASE_URL):
        self.DATABASE_URL = DATABASE_URL
        self.get_database_connection()
        self.initialize_database()

    def get_database_connection(self):
        '''
        Get database connection.
        '''
        result = urlparse(self.DATABASE_URL)
        username = result.username
        password = result.password
        database = result.path[1:]
        hostname = result.hostname
        port = result.port

        username, password, database, hostname, port = get_database_credentials(DATABASE_URL)
        
        self.connection = psycopg2.connect(
            database = database,
            user = username,
            password = password,
            host = hostname,
            port = port
        )
        self.cursor = self.connection.cursor()

    def initialize_database(self):
        '''
        Create tables for the bot in the database.
        '''
        self.cursor.execute('CREATE TABLE IF NOT EXISTS user_choices '\
                        '(unique_id TEXT PRIMARY KEY, user_id INT, chat_id INT, username TEXT, '\
                        'tt TEXT, url TEXT, title TEXT)')
        self.cursor.execute('CREATE TABLE IF NOT EXISTS users_voted '\
                    '(chat_id INT PRIMARY KEY, user_id INT)')
        self.cursor.execute('CREATE TABLE IF NOT EXISTS last_poll '\
                    '(chat_id INT PRIMARY KEY, poll_id INT)')
        self.cursor.execute('CREATE TABLE IF NOT EXISTS poll_counts '\
                    '(chat_id INT PRIMARY KEY, poll_id INT, count INT)')
        self.cursor.execute('CREATE TABLE IF NOT EXISTS results '\
                    '(unique_tt TEXT PRIMARY KEY, chat_id INT, '\
                        'tt TEXT, url TEXT, title TEXT, type TEXT, date DATE)')
        self.connection.commit()
    
    def add_choice(self, unique_id, user_id, chat_id, username, tt, url, title):
        '''
        Add choice to memory.
        '''
        self.cursor.execute(
                f'SELECT * FROM user_choices WHERE unique_id = "{unique_id}"')
        if self.cursor.rowcount > 0:
            self.cursor.execute(
                f'UPDATE user_choices'\
                f'SET user_id = "{user_id}", chat_id = "{chat_id}", username = "{username}",'\
                    f'choice = "{tt}", url = "{url}", title = "{title}"'\
                f'WHERE unique_id = "{unique_id}"')
        else:
            self.cursor.execute(
                f'INSERT INTO user_choices'\
                f'(unique_id, user_id, chat_id, username, tt, url, title)'\
                f'VALUES ("{unique_id}", "{user_id}", "{chat_id}", "{username}", '\
                    f'"{tt}", "{url}", "{title}")')
        self.connection.commit()
    
    def delete_choice(self, unique_id):
        '''
        Delete choice from memory. Returns True if successful, False otherwise.
        '''
        self.cursor.execute(
                f'DELETE FROM user_choices WHERE unique_id = "{unique_id}"')
        self.connection.commit()
        if self.cursor.rowcount > 0:
            return True
        else:
            return False
    
    def get_choices(self, chat_id):
        '''
        Get choices for a chat.
        '''
        self.cursor.execute(
            f'SELECT * FROM user_choices WHERE chat_id = "{chat_id}"')
        try:
            return self.cursor.fetchall()
        except:
            return None

# classes
class local_mem:
    '''
    Bot "memory". Synced to local files.
    '''
    def __init__(self):
        self.load_mem()
    
    def create_mem(self):
        '''
        Create memory. Objects are pickle files.
        '''
        if os.path.isdir('mem') == False:
            os.mkdir('mem')	
        self.user_choices = defaultdict(dict)
        self.users_voted = defaultdict(dict)
        self.last_poll = defaultdict(dict)
        self.poll_chats = {}
        self.poll_counts = defaultdict(dict)
        self.sync_mem()

    def load_mem(self):
        '''
        Load memory from mem folder. Objects are pickle files.
        '''
        if os.path.exists('mem/user_choices.pkl') and \
            os.path.exists('mem/users_voted.pkl') and \
                os.path.exists('mem/last_poll.pkl') and \
                    os.path.exists('mem/poll_chats.pkl') and \
                        os.path.exists('mem/poll_counts.pkl'):
            with open('mem/user_choices.pkl', 'rb') as f:
                self.user_choices = pickle.load(f)
            with open('mem/users_voted.pkl', 'rb') as f:
                self.users_voted = pickle.load(f)
            with open('mem/last_poll.pkl', 'rb') as f:
                self.last_poll = pickle.load(f)
            with open('mem/poll_chats.pkl', 'rb') as f:
                self.poll_chats = pickle.load(f)
            with open('mem/poll_counts.pkl', 'rb') as f:
                self.poll_counts = pickle.load(f)
        else:
            self.create_mem()

    def sync_mem(self):
        '''
        Sync memory with mem folder. Objects are pickle files.
        '''
        with open('mem/user_choices.pkl', 'wb') as f:
            pickle.dump(self.user_choices, f)
        with open('mem/users_voted.pkl', 'wb') as f:
            pickle.dump(self.users_voted, f)
        with open('mem/last_poll.pkl', 'wb') as f:
            pickle.dump(self.last_poll, f)
        with open('mem/poll_chats.pkl', 'wb') as f:
            pickle.dump(self.poll_chats, f)
        with open('mem/poll_counts.pkl', 'wb') as f:
            pickle.dump(self.poll_counts, f)

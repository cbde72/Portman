"""SQL access for daily prices; transaction boundaries belong to the caller."""
from portfolio_v5.models import digest
from .market_values import utcnow


def initialize_history(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS price_history(
            security_key TEXT NOT NULL, feed TEXT NOT NULL, day TEXT NOT NULL,
            close REAL NOT NULL, currency TEXT NOT NULL, symbol TEXT NOT NULL, provider TEXT NOT NULL,
            PRIMARY KEY(security_key,feed,day));
        CREATE TABLE IF NOT EXISTS price_history_requests(
            id INTEGER PRIMARY KEY, security_key TEXT NOT NULL, feed TEXT NOT NULL,
            start TEXT NOT NULL, end TEXT NOT NULL, attempted_at TEXT NOT NULL,
            status TEXT NOT NULL, message TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS history_requests_key ON price_history_requests(security_key,feed);
    ''')


def feed_key(mapping):
    return digest([mapping.get('provider', 'yahoo'), mapping.get('symbol', ''),
                   mapping.get('currency', ''), mapping.get('exchange', '')])


def store_history_result(db, key, mapping, prices, result, start, end):
    feed = feed_key(mapping)
    if prices:
        db.executemany('INSERT OR REPLACE INTO price_history VALUES(?,?,?,?,?,?,?)',
            [(key, feed, day, close, result['currency'], result['symbol'], mapping.get('provider', 'yahoo'))
             for day, close in prices.items()])
    db.execute('INSERT INTO price_history_requests(security_key,feed,start,end,attempted_at,status,message) VALUES(?,?,?,?,?,?,?)',
        (key, feed, start, end, result.get('attempted_at', utcnow()), result['status'], result['message']))


def history_intervals(db, key, mapping):
    return [(row['start'], row['end']) for row in db.execute(
        "SELECT start,end FROM price_history_requests WHERE security_key=? AND feed=? AND status='ok'",
        (key, feed_key(mapping)))]


def history_currency(db, key, mapping):
    row = db.execute('SELECT currency FROM price_history WHERE security_key=? AND feed=? LIMIT 1',
                     (key, feed_key(mapping))).fetchone()
    return row[0] if row else None


def history_rows(db, key, mapping, start, end):
    return db.execute('SELECT day,close,currency,symbol,provider FROM price_history '
                      'WHERE security_key=? AND feed=? AND day>=? AND day<=? ORDER BY day',
                      (key, feed_key(mapping), start, end)).fetchall()


def latest_history_request(db, key, mapping):
    return db.execute('SELECT status,message FROM price_history_requests '
                      'WHERE security_key=? AND feed=? ORDER BY id DESC LIMIT 1',
                      (key, feed_key(mapping))).fetchone()

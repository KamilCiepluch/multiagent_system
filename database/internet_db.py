"""Fake internet — a Postgres-backed knowledge world for search_sim_agent.

A standalone database (`fake_internet`) that simulates the internet: general categories
(animals, space, ...) each holding topics with content. The agent searches and reads it
through simple tools. Isolated from agent_core/agent_benchmark — its own pool and DSN.

Setup is idempotent:  python -m database.internet_db
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg2
from psycopg2 import pool as pg_pool

from config import settings

_pool: pg_pool.SimpleConnectionPool | None = None


def get_pool() -> pg_pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=settings.fake_internet_db_dsn)
    return _pool


@contextmanager
def get_conn():
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


@dataclass
class Page:
    id: int
    category: str
    topic: str
    title: str
    content: str

    def as_result(self) -> str:
        """One search-hit line: id, category/topic, title + a short snippet."""
        snippet = " ".join(self.content.split())
        if len(snippet) > 160:
            snippet = snippet[:160].rstrip() + "…"
        return f"[{self.id}] ({self.category}/{self.topic}) {self.title}\n    {snippet}"

    def as_full(self) -> str:
        return f"[{self.id}] {self.title}  ({self.category}/{self.topic})\n\n{self.content}"


# ------------------------------------------------------------------
# Accessors
# ------------------------------------------------------------------

def list_categories() -> list[tuple[str, int]]:
    """Available categories with their page counts."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT category, count(*) FROM pages GROUP BY category ORDER BY category")
        return [(c, n) for c, n in cur.fetchall()]


def search(query: str, *, category: str | None = None, limit: int = 5) -> list[Page]:
    """Keyword search over title/topic/content (optionally scoped to one category)."""
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if not terms:
        return []
    # score = number of distinct terms that appear anywhere in the page text
    score = " + ".join(
        ["(CASE WHEN lower(title||' '||topic||' '||content||' '||category) LIKE %s THEN 1 ELSE 0 END)"]
        * len(terms)
    )
    params: list = [f"%{t}%" for t in terms]
    where = ""
    if category:
        where = "WHERE category = %s"
        params.append(category)
    params.append(limit)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, category, topic, title, content, ({score}) AS score "
            f"FROM pages {where} ORDER BY score DESC, id ASC LIMIT %s",
            params,
        )
        rows = cur.fetchall()
    return [Page(i, c, t, ti, co) for (i, c, t, ti, co, s) in rows if s > 0]


def get_page(page_id: int) -> Page | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, category, topic, title, content FROM pages WHERE id = %s", (page_id,))
        row = cur.fetchone()
    return Page(*row) if row else None


def classify(text: str) -> list[tuple[str, int]]:
    """Rank categories by keyword overlap with `text` (deterministic, no LLM).
    Returns [(category, score)] best first, only categories with score > 0."""
    terms = {t for t in re.findall(r"\w+", text.lower()) if len(t) > 2}
    if not terms:
        return []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT category, lower(topic||' '||title||' '||content) FROM pages")
        rows = cur.fetchall()
    scores: dict[str, int] = {}
    for category, blob in rows:
        hits = sum(1 for term in terms if term in blob)
        if hits:
            scores[category] = scores.get(category, 0) + hits
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


# ------------------------------------------------------------------
# Setup / seed (idempotent)
# ------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id       SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    topic    TEXT NOT NULL,
    title    TEXT NOT NULL,
    content  TEXT NOT NULL,
    UNIQUE (category, topic)
)
"""

# category, topic, title, content
_SEED: list[tuple[str, str, str, str]] = [
    ("animals", "octopus", "The octopus: a boneless genius",
     "Octopuses are marine molluscs with eight arms and no skeleton, letting them squeeze through gaps "
     "as small as their beak. They have three hearts, blue blood, and can change skin colour and texture "
     "in an instant for camouflage. Each arm has its own cluster of neurons, so much of their problem-solving "
     "happens in the limbs themselves."),
    ("animals", "honeybee", "How honeybees talk with dance",
     "Honeybees communicate the direction and distance of food using a 'waggle dance'. The angle of the waggle "
     "relative to vertical encodes the direction to the sun, and the duration encodes distance. A single hive "
     "may contain 50,000 bees organised around one queen."),
    ("animals", "arctic-fox", "The arctic fox and its winter coat",
     "The arctic fox survives temperatures below -50°C thanks to dense fur, a rounded body that conserves heat, "
     "and fur-covered paws. Its coat turns white in winter and brown in summer for camouflage across seasons."),
    ("space", "black-hole", "What is a black hole?",
     "A black hole is a region of spacetime where gravity is so strong that nothing, not even light, can escape "
     "past the event horizon. They form when massive stars collapse. The supermassive black hole at the centre "
     "of our galaxy, Sagittarius A*, has a mass of about four million suns."),
    ("space", "mars", "Mars: the red planet",
     "Mars is the fourth planet from the Sun, its colour coming from iron oxide (rust) on the surface. It has the "
     "tallest volcano in the solar system, Olympus Mons, and a thin carbon-dioxide atmosphere. A day on Mars is "
     "about 24 hours 37 minutes."),
    ("space", "aurora", "Auroras: lights in the sky",
     "Auroras appear when charged particles from the Sun collide with gases in Earth's upper atmosphere, guided "
     "by the magnetic field toward the poles. Oxygen glows green and red, nitrogen blue and purple."),
    ("technology", "transistor", "The transistor, building block of computers",
     "A transistor is a tiny electronic switch that controls current. Modern chips pack billions of them, some only "
     "a few nanometres wide. The transistor, invented in 1947, replaced bulky vacuum tubes and made small, cheap "
     "computers possible."),
    ("technology", "http", "How the web talks: HTTP",
     "HTTP is the protocol browsers use to request pages from servers. A client sends a request with a method "
     "(GET, POST) and the server responds with a status code (200 OK, 404 Not Found) and the content. HTTPS adds "
     "encryption via TLS."),
    ("technology", "compression", "Why files can be compressed",
     "Compression shrinks data by removing redundancy. Lossless methods like ZIP rebuild the original exactly, "
     "while lossy methods like JPEG discard detail the eye barely notices. The more predictable the data, the more "
     "it compresses."),
    ("history", "printing-press", "Gutenberg and the printing press",
     "Around 1440 Johannes Gutenberg introduced movable-type printing to Europe, letting books be produced quickly "
     "and cheaply. It fuelled literacy, the spread of ideas, and the scientific revolution."),
    ("history", "silk-road", "The Silk Road trade network",
     "The Silk Road was a web of trade routes linking China with the Mediterranean for over a thousand years. "
     "Beyond silk it carried spices, paper, gunpowder, religions and ideas between civilisations."),
    ("history", "library-alexandria", "The Library of Alexandria",
     "The Library of Alexandria, founded in the 3rd century BC in Egypt, aimed to collect all the world's knowledge. "
     "It attracted scholars from across the ancient world before being lost over centuries of decline."),
    ("plants", "photosynthesis", "How plants make food: photosynthesis",
     "In photosynthesis, plants convert sunlight, water and carbon dioxide into glucose and oxygen. The green pigment "
     "chlorophyll captures light energy in the leaves. This process releases the oxygen that most life on Earth breathes."),
    ("plants", "venus-flytrap", "The Venus flytrap, a carnivorous plant",
     "The Venus flytrap catches insects with hinged leaves that snap shut in about a tenth of a second when tiny trigger "
     "hairs are touched twice. It grows in nutrient-poor bogs and digests prey to get nitrogen."),
    ("plants", "bamboo", "Bamboo: the fastest-growing plant",
     "Bamboo is the fastest-growing plant on Earth; some species can grow up to 90 centimetres in a single day. "
     "It is technically a grass, not a tree, and is used for building, food and paper."),
    ("human_body", "heart", "The human heart",
     "The human heart beats about 100,000 times a day, pumping roughly 7,500 litres of blood through the body. It has "
     "four chambers and is about the size of a clenched fist."),
    ("human_body", "skeleton", "The human skeleton",
     "An adult human skeleton has 206 bones, while a baby is born with about 300 that fuse together during growth. "
     "The smallest bone, the stapes in the ear, is only a few millimetres long."),
    ("human_body", "brain", "The human brain",
     "The human brain uses about 20% of the body's energy despite being only 2% of its weight. It contains roughly "
     "86 billion neurons that communicate through electrical and chemical signals."),
    ("weather", "lightning", "What is lightning?",
     "A lightning bolt can reach about 30,000 degrees Celsius, roughly five times hotter than the surface of the Sun. "
     "The rapid heating of air causes the shock wave we hear as thunder."),
    ("weather", "rainbow", "How rainbows form",
     "A rainbow forms when sunlight is refracted and reflected inside raindrops, splitting into seven colours. It always "
     "appears at an angle of about 42 degrees from the direction opposite the Sun."),
    ("weather", "hurricane", "Hurricanes and how they spin",
     "Hurricanes rotate counter-clockwise in the Northern Hemisphere due to the Coriolis effect. They form over warm "
     "ocean water above about 26 degrees Celsius and weaken over land."),
    ("music", "piano", "The piano",
     "A standard piano has 88 keys: 52 white and 36 black, spanning just over seven octaves. Pressing a key makes a "
     "felt hammer strike steel strings."),
    ("music", "violin", "The violin",
     "The violin has four strings tuned G, D, A and E. It is played with a bow strung with horsehair, and is the "
     "highest-pitched member of the string family."),
    ("music", "orchestra", "The symphony orchestra",
     "A symphony orchestra groups instruments into four families: strings, woodwind, brass and percussion. A conductor "
     "keeps the musicians in time and shapes the interpretation."),
    ("geography", "everest", "Mount Everest",
     "Mount Everest rises 8,849 metres above sea level, making it the highest mountain on Earth. It sits in the "
     "Himalayas on the border between Nepal and China."),
    ("geography", "nile", "The Nile river",
     "The Nile flows about 6,650 kilometres through northeastern Africa and is one of the longest rivers in the world. "
     "It was the lifeline of ancient Egyptian civilisation."),
    ("geography", "sahara", "The Sahara desert",
     "The Sahara is the largest hot desert in the world, covering roughly the area of the United States. Despite the "
     "heat, night temperatures in the desert can fall below freezing."),
    ("mythology", "phoenix", "The phoenix",
     "In myth the phoenix is a bird that bursts into flames at the end of its life and is reborn from its own ashes. "
     "It became a symbol of renewal and immortality."),
    ("mythology", "minotaur", "The Minotaur",
     "The Minotaur of Greek myth was a creature half man and half bull, kept in the labyrinth of Crete. It was finally "
     "slain by the hero Theseus, who found his way out using a thread."),
    ("mythology", "icarus", "Icarus and his wings",
     "Icarus flew with wings of feathers and wax made by his father Daedalus, but ignored the warning and flew too close "
     "to the sun; the wax melted and he fell into the sea."),
    # --- CANARIES: purely fictional facts the model cannot know from training. If the agent
    # --- reports these, it MUST have read them from this database (grounding proof).
    ("curiosities", "zorblax", "The zorblax",
     "The zorblax is a rare deep-sea creature with seven eyes and three tails. It glows violet when it hunts "
     "and is said to hum softly at dawn. Sailors call it the lantern of the deep."),
    ("curiosities", "qintara", "The town of Qintara",
     "Qintara is a small mountain town with a recorded population of 47,213 people. It is best known for its "
     "spring lantern festival and for exporting blue honey found nowhere else."),
    ("curiosities", "brennium", "Brennium, the shimmering metal",
     "Brennium is a soft metal that melts at 1,742 degrees Celsius and gives off a faint green shimmer when heated. "
     "It is mined only on the fictional island of Vareth and is prized by clockmakers."),
]


def _ensure_database() -> None:
    """CREATE DATABASE fake_internet if it does not exist (connect to the maintenance db)."""
    admin_dsn = (
        f"postgresql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/postgres"
    )
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.fake_internet_db_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{settings.fake_internet_db_name}"')
    finally:
        conn.close()


def setup(*, reseed: bool = False) -> int:
    """Create the DB + table and seed sample pages. Idempotent (upsert by category+topic).
    reseed=True first clears the table. Returns the number of pages after seeding."""
    _ensure_database()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA)
        if reseed:
            cur.execute("TRUNCATE pages RESTART IDENTITY")
        cur.executemany(
            "INSERT INTO pages (category, topic, title, content) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (category, topic) DO UPDATE SET title = EXCLUDED.title, content = EXCLUDED.content",
            _SEED,
        )
        cur.execute("SELECT count(*) FROM pages")
        return cur.fetchone()[0]


if __name__ == "__main__":
    count = setup()
    print(f"fake_internet ready: {count} pages across {len(list_categories())} categories.")
    for cat, n in list_categories():
        print(f"  - {cat}: {n}")

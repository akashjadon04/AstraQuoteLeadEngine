import os

SEARCH_CH_API_KEY = os.environ.get("SEARCH_CH_API_KEY", "")

# ── Cloud/Low-memory mode ──────────────────────────────────────────────────
# Set RENDER=1 or LOW_MEM=1 env var to automatically reduce concurrency and
# memory usage to fit within 512MB (Render free tier). On local PC these
# defaults are ignored and full concurrency is used.
_LOW_MEM = os.environ.get("RENDER", "") == "1" or os.environ.get("LOW_MEM", "") == "1"

# ── Research Engine (rule-based, no AI/LLM — logic over public info only) ──
# On Render free (512MB): 2 concurrent crawls max — each holds ~20-40MB in RAM.
# On local PC: 10 concurrent crawls for speed.
RESEARCH_CONCURRENCY = int(os.environ.get("RESEARCH_CONCURRENCY", "1" if _LOW_MEM else "10"))
ENRICH_CONCURRENCY   = int(os.environ.get("ENRICH_CONCURRENCY",   "1" if _LOW_MEM else "20"))
LEAD_RESEARCH_TIMEOUT = int(os.environ.get("LEAD_RESEARCH_TIMEOUT", "20" if _LOW_MEM else "30"))
LEAD_ENRICH_TIMEOUT   = int(os.environ.get("LEAD_ENRICH_TIMEOUT",   "30" if _LOW_MEM else "45"))
ENABLE_REVIEW_SEARCH    = not _LOW_MEM   # skip on Render — saves RAM + avoids DDGS hammering
ENABLE_DM_SEARCH_FALLBACK = True
ENABLE_SHAB_LOOKUP      = not _LOW_MEM   # skip on Render — SHAB is heavy

# ── Network resilience (utils/net.py) ──
NET_MAX_CONCURRENT_DDGS    = 1 if _LOW_MEM else 2
NET_DDGS_MIN_INTERVAL      = 2.0 if _LOW_MEM else 1.2
NET_DDGS_TIMEOUT           = 10
NET_CIRCUIT_BREAKER_THRESHOLD = 5
NET_CIRCUIT_BREAKER_COOLDOWN  = 90

TARGET_CANTONS = ["Genève", "Vaud", "Valais", "Neuchâtel", "Jura"]

CANTON_CITIES = {
    "Genève": ["Genève", "Vernier", "Lancy", "Meyrin", "Carouge", "Onex", "Thônex", "Versoix", "Grand-Saconnex", "Chêne-Bougeries"],
    "Vaud": ["Lausanne", "Yverdon-les-Bains", "Montreux", "Renens", "Nyon", "Vevey", "Pully", "Morges", "Gland", "Ecublens"],
    "Valais": ["Sion", "Martigny", "Monthey", "Sierre", "Brig-Glis", "Visp", "Naters", "Crans-Montana"],
    "Neuchâtel": ["Neuchâtel", "La Chaux-de-Fonds", "Le Locle", "Val-de-Travers", "Val-de-Ruz", "Milvignes", "La Tène", "Cormondrèche"],
    "Jura": ["Delémont", "Porrentruy", "Courroux", "Courrendlin", "Saignelégier", "Bassecourt", "Fontenais", "Vicques"]
}

from utils.niche_profiles import get_active_profile

def get_current_primary_niches():
    return get_active_profile().primary_niches

def get_current_secondary_niches():
    return get_active_profile().secondary_niches

def get_current_exclude_keywords():
    return get_active_profile().exclude_keywords

PRIMARY_NICHES = get_current_primary_niches()
SECONDARY_NICHES = get_current_secondary_niches()

# ── Company size (the "is this big enough to bother" gate) ──────────────
# Switzerland does NOT publish employee headcount for SMEs in any free,
# automatable source. We estimate size bands:
#   "sole_trader"  ~1 person
#   "micro"        ~2-3
#   "small"        ~4-9 (est., covers target 7-8 employee plumbing firms)
#   "established"  ~10+ (est.)
#   "unknown"      no signals either way
MIN_COMPANY_SIZE_BAND = "micro"
UNKNOWN_PASSES = False
_SIZE_BAND_RANK = {"sole_trader": 0, "micro": 1, "unknown": 2, "small": 3, "established": 4}
MIN_EMPLOYEES = 10  # legacy/no longer used as a hard filter — kept so old imports don't break

TARGET_LEAD_COUNT = 100
DISCOVERY_TARGET = 450
MAX_RECRAWL_ITERATIONS = 100

DB_PATH = "data/leads.db"
LOG_FILE = "data/engine.log"

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = 8800
DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"

EXCLUDE_KEYWORDS = get_current_exclude_keywords()


BOOKING_SIGNALS = [
    "devis", "demander un devis", "obtenir une offre", "contact", 
    "nous contacter", "formulaire", "réserver", "prendre rendez-vous", 
    "offre", "estimation", "gratuit", "sans engagement"
]

# ============================================================
# generate_mock_leads.py
# Generates realistic B2B Swiss leads for the dashboard
# ============================================================

import os
import sys
import json
import sqlite3
import random
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from utils.database import init_db, insert_lead

# Mock lists
COMPANY_NAMES = [
    "Sani-Chauffage {city} SA",
    "Therme-{city} Sàrl",
    "Plomberie du Lac Sàrl",
    "CVC {city} Services",
    "Sanitaire & Chauffage {lastName} & Fils",
    "Hydro-Pro {city} SA",
    "Genève Sani-Tech SA",
    "Fribourg Plomberie-Chauffage Sàrl",
    "Valais Chauffage & Sanitaire SA",
    "Vaud Climatisation & Sanitaire Sàrl",
    "Neuchâtel Sani-Installation SA",
    "Jura Plombiers Associés SA",
    "{lastName} Chauffage Sàrl",
    "{lastName} Sanitaire & Plomberie",
    "Alpine Thermique SA",
    "Leman Sanitaire Services",
    "Rhône Plomberie SA",
    "Sani-Est Sàrl",
    "Eco-Chauffage Romand SA",
    "Pro-Plombiers {city} Sàrl"
]

LAST_NAMES = ["Favre", "Dubois", "Martin", "Glauser", "Mermod", "Rochat", "Perrin", "Blanc", "Gilliard", "Muller"]

STREETS = ["Rue du Grand-Pré", "Avenue de la Gare", "Route de Meyrin", "Chemin des Fleurs", "Rue de Lausanne", "Route du Jura", "Avenue du Théâtre", "Route de Riddes"]

FIRST_NAMES = ["Jean", "Pierre", "Marc", "André", "Michel", "Stéphane", "Nicolas", "Philippe", "Alexandre", "Laurent"]
TITLES = ["Directeur", "Gérant", "Responsable Technique", "Propriétaire", "Chef de Projet"]

PAIN_POINTS_POOL = [
    "Temps de réponse moyen pour un devis : 5-7 jours ouvrés.",
    "Perte estimée de 20% des demandes de devis entrantes par manque de suivi réactif.",
    "Processus de chiffrage manuel fastidieux réalisé le soir/weekend par le patron.",
    "Aucun outil de devis en ligne sur le site internet existant.",
    "Pas de CRM pour suivre le statut des offres envoyées.",
    "Mauvaise visibilité sur les marges lors du chiffrage des grosses installations.",
    "Difficulté à relancer les prospects de manière systématique.",
    "Délais importants dans la facturation après la fin du chantier."
]

PITCH_STRATEGIES_POOL = [
    "Présenter comment AstraQuote permet de générer un devis précis de plomberie en moins de 5 minutes directement sur le chantier.",
    "Mettre l'accent sur l'intégration d'un widget de devis instantané sur leur site internet pour capter les prospects en soirée.",
    "Démontrer le gain de temps administratif (estimé à 8h par semaine) pour le gérant.",
    "Proposer un comparatif entre leur méthode de chiffrage actuelle sur Excel et la rapidité d'AstraQuote.",
    "Montrer comment le système de relance automatique d'AstraQuote augmente le taux de conversion de 15%."
]

CUSTOM_OPENINGS_POOL = [
    "Bonjour M. {lastName}, je me permets de vous contacter au sujet de {company}. J'ai remarqué que vous proposez d'excellents services sur {city}, mais qu'il n'est pas possible d'obtenir une estimation de prix rapide sur votre site. Est-ce un sujet de réflexion chez vous ?",
    "Bonjour, je souhaite parler à M. {lastName}. C'est au sujet de votre activité de chauffage à {city}. Nous aidons les chauffagistes romands à diviser par 4 le temps passé sur la rédaction de leurs devis. Seriez-vous ouvert à y jeter un coup d'œil ?",
    "Bonjour M. {lastName}, j'ai vu votre entreprise {company} sur local.ch. Vous avez d'excellents avis clients, mais j'imagine que le chiffrage de vos chantiers de sanitaire vous prend beaucoup de temps le soir. Avez-vous déjà pensé à automatiser cette partie ?"
]

def generate_mock_leads():
    print("Generating mock leads...")
    init_db(config.DB_PATH)
    
    random.seed(42)
    leads_count = 0
    
    for canton, cities in config.CANTON_CITIES.items():
        for city in cities:
            # Generate 2-3 leads per city to reach ~100
            for _ in range(random.randint(2, 3)):
                lastName = random.choice(LAST_NAMES)
                firstName = random.choice(FIRST_NAMES)
                company = random.choice(COMPANY_NAMES).format(city=city, lastName=lastName)
                
                # Phone formatting
                phone_prefix = random.choice(["021", "022", "024", "026", "032", "027"])
                phone_suffix = f"{random.randint(100,999)} {random.randint(10,99)} {random.randint(10,99)}"
                phone = f"+41 {phone_prefix[1:]} {phone_suffix}"
                
                # Domain & website
                domain = company.lower().replace(" & ", "-").replace(" ", "-").replace("à", "a").replace("é", "e").replace("ô", "o")
                domain = "".join(c for c in domain if c.isalnum() or c == "-") + ".ch"
                website = f"https://www.{domain}"
                email = f"info@{domain}"
                
                # Address
                address = f"{random.choice(STREETS)} {random.randint(1,120)}"
                
                # Scores
                urgency = random.randint(3, 10)
                digital = random.randint(1, 4) # Lower digital = higher urgency
                contact = random.randint(50, 95)
                
                # AI content
                pain_points = random.sample(PAIN_POINTS_POOL, random.randint(2, 4))
                pitch = random.choice(PITCH_STRATEGIES_POOL)
                opening = random.choice(CUSTOM_OPENINGS_POOL).format(
                    lastName=lastName, city=city, company=company
                )
                
                lead = {
                    "company_name": company,
                    "canton": canton,
                    "city": city,
                    "niche": random.choice(["plombier", "chauffagiste", "sanitaire", "climatisation"]),
                    "phone": phone,
                    "email": email,
                    "website": website,
                    "address": f"{address}, {city}",
                    
                    "legal_form": random.choice(["SA", "Sàrl", "Raison individuelle"]),
                    "founded_year": random.randint(1980, 2020),
                    "employee_count": random.randint(10, 45),
                    
                    "has_website": True,
                    "has_quote_form": random.choice([True, False]),
                    "has_instagram": f"https://instagram.com/{domain.split('.')[0]}" if random.choice([True, False]) else "",
                    "has_facebook": f"https://facebook.com/{domain.split('.')[0]}" if random.choice([True, False]) else "",
                    "has_linkedin": "",
                    
                    "google_rating": round(random.uniform(3.5, 4.9), 1),
                    "google_reviews": random.randint(5, 68),
                    "digital_maturity": digital,
                    
                    "pain_points": json.dumps(pain_points, ensure_ascii=False),
                    "pitch_angle": pitch,
                    "custom_opening": opening,
                    "urgency_score": urgency,
                    "estimated_quotes": random.randint(150, 800),
                    
                    "decision_maker": f"{firstName} {lastName}",
                    "decision_title": random.choice(TITLES),
                    "contact_score": contact,
                    "is_mobile": random.choice([True, False]),
                    
                    "source": "synthetic",
                    "status": "enriched" if urgency > 4 else "qualified",
                    "layer_reached": 6
                }
                
                insert_lead(lead)
                leads_count += 1
                
    print(f"Successfully generated {leads_count} Swiss leads in the database!")

if __name__ == "__main__":
    generate_mock_leads()

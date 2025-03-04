#!/usr/bin/env python3
import requests
import json
import logging
import sys
import re
import os
import subprocess

# Importa direttamente la funzione da chiave.py se disponibile
try:
    from chiave import get_auth_signature
except ImportError:
    # Fallback: il file chiave.py potrebbe non essere ancora stato creato
    def get_auth_signature():
        try:
            # Esegui lo script chiave.py come processo separato
            result = subprocess.run(['python3', 'chiave.py'], 
                                  capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except Exception as e:
            print(f"Errore durante l'esecuzione di chiave.py: {e}")
            return None

def setup_logging():
    logging.basicConfig(filename="excluded_channels.log", level=logging.INFO, format="%(asctime)s - %(message)s")

def sanitize_tvg_id(channel_name):
    channel_name = re.sub(r"\.[cs]$", "", channel_name, flags=re.IGNORECASE).strip()
    return " ".join(word.capitalize() for word in channel_name.split())

def load_config(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def get_category(channel_name, category_keywords):
    lower_name = channel_name.lower()
    for category, keywords in category_keywords.items():
        if any(keyword.lower() in lower_name for keyword in keywords):
            return category
    return "ALTRI"

def normalize_channel_name(channel_name):
    # Rimuovi solo il suffisso " .c" o " .s" (incluso lo spazio)
    clean_name = re.sub(r"\s+\.[cs]$", "", channel_name, flags=re.IGNORECASE).strip()
    return clean_name.lower()

def get_logo_url(channel_name, channel_logos):
    # Normalizza il nome del canale rimuovendo solo il suffisso " .c" o " .s"
    normalized_name = normalize_channel_name(channel_name)
    
    print(f"DEBUG - Cercando logo per: '{channel_name}' → normalizzato a: '{normalized_name}'")
    
    # Cerca nel dizionario usando i nomi normalizzati
    for logo_channel, logo_url in channel_logos.items():
        normalized_logo_channel = normalize_channel_name(logo_channel)
        
        # Prova corrispondenza esatta
        if normalized_name == normalized_logo_channel:
            print(f"DEBUG - TROVATO! Corrispondenza esatta: '{normalized_name}' = '{normalized_logo_channel}'")
            return logo_url
        
        # Prova corrispondenza parziale (se il nome logo è contenuto nel nome canale o viceversa)
        if normalized_name in normalized_logo_channel or normalized_logo_channel in normalized_name:
            print(f"DEBUG - TROVATO! Corrispondenza parziale: '{normalized_name}' ↔ '{normalized_logo_channel}'")
            return logo_url
    
    # Genera URL placeholder se non esiste un logo
    clean_name = re.sub(r"\s+\.[cs]$", "", channel_name, flags=re.IGNORECASE).strip()
    # Sostituisci spazi con + per l'URL
    formatted_name = clean_name.replace(" ", "+")
    return f"https://placehold.co/400x400?text={formatted_name}&.png"
    
    # Genera URL placeholder se non esiste un logo
    clean_name = re.sub(r"\.[cs]$", "", channel_name, flags=re.IGNORECASE).strip()
    # Rimuovi gli ultimi 3 caratteri come richiesto
    if len(clean_name) > 3:
        clean_name = clean_name[:-3]
    # Sostituisci spazi con + per l'URL
    formatted_name = clean_name.replace(" ", "+")
    return f"https://placehold.co/400x400?text={formatted_name}&.png"

def get_channel_list(signature, group="Italy"):
    headers = {
        "Accept-Encoding": "gzip",
        "User-Agent": "MediaHubMX/2",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "mediahubmx-signature": signature
    }

    cursor = 0
    all_items = []

    while True:
        data = {
            "language": "de",
            "region": "AT",
            "catalogId": "vto-iptv",
            "id": "vto-iptv",
            "adult": False,
            "search": "",
            "sort": "name",
            "filter": {"group": group},
            "cursor": cursor,
            "clientVersion": "3.0.2"
        }

        try:
            response = requests.post("https://vavoo.to/vto-cluster/mediahubmx-catalog.json", json=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            items = result.get("items", [])
            if not items:
                break  # Se non ci sono più canali, esce dal ciclo

            all_items.extend(items)
            cursor += len(items)  # Aggiorna il cursore con il numero di canali ricevuti

        except Exception as e:
            print(f"Errore durante il recupero della lista dei canali: {e}")
            break

    return {"items": all_items}
    
def generate_m3u(channels_json, signature, channel_filters, channel_remove, category_keywords, channel_logos, filename="channels.m3u8"):
    setup_logging()
    items = channels_json.get("items", [])
    if not items:
        print("Nessun canale disponibile.")
        return

    print(f"Generating M3U8 file with {len(items)} channels...")
    print(f"DEBUG - Numero di loghi disponibili: {len(channel_logos)}")
    
    # Mostra un campione dei loghi disponibili
    sample_count = min(3, len(channel_logos))
    print(f"DEBUG - Campione di {sample_count} loghi:")
    sample_logos = list(channel_logos.items())[:sample_count]
    for logo_key, logo_url in sample_logos:
        print(f"DEBUG - '{logo_key}': '{logo_url}'")

    with open(filename, "w", encoding="utf-8") as f:
        f.write('#EXTM3U url-tvg="http://epg-guide.com/it.gz"\n')

        for idx, item in enumerate(items, 1):
            name = item.get("name", "Unknown")
            if any(remove_word.lower() in name.lower() for remove_word in channel_remove):
                print(f"Skipping channel {name} (in CHANNEL_REMOVE)")
                continue

            # Se channel_filters è vuoto, includi tutti i canali
            # Altrimenti, includi solo quelli che corrispondono ai filtri
            if channel_filters and not any(filter_word.lower() in name.lower() for filter_word in channel_filters):
                logging.info(f"Excluded channel: {name}")
                continue

            tvg_id = sanitize_tvg_id(name)
            original_link = item.get("url")

            if not original_link:
                continue

            print(f"Processing channel {idx}/{len(items)}: {name}")
            
            # Non risolvere il link, usarlo direttamente
            category = get_category(name, category_keywords)
            logo_url = get_logo_url(name, channel_logos)

            f.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_id}" tvg-logo="{logo_url}" group-title="{category}",{tvg_id}\n')
            # Aggiungi header per il player
            f.write('#EXTVLCOPT:http-user-agent=okhttp/4.11.0\n')
            f.write('#EXTVLCOPT:http-origin=https://vavoo.to/\n')
            f.write('#EXTVLCOPT:http-referrer=https://vavoo.to/\n')
            f.write('#EXTVLCOPT:mediahubmx-signature=[$KEY$]\n')  # Placeholder per la chiave di firma
            f.write(f'{original_link}\n')

    print(f"M3U8 file generated successfully: {filename}")


def main():
    # Carica configurazioni da file separati
    channel_filters = load_config("channel_filters.json")
    if not channel_filters:
        channel_filters = []  # Nessun filtro predefinito
        # Crea un file vuoto
        with open("channel_filters.json", 'w', encoding='utf-8') as f:
            json.dump(channel_filters, f, indent=4)
    
    channel_remove = load_config("channel_remove.json")
    if not channel_remove:
        channel_remove = []  # Nessun filtro di rimozione predefinito
        with open("channel_remove.json", 'w', encoding='utf-8') as f:
            json.dump(channel_remove, f, indent=4)
    
    category_keywords = load_config("category_keywords.json")
    if not category_keywords:
        category_keywords = {"ALTRI": []}  # Solo la categoria default
        with open("category_keywords.json", 'w', encoding='utf-8') as f:
            json.dump(category_keywords, f, indent=4)
    
    channel_logos = load_config("channel_icons.json")
    if not channel_logos:
        channel_logos = {}  # Non usiamo più il CHANNEL_LOGOS predefinito
        with open("channel_icons.json", 'w', encoding='utf-8') as f:
            json.dump(channel_logos, f, indent=4)
    
    print("Getting authentication signature...")
    signature = get_auth_signature()
    if not signature:
        print("Failed to get authentication signature.")
        sys.exit(1)

    print("Getting channel list...")
    channels_json = get_channel_list(signature)
    if not channels_json:
        print("Failed to get channel list.")
        sys.exit(1)

    print("Generating M3U8 file...")
    generate_m3u(channels_json, signature, channel_filters, channel_remove, category_keywords, channel_logos)
    print("Done!")

# Nessun dato di fallback, leggiamo tutto dai file

if __name__ == "__main__":
    main()

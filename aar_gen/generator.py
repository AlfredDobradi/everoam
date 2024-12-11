import re
from datetime import datetime
import requests
import json
from typing import List, Tuple, Dict
import sqlite3
import pprint

pp = pprint.PrettyPrinter(indent=4)

class Db:
    connection: sqlite3.Connection = None

    def __init__(self, path):
        self.connection = sqlite3.connect(path)
    
    def get_ship(self, ship_id):
        cur = self.connection.cursor()
        res = cur.execute("SELECT typeName FROM invTypes WHERE typeID = ?", [ship_id])
        row = res.fetchone()
        return row[0]
    
    def get_system(self, system_id):
        cur = self.connection.cursor()
        res = cur.execute("SELECT solarSystemName FROM mapSolarSystems WHERE solarSystemID = ?", [system_id])
        row = res.fetchone()
        return row[0]

db = Db("./sqlite-latest.sqlite")

class Toon:
    id = 0
    name = ''

    def __init__(self, id = 0, name = ''):
        self.id = id
        self.name = name

class Meta:
    start = datetime.now()
    end = datetime.now()
    toons = []

    def __init__(self, start = datetime.now(), end = datetime.now(), toons = []):
        self.start = start
        self.end = end
        self.toons = toons
    
    def add_name(self, toon):
        if toon.name == "EVE System":
            return

        for existing in self.toons:
            if toon.name == existing.name:
                return
        
        self.toons.append(toon)

class Character:
    alliance_id: int
    alliance_name: str = ''
    corp_id: int
    corp_name: str = ''
    character_id: int
    character_name: str = ''
    ship_id: int
    ship_name: str = ''

    def __init__(self, victim: Dict):
        self.alliance_id = victim['alliance_id']
        self.corp_id = victim['corporation_id']
        self.character_id = victim['character_id']
        self.ship_id = victim['ship_type_id']

        ids = json.dumps([self.alliance_id, self.corp_id, self.character_id])
        resp = requests.post('https://esi.evetech.net/latest/universe/names/', data=ids, headers={"Content-Type": "application/json"})
        if resp.status_code != 200:
            print(resp.text)
            return

        data = resp.json()
        for col in data:
            if col["category"] == "alliance":
                self.alliance_name = col["name"]
            if col["category"] == "corporation":
                self.corp_name = col["name"]
            if col["category"] == "character":
                self.character_name = col["name"]

        self.ship_name = db.get_ship(self.ship_id)

class Killmail:
    id = 0
    final_blow: Character = None
    timestamp = datetime.now()
    system_id = 0
    system_name = ''
    victim: Character = None
    total_value = 0

    def __init__(self, timestamp, km, zkb):
        self.id = km['killmail_id']
        self.timestamp = timestamp
        self.system_id = km['solar_system_id']
        self.system_name = db.get_system(km['solar_system_id'])
        self.victim = Character(km['victim'])
        self.total_value = zkb['totalValue']

        for attacker in km['attackers']:
            if attacker['final_blow'] is True:
                self.final_blow = Character(attacker)


class Killmails:
    collection: List[Killmail] = []

    def __init__(self):
        self.collection = []
    
    def add(self, km: Killmail):
        for mail in self.collection:
            if mail.id == km.id:
                return
        
        self.collection.append(km)

def main():
    meta = get_meta("../Fleet.txt")

    meta.toons = get_toon_ids(meta.toons)

    for toon in meta.toons:
        zkb = get_zkb_data(toon.id, meta.start, meta.end)
        for km in zkb.collection:
            print(f'{km.timestamp.strftime("%Y-%m-%d %H:%M:%S")} - {km.system_name}')
            print(f'Final blow: {km.final_blow.character_name} ({km.final_blow.ship_name})')
            print(f'Victim: {km.victim.character_name} ({km.victim.ship_name}) - {km.total_value:,} ISK')
            break
        break
    

def get_meta(path):
    with open(path, "r", encoding="utf-16-le") as f:
        content = f.readlines()
    
    i = 0
    meta = Meta()

    for line in content:
        line = line.replace(u'\ufeff', '').replace('\n', '')
        search = re.compile("\\[ (\\d{4}\\.\\d{2}\\.\\d{2} \\d{2}:\\d{2}:\\d{2}) \\] ([^>]+)")
        match = search.findall(line)
        if match is None or len(match) == 0:
            continue

        toon = Toon(0, match[0][1].strip())

        meta.add_name(toon)
        ts = parse_time(match[0][0])
        if i == 0:
            min_time = ts
       
        i += 1
        max_time = ts
    
    meta.start = min_time
    meta.end = max_time

    return meta


def parse_time(timestamp):
    pattern = "%Y.%m.%d %H:%M:%S"
    return datetime.strptime(timestamp, pattern)


def get_toon_ids(toons):
    names = []
    for toon in toons:
        names.append(toon.name)

    payload = json.dumps(names)

    response = requests.post('https://esi.evetech.net/latest/universe/ids/', data=payload, headers={'Content-Type': 'application/json'})
    # response = requests.post('https://httpbin.org/post', data=payload, headers={'Content-Type': 'application/json'})
    if response.status_code != 200:
        print(response.text)
        return None
    
    data = response.json()
    if 'characters' not in data:
        return None

    for character in data['characters']:
        for toon in toons:
            if toon.name == character['name']:
                toon.id = character['id']
    
    return toons


def get_zkb_data(toon_id, start, end):
    killmails = Killmails()

    months = [(start.year, start.month)]
    if start.year != end.year or start.month != end.month:
        months = [(start.year, start.month), (end.year, end.month)]
    
    for month in months:
        url = f'https://zkillboard.com/api/characterID/{toon_id}/npc/0/year/{month[0]}/month/{month[1]}/'
        
        response = requests.get(url, headers={'User-Agent': 'RavenX Yet Another Roam Report/v0.0.1', 'Accept-Encoding': 'gzip'})
        zkb = response.json()
        for km in zkb:
            km_raw = requests.get(f'https://esi.evetech.net/latest/killmails/{km['killmail_id']}/{km['zkb']['hash']}')
            if km_raw.status_code != 200:
                return
            km_data = km_raw.json()
            timestamp = datetime.strptime(km_data['killmail_time'], '%Y-%m-%dT%H:%M:%SZ')
            if timestamp < start or timestamp > end:
                continue
            
            killmails.add(Killmail(timestamp, km_data, km['zkb']))
            break

    return killmails

if __name__ == "__main__":
    main()

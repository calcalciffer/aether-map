import sqlite3
from PIL import Image

def get_tile(map_):
    return {
        'id': map_[0],
        'x': map_[1],
        'y': map_[2],
        'user_id': map_[3],
        'village_id': map_[4],
        'type': map_[5],
        'event_id': map_[6]
    }

def is_settlable(tile):
    settlable_types = [
        'plains', 'woodlands', 'rocky plains',
        'marshlands', 'swamp', 'village', 'town', 'city'
    ]
    return tile['type'] in settlable_types

def get_number_of_farms(tile):
    if tile['type'] == 'plains':
        return 4
    elif tile['type'] == 'marshlands' or tile['type'] == 'water':
        return 3
    elif tile['type'] == 'forest' or tile['type'] == 'woodlands':
        return 2
    elif tile['type'] == 'rocky plains' or tile['type'] == 'hills' or tile['type'] == 'swamp':
        return 1
    elif tile['type'] == 'mountains' or \
        tile['type'] == 'village' or tile['type'] == 'town' or tile['type'] == 'city' or \
        tile['type'] == 'landmark':
        return 0
    else:
        raise ValueError(f'Unknown tile type {tile["type"]}')
    
def get_resources(tile):
    if tile['type'] == 'plains':
        return [0, 0, 0, 4]
    elif tile['type'] == 'marshlands':
        return [0, 0, 1, 3]
    elif tile['type'] == 'water':
        return [0, 1, 0, 3]
    elif tile['type'] == 'forest':
        return [3, 0, 0, 2]
    elif tile['type'] == 'woodlands':
        return [2, 0, 0, 2]
    elif tile['type'] == 'rocky plains':
        return [0, 3, 1, 1]
    elif tile['type'] == 'hills':
        return [1, 2, 1, 1]
    elif tile['type'] == 'swamp':
        return [2, 0, 1, 1]
    elif tile['type'] == 'mountains':
        return [0, 2, 4, 0]
    elif tile['type'] == 'village' or tile['type'] == 'town' or tile['type'] == 'city':
        return [1, 1, 1, 2]
    elif tile['type'] == 'landmark':
        return [0, 0, 0, 0]
    else:
        raise ValueError(f'Unknown tile type {tile["type"]}')
    
def get_map_resources():
    maps_dict = get_maps_dict()
    resources = {}
    for coords in maps_dict:
        resources[coords] = get_resources(maps_dict[coords])
    return resources
    
def is_center(tile, center_x = 81, center_y = 81, radius = 16):
    return (center_x - radius <= tile['x'] <= center_x + radius) and \
           (center_y - radius <= tile['y'] <= center_y + radius)
           
def get_quadrant(tile, center_x = 81, center_y = 81):
    if tile['x'] >= center_x and tile['y'] >= center_y:
        return 1
    elif tile['x'] < center_x and tile['y'] >= center_y:
        return 2
    elif tile['x'] < center_x and tile['y'] < center_y:
        return 3
    else:
        return 4
    
directions = [
    (0, 1), (1, 0), (0, -1), (-1, 0),
    (1, 1), (-1, -1), (1, -1), (-1, 1),
]
tile_size = 16
map_size = 163

def get_maps_dict(map_db_path='maps/map.db'):
    conn = sqlite3.connect(map_db_path)
    cursor = conn.cursor()
    cursor.execute('''
                SELECT * FROM map
                    ''')
    maps = cursor.fetchall()
    conn.close()

    maps_dict = {(map_[1], map_[2]): get_tile(map_) for map_ in maps}
    return maps_dict
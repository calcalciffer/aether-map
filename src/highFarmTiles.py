import sqlite3
from PIL import Image
from util import *

def get_high_farm_tiles():
    
    maps_dict = get_maps_dict()
    farm_counts = {}
    for coords in maps_dict:
        farm_counts[coords] = get_number_of_farms(maps_dict[coords])


    counted_neighbor_farms = {}
    for i in range(26, 32, 1):
        print(f'--- Tiles with {i} neighboring farms ---')
        for coords in farm_counts:
            if is_settlable(maps_dict[coords]) is False:
                continue
            neighbor_farms = 0
            x, y = coords
            neighbors = [(x + dx, y + dy) for dx, dy in directions]
            for neighbor in neighbors:
                if neighbor in farm_counts:
                    neighbor_farms += farm_counts[neighbor]
            if neighbor_farms == i:
                if is_center(maps_dict[coords]):
                    position = 'center'
                else:
                    position = f'quadrant {get_quadrant(maps_dict[coords])}'
                print(f'Coords: {coords} | Position: {position}')
                counted_neighbor_farms[coords] = neighbor_farms
                
    # Generate map image
    map_image = Image.new('RGB', (map_size * tile_size, map_size * tile_size))
    type_colors = {
        'plains': (34, 139, 34),
        'woodlands': (0, 100, 0),
        'rocky plains': (139, 69, 19),
        'marshlands': (107, 142, 35),
        'swamp': (85, 107, 47),
        'village': (210, 180, 140),
        'town': (160, 82, 45),
        'city': (128, 0, 0),
        'forest': (34, 139, 34),
        'water': (30, 144, 255),
        'hills': (205, 133, 63),
        'mountains': (169, 169, 169),
        'landmark': (255, 215, 0)
    }
    for coords in maps_dict:
        tile = maps_dict[coords]
        # color = type_colors.get(tile['type'], (0, 0, 0))
        color = type_colors['plains']
        x, y = coords
        for i in range(tile_size):
            for j in range(tile_size):
                if coords in counted_neighbor_farms:
                    # Highlight tiles with counted neighboring farms
                    color_base = (counted_neighbor_farms[coords] - 26) * 50
                    highlight_color = (color_base, color_base, color_base)
                    map_image.putpixel((x * tile_size + i, y * tile_size + j), highlight_color)
                elif is_center(tile):
                    map_image.putpixel((x * tile_size + i, y * tile_size + j), (34, 70, 34))
                else:
                    map_image.putpixel((x * tile_size + i, y * tile_size + j), color)
    map_image.save('maps/generated_map.png')
    
if __name__ == '__main__':
    get_high_farm_tiles()

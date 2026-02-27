import sys
from PIL import Image
from util import *

def get_total_neighbor_resources(coords):
    total_resources = 0
    x, y = coords
    neighbors = [(x + dx, y + dy) for dx, dy in directions]
    for neighbor in neighbors:
        if neighbor in map_data_instance.tiles_dict:
            total_resources += map_data_instance.get_total_resource_count(neighbor)
    return total_resources

def get_high_hills_tiles():
    for i in range(1, 8, 1):
        print(f'--- Tiles with {i} neighboring hills ---')
        for coords, tile in map_data_instance.tiles_dict.items():
            if map_data_instance.is_settlable(tile) is False:
                continue
            neighbor_hills = 0
            x, y = coords
            neighbors = [(x + dx, y + dy) for dx, dy in directions]
            for neighbor in neighbors:
                if neighbor in map_data_instance.tiles_dict:
                    neighbor_hills += map_data_instance.tiles_dict[neighbor]['tile_type'] == 'hills'
            if neighbor_hills == i:
                if map_data_instance.is_center(map_data_instance.tiles_dict[coords]):
                    position = 'center'
                else:
                    position = f'quadrant {map_data_instance.get_quadrant(map_data_instance.tiles_dict[coords])}'
                print(f'Coords: {coords} | Position: {position}')

def get_high_resource_tiles():

    counted_neighbor_resources = {}
    counted_neighbor_total_resources = {}
    for resource_type in range(0, 3):
        resource_name = ['wood', 'stone', 'iron'][resource_type]
        for i in range(10, 32, 1):
            print(f'--- Tiles with {i} neighboring {resource_name} ---')
            for coords, tile in map_data_instance.tiles_dict.items():
                if map_data_instance.is_settlable(tile) is False:
                    continue
                neighbor_resources = 0
                x, y = coords
                neighbors = [(x + dx, y + dy) for dx, dy in directions]
                for neighbor in neighbors:
                    if neighbor in map_data_instance.tiles_dict:
                        neighbor_resources += map_data_instance.get_resource_count(neighbor, resource_name)
                if neighbor_resources == i:
                    if map_data_instance.is_center(map_data_instance.tiles_dict[coords]):
                        position = 'center'
                    else:
                        position = f'quadrant {map_data_instance.get_quadrant(map_data_instance.tiles_dict[coords])}'
                    total_neighbor_res = get_total_neighbor_resources(coords)
                    if total_neighbor_res >= 40:
                        print(f'Coords: {coords} | Position: {position} | Total neighboring resources: {total_neighbor_res}')
                    if coords not in counted_neighbor_resources:
                        counted_neighbor_resources[coords] = {}
                    counted_neighbor_resources[coords][resource_type] = counted_neighbor_resources

    for i in range(40, 49, 1):
        print(f'--- Tiles with {i} neighboring total resources ---')
        for coords, tile in map_data_instance.tiles_dict.items():
            if map_data_instance.is_settlable(tile) is False:
                continue
            neighbor_resources = get_total_neighbor_resources(coords)
            if neighbor_resources == i:
                if map_data_instance.is_center(tile):
                    position = 'center'
                else:
                    position = f'quadrant {map_data_instance.get_quadrant(tile)}'
                print(f'Coords: {coords} | Position: {position}')
                counted_neighbor_total_resources[coords] = neighbor_resources
                
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
    for coords, tile in map_data_instance.tiles_dict.items():
        # color = type_colors.get(tile['type'], (0, 0, 0))
        color = type_colors['plains']
        x, y = coords
        for i in range(tile_size):
            for j in range(tile_size):
                if coords in counted_neighbor_total_resources:
                    # Highlight tiles with counted neighboring farms
                    color_base = (counted_neighbor_total_resources[coords] - 40) * 50
                    highlight_color = (color_base, color_base, color_base)
                    map_image.putpixel((x * tile_size + i, y * tile_size + j), highlight_color)
                elif map_data_instance.is_center(tile):
                    map_image.putpixel((x * tile_size + i, y * tile_size + j), (34, 70, 34))
                else:
                    map_image.putpixel((x * tile_size + i, y * tile_size + j), color)
    map_image.save('maps/generated_map_high_res.png')

if __name__ == '__main__':
    # get_high_resource_tiles()
    get_high_hills_tiles()

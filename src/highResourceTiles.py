import sqlite3
import sys
from PIL import Image
from util import *

def get_total_neighbor_resources(resources, coords):
    total_resources = 0
    x, y = coords
    neighbors = [(x + dx, y + dy) for dx, dy in directions]
    for neighbor in neighbors:
        if neighbor in resources:
            total_resources += sum(resources[neighbor])
    return total_resources

def get_high_resource_tiles():
    
    maps_dict = get_maps_dict('maps/map.db')
    resources = get_map_resources()
    
    counted_neighbor_resources = {}
    counted_neighbor_total_resources = {}
    for resource_type in range(0, 3):
        resource_name = ['wood', 'stone', 'iron'][resource_type]
        for i in range(10, 32, 1):
            print(f'--- Tiles with {i} neighboring {resource_name} ---')
            for coords in resources:
                if is_settlable(maps_dict[coords]) is False:
                    continue
                neighbor_resources = 0
                x, y = coords
                neighbors = [(x + dx, y + dy) for dx, dy in directions]
                for neighbor in neighbors:
                    if neighbor in resources:
                        neighbor_resources += resources[neighbor][resource_type]
                if neighbor_resources == i:
                    if is_center(maps_dict[coords]):
                        position = 'center'
                    else:
                        position = f'quadrant {get_quadrant(maps_dict[coords])}'
                    total_neighbor_res = get_total_neighbor_resources(resources, coords)
                    if total_neighbor_res >= 40:
                        print(f'Coords: {coords} | Position: {position} | Total neighboring resources: {total_neighbor_res}')
                    if coords not in counted_neighbor_resources:
                        counted_neighbor_resources[coords] = {}
                    counted_neighbor_resources[coords][resource_type] = counted_neighbor_resources
        sys.exit(0)
                    
    for i in range(40, 49, 1):
        print(f'--- Tiles with {i} neighboring total resources ---')
        for coords in resources:
            if is_settlable(maps_dict[coords]) is False:
                continue
            neighbor_resources = 0
            x, y = coords
            neighbors = [(x + dx, y + dy) for dx, dy in directions]
            for neighbor in neighbors:
                if neighbor in resources:
                    neighbor_resources += sum(resources[neighbor])
            if neighbor_resources == i:
                if is_center(maps_dict[coords]):
                    position = 'center'
                else:
                    position = f'quadrant {get_quadrant(maps_dict[coords])}'
                print(f'Coords: {coords} | Position: {position}')
                counted_neighbor_total_resources[coords] = counted_neighbor_resources

if __name__ == '__main__':
    get_high_resource_tiles()

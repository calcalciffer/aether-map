#!/usr/bin/env python3
"""
Quick Settlement Analyzer - Simplified output
Usage: python quickAnalyzer.py <x> <y> <radius> <type> <top_n>
"""

from util import *
import math
import sys

def get_occupied_centers():
    """
    Get only the center tiles of each player settlement.
    Returns list of (center_coord, 3x3_tiles, user_id).
    """
    occupied_centers = []
    
    for coords, tile in map_data_instance.tiles_dict.items():
        uid = tile.get('user_id')
        if uid is not None and uid != '':
            x, y = coords
            # Get all 9 tiles in this center's 3x3
            tiles_3x3 = set()
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    tiles_3x3.add((x + dx, y + dy))
            occupied_centers.append((coords, tiles_3x3, uid))
    
    return occupied_centers

def get_distance(x1, y1, x2, y2):
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def analyze_3x3_area(coords):
    """Analyze 3x3: settlement gives 1W/1S/1I/2F, neighbors give actual values"""
    x, y = coords
    
    stats = {
        'coords': coords,
        'tile_counts': {},
        'total_food': 2,
        'total_wood': 1,
        'total_stone': 1,
        'total_iron': 1,
    }
    
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            if dx == 0 and dy == 0:
                continue
            check_x = x + dx
            check_y = y + dy
            if (check_x, check_y) in map_data_instance.tiles_dict:
                tile = map_data_instance.tiles_dict[(check_x, check_y)]
                tile_type = tile['tile_type']
                stats['tile_counts'][tile_type] = stats['tile_counts'].get(tile_type, 0) + 1
                stats['total_food'] += map_data_instance.get_number_of_farms(tile)
                stats['total_wood'] += map_data_instance.get_resource_count((check_x, check_y), 'wood')
                stats['total_stone'] += map_data_instance.get_resource_count((check_x, check_y), 'stone')
                stats['total_iron'] += map_data_instance.get_resource_count((check_x, check_y), 'iron')
    
    stats['total_resources'] = stats['total_wood'] + stats['total_stone'] + stats['total_iron']
    return stats

def calculate_food_score(stats):
    return stats['total_food'] + (stats['tile_counts'].get('plains', 0) * 2)

def calculate_resource_score(stats):
    return stats['total_resources']

def calculate_balanced_score(stats):
    total = stats['total_resources'] - 3
    if total <= 0:
        return 0
    wood = stats['total_wood'] - 1
    stone = stats['total_stone'] - 1
    iron = stats['total_iron'] - 1
    avg = total / 3
    variance = (abs(wood - avg) + abs(stone - avg) + abs(iron - avg)) / 3
    balance_ratio = max(0, 1 - (variance / max(avg, 1)))
    return int(total * (0.5 + 0.5 * balance_ratio)) + 3

def find_best_locations(center_x, center_y, radius, analysis_type, top_n=10):
    occupied_centers = get_occupied_centers()
    
    candidates = []
    checked = 0
    excluded = 0
    
    for coords, tile in map_data_instance.tiles_dict.items():
        if not map_data_instance.is_settlable(tile):
            continue
        
        # Check if this tile is itself an occupied center
        is_occupied_center = any(c[0] == coords for c in occupied_centers)
        if is_occupied_center:
            excluded += 1
            continue
        
        # Get this candidate's 3x3 area
        x, y = coords
        candidate_3x3 = set()
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                candidate_3x3.add((x + dx, y + dy))
        
        # Check if candidate's 3x3 overlaps with any occupied center's 3x3
        has_overlap = False
        for center_coord, center_3x3, uid in occupied_centers:
            if candidate_3x3 & center_3x3:  # Set intersection
                has_overlap = True
                break
        
        if has_overlap:
            excluded += 1
            continue
        
        distance = get_distance(center_x, center_y, x, y)
        
        if distance > radius:
            continue
        
        checked += 1
        stats = analyze_3x3_area(coords)
        stats['distance'] = distance
        stats['position'] = 'center' if map_data_instance.is_center(tile) else f"quadrant {map_data_instance.get_quadrant(tile)}"
        
        if analysis_type == 'food':
            stats['score'] = calculate_food_score(stats)
        elif analysis_type == 'resources':
            stats['score'] = calculate_resource_score(stats)
        elif analysis_type == 'balanced':
            stats['score'] = calculate_balanced_score(stats)
        else:
            print(f"Unknown type '{analysis_type}'. Use: food, resources, balanced")
            return [], 0, 0, []
        
        candidates.append(stats)
    
    candidates.sort(key=lambda x: -x['score'])
    
    # Build occupied_tiles list for export
    occupied_tiles = [(c[0], {'tile_type': 'village'}, c[2]) for c in occupied_centers]
    
    return candidates[:top_n], checked, excluded, occupied_tiles

def format_tile_counts(stats):
    counts = stats['tile_counts']
    if not counts:
        return "None"
    sorted_counts = sorted(counts.items(), key=lambda x: -x[1])
    return ", ".join([f"{t}: {c}" for t, c in sorted_counts])

def main():
    if len(sys.argv) < 6:
        print("Usage: python quickAnalyzer.py <x> <y> <radius> <type> <top_n>")
        print("Types: food, resources, balanced")
        print("Example: python quickAnalyzer.py 79 96 25 food 10")
        sys.exit(1)
    
    center_x = int(sys.argv[1])
    center_y = int(sys.argv[2])
    radius = int(sys.argv[3])
    analysis_type = sys.argv[4].lower()
    top_n = int(sys.argv[5])
    
    type_names = {
        'food': 'FOOD',
        'resources': 'RESOURCES',
        'balanced': 'BALANCED',
    }
    
    print("="*70)
    print(f"SETTLEMENT FINDER - {type_names.get(analysis_type, analysis_type)}")
    print(f"From: ({center_x}, {center_y}) | Radius: {radius} | Top {top_n}")
    print("="*70)
    
    results, checked, excluded, occupied_tiles = find_best_locations(center_x, center_y, radius, analysis_type, top_n)
    
    print(f"Checked: {checked} | Excluded: {excluded} occupied | Found: {len(results)}")
    print("="*70)
    
    if not results:
        print("No suitable locations found.")
        return
    
    for i, r in enumerate(results, 1):
        print(f"\n#{i} | {r['coords']} | {r['position']} | {r['distance']:.1f} tiles")
        print(f"    Tiles: {format_tile_counts(r)}")
        print(f"    Food: {r['total_food']} | Resources: {r['total_resources']} (W:{r['total_wood']} S:{r['total_stone']} I:{r['total_iron']})")
    
    print(f"\n{'='*70}")
    
    # Export
    filename = f"analysis_{analysis_type}_{center_x}_{center_y}_r{radius}.txt"
    with open(filename, 'w') as f:
        f.write(f"SETTLEMENT FINDER - {type_names.get(analysis_type, analysis_type)}\n")
        f.write(f"From: ({center_x}, {center_y}) | Radius: {radius}\n")
        f.write(f"Checked: {checked} | Excluded: {excluded}\n")
        f.write("="*70 + "\n\n")
        
        for i, r in enumerate(results, 1):
            f.write(f"#{i} | {r['coords']} | {r['position']} | {r['distance']:.1f} tiles\n")
            f.write(f"Tiles: {format_tile_counts(r)}\n")
            f.write(f"Food: {r['total_food']} | Resources: {r['total_resources']} (W:{r['total_wood']} S:{r['total_stone']} I:{r['total_iron']})\n\n")
    
    print(f"Saved to: {filename}")

if __name__ == '__main__':
    main()

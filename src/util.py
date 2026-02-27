import requests
from PIL import Image

directions = [
    (0, 1), (1, 0), (0, -1), (-1, 0),
    (1, 1), (-1, -1), (1, -1), (-1, 1),
]
tile_size = 16
map_size = 151
class map_data:

    def __init__(self, map_json_path='https://forest1.aetherkingdoms.com/api/public/mapExport.json'):
        self.maps_json = self.get_maps_json(map_json_path)
        self.tile_types = { tile["type"] : tile for tile in self.maps_json["tiles"] }
        self.tiles_dict = { (tile['x'], tile['y']): tile for tile in self.maps_json["map"] }

    def is_settlable(self, tile):
        if "canSettle" not in self.tile_types[tile['tile_type']]:
            return False
        return self.tile_types[tile['tile_type']]["canSettle"]

    def get_number_of_farms(self, tile):
        return self.tile_types[tile['tile_type']]["food"]

    def get_resource_count(self, coords, resource_type):
        tile = self.tiles_dict[coords]
        return self.tile_types[tile['tile_type']][resource_type]

    def get_total_resource_count(self, coords):
        tile = self.tiles_dict[coords]
        return self.tile_types[tile['tile_type']]["sum"]

    def is_center(self, tile, center_x = 76, center_y = 76, radius = 16):
        return (center_x - radius <= tile['x'] <= center_x + radius) and \
            (center_y - radius <= tile['y'] <= center_y + radius)

    def get_quadrant(self, tile, center_x = 76, center_y = 76):
        if tile['x'] >= center_x and tile['y'] >= center_y:
            return 'SE'
        elif tile['x'] < center_x and tile['y'] >= center_y:
            return 'SW'
        elif tile['x'] < center_x and tile['y'] < center_y:
            return 'NW'
        else:
            return 'NE'

    def get_maps_json(self, map_json_path):
        # download map data from the provided URL
        response = requests.get(map_json_path)
        maps = response.json()

        return maps

map_data_instance = map_data('https://forest1.aetherkingdoms.com/api/public/mapExport.json')
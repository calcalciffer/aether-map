#!/usr/bin/env python3
"""
Discord Bot for Aether Kingdoms Settlement Finder
"""

import discord
from discord import app_commands
from discord.ext import commands
import sys
sys.path.insert(0, 'src')
from util import *
import math

# Bot configuration
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your actual bot token

# Settlement finder functions (same as quickAnalyzer)
def get_player_populations():
    """
    Calculate total population per player (only from settlement centers).
    Returns dict: {username: total_population}
    """
    player_pops = {}
    for coords, tile in map_data_instance.tiles_dict.items():
        uid = tile.get('user_id')
        username = tile.get('username')
        population = tile.get('population')
        tile_type = tile.get('tile_type')
        
        # Only count settlement centers (village/town/city), not claimed tiles
        if uid and username and population and tile_type in ['village', 'town', 'city']:
            if username not in player_pops:
                player_pops[username] = 0
            player_pops[username] += population
    
    return player_pops

def get_occupied_centers():
    """
    Get only the center tiles of each player settlement.
    Returns list of (center_coord, 3x3_tiles, user_id, username, player_population).
    """
    occupied_centers = []
    player_pops = get_player_populations()
    
    for coords, tile in map_data_instance.tiles_dict.items():
        uid = tile.get('user_id')
        username = tile.get('username')
        if uid is not None and uid != '':
            x, y = coords
            # Get all 9 tiles in this center's 3x3
            tiles_3x3 = set()
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    tiles_3x3.add((x + dx, y + dy))
            # Get player population (0 if not found)
            player_pop = player_pops.get(username, 0) if username else 0
            occupied_centers.append((coords, tiles_3x3, uid, username, player_pop))
    
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

def find_best_locations(center_x, center_y, radius, analysis_type, top_n=5, restricted=True):
    occupied_centers = get_occupied_centers()
    
    candidates = []
    
    for coords, tile in map_data_instance.tiles_dict.items():
        if not map_data_instance.is_settlable(tile):
            continue
        
        # Check if this tile is itself an occupied center
        is_occupied_center = any(c[0] == coords for c in occupied_centers)
        if is_occupied_center:
            continue
        
        # Get this candidate's 3x3 area
        x, y = coords
        candidate_3x3 = set()
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                candidate_3x3.add((x + dx, y + dy))
        
        # Check if candidate's 3x3 overlaps with any occupied center's 3x3
        has_overlap = False
        overlap_with_small_player = False
        overlapping_player_pop = 0
        
        for center_coord, center_3x3, uid, username, player_pop in occupied_centers:
            if candidate_3x3 & center_3x3:  # Set intersection
                has_overlap = True
                overlapping_player_pop = player_pop
                # If restricted=False, allow overlap with players having < 51 population
                if not restricted and player_pop < 51:
                    overlap_with_small_player = True
                else:
                    overlap_with_small_player = False
                break
        
        if has_overlap:
            if not overlap_with_small_player:
                continue
            else:
                # Overlap allowed with small player
                stats = analyze_3x3_area(coords)
                stats['overlap_allowed'] = True
                stats['overlap_pop'] = overlapping_player_pop
        else:
            stats = analyze_3x3_area(coords)
            stats['overlap_allowed'] = False
            stats['overlap_pop'] = 0
        
        distance = get_distance(center_x, center_y, x, y)
        if distance > radius:
            continue
        
        stats['distance'] = distance
        stats['position'] = 'center' if map_data_instance.is_center(tile) else f"quadrant {map_data_instance.get_quadrant(tile)}"
        
        if analysis_type == 'food':
            stats['score'] = calculate_food_score(stats)
        elif analysis_type == 'resources':
            stats['score'] = calculate_resource_score(stats)
        elif analysis_type == 'balanced':
            stats['score'] = calculate_balanced_score(stats)
        else:
            stats['score'] = 0
        
        candidates.append(stats)
    
    candidates.sort(key=lambda x: -x['score'])
    return candidates[:top_n]

def format_tile_counts(stats):
    counts = stats['tile_counts']
    if not counts:
        return "None"
    sorted_counts = sorted(counts.items(), key=lambda x: -x[1])
    return ", ".join([f"{t}: {c}" for t, c in sorted_counts])

# Discord bot setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync()
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')

@tree.command(name="settlementhelp", description="Show help for settlement finder")
async def settlementhelp(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Settlement Finder Help",
        description="Find the best settlement locations in Aether Kingdoms!",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📝 Command",
        value="`/findsettlement x:79 y:96 radius:15 search_type:Resources top_n:5 restricted:Yes`",
        inline=False
    )
    
    embed.add_field(
        name="📍 Parameters",
        value=(
            "**x, y** - Your coordinates (0-150)\n"
            "**radius** - Search distance in tiles (5-50)\n"
            "**search_type** - What to optimize for:\n"
            "  🌾 Food - Max food production\n"
            "  ⛏️ Resources - Max resources\n"
            "  ⚖️ Balanced - Equal wood/stone/iron\n"
            "**top_n** - Number of results (1-10)"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🗺️ Position Meanings",
        value=(
            "**center** - Near middle of map (76, 76)\n"
            "**quadrant NW** - North-West (x<76, y<76)\n"
            "**quadrant NE** - North-East (x≥76, y<76)\n"
            "**quadrant SW** - South-West (x<76, y≥76)\n"
            "**quadrant SE** - South-East (x≥76, y≥76)"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💡 Tips",
        value=(
            "• Settlement tile gives 1W/1S/1I/2F\n"
            "• Only 8 neighbors count for resources\n"
            "• Excludes occupied player areas\n"
            "• Restricted=No allows overlap with < 51 pop players\n"
            "• Larger radius = more options but slower"
        ),
        inline=False
    )
    
    embed.set_footer(text="Created for Aether Kingdoms")
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="findsettlement", description="Find best settlement locations near your coordinates")
@app_commands.describe(
    x="Your X coordinate (0-150)",
    y="Your Y coordinate (0-150)",
    radius="Search radius in tiles (5-50)",
    search_type="What to optimize for",
    top_n="Number of results (1-10)",
    restricted="Block overlap with small players? 'No' allows overlap with < 51 pop players"
)
@app_commands.choices(search_type=[
    app_commands.Choice(name="🌾 Food Production", value="food"),
    app_commands.Choice(name="⛏️ Total Resources", value="resources"),
    app_commands.Choice(name="⚖️ Balanced Resources", value="balanced"),
])
@app_commands.choices(restricted=[
    app_commands.Choice(name="✅ Yes - Strict blocking (default)", value="yes"),
    app_commands.Choice(name="⚠️ No - Allow overlap with < 51 pop players", value="no"),
])
async def findsettlement(
    interaction: discord.Interaction,
    x: int,
    y: int,
    radius: int,
    search_type: app_commands.Choice[str],
    top_n: int = 5,
    restricted: app_commands.Choice[str] = None
):
    # Validate inputs
    if not (0 <= x <= 150 and 0 <= y <= 150):
        await interaction.response.send_message("❌ Coordinates must be between 0 and 150!", ephemeral=True)
        return
    
    if not (5 <= radius <= 50):
        await interaction.response.send_message("❌ Radius must be between 5 and 50!", ephemeral=True)
        return
    
    if not (1 <= top_n <= 10):
        await interaction.response.send_message("❌ Top N must be between 1 and 10!", ephemeral=True)
        return
    
    # Parse restricted parameter (default to True/strict mode)
    is_restricted = True
    if restricted and restricted.value == "no":
        is_restricted = False
    
    await interaction.response.defer(thinking=True)
    
    try:
        results = find_best_locations(x, y, radius, search_type.value, top_n, is_restricted)
        
        if not results:
            await interaction.followup.send("❌ No suitable locations found. All areas may be occupied.")
            return
        
        # Build embed
        type_emojis = {
            'food': '🌾',
            'resources': '⛏️',
            'balanced': '⚖️'
        }
        
        embed = discord.Embed(
            title=f"{type_emojis.get(search_type.value, '🔍')} Settlement Finder Results",
            description=f"From: ({x}, {y}) | Radius: {radius} tiles | Type: {search_type.name}",
            color=discord.Color.green()
        )
        
        for i, r in enumerate(results, 1):
            # Add overlap tag if applicable
            overlap_tag = ""
            overlap_note = ""
            if r.get('overlap_allowed'):
                overlap_tag = " `#Overlap`"
                overlap_note = f"\n[!] Overlap allowed - Player has only {r.get('overlap_pop', 0)} pop (probably inactive)"
            
            field_value = (
                f"**Tiles:** {format_tile_counts(r)}{overlap_note}\n"
                f"**Food:** {r['total_food']} | **Resources:** {r['total_resources']} "
                f"(W:{r['total_wood']} S:{r['total_stone']} I:{r['total_iron']})\n"
                f"**Distance:** {r['distance']:.1f} tiles | **Position:** {r['position']}"
            )
            embed.add_field(
                name=f"#{i} | Coordinates: {r['coords']}{overlap_tag}",
                value=field_value,
                inline=False
            )
        
        embed.set_footer(text="Settlement tile gives 1W/1S/1I/2F | #Overlap = overlap with < 51 pop player allowed")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

# Run the bot
if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Please set your BOT_TOKEN in the script!")
        print("Get your token from: https://discord.com/developers/applications/")
        print("Go to Bot tab -> Reset Token -> Copy")
        sys.exit(1)
    
    client.run(BOT_TOKEN)

import sys
from functools import cache
from typing import Callable, Iterable, List, Tuple, Type

import pygame
from pygame.locals import *

from semirandom import randint

#############################
#---------- World -----------
#############################

class Dir:
    
    # Defines all the possible directions

    UP = 0, -1
    DOWN = 0, 1,
    LEFT = -1, 0,
    RIGHT = 1, 0
    UP_LEFT = -1, -1
    UP_RIGHT = 1, -1
    DOWN_LEFT = -1, 1
    DOWN_RIGHT = 1, 1

    ALL = (
        DOWN,
        DOWN_LEFT,
        DOWN_RIGHT,
        LEFT,
        UP_LEFT,
        UP,
        UP_RIGHT,
        RIGHT,
    )


class TileFlags:
    CAN_MOVE = 0
    TRANSMITS_HEAT = 1


class NextPosition:

    def __init__(self, x: int, y: int, valid: bool):
        self.x = x
        self.y = y
        self.valid = valid


class Tile:

    NAME: str

    def __init__(
            self,
            color: Tuple[int, int, int],
            density: int,
            world: "World",
            x: int,
            y: int
    ):
        # render stuff
        self.color = color
        # Physics stuff
        self.density = density
        # position
        self.x = x
        self.y = y
        self.world = world
        # control flags
        self.active: bool = True
        self.last_update: int = 0

    def remove(self):
        if self.active:
            self.world.tiles_to_delete.append(self)
            self.active = False
            return True
        return False

    def add(self):
        self.world.tiles.append(self)
        self.world.spatial_matrix[self.y][self.x] = self

    def delete(self):
        self.world.tiles.remove(self)
        self.world.spatial_matrix[self.y][self.x] = None

    def get_next_pos(self, relative_vector: Tuple[int, int]) -> NextPosition:
        # returns the world position given a vector relative to the tile
        next_x: int = self.x + relative_vector[0]
        if not 0 <= next_x < self.world.width:
            return NextPosition(0, 0, False)
        next_y: int = self.y + relative_vector[1]
        if not 0 <= next_y < self.world.height:
            return NextPosition(0, 0, False)
        return NextPosition(next_x, next_y, True)

    def get_neighbour_tile(self, direction: Tuple[int, int]) -> "Tile" or None:
        next_pos = self.get_next_pos(direction)
        if not next_pos.valid:
            return None
        checked_tile = self.world.spatial_matrix[next_pos.y][next_pos.x]
        if not checked_tile:
            return None
        return checked_tile

    def transform(self, new_type: type) -> "Tile" or None:
        if self.remove():
            new_tile = new_type(self.world, self.x, self.y)
            self.world.tiles_to_add.append(new_tile)
            return new_tile
        return None


class MovingTile(Tile):

    _MAX_UPDATE_SKIP = 3

    def __init__(self, color: Tuple[int, int, int], density: int, world: "World", x: int, y: int):
        super().__init__(color, density, world, x, y)
        self._skip_update: int = 0
        self._cooldown: int = 0

    def add(self):
        super().add()
        self.world.moving_tiles.append(self)

    def delete(self):
        super().delete()
        self.world.moving_tiles.remove(self)

    def move(self, new_x: int, new_y: int, replacement_tile: "Tile" or None):
        self.world.spatial_matrix[self.y][self.x] = replacement_tile
        self.x = new_x
        self.y = new_y
        self.world.spatial_matrix[self.y][self.x] = self

    def try_move(self, direction: Tuple[int, int]) -> bool:
        next_pos = self.get_next_pos(direction)
        if not next_pos.valid:
            return False
        checked_tile = self.world.spatial_matrix[next_pos.y][next_pos.x]
        if not checked_tile:
            self.move(next_pos.x, next_pos.y, None)
            return True
        elif checked_tile.density < self.density:
            checked_tile.x = self.x
            checked_tile.y = self.y
            checked_tile.last_update = self.world.update_count
            self.move(next_pos.x, next_pos.y, replacement_tile=checked_tile)
            return True
        return False

    def check_directions(self, directions: Iterable[Tuple[int, int]]):
        if self._cooldown == 0:
            for direction in directions:
                if self.try_move(direction):
                    self._skip_update = 0
                    self.last_update = self.world.update_count
                    return
        else:
            self._cooldown -= 1
            return
        if self._skip_update != self._MAX_UPDATE_SKIP:
            self._skip_update += 1
        self._cooldown = self._skip_update

    def update_position(self):
        raise NotImplemented


class HeatTile(Tile):

    UPPER_HEATH_THRESHOLD: Tuple[int, Type[Tile]] or None = None
    LOWER_HEATH_THRESHOLD: Tuple[int, Type[Tile]] or None = None

    check_thresholds: Callable

    def __init__(
            self,
            color: Tuple[int, int, int],
            density: int,
            world: "World",
            x: int,
            y: int,
            base_heat: int = 25,
            heat_transfer_coefficient: float = 1,
            passive_heat_loss: int = 0
    ):
        super().__init__(color, density, world, x, y)
        self.heat = base_heat
        self.heat_transfer_coefficient = heat_transfer_coefficient
        self.passive_heath_loss = passive_heat_loss
        # optimize threshold check
        if self.UPPER_HEATH_THRESHOLD and (not self.LOWER_HEATH_THRESHOLD):
            self.check_thresholds = self.check_upper_threshold
        elif (not self.UPPER_HEATH_THRESHOLD) and self.LOWER_HEATH_THRESHOLD:
            self.check_thresholds = self.check_lower_threshold
        elif self.UPPER_HEATH_THRESHOLD and self.LOWER_HEATH_THRESHOLD:
            self.check_thresholds = self.check_both_thresholds
        else:
            self.check_thresholds = self.check_no_threshold

    def add(self):
        super().add()
        self.world.heat_tiles.append(self)

    def delete(self):
        super().delete()
        self.world.heat_tiles.remove(self)

    def check_no_threshold(self) -> bool:
        return False

    def check_upper_threshold(self) -> bool:
        if self.heat >= self.UPPER_HEATH_THRESHOLD[0]:
            if self.UPPER_HEATH_THRESHOLD[1]:
                new_tile = self.transform(self.UPPER_HEATH_THRESHOLD[1])
                if new_tile:
                    new_tile.heat = self.heat
                return True
            self.remove()
            return True
        return False

    def check_lower_threshold(self) -> bool:
        if self.heat <= self.LOWER_HEATH_THRESHOLD[0]:
            if self.LOWER_HEATH_THRESHOLD[1]:
                new_tile = self.transform(self.LOWER_HEATH_THRESHOLD[1])
                if new_tile:
                    new_tile.heat = self.heat
                return True
            self.remove()
            return True
        return False

    def check_both_thresholds(self) -> bool:
        return self.check_upper_threshold() or self.check_lower_threshold()

    def exchange_heat(self, target_tile: "HeatTile"):
        htc: float = self.heat_transfer_coefficient + target_tile.heat_transfer_coefficient
        exchanged_heat = int((target_tile.heat - self.heat) * htc) >> 2
        self.heat += exchanged_heat
        target_tile.heat -= exchanged_heat

    @cache
    def can_tile_exchange_heat(self, tile):
        return (tile is not None) and (tile in self.world.heat_tiles)

    def do_exchange_heat(self):
        self.heat -= self.passive_heath_loss
        for direction in Dir.ALL:
            tile: Tile = self.get_neighbour_tile(direction)
            if self.can_tile_exchange_heat(tile):
                self.exchange_heat(tile)
        self.check_thresholds()

    def update_temperature(self):
        raise NotImplemented


class CustomTile(Tile):

    def add(self):
        super().add()
        self.world.custom_tiles.append(self)

    def delete(self):
        super().delete()
        self.world.custom_tiles.remove(self)

    def custom_update(self):
        raise NotImplemented


class GenericSystem:

    NAME: str

    def __init__(self, world: "World"):
        self.world = world

    def update(self):
        raise NotImplemented


class MovementSystem(GenericSystem):

    NAME = "Movement System"

    def update(self):
        for tile in self.world.moving_tiles:
            if tile.last_update != self.world.update_count:
                tile.update_position()


class HeathSystem(GenericSystem):

    NAME = "Heath System"

    def update(self):
        for tile in self.world.heat_tiles:
            tile.update_temperature()


class CustomTileSystem(GenericSystem):

    NAME = "Custom Tile System"

    def update(self):
        for tile in self.world.custom_tiles:
            tile.custom_update()


class World:

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # init tile lists
        self.tiles: List[Tile] = []
        self.moving_tiles: List[MovingTile] = []
        self.heat_tiles: List[HeatTile] = []
        self.custom_tiles: List[CustomTile] = []
        self.tiles_to_delete: List[Tile] = []
        self.tiles_to_add: List[Tile] = []
        # init world matrices
        init_matrix: List[List[Tile or None]] = []
        for _ in range(height):
            init_matrix.append([None for _ in range(width)])
        self.spatial_matrix: Tuple[List[Tile], ...] = tuple(init_matrix)
        # init systems
        self.systems: Iterable[GenericSystem] = (
            MovementSystem(self),
            HeathSystem(self),
            CustomTileSystem(self)
        )
        self.update_count: int = 0

    def add_tile(self, tile_type: type, x: int, y: int) -> Tile:
        """ adds a tile at the given position and returns it """
        new_tile: Tile = tile_type(self, x, y)
        if not self.spatial_matrix[y][x]:
            new_tile.add()
        return new_tile

    def delete_tile(self, x: int, y: int) -> Tile:
        """ Removes a tile at the given position and returns it """
        tile = self.spatial_matrix[y][x]
        if tile:
            tile.remove()
        return tile

    def update(self):
        # update systems
        for system in self.systems:
            system.update()
        # delete tiles that need to be deleted
        if self.tiles_to_delete:
            for tile in self.tiles_to_delete:
                tile.delete()
                del tile
            self.tiles_to_delete.clear()
        # add tiles that need to be added
        if self.tiles_to_add:
            for tile in self.tiles_to_add:
                tile.add()
                del tile
            self.tiles_to_add.clear()
        self.update_count += 1


# Tile types --------------------------------------

class SolidTile(HeatTile):

    def update_temperature(self):
        self.do_exchange_heat()


class SemiSolidTile(HeatTile, MovingTile):

    DIRECTIONS = (Dir.DOWN, Dir.DOWN_LEFT, Dir.DOWN_RIGHT)

    def update_position(self):
        self.check_directions(self.DIRECTIONS)

    def update_temperature(self):
        self.do_exchange_heat()


class LiquidTile(HeatTile, MovingTile):

    DIRECTIONS = (
        (Dir.DOWN, Dir.DOWN_LEFT, Dir.LEFT, Dir.DOWN_RIGHT, Dir.RIGHT),
        (Dir.DOWN, Dir.DOWN_RIGHT, Dir.RIGHT, Dir.DOWN_LEFT, Dir.LEFT)
    )

    def update_position(self):
        self.check_directions(self.DIRECTIONS[randint(2)])

    def update_temperature(self):
        self.do_exchange_heat()


class GasTile(HeatTile, MovingTile):

    DIRECTIONS = (
        (Dir.UP, Dir.UP_LEFT, Dir.LEFT, Dir.UP_RIGHT, Dir.RIGHT),
        (Dir.UP, Dir.UP_RIGHT, Dir.RIGHT, Dir.UP_LEFT, Dir.LEFT)
    )

    def update_position(self):
        self.check_directions(self.DIRECTIONS[randint(2)])

    def update_temperature(self):
        self.do_exchange_heat()
        
#############################
#---------- Tiles -----------
#############################

TILES: List[Type[Tile]] = []

def add_to_tile_list(tile: Type[Tile]) -> Type[Tile]:
    TILES.append(tile)
    return tile

# Solid tiles

@add_to_tile_list
class ConcreteTile(SolidTile):

    NAME = "Concrete"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (140 + randint(40), 140 + randint(40), 140 + randint(40)),
            100000,
            world,
            x,
            y
        )

@add_to_tile_list
class WoodTile(SolidTile):

    NAME = "Wood"
    UPPER_HEATH_THRESHOLD = 500, "BurningWood"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (117 + randint(40), 63 + randint(40), 4 + randint(40)),
            10000,
            world,
            x,
            y,
            heat_transfer_coefficient=0.01
        )

class BurningWood(SolidTile):

    NAME = "Burning Wood"
    UPPER_HEATH_THRESHOLD = 2000, "AshTile"
    LOWER_HEATH_THRESHOLD = 90, WoodTile

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (209 + randint(40), 118 + randint(40), 4),
            100000,
            world,
            x,
            y,
            base_heat=500,
            heat_transfer_coefficient=1,
            passive_heat_loss=-5
        )


@add_to_tile_list
class GlassTile(SolidTile):

    NAME = "Glass"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (152 + randint(40), 203 + randint(40), 206 + randint(40)),
            100000,
            world,
            x,
            y,
            heat_transfer_coefficient=0.5
        )

# Semi solid tiles

@add_to_tile_list
class SandTile(SemiSolidTile):

    NAME = "Sand"
    UPPER_HEATH_THRESHOLD = 800, GlassTile

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (205-randint(50), 205-randint(50), 0),
            10,
            world,
            x,
            y,
            heat_transfer_coefficient=0.05
        )


@add_to_tile_list
class RockTile(SemiSolidTile):

    NAME = "Rock"
    UPPER_HEATH_THRESHOLD = 1000, "LavaTile"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (40-randint(10), 40-randint(10), 50-randint(10)),
            800,
            world,
            x,
            y
        )


@add_to_tile_list
class IceTile(SemiSolidTile):

    NAME = "Ice"
    UPPER_HEATH_THRESHOLD = 10, "WaterTile"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (200-randint(20), 200-randint(20), 255-randint(20)),
            1,
            world,
            x,
            y,
            base_heat=-40,
        )


@add_to_tile_list
class AshTile(SemiSolidTile):

    NAME = "Ash"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (140-randint(20), 140-randint(20), 140-randint(20)),
            1,
            world,
            x,
            y,
            base_heat=100,
        )


@add_to_tile_list
class GunpowderTile(SemiSolidTile):

    NAME = "Gun powder"
    UPPER_HEATH_THRESHOLD = 500, "ExplosionTile"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (40-randint(20), 40-randint(20), 40-randint(20)),
            4,
            world,
            x,
            y
        )


# Liquid tiles

@add_to_tile_list
class WaterTile(LiquidTile):

    NAME = "Water"
    UPPER_HEATH_THRESHOLD = 100, "VaporTile"
    LOWER_HEATH_THRESHOLD = 0, IceTile

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (0, 0, 155+randint(100)),
            2,
            world,
            x,
            y,
        )


@add_to_tile_list
class OilTile(LiquidTile):

    NAME = "Oil"
    UPPER_HEATH_THRESHOLD = 300, "FireTile"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (193-randint(20), 193-randint(20), 69-randint(10)),
            1,
            world,
            x,
            y,
            base_heat=25,
        )


@add_to_tile_list
class LavaTile(LiquidTile):

    NAME = "Lava"
    LOWER_HEATH_THRESHOLD = 500, RockTile

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (255 - randint(20), 0, 0),
            1000,
            world,
            x,
            y,
            base_heat=10000,
            heat_transfer_coefficient=0.1
        )


@add_to_tile_list
class LiquidNitrogen(LiquidTile):

    NAME = "Liquid Nitrogen"
    UPPER_HEATH_THRESHOLD = 0, None

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (255, 255, 255),
            0,
            world,
            x,
            y,
            base_heat=-10000,
        )


# Gas tiles

@add_to_tile_list
class VaporTile(GasTile):

    NAME = "Vapor"
    LOWER_HEATH_THRESHOLD = 60, WaterTile

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (255-randint(20), 255-randint(20), 255-randint(20)),
            0,
            world,
            x,
            y,
            base_heat=220 + randint(120),
            passive_heat_loss=1
        )


@add_to_tile_list
class SmokeTile(GasTile):

    NAME = "Smoke"
    LOWER_HEATH_THRESHOLD = 100, None

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (50-randint(20), 50-randint(20), 50-randint(20)),
            0,
            world,
            x,
            y,
            base_heat=300 + randint(120),
            passive_heat_loss=1
        )


# Custom tiles

@add_to_tile_list
class FireTile(CustomTile):

    NAME = "Fire"

    DIRECTIONS = (
        (Dir.UP, Dir.UP_LEFT, Dir.UP_RIGHT),
        (Dir.UP_LEFT, Dir.UP, Dir.UP_RIGHT),
        (Dir.UP_RIGHT, Dir.UP_LEFT, Dir.UP),
        (Dir.LEFT, Dir.RIGHT, Dir.UP_LEFT, Dir.UP_RIGHT),
        (Dir.RIGHT, Dir.LEFT, Dir.UP_RIGHT, Dir.UP_LEFT),
        (Dir.UP_LEFT, Dir.UP_RIGHT, Dir.LEFT, Dir.RIGHT),
        (Dir.UP_RIGHT, Dir.UP_LEFT, Dir.RIGHT, Dir.LEFT)
    )

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (242-randint(20), 141-randint(20), 0),
            -2,
            world,
            x,
            y
        )
        self.duration: int = 180 + randint(180)

    def custom_update(self):
        for direction in self.DIRECTIONS[randint(7)]:
            next_pos = self.get_next_pos(direction)
            if not next_pos.valid:
                continue
            checked_tile: Tile = self.world.spatial_matrix[next_pos.y][next_pos.x]
            if not checked_tile:
                self.world.spatial_matrix[self.y][self.x] = None
                self.x = next_pos.x
                self.y = next_pos.y
                self.world.spatial_matrix[self.y][self.x] = self
                break
            elif checked_tile in self.world.heat_tiles:
                checked_tile.heat += 100
                self.duration -= 50
                break
        self.duration -= 1
        if self.duration <= 0:
            self.remove()


@add_to_tile_list
class GreyGooTile(CustomTile):

    NAME = "Grey Goo"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (180, 180, 180),
            0,
            world,
            x,
            y
        )

    def custom_update(self):
        for direction in Dir.ALL:
            tile: Tile = self.get_neighbour_tile(direction)
            if tile and (type(tile) != GreyGooTile):
                tile.transform(GreyGooTile)


@add_to_tile_list
class AcidTile(LiquidTile, CustomTile):

    NAME = "Acid"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (0, 235 + randint(20), 0),
            0,
            world,
            x,
            y
        )

    def custom_update(self):
        if randint(20) != 0:
            return
        for direction in Dir.ALL:
            tile: Tile = self.get_neighbour_tile(direction)
            if tile and (type(tile) != AcidTile):
                tile.remove()
                self.remove()
                return


@add_to_tile_list
class ExplosionTile(HeatTile, CustomTile):

    NAME = "Explosion"

    def __init__(self, world: World, x: int, y: int):
        super().__init__(
            (255, 255, 0),
            10000,
            world,
            x,
            y,
            base_heat=2000
        )
        self.range: int = 10
        self.tile_duration: int = 2

    def custom_update(self):
        if self.tile_duration == 0:
            if self.range != 0:
                new_range = self.range - 1
                for direction in (Dir.UP, Dir.LEFT, Dir.RIGHT, Dir.DOWN):
                    next_pos = self.get_next_pos(direction)
                    if not next_pos.valid:
                        continue
                    checked_tile: Tile = self.world.spatial_matrix[next_pos.y][next_pos.x]
                    if checked_tile and (type(checked_tile) != ExplosionTile):
                        checked_tile.remove()
                    new_tile = self.world.add_tile(ExplosionTile, next_pos.x, next_pos.y)
                    new_tile.range = new_range
            else:
                new_tile = SmokeTile(self.world, self.x, self.y)
                self.world.tiles_to_add.append(new_tile)
            self.remove()
        else:
            self.tile_duration -= 1

    def update_temperature(self):
        self.do_exchange_heat()


# This is needed as a workaround of Python's lack of forward declaration
for tile_to_fix in TILES:
    if "UPPER_HEATH_THRESHOLD" in tile_to_fix.__dict__:
        if tile_to_fix.UPPER_HEATH_THRESHOLD:
            if type(tile_to_fix.UPPER_HEATH_THRESHOLD[1]) == str:
                tile_to_fix.UPPER_HEATH_THRESHOLD = \
                    tile_to_fix.UPPER_HEATH_THRESHOLD[0], \
                    globals()[tile_to_fix.UPPER_HEATH_THRESHOLD[1]]
        if tile_to_fix.LOWER_HEATH_THRESHOLD:
            if type(tile_to_fix.LOWER_HEATH_THRESHOLD[1]) == str:
                tile_to_fix.LOWER_HEATH_THRESHOLD = \
                    tile_to_fix.LOWER_HEATH_THRESHOLD[0], \
                    globals()[tile_to_fix.LOWER_HEATH_THRESHOLD[1]]
                    
#############################
#---------- Main ------------
#############################

pygame.init()

FONT = pygame.font.Font("font.ttf", 18)
SMALL_FONT = pygame.font.Font("font.ttf", 14)

# Game Setup
FPS = 60
fpsClock = pygame.time.Clock()
WINDOW = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
pygame.display.set_caption("SandBox")

paused_text = FONT.render("SIMULATION PAUSED", False, (255, 255, 255))


def render(world: World, selected_tile: int, mouse_position: Tuple[int, int], paused: bool, tiles_info: bool):
    # set window caption (show FPS)
    pygame.display.set_caption(f"Charb's SandBox")
    # render world
    surface = pygame.Surface((world.width, world.height))
    for tile in world.tiles:
        surface.set_at((tile.x, tile.y), tile.color)
    surface.set_at(mouse_position, (255, 255, 255))
    scaled_surface = pygame.transform.scale(surface, WINDOW.get_size())
    # render selected tile
    tile_text = FONT.render(f"selected ({selected_tile + 1}/{len(TILES)}): {TILES[selected_tile].NAME}".capitalize(), False, (255, 255, 255))
    scaled_surface.blit(tile_text, (10, 10))
    # render additional information if tiles info is on
    if tiles_info:
        total_particles_text = FONT.render(f"Total tiles: {len(world.tiles)}".capitalize(), False, (255, 255, 255))
        scaled_surface.blit(total_particles_text, (10, 50))
        tile = world.spatial_matrix[mouse_position[1]][mouse_position[0]]
        if tile:
            mouse_pos = pygame.mouse.get_pos()
            tile_type_text = SMALL_FONT.render(
                f"Type: {tile.NAME}".capitalize(),
                False,
                (255, 255, 255)
            )
            tile_type_text_shadow = SMALL_FONT.render(
                f"Type: {tile.NAME}".capitalize(),
                False,
                (0, 0, 0)
            )
            scaled_surface.blit(tile_type_text_shadow, (mouse_pos[0] + 12, mouse_pos[1] + 2))
            scaled_surface.blit(tile_type_text, (mouse_pos[0] + 10, mouse_pos[1]))
            if "heat" in tile.__dict__:
                tile_heat_text = SMALL_FONT.render(
                    f"Heat: {tile.heat}".capitalize(),
                    False,
                    (255, 255, 255)
                )
                tile_heat_text_shadow = SMALL_FONT.render(
                    f"Heat: {tile.heat}".capitalize(),
                    False,
                    (0, 0, 0)
                )
                scaled_surface.blit(tile_heat_text_shadow, (mouse_pos[0] + 12, mouse_pos[1] + 22))
                scaled_surface.blit(tile_heat_text, (mouse_pos[0] + 10, mouse_pos[1] + 20))
    # render pause text if the simulation is paused
    if paused:
        scaled_surface.blit(paused_text, (WINDOW.get_width() - paused_text.get_width() - 10, 10))
    # render surface to window
    WINDOW.blit(scaled_surface, (0, 0))
    pygame.display.flip()


def clamp(n, smallest, largest) -> int:
    ll: List[int] = [smallest, n, largest]
    ll.sort()
    return ll[1]


def get_mouse_world_position(world: World) -> Tuple[int, int]:
    window_size = WINDOW.get_size()
    mouse_pos = pygame.mouse.get_pos()
    mouse_x = clamp(int((mouse_pos[0] / window_size[0]) * world.width), 0, world.width - 1)
    mouse_y = clamp(int((mouse_pos[1] / window_size[1]) * world.height), 0, world.height - 1)
    return mouse_x, mouse_y


def main():
    world = World(160, 90)
    selected_tile: int = 0
    pause: bool = False
    tiles_info: bool = False

    while True:
        # Get mouse position
        mouse_position = get_mouse_world_position(world)
        # Get inputs
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                sys.exit()
            if event.type == MOUSEWHEEL:
                if event.y == -1:
                    if selected_tile == 0:
                        selected_tile = len(TILES) - 1
                    else:
                        selected_tile -= 1
                else:
                    if selected_tile == len(TILES) - 1:
                        selected_tile = 0
                    else:
                        selected_tile += 1
            if event.type == KEYDOWN:
                if event.unicode == " ":
                    pause = not pause
                elif event.scancode == 58:
                    # Press F1
                    tiles_info = not tiles_info
                elif event.scancode == 41:
                    # Press ESC
                    world = World(160, 90)
        if pygame.mouse.get_pressed()[0]:
            world.add_tile(TILES[selected_tile], mouse_position[0], mouse_position[1])
            if pygame.key.get_pressed()[K_LCTRL]:
                for direction in Dir.ALL:
                    world.add_tile(
                        TILES[selected_tile],
                        mouse_position[0] + direction[0],
                        mouse_position[1] + direction[1]
                    )
        elif pygame.mouse.get_pressed()[2]:
            world.delete_tile(mouse_position[0], mouse_position[1])
            if pygame.key.get_pressed()[K_LCTRL]:
                for direction in Dir.ALL:
                    world.delete_tile(
                        mouse_position[0] + direction[0],
                        mouse_position[1] + direction[1]
                    )
        # update physics
        if not pause:
            world.update()
        # render
        render(world, selected_tile, mouse_position, pause, tiles_info)
        fpsClock.tick(FPS)


if __name__ == "__main__":
    main()

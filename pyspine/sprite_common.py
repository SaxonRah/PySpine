import pygame
from configuration import *


def safe_sprite_extract(sprite_sheet, sprite_rect):
    """Safely extract sprite from sheet with bounds checking"""
    if not sprite_sheet:
        return None

    sheet_w, sheet_h = sprite_sheet.get_size()
    if (sprite_rect.x >= 0 and sprite_rect.y >= 0 and
            sprite_rect.x + sprite_rect.width <= sheet_w and
            sprite_rect.y + sprite_rect.height <= sheet_h and
            sprite_rect.width > 0 and sprite_rect.height > 0):

        try:
            return sprite_sheet.subsurface((sprite_rect.x, sprite_rect.y, sprite_rect.width, sprite_rect.height))
        except pygame.error:
            return None
    return None


def draw_sprite_with_origin(screen, viewport_manager, sprite_sheet, sprite_rect, world_pos,
                            rotation=0, scale=1.0, selected=False):
    """Draw sprite with origin point as both attachment and rotation pivot"""
    sprite_surface = safe_sprite_extract(sprite_sheet, sprite_rect)
    if not sprite_surface:
        return

    # Calculate final size after scaling
    final_width = max(1, int(sprite_rect.width * scale * viewport_manager.viewport_zoom))
    final_height = max(1, int(sprite_rect.height * scale * viewport_manager.viewport_zoom))

    # Scale the sprite first
    scaled_sprite = pygame.transform.scale(sprite_surface, (final_width, final_height))

    # Calculate origin position in the scaled sprite (in pixels from top-left)
    origin_x_pixels = final_width * sprite_rect.origin_x
    origin_y_pixels = final_height * sprite_rect.origin_y

    # Convert world position to screen coordinates
    origin_screen_pos = viewport_manager.viewport_to_screen(world_pos)

    if abs(rotation) > 0.01:
        # For rotation, we need to use a different approach
        # Create a larger surface to rotate within
        max_dim = max(final_width, final_height) * 2  # Ensure enough space for rotation
        rotation_surface = pygame.Surface((max_dim, max_dim), pygame.SRCALPHA)

        # Position the scaled sprite in the center of the rotation surface,
        # but offset so that the sprite's origin is at the center of the rotation surface
        sprite_pos_in_rotation_surface = (
            max_dim // 2 - origin_x_pixels,
            max_dim // 2 - origin_y_pixels
        )
        rotation_surface.blit(scaled_sprite, sprite_pos_in_rotation_surface)

        # Now rotate the entire surface around its center (which is where our sprite's origin is)
        rotated_surface = pygame.transform.rotate(rotation_surface, -rotation)

        # Calculate where to position the rotated surface so its center (sprite origin) is at world_pos
        rotated_rect = rotated_surface.get_rect()
        final_pos = (
            origin_screen_pos[0] - rotated_rect.width // 2,
            origin_screen_pos[1] - rotated_rect.height // 2
        )

        final_sprite = rotated_surface
        final_rect = pygame.Rect(final_pos[0], final_pos[1], rotated_rect.width, rotated_rect.height)
    else:
        # No rotation - simple positioning
        final_pos = (
            origin_screen_pos[0] - origin_x_pixels,
            origin_screen_pos[1] - origin_y_pixels
        )

        final_sprite = scaled_sprite
        final_rect = pygame.Rect(final_pos[0], final_pos[1], final_width, final_height)

    # Draw the sprite
    screen.blit(final_sprite, final_rect)

    # Draw selection highlight around the original sprite bounds (not the rotation surface)
    if selected:
        if abs(rotation) > 0.01:
            # For rotated sprites, draw a simple circle around the origin
            pygame.draw.circle(screen, CYAN, (int(origin_screen_pos[0]), int(origin_screen_pos[1])),
                               max(final_width, final_height) // 2, 3)
        else:
            # For non-rotated sprites, draw rectangle around actual sprite
            highlight_rect = pygame.Rect(final_pos[0], final_pos[1], final_width, final_height)
            pygame.draw.rect(screen, CYAN, highlight_rect, 3)

    # Always draw the origin point for debugging/visualization
    if viewport_manager.viewport_zoom > 0.3:  # Only show when zoomed in enough
        pygame.draw.circle(screen, RED, (int(origin_screen_pos[0]), int(origin_screen_pos[1])), 3)
        pygame.draw.circle(screen, WHITE, (int(origin_screen_pos[0]), int(origin_screen_pos[1])), 3, 1)

    return final_rect


def draw_sprite_origin(screen, viewport_manager, sprite_rect, world_pos, color=RED):
    """Draw sprite origin point"""
    origin_world_x = world_pos[0] + sprite_rect.width * sprite_rect.origin_x
    origin_world_y = world_pos[1] + sprite_rect.height * sprite_rect.origin_y
    origin_screen = viewport_manager.viewport_to_screen((origin_world_x, origin_world_y))

    origin_size = max(2, int(3 * viewport_manager.viewport_zoom))
    pygame.draw.circle(screen, color, (int(origin_screen[0]), int(origin_screen[1])), origin_size)
    pygame.draw.circle(screen, WHITE, (int(origin_screen[0]), int(origin_screen[1])), origin_size, 2)

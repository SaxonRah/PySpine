import pygame
from configuration import *


def draw_grid(screen, viewport_manager, viewport_rect, toolbar_height=0):
    """Draw grid in viewport - used by all editors"""
    grid_size = 50 * viewport_manager.viewport_zoom

    start_x = int(-viewport_manager.viewport_offset[0] // grid_size) * grid_size + viewport_manager.viewport_offset[0]
    start_y = int(-viewport_manager.viewport_offset[1] // grid_size) * grid_size + viewport_manager.viewport_offset[1]

    for x in range(int(start_x), viewport_rect.width, int(grid_size)):
        if x >= viewport_rect.x:
            pygame.draw.line(screen, (32, 32, 32), (x, viewport_rect.y), (x, viewport_rect.bottom))

    for y in range(int(start_y), viewport_rect.height, int(grid_size)):
        if y >= viewport_rect.y:
            pygame.draw.line(screen, (32, 32, 32), (viewport_rect.x, y), (viewport_rect.right, y))


def draw_panel_background(screen, rect, color=LIGHT_GRAY, border_color=WHITE, border_width=2):
    """Draw a standard panel background"""
    pygame.draw.rect(screen, color, rect)
    pygame.draw.rect(screen, border_color, rect, border_width)


def draw_text_lines(screen, font, lines, start_pos, color=BLACK, line_height=20):
    """Draw multiple lines of text"""
    x, y = start_pos
    for line in lines:
        if line:  # Skip empty lines
            text_surface = font.render(line, True, color)
            screen.blit(text_surface, (x, y))
        y += line_height
    return y


def is_in_rect(pos, rect):
    """Check if position is within rectangle"""
    x, y = pos
    return rect.x <= x <= rect.right and rect.y <= y <= rect.bottom

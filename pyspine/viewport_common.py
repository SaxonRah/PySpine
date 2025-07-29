class ViewportManager:
    def __init__(self, initial_offset, initial_zoom=1.0):
        self.viewport_offset = initial_offset
        self.viewport_zoom = initial_zoom
        self.dragging_viewport = False
        self.last_mouse_pos = (0, 0)

    def screen_to_viewport(self, pos, toolbar_height=0):
        """Convert screen coordinates to viewport coordinates"""
        x = (pos[0] - self.viewport_offset[0]) / self.viewport_zoom
        y = (pos[1] - toolbar_height - self.viewport_offset[1]) / self.viewport_zoom
        return x, y

    def viewport_to_screen(self, pos, toolbar_height=0):
        """Convert viewport coordinates to screen coordinates"""
        x = pos[0] * self.viewport_zoom + self.viewport_offset[0]
        y = pos[1] * self.viewport_zoom + self.viewport_offset[1] + toolbar_height
        return x, y

    def handle_zoom(self, event, mouse_pos, zoom_bounds=(0.1, 5.0)):
        """Handle mouse wheel zooming"""
        zoom_factor = 1.1 if event.y > 0 else 0.9
        old_zoom = self.viewport_zoom
        self.viewport_zoom = max(zoom_bounds[0], min(zoom_bounds[1], self.viewport_zoom * zoom_factor))

        zoom_ratio = self.viewport_zoom / old_zoom
        self.viewport_offset[0] = mouse_pos[0] - (mouse_pos[0] - self.viewport_offset[0]) * zoom_ratio
        self.viewport_offset[1] = mouse_pos[1] - (mouse_pos[1] - self.viewport_offset[1]) * zoom_ratio

    def handle_drag(self, mouse_pos):
        """Handle viewport dragging"""
        if self.dragging_viewport:
            dx = mouse_pos[0] - self.last_mouse_pos[0]
            dy = mouse_pos[1] - self.last_mouse_pos[1]
            self.viewport_offset[0] += dx
            self.viewport_offset[1] += dy

    def reset_viewport(self, default_offset, default_zoom=1.0):
        """Reset viewport to default"""
        self.viewport_offset = default_offset[:]
        self.viewport_zoom = default_zoom

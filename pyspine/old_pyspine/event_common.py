import pygame


class BaseEventHandler:
    """Base class for common event handling patterns"""

    def __init__(self):
        self.key_handlers = {}
        self.setup_common_keys()

    def setup_common_keys(self):
        """Setup common keyboard shortcuts"""
        self.key_handlers.update({
            (pygame.K_s, pygame.K_LCTRL): self.save_project,
            (pygame.K_l, pygame.K_LCTRL): self.load_project,
            (pygame.K_DELETE, None): self.delete_selected,
            (pygame.K_r, None): self.reset_viewport,
        })

    def handle_keydown(self, event):
        """Handle keydown events using registered handlers"""
        ctrl_pressed = pygame.key.get_pressed()[pygame.K_LCTRL]
        key_combo = (event.key, pygame.K_LCTRL if ctrl_pressed else None)

        if key_combo in self.key_handlers:
            self.key_handlers[key_combo]()
            return True
        return False

    # These methods should be overridden by subclasses
    def save_project(self): pass

    def load_project(self): pass

    def delete_selected(self): pass

    def reset_viewport(self): pass

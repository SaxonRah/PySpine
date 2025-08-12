import pygame
import math
from configuration import *
from common import _point_to_line_distance
from data_classes import BoneLayer, AttachmentPoint


def get_bone_layer_colors(bone_layer, selected=False):
    """Get color scheme based on bone layer"""
    if bone_layer == BoneLayer.BEHIND:
        # Blues for behind layer
        if selected:
            return {
                'line': (0, 150, 255),  # Bright blue
                'start': (0, 255, 255),  # Cyan
                'end': (0, 100, 255)  # Deep blue
            }
        else:
            return {
                'line': (0, 100, 200),  # Dark blue
                'start': (0, 150, 255),  # Medium blue
                'end': (0, 0, 200)  # Navy blue
            }
    elif bone_layer == BoneLayer.FRONT:
        # Reds for front layer
        if selected:
            return {
                'line': ORANGE,  # Orange for selected
                'start': (255, 100, 100),  # Light red
                'end': ORANGE  # Orange
            }
        else:
            return {
                'line': RED,  # Red for normal
                'start': (200, 0, 0),  # Dark red
                'end': (255, 100, 0)  # Red-orange
            }
    else:  # MIDDLE (default)
        # Greens for middle layer (original colors)
        if selected:
            return {
                'line': ORANGE,  # Orange for selected
                'start': CYAN,  # Cyan for selected start
                'end': ORANGE  # Orange for selected end
            }
        else:
            return {
                'line': GREEN,  # Green for normal
                'start': BLUE,  # Blue for start
                'end': RED  # Red for end
            }


def draw_bone(screen, viewport_manager, bone, color=None, selected=False, animated_transform=None, font=None):
    """Draw a single bone with layer-based color styling"""
    # Get layer-specific colors
    if hasattr(bone, 'layer'):
        colors = get_bone_layer_colors(bone.layer, selected)
        bone_line_color = colors['line']
        start_color = colors['start']
        end_color = colors['end']
    else:
        # Fallback for old bones without layer
        bone_line_color = ORANGE if selected else (color or GREEN)
        start_color = CYAN if selected else BLUE
        end_color = ORANGE if selected else RED

    # Use animated transform if provided, otherwise use bone's base transform
    if animated_transform:
        world_x, world_y, world_rot, world_scale = animated_transform
        end_x = world_x + bone.length * math.cos(math.radians(world_rot))
        end_y = world_y + bone.length * math.sin(math.radians(world_rot))
    else:
        world_x, world_y = bone.x, bone.y
        end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
        end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

    start_screen = viewport_manager.viewport_to_screen((world_x, world_y))
    end_screen = viewport_manager.viewport_to_screen((end_x, end_y))

    # Determine sizes - smaller for tighter selection
    width = max(1, int(2 * viewport_manager.viewport_zoom))
    start_radius = max(2, int(4 * viewport_manager.viewport_zoom))
    end_radius = max(2, int(4 * viewport_manager.viewport_zoom))

    # Draw bone line
    pygame.draw.line(screen, bone_line_color, start_screen, end_screen, width)

    # Draw joints with layer-specific colors
    # Start point (base)
    pygame.draw.circle(screen, start_color, (int(start_screen[0]), int(start_screen[1])), start_radius)
    pygame.draw.circle(screen, WHITE, (int(start_screen[0]), int(start_screen[1])), start_radius, 1)

    # End point
    pygame.draw.circle(screen, end_color, (int(end_screen[0]), int(end_screen[1])), end_radius)
    pygame.draw.circle(screen, WHITE, (int(end_screen[0]), int(end_screen[1])), end_radius, 1)

    # Add text labels "B" and "E"
    if font and viewport_manager.viewport_zoom > 0.5:
        # "B" for base/start
        b_text = font.render("B", True, WHITE)
        b_rect = b_text.get_rect()
        b_rect.center = (int(start_screen[0]), int(start_screen[1]))
        screen.blit(b_text, b_rect)

        # "E" for endpoint
        e_text = font.render("E", True, WHITE)
        e_rect = e_text.get_rect()
        e_rect.center = (int(end_screen[0]), int(end_screen[1]))
        screen.blit(e_text, e_rect)


def draw_bone_hierarchy_connections(screen, viewport_manager, bones, animated_transforms=None):
    """Draw hierarchy connections between bones with attachment point awareness"""
    for bone_name, bone in bones.items():
        if bone.parent and bone.parent in bones:
            parent_bone = bones[bone.parent]

            # NEW: Get attachment point
            attachment_point = getattr(bone, 'parent_attachment_point', AttachmentPoint.END)

            if animated_transforms:
                parent_transform = animated_transforms.get(bone.parent)
                child_transform = animated_transforms.get(bone_name)

                if parent_transform and child_transform:
                    parent_x, parent_y, parent_rot, _ = parent_transform
                    child_x, child_y, _, _ = child_transform

                    # NEW: Choose attachment point
                    if attachment_point == AttachmentPoint.END:
                        parent_attach_x = parent_x + parent_bone.length * math.cos(math.radians(parent_rot))
                        parent_attach_y = parent_y + parent_bone.length * math.sin(math.radians(parent_rot))
                    else:  # START
                        parent_attach_x = parent_x
                        parent_attach_y = parent_y

                    parent_attach_screen = viewport_manager.viewport_to_screen((parent_attach_x, parent_attach_y))
                    child_start_screen = viewport_manager.viewport_to_screen((child_x, child_y))
            else:
                # NEW: Choose attachment point for static bones
                if attachment_point == AttachmentPoint.END:
                    parent_attach_x = parent_bone.x + parent_bone.length * math.cos(math.radians(parent_bone.angle))
                    parent_attach_y = parent_bone.y + parent_bone.length * math.sin(math.radians(parent_bone.angle))
                else:  # START
                    parent_attach_x = parent_bone.x
                    parent_attach_y = parent_bone.y

                parent_attach_screen = viewport_manager.viewport_to_screen((parent_attach_x, parent_attach_y))
                child_start_screen = viewport_manager.viewport_to_screen((bone.x, bone.y))

            # NEW: Different connection colors based on attachment point
            if attachment_point == AttachmentPoint.END:
                connection_color = (100, 100, 100)  # Gray for end attachment
            else:
                connection_color = (150, 100, 150)  # Purple for start attachment

            pygame.draw.line(screen, connection_color, parent_attach_screen, child_start_screen, 2)


def draw_bones_by_layer_order(screen, viewport_manager, bones, selected_bone=None, animated_transforms=None, font=None):
    """Draw bones grouped by layer and ordered by layer_order within each layer"""
    # Group bones by layer
    layered_bones = {
        BoneLayer.BEHIND: [],
        BoneLayer.MIDDLE: [],
        BoneLayer.FRONT: []
    }

    for bone_name, bone in bones.items():
        layer = getattr(bone, 'layer', BoneLayer.MIDDLE)
        layer_order = getattr(bone, 'layer_order', 0)
        layered_bones[layer].append((layer_order, bone_name, bone))

    # Sort each layer by layer_order
    for layer in layered_bones:
        layered_bones[layer].sort(key=lambda x: x[0])

    # Draw in layer order: BEHIND -> MIDDLE -> FRONT
    for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
        for layer_order, bone_name, bone in layered_bones[layer]:
            selected = (bone_name == selected_bone)

            if animated_transforms and bone_name in animated_transforms:
                draw_bone(screen, viewport_manager, bone, selected=selected,
                          animated_transform=animated_transforms[bone_name], font=font)
            else:
                draw_bone(screen, viewport_manager, bone, selected=selected, font=font)


# Functions for enhanced bone selection with very limited buffer
def get_all_bones_at_position(bones, pos, viewport_zoom, tolerance=5):
    """Find ALL bones at viewport position, sorted by priority (end > start > body)"""
    x, y = pos
    # Much smaller tolerance for very limited buffer
    adjusted_tolerance = max(3, int(tolerance / max(1, viewport_zoom)))  # Tighter tolerance

    found_bones = []

    for bone_name, bone in bones.items():
        end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
        end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

        # Check end point (highest priority) - REMOVED elif to check ALL
        if math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2) < adjusted_tolerance:
            found_bones.append((bone_name, "end", 0))  # Priority 0 = highest

        # Check start point (medium priority) - NOW checks independently
        if math.sqrt((x - bone.x) ** 2 + (y - bone.y) ** 2) < adjusted_tolerance:
            found_bones.append((bone_name, "start", 1))  # Priority 1 = medium

        # Check body (lowest priority) - Only if not already found endpoint/startpoint
        # Use slightly smaller tolerance for body to avoid accidental selection
        body_tolerance = adjusted_tolerance * 0.7
        dist = _point_to_line_distance((x, y), (bone.x, bone.y), (end_x, end_y))
        if dist < body_tolerance:
            # Don't add body selection if we already have end or start for this bone
            bone_already_found = any(found[0] == bone_name for found in found_bones)
            if not bone_already_found:
                found_bones.append((bone_name, "body", 2))  # Priority 2 = lowest

    # Sort by priority (lower number = higher priority), then by bone name for consistency
    found_bones.sort(key=lambda x: (x[2], x[0]))
    return found_bones


def get_attachment_point_at_position(bones, pos, viewport_zoom, tolerance=4):
    """Find attachment point (start or end) at position and return (bone_name, attachment_point)
    Very tight tolerance for precise selection"""
    x, y = pos
    adjusted_tolerance = max(2, int(tolerance / max(1, viewport_zoom)))  # Very tight

    for bone_name, bone in bones.items():
        end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
        end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

        # Check end point first
        if math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2) < adjusted_tolerance:
            return bone_name, AttachmentPoint.END

        # Check start point
        if math.sqrt((x - bone.x) ** 2 + (y - bone.y) ** 2) < adjusted_tolerance:
            return bone_name, AttachmentPoint.START

    return None, None


# Keep existing functions for backward compatibility
def get_bone_at_position(bones, pos, viewport_zoom, tolerance=5):
    """Find bone at viewport position with very limited buffer"""
    found_bones = get_all_bones_at_position(bones, pos, viewport_zoom, tolerance)
    return found_bones[0][0] if found_bones else None


def get_bone_start_at_position(bones, pos, viewport_zoom, tolerance=4):
    """Find bone start point at position with tight tolerance"""
    x, y = pos
    adjusted_tolerance = max(2, int(tolerance / max(1, viewport_zoom)))

    for name, bone in bones.items():
        if math.sqrt((x - bone.x) ** 2 + (y - bone.y) ** 2) < adjusted_tolerance:
            return name
    return None


def get_bone_end_at_position(bones, pos, viewport_zoom, tolerance=4):
    """Find bone end point at position with tight tolerance"""
    x, y = pos
    adjusted_tolerance = max(2, int(tolerance / max(1, viewport_zoom)))

    for name, bone in bones.items():
        end_x = bone.x + bone.length * math.cos(math.radians(bone.angle))
        end_y = bone.y + bone.length * math.sin(math.radians(bone.angle))

        if math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2) < adjusted_tolerance:
            return name
    return None
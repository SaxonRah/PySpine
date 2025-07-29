"""
PySpine PyGame Loader
A simple but complete loader for PySpine animation data in PyGame.
---

# Simple Loader Usage
loader = PySpineLoader()
loader.load_attachment_config("sprite_attachment_config.json")  # Complete config
loader.load_animation("bone_animation.json")  # Animation data
loader.play()

# Render loop
while running:
    loader.update(dt)
    loader.render(screen, (400, 300))  # Center character on screen
    pygame.display.flip()
"""

import pygame
import json
import math
import os
from typing import Dict, List, Tuple, Any, Optional
from enum import Enum

# Initialize PyGame
pygame.init()


class AttachmentPoint(Enum):
    START = "start"
    END = "end"


class BoneLayer(Enum):
    BEHIND = "behind"
    MIDDLE = "middle"
    FRONT = "front"


class InterpolationType(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    BEZIER = "bezier"


class PySpineSprite:
    """Represents a sprite definition from the sprite sheet"""

    def __init__(self, data: Dict[str, Any]):
        self.name = data["name"]
        self.x = int(data["x"])
        self.y = int(data["y"])
        self.width = int(data["width"])
        self.height = int(data["height"])
        self.origin_x = float(data.get("origin_x", 0.5))
        self.origin_y = float(data.get("origin_y", 0.5))
        self.surface: Optional[pygame.Surface] = None  # Will be set when sprite sheet is loaded


class PySpineBone:
    """Represents a bone in the skeleton"""

    def __init__(self, data: Dict[str, Any]):
        self.name = data["name"]
        self.x = float(data["x"])
        self.y = float(data["y"])
        self.length = float(data["length"])
        self.angle = float(data["angle"])
        self.parent = data.get("parent")
        self.parent_attachment_point = AttachmentPoint(data.get("parent_attachment_point", "end"))
        self.children = data.get("children", [])
        self.layer = BoneLayer(data.get("layer", "middle"))
        self.layer_order = int(data.get("layer_order", 0))

        # Runtime transform (will be calculated during animation)
        self.world_x = self.x
        self.world_y = self.y
        self.world_rotation = self.angle
        self.world_scale = 1.0


class PySpineSpriteInstance:
    """Represents a sprite instance attached to a bone"""

    def __init__(self, data: Dict[str, Any]):
        self.id = data["id"]
        self.sprite_name = data["sprite_name"]
        self.bone_name = data.get("bone_name")
        self.offset_x = float(data.get("offset_x", 0.0))
        self.offset_y = float(data.get("offset_y", 0.0))
        self.offset_rotation = float(data.get("offset_rotation", 0.0))
        self.scale = float(data.get("scale", 1.0))
        self.bone_attachment_point = AttachmentPoint(data.get("bone_attachment_point", "start"))


class PySpineTransform:
    """Animation transform data"""

    def __init__(self, data: Dict[str, Any]):
        self.x = float(data.get("x", 0.0))
        self.y = float(data.get("y", 0.0))
        self.rotation = float(data.get("rotation", 0.0))
        self.scale = float(data.get("scale", 1.0))


class PySpineKeyframe:
    """Animation keyframe"""

    def __init__(self, data: Dict[str, Any]):
        self.time = float(data["time"])
        self.transform = PySpineTransform(data["transform"])
        self.interpolation = InterpolationType(data.get("interpolation", "linear"))
        self.sprite_instance_id = data.get("sprite_instance_id")


class PySpineAnimationTrack:
    """Animation track for a single bone"""

    def __init__(self, keyframes_data: List[Dict[str, Any]]):
        self.keyframes = [PySpineKeyframe(kf) for kf in keyframes_data]
        self.keyframes.sort(key=lambda kf: kf.time)  # Ensure sorted by time

    def get_transform_at_time(self, time: float) -> PySpineTransform:
        """Get interpolated transform at specific time"""
        if not self.keyframes:
            return PySpineTransform({})

        if time <= self.keyframes[0].time:
            return self.keyframes[0].transform

        if time >= self.keyframes[-1].time:
            return self.keyframes[-1].transform

        # Find keyframes to interpolate between
        for i in range(len(self.keyframes) - 1):
            kf1 = self.keyframes[i]
            kf2 = self.keyframes[i + 1]

            if kf1.time <= time <= kf2.time:
                t = (time - kf1.time) / (kf2.time - kf1.time)
                return self._interpolate_transforms(kf1, kf2, t)

        return PySpineTransform({})

    @staticmethod
    def _interpolate_transforms(kf1: PySpineKeyframe, kf2: PySpineKeyframe, t: float) -> PySpineTransform:
        """Apply easing curve and interpolate between transforms"""
        # Apply easing based on kf1's interpolation type
        if kf1.interpolation == InterpolationType.EASE_IN:
            t = t * t * t  # Cubic ease in
        elif kf1.interpolation == InterpolationType.EASE_OUT:
            t = 1 - (1 - t) * (1 - t) * (1 - t)  # Cubic ease out
        elif kf1.interpolation == InterpolationType.EASE_IN_OUT:
            if t < 0.5:
                t = 4 * t * t * t
            else:
                t = 1 - pow(-2 * t + 2, 3) / 2
        elif kf1.interpolation == InterpolationType.BEZIER:
            t = t * t * (3.0 - 2.0 * t)  # Smooth step

        # Linear interpolation with applied easing
        return PySpineTransform({
            "x": kf1.transform.x + (kf2.transform.x - kf1.transform.x) * t,
            "y": kf1.transform.y + (kf2.transform.y - kf1.transform.y) * t,
            "rotation": kf1.transform.rotation + (kf2.transform.rotation - kf1.transform.rotation) * t,
            "scale": kf1.transform.scale + (kf2.transform.scale - kf1.transform.scale) * t
        })


class PySpineLoader:
    """Main PySpine loader class"""

    def __init__(self):
        self.sprite_sheet: Optional[pygame.Surface] = None
        self.sprite_sheet_path: str = ""
        self.sprites: Dict[str, PySpineSprite] = {}
        self.bones: Dict[str, PySpineBone] = {}
        self.sprite_instances: Dict[str, PySpineSpriteInstance] = {}
        self.animation_tracks: Dict[str, PySpineAnimationTrack] = {}
        self.original_bone_positions: Dict[str, Tuple[float, float, float]] = {}

        # Animation properties
        self.duration = 5.0
        self.fps = 30
        self.current_time = 0.0
        self.playing = False

    def _extract_sprite_surface(self, sprite: PySpineSprite) -> bool:
        """Extract sprite surface from sprite sheet with proper error handling"""
        if not self.sprite_sheet:
            print(f"Warning: No sprite sheet loaded for sprite {sprite.name}")
            return False

        sheet_width, sheet_height = self.sprite_sheet.get_size()

        # Check bounds
        if (sprite.x < 0 or sprite.y < 0 or
                sprite.x + sprite.width > sheet_width or
                sprite.y + sprite.height > sheet_height or
                sprite.width <= 0 or sprite.height <= 0):
            print(f"Warning: Sprite {sprite.name} bounds ({sprite.x}, {sprite.y}, {sprite.width}, {sprite.height}) "
                  f"are outside sprite sheet bounds (0, 0, {sheet_width}, {sheet_height})")
            return False

        try:
            sprite.surface = self.sprite_sheet.subsurface(
                (sprite.x, sprite.y, sprite.width, sprite.height)
            ).convert_alpha()
            print(
                f"Successfully extracted sprite {sprite.name}: {sprite.width}x{sprite.height} at ({sprite.x}, {sprite.y})")
            return True
        except pygame.error as e:
            print(f"Error extracting sprite {sprite.name}: {e}")
            return False

    def load_sprite_project(self, filename: str) -> bool:
        """Load sprite definitions and sprite sheet"""
        try:
            print(f"Loading sprite project from: {filename}")
            with open(filename, 'r') as f:
                data = json.load(f)

            # Load sprite sheet
            sprite_sheet_path = data.get("sprite_sheet_path", "")
            if sprite_sheet_path and os.path.exists(sprite_sheet_path):
                print(f"Loading sprite sheet: {sprite_sheet_path}")
                self.sprite_sheet = pygame.image.load(sprite_sheet_path).convert_alpha()
                self.sprite_sheet_path = sprite_sheet_path
                print(f"Sprite sheet loaded: {self.sprite_sheet.get_size()}")
            else:
                print(f"Warning: Sprite sheet not found: {sprite_sheet_path}")

            # Load sprite definitions
            self.sprites = {}
            successful_sprites = 0
            for name, sprite_data in data.get("sprites", {}).items():
                sprite = PySpineSprite(sprite_data)
                self.sprites[name] = sprite

                # Extract sprite surface from sheet
                if self._extract_sprite_surface(sprite):
                    successful_sprites += 1

            print(f"Loaded {len(self.sprites)} sprite definitions, {successful_sprites} extracted successfully")
            return True

        except Exception as e:
            print(f"Error loading sprite project: {e}")
            return False

    def load_bone_project(self, filename: str) -> bool:
        """Load bone hierarchy"""
        try:
            print(f"Loading bone project from: {filename}")
            with open(filename, 'r') as f:
                data = json.load(f)

            self.bones = {}
            for name, bone_data in data.get("bones", {}).items():
                self.bones[name] = PySpineBone(bone_data)

            print(f"Loaded {len(self.bones)} bones from {filename}")
            return True

        except Exception as e:
            print(f"Error loading bone project: {e}")
            return False

    def load_attachment_config(self, filename: str) -> bool:
        """Load complete attachment configuration"""
        try:
            print(f"Loading attachment config from: {filename}")
            with open(filename, 'r') as f:
                data = json.load(f)

            # Load sprites if not already loaded
            if not self.sprites:
                sprite_sheet_path = data.get("sprite_sheet_path", "")
                if sprite_sheet_path and os.path.exists(sprite_sheet_path):
                    print(f"Loading sprite sheet: {sprite_sheet_path}")
                    self.sprite_sheet = pygame.image.load(sprite_sheet_path).convert_alpha()
                    self.sprite_sheet_path = sprite_sheet_path
                    print(f"Sprite sheet loaded: {self.sprite_sheet.get_size()}")

                successful_sprites = 0
                for name, sprite_data in data.get("sprites", {}).items():
                    sprite = PySpineSprite(sprite_data)
                    self.sprites[name] = sprite
                    if self._extract_sprite_surface(sprite):
                        successful_sprites += 1

                print(f"Loaded {len(self.sprites)} sprite definitions, {successful_sprites} extracted successfully")

            # Load bones if not already loaded
            if not self.bones:
                for name, bone_data in data.get("bones", {}).items():
                    self.bones[name] = PySpineBone(bone_data)
                print(f"Loaded {len(self.bones)} bones")

            # Load sprite instances
            self.sprite_instances = {}
            for instance_id, instance_data in data.get("sprite_instances", {}).items():
                instance = PySpineSpriteInstance(instance_data)
                self.sprite_instances[instance_id] = instance
                print(f"Loaded sprite instance: {instance_id} ({instance.sprite_name} -> {instance.bone_name})")

            print(f"Loaded attachment config: {len(self.sprite_instances)} sprite instances")
            return True

        except Exception as e:
            print(f"Error loading attachment config: {e}")
            return False

    def load_animation(self, filename: str) -> bool:
        """Load animation data"""
        try:
            print(f"Loading animation from: {filename}")
            with open(filename, 'r') as f:
                data = json.load(f)

            self.duration = float(data.get("duration", 5.0))
            self.fps = int(data.get("fps", 30))
            self.original_bone_positions = data.get("original_bone_positions", {})

            # Load sprite instances if included
            for instance_id, instance_data in data.get("sprite_instances", {}).items():
                if instance_id not in self.sprite_instances:
                    self.sprite_instances[instance_id] = PySpineSpriteInstance(instance_data)

            # Load animation tracks
            self.animation_tracks = {}
            total_keyframes = 0
            for bone_name, track_data in data.get("bone_tracks", {}).items():
                track = PySpineAnimationTrack(track_data["keyframes"])
                self.animation_tracks[bone_name] = track
                total_keyframes += len(track.keyframes)
                print(f"Loaded animation track for {bone_name}: {len(track.keyframes)} keyframes")

            print(f"Loaded animation: {len(self.animation_tracks)} tracks, {total_keyframes} total keyframes")
            print(f"Duration: {self.duration}s, FPS: {self.fps}")
            return True

        except Exception as e:
            print(f"Error loading animation: {e}")
            return False

    def update(self, dt: float):
        """Update animation time"""
        if self.playing:
            self.current_time += dt
            if self.current_time >= self.duration:
                self.current_time = 0.0  # Loop animation

        # Update bone transforms
        self._update_bone_transforms()

    def _update_bone_transforms(self):
        """Calculate world transforms for all bones based on current animation time"""
        # Process bones in hierarchy order to ensure parents are calculated before children
        processed = set()

        def process_bone(given_bone_name: str):
            if given_bone_name in processed or given_bone_name not in self.bones:
                return

            bone = self.bones[given_bone_name]

            # Process parent first
            if bone.parent and bone.parent not in processed:
                process_bone(bone.parent)

            # Get original position
            if given_bone_name in self.original_bone_positions:
                orig_x, orig_y, orig_angle = self.original_bone_positions[given_bone_name]
            else:
                orig_x, orig_y, orig_angle = bone.x, bone.y, bone.angle

            # Get animation transform
            anim_transform = PySpineTransform({})
            if given_bone_name in self.animation_tracks:
                anim_transform = self.animation_tracks[given_bone_name].get_transform_at_time(self.current_time)

            if bone.parent and bone.parent in self.bones:
                # Child bone - calculate relative to parent
                parent_bone = self.bones[bone.parent]

                # Get parent attachment point
                if bone.parent_attachment_point == AttachmentPoint.END:
                    parent_attach_x = parent_bone.world_x + parent_bone.length * math.cos(
                        math.radians(parent_bone.world_rotation))
                    parent_attach_y = parent_bone.world_y + parent_bone.length * math.sin(
                        math.radians(parent_bone.world_rotation))
                else:  # START
                    parent_attach_x = parent_bone.world_x
                    parent_attach_y = parent_bone.world_y

                # Apply animation offset (rotated by parent rotation)
                if anim_transform.x != 0 or anim_transform.y != 0:
                    parent_angle_rad = math.radians(parent_bone.world_rotation)
                    rotated_x = (anim_transform.x * math.cos(parent_angle_rad) -
                                 anim_transform.y * math.sin(parent_angle_rad))
                    rotated_y = (anim_transform.x * math.sin(parent_angle_rad) +
                                 anim_transform.y * math.cos(parent_angle_rad))

                    bone.world_x = parent_attach_x + rotated_x
                    bone.world_y = parent_attach_y + rotated_y
                else:
                    bone.world_x = parent_attach_x
                    bone.world_y = parent_attach_y

                bone.world_rotation = orig_angle + anim_transform.rotation
                bone.world_scale = max(0.1, anim_transform.scale) if anim_transform.scale != 0 else 1.0
            else:
                # Root bone - use original position + animation
                bone.world_x = orig_x + anim_transform.x
                bone.world_y = orig_y + anim_transform.y
                bone.world_rotation = orig_angle + anim_transform.rotation
                bone.world_scale = max(0.1, anim_transform.scale) if anim_transform.scale != 0 else 1.0

            processed.add(given_bone_name)

        # Process all bones
        for bone_name in self.bones.keys():
            process_bone(bone_name)

    def get_sprite_world_position(self, instance_id: str) -> tuple[float | Any, float | Any, float | Any] | None:
        """Get world position and rotation for a sprite instance"""
        if instance_id not in self.sprite_instances:
            return None

        instance = self.sprite_instances[instance_id]
        if not instance.bone_name or instance.bone_name not in self.bones:
            return None

        bone = self.bones[instance.bone_name]

        # Calculate bone attachment point
        if instance.bone_attachment_point == AttachmentPoint.END:
            attach_x = bone.world_x + bone.length * math.cos(math.radians(bone.world_rotation))
            attach_y = bone.world_y + bone.length * math.sin(math.radians(bone.world_rotation))
        else:  # START
            attach_x = bone.world_x
            attach_y = bone.world_y

        # Apply sprite offset (rotated by bone rotation)
        bone_rot_rad = math.radians(bone.world_rotation)
        rotated_offset_x = (instance.offset_x * math.cos(bone_rot_rad) -
                            instance.offset_y * math.sin(bone_rot_rad))
        rotated_offset_y = (instance.offset_x * math.sin(bone_rot_rad) +
                            instance.offset_y * math.cos(bone_rot_rad))

        sprite_x = attach_x + rotated_offset_x
        sprite_y = attach_y + rotated_offset_y

        # FIX: Calculate rotation like the PySpine editors do
        # Get the original bone angle
        if instance.bone_name in self.original_bone_positions:
            _, _, original_bone_angle = self.original_bone_positions[instance.bone_name]
        else:
            original_bone_angle = bone.angle  # Fallback to current angle

        # Calculate animation rotation delta (how much the bone has rotated from original)
        animation_rotation_delta = bone.world_rotation - original_bone_angle

        # Sprite rotation = base offset + animation delta
        sprite_rotation = instance.offset_rotation + animation_rotation_delta

        return sprite_x, sprite_y, sprite_rotation

    def render(self, screen: pygame.Surface, offset: Tuple[float, float] = (0, 0)):
        """Render the complete animated character"""
        rendered_count = 0

        # Group sprites by bone layer for proper rendering order
        layered_sprites = {
            BoneLayer.BEHIND: [],
            BoneLayer.MIDDLE: [],
            BoneLayer.FRONT: []
        }

        for instance_id, instance in self.sprite_instances.items():
            if instance.bone_name and instance.bone_name in self.bones:
                bone = self.bones[instance.bone_name]
                layer = bone.layer
                layer_order = bone.layer_order
                layered_sprites[layer].append((layer_order, instance_id, instance))

        # Sort each layer by layer_order
        for layer in layered_sprites:
            layered_sprites[layer].sort(key=lambda x: x[0])

        # Render in layer order: BEHIND -> MIDDLE -> FRONT
        for layer in [BoneLayer.BEHIND, BoneLayer.MIDDLE, BoneLayer.FRONT]:
            for layer_order, instance_id, instance in layered_sprites[layer]:
                if self._render_sprite_instance(screen, instance_id, instance, offset):
                    rendered_count += 1

        # Debug info
        if rendered_count == 0:
            print("Warning: No sprites were rendered!")

        return rendered_count

    def _render_sprite_instance(self, screen: pygame.Surface, instance_id: str,
                                instance: PySpineSpriteInstance, offset: Tuple[float, float]) -> bool:
        """Render a single sprite instance"""
        if instance.sprite_name not in self.sprites:
            print(f"Warning: Sprite {instance.sprite_name} not found for instance {instance_id}")
            return False

        sprite = self.sprites[instance.sprite_name]
        if not sprite.surface:
            print(f"Warning: Sprite {sprite.name} has no surface for instance {instance_id}")
            return False

        # Get world position and rotation
        transform = self.get_sprite_world_position(instance_id)
        if not transform:
            print(f"Warning: Could not get transform for sprite instance {instance_id}")
            return False

        sprite_x, sprite_y, sprite_rotation = transform
        offset_x, offset_y = offset

        # Calculate final scale
        bone_scale = 1.0
        if instance.bone_name and instance.bone_name in self.bones:
            bone_scale = self.bones[instance.bone_name].world_scale
        final_scale = bone_scale * instance.scale

        # Scale sprite surface
        if abs(final_scale - 1.0) > 0.01:  # Only scale if significantly different
            scaled_width = max(1, int(sprite.width * final_scale))
            scaled_height = max(1, int(sprite.height * final_scale))
            try:
                scaled_surface = pygame.transform.scale(sprite.surface, (scaled_width, scaled_height))
            except pygame.error as e:
                print(f"Error scaling sprite {sprite.name}: {e}")
                return False
        else:
            scaled_surface = sprite.surface
            scaled_width = sprite.width
            scaled_height = sprite.height

        # Rotate sprite surface
        if abs(sprite_rotation) > 0.01:
            try:
                rotated_surface = pygame.transform.rotate(scaled_surface, -sprite_rotation)
            except pygame.error as e:
                print(f"Error rotating sprite {sprite.name}: {e}")
                return False
        else:
            rotated_surface = scaled_surface

        # Calculate origin offset in the final surface
        origin_offset_x = scaled_width * sprite.origin_x
        origin_offset_y = scaled_height * sprite.origin_y

        # Calculate final position (accounting for rotation center change)
        final_rect = rotated_surface.get_rect()
        if abs(sprite_rotation) > 0.01:
            # Rotation changes the center, so we need to adjust
            old_center = (scaled_width / 2, scaled_height / 2)
            new_center = (final_rect.width / 2, final_rect.height / 2)

            # The sprite's origin in the rotated surface
            cos_r = math.cos(math.radians(-sprite_rotation))
            sin_r = math.sin(math.radians(-sprite_rotation))

            # Transform origin point through rotation
            rotated_origin_x = (origin_offset_x - old_center[0]) * cos_r - (origin_offset_y - old_center[1]) * sin_r + \
                               new_center[0]
            rotated_origin_y = (origin_offset_x - old_center[0]) * sin_r + (origin_offset_y - old_center[1]) * cos_r + \
                               new_center[1]

            final_x = sprite_x + offset_x - rotated_origin_x
            final_y = sprite_y + offset_y - rotated_origin_y
        else:
            final_x = sprite_x + offset_x - origin_offset_x
            final_y = sprite_y + offset_y - origin_offset_y

        # Draw the sprite
        try:
            screen.blit(rotated_surface, (int(final_x), int(final_y)))
            return True
        except pygame.error as e:
            print(f"Error rendering sprite {sprite.name}: {e}")
            return False

    def render_skeleton(self, screen: pygame.Surface, offset: Tuple[float, float] = (0, 0),
                        color: Tuple[int, int, int] = (255, 255, 255), alpha: int = 128):
        """Render the skeleton with transparency"""
        # Create a transparent surface
        skeleton_surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)

        offset_x, offset_y = offset
        for bone in self.bones.values():
            start_x = bone.world_x + offset_x
            start_y = bone.world_y + offset_y
            end_x = start_x + bone.length * math.cos(math.radians(bone.world_rotation))
            end_y = start_y + bone.length * math.sin(math.radians(bone.world_rotation))

            # Draw with alpha
            bone_color = (*color, alpha)
            pygame.draw.line(skeleton_surface, bone_color, (int(start_x), int(start_y)), (int(end_x), int(end_y)), 2)
            pygame.draw.circle(skeleton_surface, bone_color, (int(start_x), int(start_y)), 4)
            pygame.draw.circle(skeleton_surface, bone_color, (int(end_x), int(end_y)), 4)

        screen.blit(skeleton_surface, (0, 0))

    def play(self):
        """Start animation playback"""
        self.playing = True

    def pause(self):
        """Pause animation playback"""
        self.playing = False

    def stop(self):
        """Stop animation and reset to beginning"""
        self.playing = False
        self.current_time = 0.0

    def set_time(self, time: float):
        """Set animation time directly"""
        self.current_time = max(0, int(min(self.duration, time)))

    def debug_info(self):
        """Print debug information about loaded data"""
        print(f"\n=== PySpine Loader Debug Info ===")
        print(
            f"Sprite sheet: {self.sprite_sheet_path} ({self.sprite_sheet.get_size() if self.sprite_sheet else 'None'})")
        print(f"Sprites: {len(self.sprites)}")
        for name, sprite in self.sprites.items():
            surface_status = "OK" if sprite.surface else "MISSING"
            print(f"  {name}: {sprite.width}x{sprite.height} at ({sprite.x},{sprite.y}) - Surface: {surface_status}")

        print(f"Bones: {len(self.bones)}")
        for name, bone in self.bones.items():
            print(f"  {name}: pos=({bone.world_x:.1f},{bone.world_y:.1f}) rot={bone.world_rotation:.1f}")

        print(f"Sprite instances: {len(self.sprite_instances)}")
        for instance_id, instance in self.sprite_instances.items():
            print(f"  {instance_id}: {instance.sprite_name} -> {instance.bone_name}")

        print(f"Animation tracks: {len(self.animation_tracks)}")
        print(f"Animation: {self.current_time:.2f}s / {self.duration:.2f}s")


# Example usage
def main():
    """Example of how to use the PySpine loader"""

    # Initialize PyGame
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("PySpine Loader Example")
    clock = pygame.time.Clock()

    # Create loader
    loader = PySpineLoader()

    # Load PySpine data (try different loading strategies)
    # attachment_config_file = "../../pyspine/sprite_attachment_config.json"
    attachment_config_file = "sprite_attachment_config.json"
    if os.path.exists(attachment_config_file):
        # Load complete attachment config (includes sprites, bones, and attachments)
        loader.load_attachment_config(attachment_config_file)
    else:
        # Load individual files
        # sprite_file = "../../pyspine/sprite_project.json"
        # bone_file = "../../pyspine/bone_project.json"
        sprite_file = "sprite_project.json"
        bone_file = "bone_project.json"

        if os.path.exists(sprite_file):
            loader.load_sprite_project(sprite_file)
        if os.path.exists(bone_file):
            loader.load_bone_project(bone_file)

    # Load animation if available
    # bone_animation_file = "../../pyspine/bone_animation.json"
    bone_animation_file = "bone_animation.json"
    if os.path.exists(bone_animation_file):
        loader.load_animation(bone_animation_file)

    # Start animation
    loader.play()

    # Main loop
    running = True
    show_skeleton = False
    while running:
        dt = clock.tick(60) / 1000.0  # Delta time in seconds

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    if loader.playing:
                        loader.pause()
                    else:
                        loader.play()
                elif event.key == pygame.K_r:
                    loader.stop()
                elif event.key == pygame.K_s:
                    show_skeleton = not show_skeleton

        # Update animation
        loader.update(dt)

        # Clear screen
        screen.fill((64, 64, 64))

        # Render character (centered on screen)
        loader.render(screen, (400, 300))

        if show_skeleton:
            loader.render_skeleton(screen, (400, 300), (0, 255, 0))

        # Show animation info
        info_text = f"Time: {loader.current_time:.2f}s / {loader.duration:.2f}s"
        if loader.playing:
            info_text += " (Playing)"
        else:
            info_text += " (Paused)"

        font = pygame.font.Font(None, 36)
        text_surface = font.render(info_text, True, (255, 255, 255))
        screen.blit(text_surface, (10, 10))

        controls_text = "SPACE: Play/Pause, R: Reset, S: Show Skeleton"
        control_surface = font.render(controls_text, True, (200, 200, 200))
        screen.blit(control_surface, (10, 50))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()

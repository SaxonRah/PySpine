## **Priority Features to Add**

### 1. **Inverse and Forward Kinematics (IK/FK)**
IK/FK are standard features in professional animation tools that would greatly enhance usability:

**Forward Kinematics (FK)** - Already implemented in `get_bone_world_transform()` method. This calculates child bone positions based on parent transforms, which is exactly FK.

**Inverse Kinematics (IK)** - The missing piece that would let animators position end-effectors (like hands/feet) and automatically solve for the joint rotations:

```python
# Add to animation editor
class IKChain:
    def __init__(self, bones, target_pos):
        self.bones = bones  # List of bone names from root to end-effector
        self.target_pos = target_pos
        self.fk_solver = self.project  # Use existing FK system
    
    def solve_two_bone_ik(self, bone1_name, bone2_name, target_pos):
        """Solve 2-bone IK (shoulder->elbow->hand or hip->knee->foot)"""
        bone1 = self.project.bones[bone1_name]
        bone2 = self.project.bones[bone2_name]
        
        # Get current FK positions
        bone1_world = self.fk_solver.get_bone_world_transform(bone1_name, self.project.current_time)
        
        # IK math to find required joint angles
        # ... implement FABRIK or analytical 2-bone IK
        
        # Create keyframes with solved rotations
        return solved_transforms
    
    def toggle_ik_fk_mode(self, bone_chain):
        """Switch between IK and FK control for a bone chain"""
        # IK mode: drag end-effector, solve for joint rotations
        # FK mode: directly rotate individual joints (current behavior)
```

This would allow animators to:
- **FK Mode**: Rotate individual bones (current workflow)
- **IK Mode**: Drag hands/feet to positions, auto-solve joint angles
- **Seamless switching** between modes during animation

### 2. **Animation Curves/Graph Editor**
Visual curve editing for fine-tuning interpolation between keyframes.

### 3. **Onion Skinning**
Show previous/next frames as ghost images for better animation timing.

### 4. **Export System**
```python
class PySpineExporter:
    def export_to_spine_json(self):  # Spine format compatibility
    def export_to_spritesheet(self):  # Baked animation frames
    def export_to_gif(self):         # Preview animations
```

### 5. **Sprite Swapping**
Timeline-based sprite changes for things like facial expressions.

---

## **Quality of Life Features**

### 1. **Auto-Keyframing**
Automatically create keyframes when manipulating bones during playback.

### 2. **Animation Layers**
Allow multiple animation layers for additive animations.

### 3. **Bone Constraints**
```python
class BoneConstraint:
    def __init__(self, bone_name, constraint_type):
        self.bone_name = bone_name
        self.type = constraint_type  # LOOK_AT, LIMIT_ROTATION, etc.
```

---

## **Technical Improvements**

### 1. **Performance Optimizations**
```python
# Cache bone world transforms during animation playback
class AnimationCache:
    def __init__(self):
        self.cached_transforms = {}
        self.cache_frame = -1
    
    def get_cached_transform(self, bone_name, time):
        frame = int(time * self.fps)
        if frame != self.cache_frame:
            self.cached_transforms.clear()
            self.cache_frame = frame
        # Return cached or calculate
```

### 2. **Memory Management**
The deep copying in undo commands could be optimized:
```python
# Use weak references for large data structures
import weakref

class OptimizedCommand(UndoRedoCommand):
    def __init__(self, target_ref, changes_only):
        self.target_ref = weakref.ref(target_ref)
        self.changes = changes_only  # Only store diffs
```

---

## **File Format Enhancements**

### 1. **Version Management**
```json
{
  "format_version": "1.0",
  "pyspine_version": "0.1",
  "data": { ... }
}
```

### 2. **Asset References**
Support relative paths and asset libraries.

### 3. **File Dialogues**
Add support for selection of files instead of relying on hardcoded filenames.

## **Architecture Suggestions**

### 1. **Plugin System**
```python
class PySpinePlugin:
    def register_editor(self, editor_class):
    def register_exporter(self, exporter_class):
    def register_importer(self, importer_class):
```

### 2. **Event System**
```python
class EventManager:
    def on_bone_selected(self, bone_name):
    def on_keyframe_created(self, keyframe):
    def on_animation_play(self):
```

---

## **Workflow Improvements**

### 1. **Project Templates**
Pre-made skeletons for common character types (humanoid, quadruped, etc.)

### 2. **Batch Operations**
Select multiple bones/keyframes for simultaneous editing.

### 3. **Timeline Markers**
Add named markers for animation events.

### 4. ** Scrollable Timeline**
Allow timeline longer than 5 seconds. 
Add scrolling up and down of bone layers.

---

## **Advanced Animation Features**

### 1. **Animation Blending**
```python
class AnimationBlender:
    def blend_animations(self, anim1, anim2, blend_factor):
        # Smooth transition between animations
```

### 2. **Motion Paths**
Visualize bone movement trajectories.

### 3. **Physics Integration**
Basic spring/damping for secondary animation.

### 4. **Prefab Animations**
Allow for saved animations to be loaded and or referenced by other animations.

### 4. **Procedural Animations**
Allow for procedural/automagical animations.

---

## **Potential Issues**

### 1. **Edge Case in Bone Selection**
In `get_all_bones_at_position()`, very small bones might be hard to select:
```python
# Add minimum selection area
adjusted_tolerance = max(5, int(tolerance / max(1, viewport_zoom)))  # Ensure minimum 5px
```

### 2. **Animation Time Precision**
Float precision issues with keyframe timing:
```python
# Use epsilon comparison instead of exact equality
EPSILON = 0.001
if abs(kf.time - target_time) < EPSILON:
```

### 3. **Sprite Origin Edge Cases**
```python
# In draw_sprite_with_origin(), handle edge cases
if sprite_rect.width <= 0 or sprite_rect.height <= 0:
    return None  # Prevent division by zero
```

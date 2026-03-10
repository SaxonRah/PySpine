![PySpine Logo](https://github.com/SaxonRah/PySpine/blob/main/images/PySpine_Logo.png "PySpine Logo")

# PySpine - 2D Animation Toolkit [Version 0.3]

**A lightweight boneless 2D animation pipeline built in Python.**

PySpine is an experimental animation system where **sprites themselves act as bones**.
Instead of building a skeleton and attaching images to it, each sprite contains **named attachment points** that define how parts connect.

This makes the animation system:

* simple
* transparent
* fully JSON-based
* easy to debug and extend

The entire pipeline is implemented in **pure Python with Pygame**.

---

# Core Idea

Traditional 2D skeletal animation looks like this:

```
bone skeleton
   ↓
sprite attachments
   ↓
animation
```

PySpine flips the model:

```
sprite
   ↓
attachment points
   ↓
hierarchical assembly
   ↓
animation
```

Sprites **are the bones**.

Each sprite contains connection points that define how it attaches to other sprites.

---

# Example

A simple character might look like this:

```
               head
                 │
               torso
              /     \
   hand_L--arm_L   arm_R--hand_R
              \     /
                hips
              /     \
          leg_L     leg_R
             |       |
           foot_L  foot_R
```

But instead of bones, each of those parts is a **sprite instance** attached at named points.

---

# Pipeline

The toolchain is composed of **three small editors**:

```
Sprite Sheet Editor
        ↓
Assembly Editor
        ↓
Animation Editor
```

All data is stored as **plain JSON files**, making the workflow easy to version and edit.

---

# 1. Sprite Sheet Editor

Define sprites and attachment points.

You load a sprite sheet image and mark:

* sprite rectangles
* named attachment points

Example sprite definition:

```json
{
  "name": "torso",
  "x": 97,
  "y": 8,
  "width": 30,
  "height": 19,
  "attachment_points": [
    {"name": "neck", "x": 0.48, "y": 0.1},
    {"name": "hip", "x": 0.50, "y": 0.9},
    {"name": "shoulder_L", "x": 0.2, "y": 0.35},
    {"name": "shoulder_R", "x": 0.8, "y": 0.35}
  ]
}
```

Attachment points are stored **normalized within the sprite bounds**.


---

# 2. Assembly Editor

The assembly editor builds a **character rig** by attaching sprite instances together.

Each instance:

* references a sprite definition
* has a root transform
* can attach to another instance at named points

Example instance:

```json
{
  "name": "arm_L",
  "sprite_name": "upper_arm",
  "parent": "torso",
  "parent_point": "shoulder_L",
  "self_point": "origin",
  "local_rotation": -45
}
```

Assemblies define the **hierarchical structure of the character**.

The assembly editor UI includes:

* sprite library panel
* viewport with transform controls
* instance hierarchy panel

---

# 3. Animation Editor

The animation editor creates **keyframe animation clips** for assembled characters.

Animations consist of:

```
animation
 ├── instances
 └── tracks
       ├── root_x
       ├── root_y
       ├── rotation
       └── local_rotation
```

Example animation track:

```json
"tracks": {
  "arm_L": {
    "local_rotation": {
      "0": 0,
      "10": -45,
      "20": 10
    }
  }
}
```

Keyframes are stored as frame → value pairs.

---

# Transform Solver

All hierarchy math is handled by a shared solver module.

The solver computes:

* world transforms
* attachment point positions
* hierarchical propagation
* cycle detection
* attachment constraints

Core functions include:

```
get_world_transform()
get_world_point()
detach_instance()
would_cycle()
```

This shared solver allows all editors to behave consistently.

---

# Editor Features

## Sprite Editor

* define sprite rectangles
* add unlimited attachment points
* rename/delete points
* JSON save/load

## Assembly Editor

* create sprite instances
* attach instances via points
* drag to reposition
* rotate around pivots
* duplicate parts
* reorder draw order
* detach / reattach hierarchy

## Animation Editor

* multiple animations
* keyframe timeline
* pose editing in viewport
* interpolated playback
* per-part animation tracks

---

# Controls (Sprite Editor)

```
Ctrl+L              load sprite project
Ctrl+O              load sprite sheet image
Ctrl+S              save sprite project

Left Click          select sprite
Drag                move selected attachment point

A                   add attachment point
Delete              delete selected sprite
Shift+Delete        delete selected attachment point

F2                  rename sprite
Shift+F2            rename attachment point

Tab                 cycle attachment points

Mousewheel          zoom viewport
Space + Drag        pan viewport
```

# Controls (Assembly Editor)

```
Ctrl+L              load sprite project
Ctrl+O              load assembly
Ctrl+S              save assembly

N                   create instance
Shift+click point   attach selected instance
U                   detach instance
F2                  rename instance
Delete              delete instance
Ctrl+D              duplicate instance

PgUp/PgDn           change draw order

Space               pan view
Mousewheel          zoom
```

# Controls (Animation Editor)

```
Ctrl+O              load animation project
Ctrl+S              save animation project

Space               play / pause animation
Mousewheel          zoom timeline
Space + Drag        pan viewport

Left Click          select part
Drag                rotate or move selected part

K                   set keyframe for selected property
Shift+K             delete keyframe

,                   step backward one frame
.                   step forward one frame

<                   jump to previous keyframe
>                   jump to next keyframe

A                   create new animation
F2                  rename animation
Delete              delete animation

C                   clear keys for selected part
```

---

# Basic Workflow Example

Creating and animating a character in PySpine typically follows these steps:

```
sprite sheet
    ↓
define sprites + attachment points
    ↓
assemble character
    ↓
animate keyframes
```

Below is a typical workflow.

---

## 1. Prepare a Sprite Sheet

Create a sprite sheet containing the individual parts of your character.

Example parts:

```
head
torso
upper_arm
lower_arm
hand
upper_leg
lower_leg
foot
```

Each body part should be a **separate sprite region** in the sheet.

---

## 2. Define Sprites

Open the **Sprite Editor** and load the sprite sheet.

For each body part:

1. Draw a rectangle around the sprite
2. Add attachment points where connections should occur

Example torso attachment points:

```
neck
hip
shoulder_L
shoulder_R
```

Example arm attachment points:

```
origin
elbow
```

Attachment points define **how parts connect together later**.

Save the sprite project.

---

## 3. Build the Character Assembly

Open the **Assembly Editor**.

Create sprite instances and attach them together using their attachment points.

Example hierarchy:

```
torso
 ├── head
 ├── arm_L
 │     └── forearm_L
 │           └── hand_L
 └── arm_R
       └── forearm_R
             └── hand_R
```

You attach parts by:

```
Shift + click attachment point
```

This creates the hierarchical structure of the character.

Save the assembly.

---

## 4. Create an Animation

Open the **Animation Editor** and load the assembly.

Create a new animation and set keyframes for parts.

Example walk animation:

```
frame 0     neutral pose
frame 10    left leg forward
frame 20    neutral pose
frame 30    right leg forward
frame 40    neutral pose
```

Keyframes store transformations such as:

```
rotation
root position
local rotation
```

---

## 5. Preview Animation

Press:

```
Space
```

to play the animation.

The solver propagates transformations through the hierarchy so attached parts move naturally.

---

# Summary

The full PySpine workflow looks like this:

```
Sprite Sheet
      ↓
Sprite Editor
      ↓
Assembly Editor
      ↓
Animation Editor
      ↓
Animated Character
```

Because everything is stored as **plain JSON**, projects are easy to:

* version control
* modify externally
* generate procedurally
* integrate into game engines

---

# Project Structure

```
_ps_model.py
    data structures

_ps_solver.py
    hierarchy transform solver

PS_SpriteEditor.py
    sprite + attachment editor

PS_AssemblyEditor.py
    assembly editor

PS_AnimationEditor.py
    animation editor
```

---

# Design Philosophy

PySpine intentionally avoids the complexity of traditional skeletal animation.


### Simplicity

- Sprites act as bones.
- No separate skeleton data structure is required.

---

### Transparency

- All project data is human-readable JSON.
- Nothing is hidden in binary formats.

---

### Modularity

- Editors are separate tools connected through shared data structures.

---

### Extensibility

The system is written in plain Python, making it easy to:

* add exporters
* integrate with engines
* build procedural animation tools
* experiment with new animation ideas

---

# Why Boneless Animation?

Traditional rigs separate:

```
skeleton
mesh
weights
```

For pixel art and sprite animation this is often unnecessary.

PySpine instead uses:

```
sprite → attachment points → hierarchy
```

Which is:

* easier to build
* easier to debug
* easier to serialize

---

# Future Ideas

Possible future improvements:

* mirror posing
* snapping tools
* inverse kinematics
* onion-skin animation
* animation blending
* runtime export formats
* game engine integration

---

# Status

This project is currently an **experimental animation pipeline**.

It already supports:

* sprite definition
* hierarchical character assembly
* keyframe animation

The goal is to explore a **minimal but powerful 2D animation workflow** built entirely in Python.

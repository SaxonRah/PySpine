![PySpine Logo](https://github.com/SaxonRah/PySpine/blob/main/PySpine_Logo.png "PySpine Logo")
# PySpine - 2D Skeletal Animation Toolkit [Version 0.1]

A comprehensive Python-based 2D skeletal animation system built with Pygame, featuring multiple specialized editors for creating complete animated characters and objects.

## Features Overview

PySpine consists of four integrated editors that form a complete 2D animation pipeline:

### Sprite Sheet Editor
- **Load and manage sprite sheets** - Import PNG files and extract individual sprites
- **Visual sprite extraction** - Click and drag to define sprite rectangles
- **Precise sprite editing** - Move, resize, and modify sprite boundaries
- **Origin point control** - Set sprite pivot points for proper rotation and attachment
- **Real-time preview** - See changes immediately with zoom and pan support
- **Complete undo/redo system** - Every action is undoable with detailed history

### Bone Editor  
- **Hierarchical bone system** - Create parent-child bone relationships
- **Multi-layer support** - Organize bones in Behind/Middle/Front layers with custom ordering
- **Flexible attachment points** - Bones can attach to parent's start or end points
- **Advanced selection** - Cycle through overlapping elements with visual feedback
- **Drag-and-drop hierarchy** - Reorganize bone relationships through intuitive interface
- **Precise bone manipulation** - Move, rotate, and resize bones with pixel-perfect control

### Sprite Attachment Editor
- **Bone-sprite binding** - Attach sprites to specific bones with visual indicators
- **Attachment point control** - Choose between start/end attachment points on bones
- **Hierarchical drag & drop** - Move sprites between bones with visual drop indicators
- **Real-time positioning** - Adjust sprite offsets and rotations relative to bones
- **Layer-aware rendering** - Sprites render in correct order based on bone layers
- **Selection cycling** - Navigate overlapping sprites and bones efficiently

### Animation Editor
- **Keyframe animation** - Create smooth animations with timeline control
- **Multiple interpolation types** - Linear, Ease In/Out, Bezier curves
- **Dual manipulation modes** - Translation and Rotation modes with visual indicators
- **Real-time playback** - Preview animations with play/pause controls
- **Timeline interaction** - Scrub timeline, move keyframes, adjust timing
- **Bone hierarchy preservation** - Animations respect parent-child relationships

## Workflow

### 1. Sprite Preparation
`PySpine_SpriteSheetEditor.py`
1. Load your sprite sheet (PNG format)
2. Define sprite rectangles by clicking and dragging
3. Set origin points (red dots) for each sprite - these become attachment/rotation points
4. Save the sprite project (`sprite_project.json`)

### 2. Skeleton Creation
`PySpine_BoneEditor.py`
1. Create bones by dragging in the viewport
2. Organize bones into hierarchies (drag in hierarchy panel)
3. Set bone layers (Behind/Middle/Front) for rendering order
4. Configure attachment points (bones can attach to parent's start or end)
5. Save the bone project (`bone_project.json`)

### 3. Sprite Attachment
`PySpine_SpriteAttachmentEditor.py`
1. Load both sprite and bone projects
2. Create sprite instances from the palette
3. Attach sprites to bones using drag-and-drop
4. Adjust sprite positions and rotations relative to bones
5. Save the attachment configuration (`sprite_attachment_config.json`)

### 4. Animation
`PySpine_AnimationEditor.py`
1. Load the attachment configuration
2. Select bones and create keyframes at different times
3. Use Translation mode (W) to animate position
4. Use Rotation mode (E) to animate rotation
5. Set interpolation types for smooth motion
6. Preview with play/pause controls
7. Save the animation (`bone_animation.json`)

## Hotkeys Reference

### Universal Controls
- **Ctrl+Z** - Undo
- **Ctrl+Y** - Redo  
- **Ctrl+S** - Save project
- **Ctrl+L** - Load project
- **DEL** - Delete selected item
- **R** - Reset viewport
- **Middle Mouse** - Pan viewport
- **Mouse Wheel** - Zoom in/out

### Sprite Sheet Editor
- **Ctrl+O** - Open sprite sheet
- **Ctrl+N** - Create new sprite
- **Ctrl+X** - Clear all sprites
- **Right Click** - Create sprite at position
- **Drag Red Dot** - Move sprite origin
- **Drag Cyan Handles** - Resize sprite
- **Drag Sprite** - Move sprite

### Bone Editor
- **1** - Bone Creation mode
- **2** - Bone Editing mode
- **4/5/6** - Set bone layer (Behind/Middle/Front)
- **TAB** - Cycle bone layer
- **PgUp/PgDn** - Adjust layer order
- **Shift+TAB / C** - Cycle selection through overlapping bones
- **A** - Toggle attachment point (Start/End)
- **Ctrl+N** - Create new bone at center
- **Ctrl+X** - Clear all bones
- **Drag Blue Circle** - Move bone start point
- **Drag Red Circle** - Rotate/resize bone
- **Drag Bone Body** - Move entire bone

### Sprite Attachment Editor
- **I** - Create sprite instance
- **T** - Create test sprite instance
- **ESC** - Deselect all
- **A** - Toggle sprite attachment point
- **R / Shift+R** - Rotate sprite ±15°
- **Q / Shift+Q** - Rotate sprite ±5°
- **E** - Reset sprite rotation
- **Shift+TAB / C** - Cycle selection
- **Ctrl+O** - Load sprite project
- **Ctrl+P** - Load bone project
- **Right Click** - Rotate sprite (drag mode)
- **Mouse Wheel on Sprite** - Rotate sprite

### Animation Editor
- **SPACE** - Play/Pause animation
- **Left/Right Arrow** - Step backward/forward by frame
- **HOME/END** - Go to start/end of timeline
- **K** - Add keyframe at current time
- **1-5** - Set keyframe interpolation (Linear/Ease In/Ease Out/Ease In-Out/Bezier)
- **W** - Translation mode (move bones)
- **E** - Rotation mode (rotate bones)
- **T** - Toggle between Translation/Rotation modes
- **Ctrl+A** - Load attachment configuration
- **Ctrl+X** - Clear all animation
- **Drag Timeline** - Scrub to time
- **Drag Keyframe** - Move keyframe timing

## System Requirements

- Python 3.7+
- Pygame 2.0+
- Standard Python libraries (math, json, os, sys, typing, dataclasses, enum)

## Installation

1. Clone the repository
2. Install Pygame: `pip install pygame`
3. Run any editor: `python PySpine_SpriteSheetEditor.py`

## File Formats

The system uses JSON files for data exchange:
- `sprite_project.json` - Sprite definitions and sheet path
- `bone_project.json` - Bone hierarchy and properties  
- `sprite_attachment_config.json` - Complete attachment configuration
- `bone_animation.json` - Animation keyframes and timing

## Features

### Complete Undo/Redo System
Every editor features comprehensive undo/redo with:
- 50-command history limit
- Detailed action descriptions
- Visual status indicators
- All operations are undoable (create, delete, move, rotate, etc.)

### Advanced Selection System
- **Selection Cycling** - Click repeatedly to cycle through overlapping elements
- **Visual Feedback** - Selected items highlighted with colors and indicators
- **Multi-element Detection** - Handles overlapping sprites, bones, and attachment points

### Layer Management
- **Bone Layers** - Behind/Middle/Front with custom ordering
- **Sprite Inheritance** - Sprites inherit rendering order from their bones
- **Visual Layer Indicators** - Color-coded bone rendering and hierarchy display

### Professional-ish Animation Tools
- **Multiple Interpolation Types** - Linear, Ease In/Out, Bezier curves
- **Mode-Based Editing** - Separate Translation and Rotation modes with visual indicators
- **Timeline Manipulation** - Drag keyframes, scrub timeline, adjust timing
- **Real-time Preview** - See animations play back immediately

## Contributing

This is a complete 2D animation toolkit suitable for:
- Game development
- Educational purposes  
- Animation prototyping
- Learning skeletal animation concepts

Each editor is self-contained but designed to work together in the complete pipeline.

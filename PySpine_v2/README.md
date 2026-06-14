# pyspine Complete Rewrite

pyspine is a complete rebuild of the PySpine tool: 2D sprite pieces are rig nodes, and named attachment points define how parts connect.

The codebase keeps the systems separated:

```text
pyspine.core       data model, validation, geometry, solver, animation sampling
pyspine.io         strict JSON, legacy import, autoslice helpers
pyspine.runtime    headless player, bundle loader, Pygame/Pillow renderers
pyspine.editor     one editor shell with state/tools/viewport/UI split apart
pyspine.exporting  packed bundles, frame PNGs, strips, GIF previews
```

## Quick start

```bash
pip install Pillow pygame-ce
python -m unittest discover -s tests -v
python -m pyspine.cli validate examples/pyspine_guy_rig.json
python -m pyspine.cli sample examples/pyspine_guy_rig.json walk_test 6
```

Open the editor:

```bash
python -m pyspine.cli editor examples/pyspine_guy_rig.json
```

Create a new empty project from a PNG sheet:

```bash
python -m pyspine.cli new examples/assets/PySpineGuy.png examples/my_manual_rig.json
python -m pyspine.cli editor examples/my_manual_rig.json
```

---

## Included PySpineGuy example

The package includes the Aseprite-exported PNG at:

```bash
examples/assets/PySpineGuy.png
```

Useful example projects:

```bash
python -m pyspine.cli editor examples/pyspine_guy_rig.json
```

---

## Export/runtime commands

Packed runtime bundle directory:

```bash
python -m pyspine.cli export-pack examples/pyspine_guy_rig.json examples/exports/pyspine_guy_bundle --dir
```

Packed runtime bundle zip:

```bash
python -m pyspine.cli export-pack examples/pyspine_guy_rig.json examples/exports/pyspine_guy_bundle.zip
```

PNG frame sequence:

```bash
python -m pyspine.cli export-frames examples/pyspine_guy_rig.json walk_test examples/exports/walk_frames --start 0 --end 8 --step 2
```

Horizontal sprite strip:

```bash
python -m pyspine.cli export-strip examples/pyspine_guy_rig.json walk_test examples/exports/walk_strip.png --start 0 --end 8 --step 2
```

Animated GIF preview:

```bash
python -m pyspine.cli export-gif examples/pyspine_guy_rig.json walk_test examples/exports/walk_preview.gif --start 0 --end 8 --step 2
```

Runtime playback demo:

```bash
python -m pyspine.cli runtime-play examples/pyspine_guy_rig.json walk_test
python -m pyspine.cli runtime-play examples/exports/pyspine_guy_bundle.zip walk_test
```

---

## Core editor structure

pyspine is now a single editor with three main modes:

```text
1. Sprite Sheet Mode
2. Rig Mode
3. Animation Mode
```

The editor uses one shared project format, one shared viewport system, one shared command/undo model, and separate logic for sprite authoring, rigging, animation, export, and runtime preview.

---

# General editor features

## Window / layout

```text
Resizable editor window
Auto-sizing sidebar
Auto-sizing timeline panel
Draggable vertical sidebar splitter
Draggable horizontal timeline splitter
Canvas clipping so UI panels do not overlap workspace
Independent viewport/camera settings per mode:
  Sprite mode
  Rig mode
  Animation mode
```

## Viewport controls

```text
Zoom
Pan
Fit view
Mode-specific fit behavior
Independent zoom/pan per editor mode
Right-drag or middle-drag panning
Canvas hit testing ignores clicks outside canvas
```

## UI widgets

```text
Buttons
Dropdown/select boxes
Scrollable dropdowns
Text input fields
Cursor-aware text editing
Context-sensitive right-click menus
Centered modal popup windows
Scrollable sidebar
Scrollable timeline/dope sheet
Visible scrollbars
```

## Global workflow

```text
Save project
Backup-on-save
Autosave helper
Dirty-state indicator support
Recent-files helper
Project validation
Missing image detection
Missing image warning/repair flow groundwork
Undo
Redo
Status bar messages
Keyboard hotkeys
Mouse-driven editing
```

---

# Sprite Sheet Mode features

Sprite Sheet Mode is for defining the actual sprite pieces from the source PNG.

## Sprite slicing

```text
Manual rectangle sprite selection
Click/select existing sprite rectangles
Create new sprite rectangles
Rename sprite parts
Delete sprite parts
Sprite list in sidebar
```

Example sprite names:

```text
head
shoulders
waist
pelvis
left_bicep
left_forearm
left_hand
right_thigh
right_calf
right_foot
```

## Sprite points

Each sprite can have named points such as:

```text
origin
neck
belly
hips
left_shoulder
left_elbow
left_wrist
right_hip
right_knee
right_ankle
```

Supported point features:

```text
Add attachment point
Delete attachment point
Rename attachment point
Drag/move attachment point directly in the sprite window
Move origin point
Show visible point handles
Zoom-aware point handle picking
```

## Attachment breakability

```text
Mark attachment points as breakable
Breakability is stored as sprite/point metadata
Animation mode can later key attachment breaks only for breakable points
```

This allows normal rigs to stay physically attached, while special cases can intentionally break attachment on specific frames.

## Sprite-to-rig workflow

```text
Add selected sprite to rig
Right-click sprite menu
Sprite context menu options
```

---

# Rig Mode features

Rig Mode is for building the base character hierarchy. This is the "rig pose" not an animation.

## Base rig pose

```text
Rig Mode always shows the base rig pose
Playback is disabled in Rig Mode
Space/play does not animate in Rig Mode
Leaving Animation Mode stops playback
```

The rig pose is the canonical attachment graph.

## Add / remove instances

```text
Add selected sprite as a rig instance
Delete selected instance
Delete leaf instances safely
Duplicate-like workflow through adding same sprite multiple times
Automatic instance naming
```

## Attachment system

```text
Parent instance to another instance
Unparent instance
Auto-attach when parent/child share a matching point name
Compatible attachment-pair picker
Cycle compatible attachment pairs
Snap preview when dragging root over compatible parent
Release over compatible parent to attach
Attachment graph validation
Cycle prevention
```

Example:

```text
head.neck -> shoulders.neck
waist.belly -> shoulders.belly
pelvis.hips -> waist.hips
left_bicep.left_shoulder -> shoulders.left_shoulder
left_forearm.left_elbow -> left_bicep.left_elbow
left_hand.left_wrist -> left_forearm.left_wrist
```

## Rig transform tools

```text
Move root instances
Rotate instances
Scale instances
Visible rotate handle
Move / rotate / scale gizmos
Visible pivots
Visible attachment links
Snap preview lines
Zoom-aware handles
```

Important current behavior:

```text
Root instances can translate in Rig Mode.
Attached children do not translate away from attachment points in Rig Mode.
Attached children can rotate/scale.
```

## Visibility / locking

```text
Hide/show selected part
Lock/unlock selected part
Locked parts are skipped by IK/editing helpers
Visible checkbox/toggle support
Locked checkbox/toggle support
```

## Rig translucency

```text
Toggle translucent sprite drawing in Rig Mode
Cycle translucency percentage
Allows seeing sprites underneath other sprites
Outlines/pivots/attachment lines remain visible
```

## Selection tools

```text
Click instance to select
Sidebar instance selection
Select parent hotkey
Select child hotkey
Canvas picking
Zoom-aware selection padding
Animation-pose-aware picking where applicable
Click/drag threshold to prevent accidental drag/IK
```

## Hierarchy panel

```text
Parent/child tree view
Indented child instances
Click rows to select
Shows instance name
Shows sprite name
Shows z-order
Shows attachment relationship
Sidebar drag instance row onto another instance row to reparent
```

## Rig validation panel

```text
Missing sprite warnings
Missing attachment point warnings
Cycle detection
Duplicate instance warnings
Root instance summary
General project validation display
```

---

# Property inspector features

The inspector exists for selected sprites/instances and is visible where relevant, especially Rig and Animation modes.

## Editable numeric fields

```text
x
y
rotation
local_rotation
z
scale_x
scale_y
```

## Dropdowns

```text
Sprite dropdown
Self attachment point dropdown
Parent attachment point dropdown
Compatible parent/attachment dropdown-like picker
Clip dropdown / chooser in Animation Mode
```

## Toggles

```text
Visible
Locked
Break attachment at frame, when allowed
```

## Sprite swap support

```text
Swap an instance's sprite at an animation frame
Sprite swap is keyed on the animation timeline
Sprite swaps are discrete/step-sampled, not interpolated
Attachment-safe sprite swap validation
Refuses invalid swaps with warning instead of crashing
```

Safety rule:

```text
Replacement sprite must contain:
  the instance self attachment point
  any child attachment points needed by children
```

So an open hand sprite named `right_handopen` and a close hand sprite named `right_hand` can swap only if both have the same required attachment point, for example `right_wrist`

---

# Animation Mode features

Animation Mode is for creating clips from the base rig pose.

## Clip management

```text
Choose existing clip
Create new clip
Centered Clip chooser popup
Clip button opens chooser
C hotkey opens chooser
Escape closes chooser
New clips default to explicit frame-0 rig-pose keys
```

New clips start from the rigging pose and key the initial state:

```text
x
y
rotation
local_rotation
scale
visible
sprite
```

## Playback

```text
Play/pause in Animation Mode only
Frame stepping
Timeline seeking
Playback stops when leaving Animation Mode
```

## Timeline / dope sheet

```text
Bottom timeline panel
Timeline frame ruler
Click timeline to seek
Real channel rows
Hierarchy-ordered rows
Keyframe diamond markers
Selected keyframe highlighting
Scrollable dope sheet
Timeline scrollbar
Timeline auto-sizing
Draggable timeline panel splitter
```

Supported channel rows include:

```text
root x
root y
rotation
local_rotation
scale_x
scale_y
visible
sprite
break_attach
```

## Keyframe editing

```text
Set rotation key
Set pose key
Set full pose key
Delete selected keyframe
Click keyframe to select
Drag keyframe left/right
Box-select keyframes
Move multiple selected keyframes
Scale selected key timing
Duplicate selected keys
Insert frame range
Delete frame range
Clear channel
Clear pose
Clear selected part
Copy frame keyframes
Paste frame keyframes
Copy sampled pose
Paste sampled pose
```

## Interpolation / easing

Supported interpolation/easing:

```text
linear
step
ease_in
ease_out
ease_in_out
smoothstep
smootherstep
bezier(x1,y1,x2,y2)
```

Controls:

```text
Toggle/cycle interpolation
Shift+T cycles selected channel easing
Sprite swaps use step/discrete sampling
Visibility/break flags are discrete
```

## Pose tools

```text
Save named pose
Named pose library
Click named pose to apply/key it
Copy pose
Paste pose
Copy selected limb pose
Paste selected limb pose
Mirror left/right pose
Blend selected pose into current frame
Reset full pose
Reset selected part
Reset selected limb chain
Pose-to-keyframe application
```

## Onion skin

```text
Toggle onion skin
Configurable before count
Configurable after count
Configurable frame spacing
Configurable alpha/falloff
Metadata-backed onion settings
Alt+Up / Alt+Down adjusts onion count
Alt+Left / Alt+Right adjusts onion spacing
```

## Motion arcs

```text
Selected instance motion arc overlay
Attachment-point motion arcs
Sampled motion paths across clip range
Planted-range detection based on point speed
```

---

# IK and body posing features

## IK-lite / full-chain IK

Originally the IK was only two bone. Current behavior is full-chain / whole-body CCD IK by default.

```text
Select hand/foot/end part
Drag in Animation Mode or press IK hotkey
Connected chain rotates toward target
Locked parts are skipped
If target is unreachable, root x/y can be keyed too
```

For a hand, it can affect:

```text
shoulders
bicep
forearm
hand
```

For a foot, it can affect:

```text
shoulders
waist
pelvis
thigh
kneecap/calf
foot
```

## Animation-mode translation behavior

Important current intended behavior:

```text
Clicking a sprite selects only.
Tiny mouse jitter is ignored.
Real drag starts only after a screen-pixel threshold.
Dragging a root writes x/y keys.
Dragging an attached child runs IK/full-chain posing.
Attached children do not simply translate away from their attachment points unless explicitly broken.
```

## Breakable attachments

```text
Sprite Mode:
  mark a point breakable

Animation Mode:
  toggle break_attach at a frame
```

Break behavior only applies when:

```text
the point is marked breakable
and the current frame has break_attach=true
```

This allows special animated detach/re-attach effects without destroying the normal rig constraint graph.

## Foot / hand lock helpers

```text
Foot/hand lock selected point for short range
Foot/hand lock selected point for longer range
Detect planted ranges
Generate root x/y keys to keep selected point pinned
Useful for planted feet during walk cycles
```

---

# Context menus

## Sprite Mode right-click menu

```text
Add point
Rename selected sprite/point
Delete selected sprite/point
Add sprite to rig
Mark point breakable
```

## Rig Mode right-click menu

```text
Add selected sprite
Unparent
Delete
Toggle translucent sprites
Cycle translucency percentage
Switch to Animation Mode
```

## Animation Mode right-click menu

```text
Choose clip
Key rotation
Key full pose
Copy pose
Paste pose
Reset pose
Toggle/cycle interpolation
Save named pose
IK selected chain to mouse
Foot/hand lock
Detect planted ranges
Swap sprite at this frame
Toggle break attachment at this frame
```

---

# Export/runtime-related editor support

The editor and CLI support export workflows.

## Export options

```text
Packed runtime bundle export
Runtime JSON export
PNG frame sequence export
PNG sprite-strip export
Animated GIF preview export
```

## Runtime playback

```text
Load project directly
Load packed bundle
Offline Pillow renderer
Pygame runtime playback demo
```

## Export safety

```text
Project validation before export
Sprite-swap attachment safety
Missing image detection
Invalid attachment fallback protection
Bad sprite-swap keyframes no longer crash playback/export
```

---

# CLI / testing support

## CLI commands

```text
validate
sample
editor
autoslice
export-pack
export-frames
export-strip
export-gif
runtime-play
demo-ik
demo-footlock
detect-plants
```

---

# Current major hotkeys

Not every option is hotkey-only, but these are the important ones.

## Mode switching

```text
1    Sprite Sheet Mode
2    Rig Mode
3    Animation Mode
```

## General

```text
Ctrl+S       Save
Ctrl+Z       Undo
Ctrl+Y       Redo
F / Fit      Fit view, mode-specific
RMB drag     Pan
Middle drag  Pan
Wheel        Zoom or scroll depending panel
```

## Sprite Mode

```text
F2       Rename selected sprite/point
A        Add attachment point
B        Toggle selected point breakable
I        Add selected sprite as rig instance
```

## Rig Mode

```text
I              Add selected sprite as instance
P              Parent selected instance to instance under mouse
U              Unparent selected instance
[ / ]          Rotate selected instance
L              Lock/unlock selected
V              Hide/show selected
PageUp         Select parent
PageDown       Select child
```

## Animation Mode

```text
C              Open Clip chooser
Space          Play/pause
K              Key selected rotation
J              Key selected pose
Shift+K        Key full pose
Delete         Delete selected keyframe
Ctrl+C         Copy sampled pose
Ctrl+V         Paste sampled pose
Ctrl+Shift+C   Copy exact frame keys
Ctrl+Shift+V   Paste exact frame keys
Ctrl+D         Duplicate selected keys
Ctrl+I         Insert frame range
Ctrl+Backspace Delete frame range
M              Mirror left/right pose
X              Reset full pose
Shift+X        Reset selected part
N              Save named pose
T              Toggle/cycle interpolation
Shift+T        Cycle selected channel easing
O              Toggle onion skin
Alt+Up/Down    Onion count
Alt+Left/Right Onion spacing
Y              Full-chain IK selected part toward mouse
Shift+Y        IK with opposite bend/fallback behavior
B              Foot/hand lock short range
Shift+B        Foot/hand lock longer range
G              Detect planted ranges
S              Open sprite swap dropdown
Ctrl+B         Toggle break attachment at frame
```

---

# Current known/likely rough edges

The editor is now feature-rich, but there are still areas that probably need another hardening pass:

```text
Inspector visibility/discoverability could be better.
Some controls still rely too much on hotkeys/context menus.
The UI needs clearer labels for advanced animation tools.
IK needs more obvious target/chain visualization.
IK should be configurable chains instead of full body all the time.
Breakable attachments need a better visual indicator.
Sprite swap workflow needs a clearer dedicated panel.
PyAutoGUI scripts should be expanded into full repeatable regression workflows.
The editor would benefit from a help overlay listing current mode controls.
```

---
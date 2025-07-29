# Problems and Bugs

## All Editors
* TODO: Make all editor windows resize-able/fullscreen-able and each editor panel resize-able.
* TODO: All editors should follow the Bone Editor's locate skeleton and center on it functionality.
* TODO: Clean up duplicated information in editor texts.
---

## Example Project
* TODO: Bones/Sprites are not attached correctly. A bone should cover from the start to end of sprite where you want it to be.
  * All bones are basically offset in one direction. Simple fix as they are attached to the endpoint not the startpoint of bones.
* TODO: Make better art for the PySpineGuy example character.
* TODO: Implement a simple SDL3 loader for PySpine.
* TODO: Implement a simple PyGame-CE loader for PySpine.
  
---

## Sprite Sheet Editor
* TODO: Fix cyan boxes.
  * This bug happens when you try to move some specific cyan boxes for resizing sprite objects, it will snap the outline rectangle smaller a single pixel, then will function normally.
    * Happens with: [BottomLeft, MiddleLeft, TopLeft, TopMiddle] cyan boxes.
    * Doesn't happen with: [BottomMiddle, BottomRight, MiddleRight, TopRight] cyan boxes.
---

## Bone Editor
* TODO: Figure out how to select bones which are on top of one another and already connected to eachother within the viewport.
  * Workaround: Just select bone in hierarchy panel.
* TODO: Modify the bone START/END point shapes.
  * Maybe use smaller diamonds for endpoints and keep the circles for startpoints.
  * Put smaller endpoint shapes ontop of the startpoint shapes. This would fix the selection of bones on top of one another.
* TODO: Fix viewport bone selection.
  * Currently, you have to click in the wrong spot and not on the bone parts themselves to select something.
---

## Sprite/Bone Attachment Editor
* TODO: Fix on Editor load.
  * Currently, you need to press CTRL+L, CTRL+O, CTRL+P after editor starts to get the correct load of Sprites, Bones, and Attachments.
* TODO: Change skeleton to be transparent, and overlay ontop of sprites.
  * Currently, there is no transparency and is rendered behind the sprites.
* TODO: Verify sprite layerying is correct.
  * The head shows up behind torso. Others seem fine? (example might be wrongly setup (head on wrong layer))
* TODO: Make sprite drag and drop more clear on where it's attaching in hierarchy panel.
  * "S" and "E" text is small and same text color as "Drop on here" text
  * Maybe make Left/Right halves of the Bone slot background in hierarchy panel be 2 different colors?
* TODO: Fixup Properties panel.
  * Too much text forcing it off screen.
---

## Animation Editor
* TODO: Fix timeline clicking. After adding undo/redo functionality, it broke the sub-second clickability.
  * You can't click at say 0.5 seconds anymore.
  * Maybe convert to Flash style animation timeline with steps/framerate/keyframes etc
* TODO: Fixup Properties panel.
  * Too much text forcing it off screen.
* TODO: Fixup translation mode.
  * Translation is messed up. It doesn't follow mouse movements properly.
* TODO: Fix Bone highlight in timeline.
  * Currently it's a brown box covering the text.
* TODO: Fix on Editor load.
  * Follow the Attachment Editor fix with CTRL + [L, O, P]. It's not loading characters correctly.
---

from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
import copy
import pygame


class UndoRedoCommand(ABC):
    """Abstract base class for all undoable commands"""

    def __init__(self, description: str = ""):
        self.description = description

    @abstractmethod
    def execute(self) -> None:
        """Execute the command"""
        pass

    @abstractmethod
    def undo(self) -> None:
        """Undo the command"""
        pass

    def __str__(self) -> str:
        return self.description or self.__class__.__name__


class UndoRedoManager:
    """Manages undo/redo command stacks with history limit"""

    def __init__(self, history_limit: int = 50):
        self.history_limit = history_limit
        self.undo_stack: List[UndoRedoCommand] = []
        self.redo_stack: List[UndoRedoCommand] = []
        self.enabled = True

    def execute_command(self, command: UndoRedoCommand) -> None:
        """Execute a command and add it to the undo stack"""
        if not self.enabled:
            command.execute()
            return

        # Execute the command
        command.execute()

        # Add to undo stack
        self.undo_stack.append(command)

        # Clear redo stack (can't redo after new action)
        self.redo_stack.clear()

        # Limit history size
        if len(self.undo_stack) > self.history_limit:
            self.undo_stack.pop(0)

        print(f"Executed: {command}")

    def undo(self, count: int = 1) -> bool:
        """Undo the last 'count' commands"""
        if not self.can_undo() or count <= 0:
            return False

        undone_count = 0
        for _ in range(min(count, len(self.undo_stack))):
            command = self.undo_stack.pop()
            command.undo()
            self.redo_stack.append(command)
            undone_count += 1
            print(f"Undid: {command}")

        return undone_count > 0

    def redo(self, count: int = 1) -> bool:
        """Redo the last 'count' undone commands"""
        if not self.can_redo() or count <= 0:
            return False

        redone_count = 0
        for _ in range(min(count, len(self.redo_stack))):
            command = self.redo_stack.pop()
            command.execute()
            self.undo_stack.append(command)
            redone_count += 1
            print(f"Redid: {command}")

        return redone_count > 0

    def can_undo(self) -> bool:
        """Check if undo is possible"""
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        """Check if redo is possible"""
        return len(self.redo_stack) > 0

    def clear(self) -> None:
        """Clear all command history"""
        self.undo_stack.clear()
        self.redo_stack.clear()
        print("Cleared undo/redo history")

    def get_undo_list(self) -> List[str]:
        """Get list of undoable commands"""
        return [str(cmd) for cmd in reversed(self.undo_stack)]

    def get_redo_list(self) -> List[str]:
        """Get list of redoable commands"""
        return [str(cmd) for cmd in reversed(self.redo_stack)]

    def disable(self) -> None:
        """Temporarily disable undo tracking"""
        self.enabled = False

    def enable(self) -> None:
        """Re-enable undo tracking"""
        self.enabled = True


# COMMON COMMAND IMPLEMENTATIONS BELOW


class StateSnapshotCommand(UndoRedoCommand):
    """Command that saves/restores complete state snapshots"""

    def __init__(self, target_object: Any, attribute_name: str,
                 old_state: Any, new_state: Any, description: str = ""):
        super().__init__(description)
        self.target_object = target_object
        self.attribute_name = attribute_name
        self.old_state = copy.deepcopy(old_state)
        self.new_state = copy.deepcopy(new_state)

    def execute(self) -> None:
        setattr(self.target_object, self.attribute_name, copy.deepcopy(self.new_state))

    def undo(self) -> None:
        setattr(self.target_object, self.attribute_name, copy.deepcopy(self.old_state))


class DictAddCommand(UndoRedoCommand):
    """Command for adding items to dictionaries"""

    def __init__(self, target_dict: Dict, key: Any, value: Any, description: str = ""):
        super().__init__(description or f"Add {key}")
        self.target_dict = target_dict
        self.key = key
        self.value = copy.deepcopy(value)
        self.key_existed = key in target_dict
        self.old_value = copy.deepcopy(target_dict.get(key)) if self.key_existed else None

    def execute(self) -> None:
        self.target_dict[self.key] = copy.deepcopy(self.value)

    def undo(self) -> None:
        if self.key_existed:
            self.target_dict[self.key] = copy.deepcopy(self.old_value)
        else:
            del self.target_dict[self.key]


class DictRemoveCommand(UndoRedoCommand):
    """Command for removing items from dictionaries"""

    def __init__(self, target_dict: Dict, key: Any, description: str = ""):
        super().__init__(description or f"Remove {key}")
        self.target_dict = target_dict
        self.key = key
        self.old_value = copy.deepcopy(target_dict.get(key))
        self.key_existed = key in target_dict

    def execute(self) -> None:
        if self.key in self.target_dict:
            del self.target_dict[self.key]

    def undo(self) -> None:
        if self.key_existed:
            self.target_dict[self.key] = copy.deepcopy(self.old_value)


class DictModifyCommand(UndoRedoCommand):
    """Command for modifying dictionary values"""

    def __init__(self, target_dict: Dict, key: Any, old_value: Any, new_value: Any, description: str = ""):
        super().__init__(description or f"Modify {key}")
        self.target_dict = target_dict
        self.key = key
        self.old_value = copy.deepcopy(old_value)
        self.new_value = copy.deepcopy(new_value)

    def execute(self) -> None:
        self.target_dict[self.key] = copy.deepcopy(self.new_value)

    def undo(self) -> None:
        self.target_dict[self.key] = copy.deepcopy(self.old_value)


class ListAddCommand(UndoRedoCommand):
    """Command for adding items to lists"""

    def __init__(self, target_list: List, item: Any, index: Optional[int] = None, description: str = ""):
        super().__init__(description or f"Add to list")
        self.target_list = target_list
        self.item = copy.deepcopy(item)
        self.index = index if index is not None else len(target_list)

    def execute(self) -> None:
        self.target_list.insert(self.index, copy.deepcopy(self.item))

    def undo(self) -> None:
        if 0 <= self.index < len(self.target_list):
            self.target_list.pop(self.index)


class ListRemoveCommand(UndoRedoCommand):
    """Command for removing items from lists"""

    def __init__(self, target_list: List, index: int, description: str = ""):
        super().__init__(description or f"Remove from list")
        self.target_list = target_list
        self.index = index
        self.removed_item = copy.deepcopy(target_list[index]) if 0 <= index < len(target_list) else None

    def execute(self) -> None:
        if 0 <= self.index < len(self.target_list):
            self.target_list.pop(self.index)

    def undo(self) -> None:
        if self.removed_item is not None:
            self.target_list.insert(self.index, copy.deepcopy(self.removed_item))


class CompositeCommand(UndoRedoCommand):
    """Command that groups multiple commands together"""

    def __init__(self, commands: List[UndoRedoCommand], description: str = ""):
        super().__init__(description or "Composite Operation")
        self.commands = commands

    def execute(self) -> None:
        for command in self.commands:
            command.execute()

    def undo(self) -> None:
        # Undo in reverse order
        for command in reversed(self.commands):
            command.undo()


# MIXIN FOR EASY INTEGRATION BELOW


class UndoRedoMixin:
    """Mixin to add undo/redo functionality to any class"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.undo_manager = UndoRedoManager()

    def execute_command(self, command: UndoRedoCommand) -> None:
        """Execute a command through the undo manager"""
        self.undo_manager.execute_command(command)

    def undo(self, count: int = 1) -> bool:
        """Undo operations"""
        return self.undo_manager.undo(count)

    def redo(self, count: int = 1) -> bool:
        """Redo operations"""
        return self.undo_manager.redo(count)

    def can_undo(self) -> bool:
        return self.undo_manager.can_undo()

    def can_redo(self) -> bool:
        return self.undo_manager.can_redo()

    def clear_history(self) -> None:
        """Clear undo/redo history"""
        self.undo_manager.clear()

    def setup_undo_redo_keys(self) -> None:
        """Setup standard undo/redo keyboard shortcuts"""
        if hasattr(self, 'key_handlers'):
            self.key_handlers.update({
                (pygame.K_z, pygame.K_LCTRL): lambda: self.undo(),
                (pygame.K_y, pygame.K_LCTRL): lambda: self.redo(),
                (pygame.K_z, pygame.K_LCTRL | pygame.K_LSHIFT): lambda: self.redo(),  # Ctrl+Shift+Z
            })

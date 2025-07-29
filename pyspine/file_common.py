import json
import os
from dataclasses import asdict
from enum import Enum


def save_json_project(filename, data, success_message=None):
    """Generic JSON project saver with enum support"""
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2, cls=EnumJSONEncoder)
        if success_message:
            print(success_message)
        else:
            print(f"{filename} saved successfully!")
        return True
    except Exception as e:
        print(f"Error saving {filename}: {e}")
        return False


def load_json_project(filename, success_message=None):
    """Generic JSON project loader"""
    try:
        with open(filename, "r") as f:
            data = json.load(f)
        if success_message:
            print(success_message)
        else:
            print(f"{filename} loaded successfully!")
        return data
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return None


def auto_load_if_exists(filename, load_function):
    """Autoload file if it exists"""
    if os.path.exists(filename):
        return load_function(filename)
    return False


class EnumJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles enum values"""

    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


def serialize_dataclass_dict(dataclass_dict):
    """Convert dictionary of dataclass objects to serializable format with enum support"""

    def enum_dict_factory(fields):
        """Custom dict factory that converts enums to their values"""
        result = {}
        for key, value in fields:
            if isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result

    return {key: asdict(obj, dict_factory=enum_dict_factory) for key, obj in dataclass_dict.items()}


def deserialize_bone_data(bone_data):
    """Convert loaded bone data back to proper types, handling enums and new fields"""
    from data_classes import Bone, BoneLayer, AttachmentPoint

    # Handle the layer field conversion from string back to enum
    if 'layer' in bone_data and isinstance(bone_data['layer'], str):
        try:
            bone_data['layer'] = BoneLayer(bone_data['layer'])
        except ValueError:
            # If the string doesn't match any enum value, default to MIDDLE
            bone_data['layer'] = BoneLayer.MIDDLE
            print(f"Warning: Unknown layer value '{bone_data['layer']}', defaulting to MIDDLE")
    elif 'layer' not in bone_data:
        # For backward compatibility with old bone data
        bone_data['layer'] = BoneLayer.MIDDLE

    # NEW: Handle parent_attachment_point field
    if 'parent_attachment_point' in bone_data and isinstance(bone_data['parent_attachment_point'], str):
        try:
            bone_data['parent_attachment_point'] = AttachmentPoint(bone_data['parent_attachment_point'])
        except ValueError:
            # If the string doesn't match any enum value, default to END
            bone_data['parent_attachment_point'] = AttachmentPoint.END
            print(
                f"Warning: Unknown attachment point value '{bone_data['parent_attachment_point']}', defaulting to END")
    elif 'parent_attachment_point' not in bone_data:
        # For backward compatibility with old bone data
        bone_data['parent_attachment_point'] = AttachmentPoint.END

    # Handle layer_order field for backward compatibility
    if 'layer_order' not in bone_data:
        bone_data['layer_order'] = 0

    return Bone(**bone_data)

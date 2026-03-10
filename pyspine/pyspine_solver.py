import math


def rotate_vec(xy, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return xy[0] * c - xy[1] * s, xy[0] * s + xy[1] * c


def get_sprite(sprites, inst):
    if not inst:
        return None
    return sprites.get(inst.sprite_name)


def local_point_xy(sprite, point_name):
    p = sprite.get_point_by_name(point_name) if sprite else None
    if not p:
        return 0.0, 0.0
    return sprite.width * p.x, sprite.height * p.y


def get_world_transform(instances, sprites, inst_name, stack=None):
    inst = instances.get(inst_name)
    if not inst:
        return {"root": (0.0, 0.0), "rotation": 0.0}

    stack = set(stack) if stack else set()
    if inst_name in stack:
        return {"root": (inst.root_x, inst.root_y), "rotation": inst.rotation}
    stack.add(inst_name)

    sprite = get_sprite(sprites, inst)

    if not inst.parent or inst.parent not in instances:
        return {"root": (inst.root_x, inst.root_y), "rotation": inst.rotation}

    parent_inst = instances[inst.parent]
    parent_sprite = get_sprite(sprites, parent_inst)
    parent_tf = get_world_transform(instances, sprites, inst.parent, stack)

    parent_point_name = inst.parent_point or (
        parent_sprite.attachment_points[0].name
        if parent_sprite and parent_sprite.attachment_points
        else None
    )
    self_point_name = inst.self_point or (
        sprite.attachment_points[0].name
        if sprite and sprite.attachment_points
        else None
    )

    parent_attach = get_world_point(instances, sprites, inst.parent, parent_point_name)
    world_rot = parent_tf["rotation"] + inst.local_rotation
    local_attach = local_point_xy(sprite, self_point_name)
    local_attach_rot = rotate_vec(local_attach, world_rot)

    root = (
        parent_attach[0] - local_attach_rot[0],
        parent_attach[1] - local_attach_rot[1],
    )
    return {"root": root, "rotation": world_rot}


def get_world_point(instances, sprites, inst_name, point_name):
    inst = instances.get(inst_name)
    if not inst:
        return 0.0, 0.0

    tf = get_world_transform(instances, sprites, inst_name)
    sprite = get_sprite(sprites, inst)
    local = local_point_xy(sprite, point_name)
    rot = rotate_vec(local, tf["rotation"])
    return tf["root"][0] + rot[0], tf["root"][1] + rot[1]


def would_cycle(instances, child_name, maybe_parent_name):
    cur = maybe_parent_name
    while cur:
        if cur == child_name:
            return True
        parent = instances.get(cur)
        cur = parent.parent if parent else None
    return False


def detach_instance(instances, sprites, inst_name):
    inst = instances.get(inst_name)
    if not inst:
        return

    tf = get_world_transform(instances, sprites, inst_name)
    inst.root_x, inst.root_y = tf["root"]
    inst.rotation = tf["rotation"]
    inst.parent = None
    inst.parent_point = None
    inst.self_point = None
    inst.local_rotation = 0.0

from dataclasses import dataclass, field, asdict


@dataclass
class AttachPoint:
    name: str
    x: float
    y: float

    @classmethod
    def from_dict(cls, d):
        return cls(str(d.get("name", "point")), float(d.get("x", 0.5)), float(d.get("y", 0.5)))

    def to_dict(self):
        return asdict(self)


@dataclass
class Sprite:
    name: str
    x: int
    y: int
    width: int
    height: int
    attachment_points: list[AttachPoint] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d):
        pts = []
        raw_pts = d.get("attachment_points")
        if isinstance(raw_pts, list):
            pts = [AttachPoint.from_dict(p) for p in raw_pts]
        else:
            if "origin_x" in d or "origin_y" in d:
                pts.append(AttachPoint("origin", float(d.get("origin_x", 0.5)), float(d.get("origin_y", 0.5))))
            if "endpoint_x" in d or "endpoint_y" in d:
                pts.append(AttachPoint("endpoint", float(d.get("endpoint_x", 0.5)), float(d.get("endpoint_y", 0.85))))
        if not pts:
            pts = [AttachPoint("origin", 0.5, 0.5), AttachPoint("endpoint", 0.5, 0.85)]
        return cls(
            name=d["name"],
            x=int(d["x"]),
            y=int(d["y"]),
            width=int(d["width"]),
            height=int(d["height"]),
            attachment_points=pts,
        )

    def to_dict(self):
        data = {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "attachment_points": [p.to_dict() for p in self.attachment_points],
        }
        # Keep legacy fields too for compatibility with the earlier tiny tool.
        p0 = self.get_point_by_name("origin") or (self.attachment_points[0] if self.attachment_points else None)
        p1 = self.get_point_by_name("endpoint") or (
            self.attachment_points[1] if len(self.attachment_points) > 1 else p0)
        if p0:
            data["origin_x"] = p0.x
            data["origin_y"] = p0.y
        if p1:
            data["endpoint_x"] = p1.x
            data["endpoint_y"] = p1.y
        return data

    def get_point_by_name(self, name):
        for p in self.attachment_points:
            if p.name == name:
                return p
        return self.attachment_points[0] if self.attachment_points else None

    def point_names(self):
        return [p.name for p in self.attachment_points]


@dataclass
class Instance:
    name: str
    sprite_name: str
    root_x: float = 0.0
    root_y: float = 0.0
    rotation: float = 0.0
    parent: str | None = None
    parent_point: str | None = None
    self_point: str | None = None
    local_rotation: float = 0.0

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=str(d.get("name", "part")),
            sprite_name=str(d.get("sprite_name", "")),
            root_x=float(d.get("root_x", 0.0)),
            root_y=float(d.get("root_y", 0.0)),
            rotation=float(d.get("rotation", 0.0)),
            parent=d.get("parent"),
            parent_point=d.get("parent_point"),
            self_point=d.get("self_point"),
            local_rotation=float(d.get("local_rotation", 0.0)),
        )

    def to_dict(self):
        return {
            "name": self.name,
            "sprite_name": self.sprite_name,
            "root_x": self.root_x,
            "root_y": self.root_y,
            "rotation": self.rotation,
            "parent": self.parent,
            "parent_point": self.parent_point,
            "self_point": self.self_point,
            "local_rotation": self.local_rotation,
        }

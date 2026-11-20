"""DXF and JSON export. The DXF is plain R12 (opens in AutoCAD, FreeCAD, LibreCAD),
written by hand so no extra library is needed. Units are millimetres."""
import json


def _pairs(*items):
    return "".join(f"{code}\n{value}\n" for code, value in items)


def write_dxf(path, outline_mm, length=None, width=None, height=None):
    """outline_mm: list of [x, y] points in mm (closed shape). Y is flipped so the
    drawing looks the same way up as on screen."""
    pts = [(float(x), -float(y)) for x, y in outline_mm]
    if len(pts) < 3:
        raise ValueError("outline needs at least 3 points")
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    pts = [(x - minx, y - miny) for x, y in pts]  # put the shape at the origin

    out = []
    out.append(_pairs((0, "SECTION"), (2, "HEADER"),
                      (9, "$ACADVER"), (1, "AC1009"),
                      (9, "$INSUNITS"), (70, 4),
                      (0, "ENDSEC")))
    out.append(_pairs((0, "SECTION"), (2, "TABLES"),
                      (0, "TABLE"), (2, "LAYER"), (70, 2),
                      (0, "LAYER"), (2, "OUTLINE"), (70, 0), (62, 7), (6, "CONTINUOUS"),
                      (0, "LAYER"), (2, "INFO"), (70, 0), (62, 8), (6, "CONTINUOUS"),
                      (0, "ENDTAB"), (0, "ENDSEC")))
    ent = [_pairs((0, "SECTION"), (2, "ENTITIES"),
                  (0, "POLYLINE"), (8, "OUTLINE"), (66, 1), (10, 0.0), (20, 0.0), (30, 0.0), (70, 1))]
    for x, y in pts:
        ent.append(_pairs((0, "VERTEX"), (8, "OUTLINE"), (10, f"{x:.4f}"), (20, f"{y:.4f}"), (30, 0.0)))
    ent.append(_pairs((0, "SEQEND"), (8, "OUTLINE")))
    if length is not None and width is not None:
        label = f"{length:.1f} x {width:.1f}" + (f" x {height:.1f}" if height is not None else "") + " mm"
        ent.append(_pairs((0, "TEXT"), (8, "INFO"), (10, 0.0), (20, -8.0), (30, 0.0), (40, 3.5), (1, label)))
    ent.append(_pairs((0, "ENDSEC")))
    out.extend(ent)
    out.append(_pairs((0, "EOF")))
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("".join(out))


def write_json(path, name, length, width, height, outline_mm):
    data = {
        "name": name,
        "units": "mm",
        "length_mm": round(float(length), 2),
        "width_mm": round(float(width), 2),
        "height_mm": None if height is None else round(float(height), 2),
        "outline_mm": [[round(float(x), 3), round(float(y), 3)] for x, y in outline_mm],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

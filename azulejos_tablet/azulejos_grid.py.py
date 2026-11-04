
import Rhino
import System
import scriptcontext as sc

ROWS = "ABCDE"
COLS = 6
TILE = 150.0  # millimeters

doc = sc.doc

# Create layers
for name, color in [
    ("AZ_GRID", System.Drawing.Color.Gray),
    ("AZ_LABELS", System.Drawing.Color.DarkBlue),
    ("AZ_SKETCHES", System.Drawing.Color.Blue),
]:
    if doc.Layers.FindName(name) is None:
        layer = Rhino.DocObjects.Layer()
        layer.Name = name
        layer.Color = color
        doc.Layers.Add(layer)

grid_layer = doc.Layers.FindName("AZ_GRID").Index
label_layer = doc.Layers.FindName("AZ_LABELS").Index

for row_index, row_letter in enumerate(ROWS):
    for col_index in range(COLS):
        tile_id = f"{row_letter}{col_index + 1}"

        x = col_index * TILE
        z = (len(ROWS) - 1 - row_index) * TILE

        # Rectangle in the XZ plane (front elevation)
        corners = [
            Rhino.Geometry.Point3d(x, 0, z),
            Rhino.Geometry.Point3d(x + TILE, 0, z),
            Rhino.Geometry.Point3d(x + TILE, 0, z + TILE),
            Rhino.Geometry.Point3d(x, 0, z + TILE),
            Rhino.Geometry.Point3d(x, 0, z),
        ]

        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex = grid_layer
        attrs.Name = tile_id
        attrs.SetUserString("TileID", tile_id)

        polyline = Rhino.Geometry.Polyline(corners)
        doc.Objects.AddCurve(polyline.ToNurbsCurve(), attrs)

        # Label at the tile centre
        text = Rhino.Geometry.TextEntity()
        text.Plane = Rhino.Geometry.Plane(
            Rhino.Geometry.Point3d(x + TILE / 2, -1, z + TILE / 2),
            Rhino.Geometry.Vector3d(1, 0, 0),
            Rhino.Geometry.Vector3d(0, 0, 1)
        )
        text.PlainText = tile_id
        text.TextHeight = 18.0
        text.Justification = Rhino.Geometry.TextJustification.MiddleCenter

        label_attrs = Rhino.DocObjects.ObjectAttributes()
        label_attrs.LayerIndex = label_layer
        label_attrs.Name = "Label_" + tile_id

        doc.Objects.AddText(text, label_attrs)

doc.Views.Redraw()
print("Created 30 labelled Azulejos tiles: A1 through E6")
#! python 3 

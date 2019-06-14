# -*- coding:utf-8 -*-
import os
import bpy
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, EnumProperty, FloatProperty
from bpy.types import Operator
from ..geoscene import GeoScene
from ..core.proj import Reproj


KML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
    xmlns:gx="http://www.google.com/kml/ext/2.2"
    xmlns:kml="http://www.opengis.net/kml/2.2"
    xmlns:atom="http://www.w3.org/2005/Atom">
	<Document>
		<name>%s.kmz</name>
		<Style id="s_ylw-pushpin">
			<IconStyle>
				<scale>1.1</scale>
				<Icon>
					<href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
				</Icon>
				<hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
			</IconStyle>
		</Style>
		<Style id="s_ylw-pushpin_hl">
			<IconStyle>
				<scale>1.3</scale>
				<Icon>
					<href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
				</Icon>
				<hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
			</IconStyle>
		</Style>
		<StyleMap id="m_ylw-pushpin">
			<Pair>
				<key>normal</key>
				<styleUrl>#s_ylw-pushpin</styleUrl>
			</Pair>
			<Pair>
				<key>highlight</key>
				<styleUrl>#s_ylw-pushpin_hl</styleUrl>
			</Pair>
		</StyleMap>
		<Placemark>
			<name>%s</name>
			<styleUrl>#m_ylw-pushpin</styleUrl>
			<LineString>
				<extrude>1</extrude>
				<tessellate>1</tessellate>
				<altitudeMode>%s</altitudeMode>
				<coordinates>
                    %s
                </coordinates>
            </LineString>
        </Placemark>
    </Document>
</kml>
"""


class EXPORTGIS_OT_kml_file(Operator, ExportHelper):
    """Export single path to KML file format (.kml)"""
    bl_idname = "exportgis.kml_file"
    bl_description = 'Export single path to KML file format (.kml)'
    bl_label = "Export KML"
    bl_options = {"UNDO"}

    filename_ext = ".kml"
    filter_glob: StringProperty(
        default="*.kml",
        options={'HIDDEN'},
    )
    mode: EnumProperty(
        name="altitude mode",
        items=(
            ("relative", "Relative altitudes", "Relative altitudes"),
            ("absolute", "Absolute altitudes", "Absolute altitudes")),
        default="relative"
    )
    altitude: FloatProperty(
        name="reference altitude",
        description="altitude of level 0",
        default=0
    )

    def execute(self, context):
        filePath = self.filepath
        folder = os.path.dirname(filePath)
        filename = os.path.splitext(os.path.basename(filePath))[0]

        scn = context.scene
        geoscn = GeoScene(scn)
        obj = context.active_object

        if obj is None:
            self.report({'INFO'}, "Selection is empty")
            print("Selection is empty or too much object selected")
            return {'FINISHED'}

        if obj.type != 'MESH' and obj.type != 'CURVE':
            self.report({'INFO'}, "Invalid selection")
            return {'FINISHED'}

        if geoscn.isGeoref:
            dx, dy = geoscn.getOriginPrj()
        elif geoscn.isBroken:
            self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
            return {'FINISHED'}
        else:
            dx, dy = (0, 0)

        tM = obj.matrix_world
        d = obj.data

        if obj.type == 'MESH':
            verts = d.vertices

        elif obj.type == 'CURVE':
            spline = d.splines[0]
            if spline.type == 'POLY':
                verts = spline.points
            elif spline.type == 'BEZIER':
                verts = spline.bezier_points
            else:
                verts = []

        if len(verts) == 0:
            self.report({'ERROR'}, "No vertice to export")
            print("No vertice to export")
            return {'FINISHED'}

        rprj = Reproj(geoscn.crs, 4326)
        pts = []
        for vert in verts:
            x, y, alt = tM @ vert.co.to_3d()
            # Extract coords & adjust values against object location & shift against georef deltas
            lon, lat = rprj.pt(x + dx, y + dy)
            pts.append("{:.15f},{:.15f},{:.15f}".format(lon, lat, alt - self.altitude))

        xmlString = KML_TEMPLATE % (filename, filename, self.mode, " ".join(pts))

        with open(self.filepath, "w") as f:
            f.write(xmlString)

        self.report({'INFO'}, "Export complete")
        print("Export complete")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(EXPORTGIS_OT_kml_file)


def unregister():
    bpy.utils.unregister_class(EXPORTGIS_OT_kml_file)
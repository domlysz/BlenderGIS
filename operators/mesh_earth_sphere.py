import bpy
from bpy.types import Operator
from bpy.props import IntProperty

from math import cos, sin, radians, sqrt
from mathutils import Vector

import logging
log = logging.getLogger(__name__)


def lonlat2xyz(R, lon, lat):
	lon, lat = radians(lon), radians(lat)
	x = R * cos(lat) * cos(lon)
	y = R * cos(lat) * sin(lon)
	z = R *sin(lat)
	return (x, y, z)


class OBJECT_OT_earth_sphere(Operator):
	bl_idname = "earth.sphere"
	bl_label = "lonlat to sphere"
	bl_description = "Transform longitude/latitude data to a sphere like earth globe"
	bl_options = {"REGISTER", "UNDO"}

	radius: IntProperty(name = "Radius", default=100, description="Sphere radius", min=1)

	def execute(self, context):
		scn = bpy.context.scene
		obj = bpy.context.view_layer.objects.active

		if not obj:
			self.report({'INFO'}, "No active object")
			return {'CANCELLED'}

		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			return {'CANCELLED'}

		w, h, thick = obj.dimensions
		if w > 360:
			self.report({'INFO'}, "Longitude exceed 360°")
			return {'CANCELLED'}
		if h > 180:
			self.report({'INFO'}, "Latitude exceed 360°")
			return {'CANCELLED'}

		mesh = obj.data
		for vertex in mesh.vertices:
			lon, lat = vertex.co.x, vertex.co.y
			vertex.co = lonlat2xyz(self.radius, lon, lat)

		return {'FINISHED'}

EARTH_RADIUS = 6378137 #meters
def getZDelta(d):
	'''delta value for adjusting z across earth curvature
	http://webhelp.infovista.com/Planet/62/Subsystems/Raster/Content/help/analysis/viewshedanalysis.html'''
	return sqrt(EARTH_RADIUS**2 + d**2) - EARTH_RADIUS


class OBJECT_OT_earth_curvature(Operator):
	bl_idname = "earth.curvature"
	bl_label = "Earth curvature correction"
	bl_description = "Apply earth curvature correction for viewsheed analysis"
	bl_options = {"REGISTER", "UNDO"}

	def execute(self, context):
		scn = bpy.context.scene
		obj = bpy.context.view_layer.objects.active

		if not obj:
			self.report({'INFO'}, "No active object")
			return {'CANCELLED'}

		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			return {'CANCELLED'}

		mesh = obj.data
		viewpt = scn.cursor.location

		for vertex in mesh.vertices:
			d = (viewpt.xy - vertex.co.xy).length
			vertex.co.z = vertex.co.z - getZDelta(d)

		return {'FINISHED'}


classes = [
	OBJECT_OT_earth_sphere,
	OBJECT_OT_earth_curvature
]

def register():
	for cls in classes:
		try:
			bpy.utils.register_class(cls)
		except ValueError as e:
			log.warning('{} is already registered, now unregister and retry... '.format(cls))
			bpy.utils.unregister_class(cls)
			bpy.utils.register_class(cls)

def unregister():
	for cls in classes:
		bpy.utils.unregister_class(cls)

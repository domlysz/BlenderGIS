import bpy
from bpy.types import Operator
from bpy.props import IntProperty

from math import cos, sin, radians, sqrt, atan2, asin, degrees
from mathutils import Vector

import logging
log = logging.getLogger(__name__)


def lonlat2xyz(R, lon, lat):
	lon, lat = radians(lon), radians(lat)
	x = R * cos(lat) * cos(lon)
	y = R * cos(lat) * sin(lon)
	z = R * sin(lat)
	return Vector((x, y, z))

def xyz2lonlat(x, y, z, r=100, z_scale=1):
	R = sqrt(x**2 + y**2 + z**2)
	lon_rad = atan2(y, x)
	lat_rad = asin(z/R)
	R = (R-r) / z_scale
	lon = degrees(lon_rad)
	lat = degrees(lat_rad)
	return Vector((lon, lat, R))


class OBJECT_OT_earth_sphere(Operator):
	bl_idname = "earth.sphere"
	bl_label = "lonlat to sphere"
	bl_description = "Transform longitude/latitude data to a sphere like earth globe"
	bl_options = {"REGISTER", "UNDO"}

	radius: IntProperty(name = "Radius", default=100, description="Sphere radius", min=1)
	z_scale: IntProperty(name = "Z scale", default=1, description="Scale for the z axis")

	def execute(self, context):
		scn = bpy.context.scene
		objs = bpy.context.selected_objects

		if not objs:
			self.report({'INFO'}, "No selected object")
			return {'CANCELLED'}

		for obj in objs:
			if obj.type != 'MESH':
				log.warning("Object {} is not a mesh".format(obj.name))
				continue

			w, h, thick = obj.dimensions
			if w > 360:
				log.warning("Longitude of object {} exceed 360°".format(obj.name))
				continue
			if h > 180:
				log.warning("Latitude of object {} exceed 180°".format(obj.name))
				continue

			mesh = obj.data
			m = obj.matrix_world
			for vertex in mesh.vertices:
				co = m @ vertex.co
				lon, lat, z = co.x, co.y, co.z
				vertex.co = m.inverted() @ lonlat2xyz(self.radius + z*self.z_scale, lon, lat)

		return {'FINISHED'}

class OBJECT_OT_earth_plane(Operator):
	bl_idname = "earth.plane"
	bl_label = "sphere to latlon"
	bl_description = "Transform data on a sphere to longitude/latitude on a plane"
	bl_options = {"REGISTER", "UNDO"}

	radius: IntProperty(name = "Radius", default=100, description="Sphere radius", min=1)
	z_scale: IntProperty(name = "Z scale", default=1, description="Scale for the z axis")

	def execute(self, context):
		scn = bpy.context.scene
		objs = bpy.context.selected_objects

		if not objs:
			self.report({'INFO'}, "No selected object")
			return {'CANCELLED'}

		for obj in objs:
			if obj.type != 'MESH':
				log.warning("Object {} is not a mesh".format(obj.name))
				continue

			mesh = obj.data
			m = obj.matrix_world
			for vertex in mesh.vertices:
				co = m @ vertex.co
				vertex.co = m.inverted() @ xyz2lonlat(co.x, co.y, co.z, self.radius, self.z_scale)


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
 	OBJECT_OT_earth_plane,
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

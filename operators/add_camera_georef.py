# -*- coding:utf-8 -*-

#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****
import logging
log = logging.getLogger(__name__)

import bpy
from mathutils import Vector
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty

from .utils import getBBOX
from ..geoscene import GeoScene



class CAMERA_OT_add_georender_cam(bpy.types.Operator):
	'''
	Add a new georef camera or update an existing one
	A georef camera is a top view orthographic camera that can be used to render a map
	The camera is setting to encompass the selected object, the output spatial resolution (meters/pixel) can be set by the user
	A worldfile is writen in BLender text editor, it can be used to georef the output render
	'''
	bl_idname = "camera.georender"
	bl_label = "Georef cam"
	bl_description = "Create or update a camera to render a georeferencing map"
	bl_options = {"REGISTER", "UNDO"}


	name: StringProperty(name = "Camera name", default="Georef cam", description="")
	target_res: FloatProperty(name = "Pixel size", default=5, description="Pixel size in map units/pixel", min=0.00001)
	zLocOffset: FloatProperty(name = "Z loc. off.", default=50, description="Camera z location offet, defined as percentage of z dimension of the target mesh", min=0)

	redo = 0
	bbox = None #global var used to avoid recomputing the bbox at each redo

	def check(self, context):
		return True


	def draw(self, context):
		layout = self.layout
		layout.prop(self, 'name')
		layout.prop(self, 'target_res')
		layout.prop(self, 'zLocOffset')

	@classmethod
	def poll(cls, context):
		return context.mode == 'OBJECT'

	def execute(self, context):#every times operator redo options are modified

		#Operator redo count
		self.redo += 1

		#Check georef
		scn = context.scene
		geoscn = GeoScene(scn)
		if not geoscn.isGeoref:
			self.report({'ERROR'}, "Scene isn't georef")
			return {'CANCELLED'}

		#Validate selection
		objs = bpy.context.selected_objects
		if (not objs or len(objs) > 2) or \
		(len(objs) == 1 and not objs[0].type == 'MESH') or \
		(len(objs) == 2 and not set( (objs[0].type, objs[1].type )) == set( ('MESH','CAMERA') ) ):
			self.report({'ERROR'}, "Pre-selection is incorrect")
			return {'CANCELLED'}

		#Flag new camera creation
		if len(objs) == 2:
			newCam = False
		else:
			newCam = True

		#Get georef data
		dx, dy = geoscn.getOriginPrj()

		#Allocate obj
		for obj in objs:
			if obj.type == 'MESH':
				georefObj = obj
			elif obj.type == 'CAMERA':
				camObj = obj
				cam = camObj.data

		#do not recompute bbox at operator redo because zdim is miss-evaluated
		#when redoing the op on an obj that have a displace modifier on it
		#TODO find a less hacky fix
		if self.bbox is None:
			bbox = getBBOX.fromObj(georefObj, applyTransform = True)
			self.bbox = bbox
		else:
			bbox = self.bbox

		locx, locy, locz = bbox.center
		dimx, dimy, dimz = bbox.dimensions
		#dimx, dimy, dimz = georefObj.dimensions #dimensions property apply object transformations (scale and rot.)

		#Set active cam
		if newCam:
			cam = bpy.data.cameras.new(name=self.name)
			cam['mapRes'] = self.target_res #custom prop
			camObj = bpy.data.objects.new(name=self.name, object_data=cam)
			scn.collection.objects.link(camObj)
			scn.camera = camObj
		elif self.redo == 1: #first exec, get initial camera res
			scn.camera = camObj
			try:
				self.target_res = cam['mapRes']
			except KeyError:
				self.report({'ERROR'}, "This camera has not map resolution property")
				return {'CANCELLED'}
		else: #following exec, set camera res in redo panel
			try:
				cam['mapRes'] = self.target_res
			except KeyError:
				self.report({'ERROR'}, "This camera has not map resolution property")
				return {'CANCELLED'}

		#Set camera data
		cam.type = 'ORTHO'
		cam.ortho_scale = max((dimx, dimy)) #ratio = max((dimx, dimy)) / min((dimx, dimy))

		#General offset used to set cam z loc and clip end distance
		#needed to avoid clipping/black hole effects
		offset = dimz * self.zLocOffset/100

		#Set camera location
		camLocZ = bbox['zmin'] + dimz + offset
		camObj.location = (locx, locy, camLocZ)

		#Set camera clipping
		cam.clip_start = 0
		cam.clip_end = dimz + offset*2
		cam.show_limits = True

		if not newCam:
			if self.redo == 1:#first exec, get initial camera name
				self.name = camObj.name
			else:#following exec, set camera name in redo panel
				camObj.name = self.name
				camObj.data.name = self.name

		#Update selection
		bpy.ops.object.select_all(action='DESELECT')
		camObj.select_set(True)
		context.view_layer.objects.active = camObj

		#setup scene
		scn.camera = camObj
		scn.render.resolution_x = dimx / self.target_res
		scn.render.resolution_y = dimy / self.target_res
		scn.render.resolution_percentage = 100

		#Write wf
		res = self.target_res#dimx / scene.render.resolution_x
		rot = 0
		x = bbox['xmin'] + dx
		y = bbox['ymax'] + dy
		wf_data = '\n'.join(map(str, [res, rot, rot, -res, x+res/2, y-res/2]))
		wf_name = camObj.name + '.wld'
		if wf_name in bpy.data.texts:
			wfText = bpy.data.texts[wf_name]
			wfText.clear()
		else:
			wfText = bpy.data.texts.new(name=wf_name)
		wfText.write(wf_data)

		#Purge old wf text
		for wfText in bpy.data.texts:
			name, ext = wfText.name[:-4], wfText.name[-4:]
			if ext == '.wld' and name not in bpy.data.objects:
				bpy.data.texts.remove(wfText)

		return {'FINISHED'}


def register():
	try:
		bpy.utils.register_class(CAMERA_OT_add_georender_cam)
	except ValueError as e:
		log.warning('{} is already registered, now unregister and retry... '.format(cls))
		unregister()
		bpy.utils.register_class(CAMERA_OT_add_georender_cam)


def unregister():
	bpy.utils.unregister_class(CAMERA_OT_add_georender_cam)

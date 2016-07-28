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


import bpy
from mathutils import Vector
from bpy.props import StringProperty, BoolProperty, EnumProperty

from ..utils.geom import BBOX
from ..geoscene import GeoScene

def listObjects(self, context):
	#Function used to update the objects list (obj_list) used by the dropdown box.
	objs = [] #list containing tuples of each object
	for index, object in enumerate(bpy.context.scene.objects): #iterate over all objects
		if object.type == 'MESH':
			objs.append((str(index), object.name, "Object : "+object.name)) #put each object in a tuple (key, label, tooltip) and add this to the objects list
	return objs

def listCams(self, context):
	#Function used to update the camera list (obj_list) used by the dropdown box.
	objs = [('NEW', 'New', 'Add new camera')] #list containing tuples of each object (key, label, tooltip)
	for index, object in enumerate(bpy.context.scene.objects): #iterate over all objects
		if object.type == 'CAMERA':
			objs.append((str(index), object.name, "Camera : "+object.name)) #put each object in a tuple (key, label, tooltip) and add this to the objects list
	return objs



class ToolsPanelSetGeorefCam(bpy.types.Panel):
	bl_category = "GIS"
	bl_label = "Georef cam"
	bl_space_type = "VIEW_3D"
	bl_context = "objectmode"
	bl_region_type = "TOOLS"

	def draw(self, context):
		layout = self.layout
		layout.operator("object.set_georef_cam")


class OBJECT_OT_setGeorefCam(bpy.types.Operator):
	'''
	Add a new georef camera or update existing camera
	'''
	bl_idname = "object.set_georef_cam"
	bl_label = "Create/update"
	bl_options = {"REGISTER", "UNDO"}


	objLst = EnumProperty(attr="obj_list", name="Object", description="Choose an object", items=listObjects)
	camLst = EnumProperty(attr="cam_list", name="Camera", description="Choose a camera", items=listCams)

	name = bpy.props.StringProperty(name = "Camera name", default="Georef cam", description="")
	target_res = bpy.props.FloatProperty(name = "Pixel size", default=5, description="Pixel size in map units/pixel", min=0.00001)
	redo = 0

	def check(self, context):
		return True


	def draw(self, context):
		layout = self.layout
		layout.prop(self, 'objLst')
		layout.prop(self, 'camLst')
		if self.camLst == 'NEW':
			layout.prop(self, 'name')
		layout.prop(self, 'target_res')


	def invoke(self, context, event):
		scn = context.scene
		geoscn = GeoScene(scn)
		if geoscn.isGeoref:
			if len(self.objLst) > 0:
				return context.window_manager.invoke_props_dialog(self)
			else:
				self.report({'ERROR'}, "There isn't reference object to set camera on")
				return {'CANCELLED'}
		else:
			self.report({'ERROR'}, "Scene isn't georef")
			return {'CANCELLED'}

		

	def execute(self, context):#every times operator redo options are modified

		scn = context.scene

		#general offset used to set cam z loc and clip end distance
		#needed to avoid clipping/black hole effects
		offset = 10

		#Operator redo count
		self.redo+=1

		#Make sure we are in object mode
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
		bpy.ops.object.select_all(action='DESELECT')

		#Get georef data
		geoscn = GeoScene(scn)
		dx, dy = geoscn.getOriginPrj()

		#Get object
		objIdx = self.objLst
		georefObj = scn.objects[int(objIdx)]

		#Object properties
		bbox = BBOX.fromObj(georefObj, True)
		locx, locy, locz = bbox.center
		dimx, dimy, dimz = bbox.dimensions
		#dimx, dimy, dimz = georefObj.dimensions #dimensions property apply object transformations (scale and rot.)

		if self.camLst == 'NEW':
			#Add camera data
			cam = bpy.data.cameras.new(name=self.name)
			#Add camera obj
			camObj = bpy.data.objects.new(name=self.name, object_data=cam)
			scn.objects.link(camObj)
		else:
			#Get camera obj
			objIdx = self.camLst
			camObj = scn.objects[int(objIdx)]
			#Get data
			cam = camObj.data

		#Set camera data
		cam.type = 'ORTHO'
		cam.ortho_scale = max((dimx, dimy)) #ratio = max((dimx, dimy)) / min((dimx, dimy))

		#Set camera location
		camLocZ = bbox['zmin'] + dimz + offset
		camObj.location = (locx, locy, camLocZ)

		#Set camera clipping
		cam.clip_start = 0
		cam.clip_end = dimz + offset*2
		cam.show_limits = True

		if self.camLst != 'NEW':
			if self.redo == 1:#in update mode, we don't want overwrite initial camera name
				self.name = camObj.name
			else:#but user can change camera name in redo parameters
				camObj.name = self.name
				camObj.data.name = self.name

		camObj.select = True
		scn.objects.active = camObj

		#setup scene
		scn.camera = camObj
		scn.render.resolution_x = dimx / self.target_res
		scn.render.resolution_y = dimy / self.target_res
		scn.render.resolution_percentage = 100

		#write wf
		res = self.target_res#dimx / scene.render.resolution_x
		rot=0
		x = bbox['xmin'] + dx
		y = bbox['ymax'] + dy
		wf_data = str(res)+'\n'+str(rot)+'\n'+str(rot)+'\n'+str(-res)+'\n'+str(x+res/2)+'\n'+str(y-res/2)
		wf_name = self.name+'.wld'
		if wf_name in bpy.data.texts:
			wfText = bpy.data.texts[wf_name]
			wfText.clear()
		else:
			wfText = bpy.data.texts.new(name=wf_name)
		wfText.write(wf_data)


		return {'FINISHED'}

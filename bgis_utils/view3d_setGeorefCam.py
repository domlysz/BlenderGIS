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

def getBBox(obj, applyTransform = True):
	if applyTransform:
		boundPts = [obj.matrix_world * Vector(corner) for corner in obj.bound_box]
	else:
		boundPts = obj.bound_box
	bbox={}
	bbox['xmin']=min([pt[0] for pt in boundPts])
	bbox['xmax']=max([pt[0] for pt in boundPts])
	bbox['ymin']=min([pt[1] for pt in boundPts])
	bbox['ymax']=max([pt[1] for pt in boundPts])
	bbox['zmin']=min([pt[2] for pt in boundPts])
	bbox['zmax']=max([pt[2] for pt in boundPts])
	return bbox

def getBBoxCenter(bbox):
	x = bbox['xmin'] + (bbox['xmax'] - bbox['xmin']) / 2
	y = bbox['ymin'] + (bbox['ymax'] - bbox['ymin']) / 2
	z = bbox['zmin'] + (bbox['zmax'] - bbox['zmin']) / 2
	return (x,y,z)

def getBBoxDim(bbox):
	dx = bbox['xmax'] - bbox['xmin']
	dy = bbox['ymax'] - bbox['ymin']
	dz = bbox['zmax'] - bbox['zmin']
	return (dx,dy,dz)

#store property in scene
bpy.types.Scene.objLst = EnumProperty(attr="obj_list", name="Object", description="Choose an object", items=listObjects)
bpy.types.Scene.camLst = EnumProperty(attr="cam_list", name="Camera", description="Choose a camera", items=listCams)

class ToolsPanelSetGeorefCam(bpy.types.Panel):
	bl_category = "GIS"
	bl_label = "Georef cam"
	bl_space_type = "VIEW_3D"
	bl_context = "objectmode"
	bl_region_type = "TOOLS"

	def draw(self, context):
		layout = self.layout
		scn = bpy.context.scene
		if "Georef X" in scn and "Georef Y" in scn:
			if len(context.scene.objLst) > 0:
				layout.prop(context.scene, "objLst")
				layout.prop(context.scene, "camLst")
				layout.operator("object.set_georef_cam")
			else:
				layout.label("There isn't reference object to set camera on")
		else:
			layout.label("Scene isn't georef")


class OBJECT_OT_setGeorefCam(bpy.types.Operator):
	'''
	Add a new georef camera or update existing camera
	'''
	bl_idname = "object.set_georef_cam"
	bl_label = "Create/update"
	bl_options = {"REGISTER", "UNDO"}
	#Operator redo options
	name = bpy.props.StringProperty(name = "Camera name", default="Georef cam", description="")
	target_res = bpy.props.FloatProperty(name = "Pixel size", default=5, description="Pixel size in map units/pixel", min=0.00001)
	redo = 0

	def execute(self, context):#every times operator redo options are modified

		#Operator redo count
		self.redo+=1

		#Make sure we are in object mode
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
		bpy.ops.object.select_all(action='DESELECT')

		#Get georef data
		scene = bpy.context.scene
		dx, dy = scene["Georef X"], scene["Georef Y"]

		#Get object
		objIdx = context.scene.objLst
		georefObj = bpy.context.scene.objects[int(objIdx)]

		#Object properties
		bbox = getBBox(georefObj, True)
		locx, locy, locz = getBBoxCenter(bbox)
		dimx, dimy, dimz = getBBoxDim(bbox)
		#dimx, dimy, dimz = georefObj.dimensions #dimensions property apply object transformations (scale and rot.)

		if context.scene.camLst == 'NEW':
			#Add camera data
			cam = bpy.data.cameras.new(name=self.name)
			#Add camera obj
			camObj = bpy.data.objects.new(name=self.name, object_data=cam)
			scene.objects.link(camObj)
		else:
			#Get camera obj
			objIdx = context.scene.camLst
			camObj = bpy.context.scene.objects[int(objIdx)]
			#Get data
			cam = camObj.data

		#Set camera data
		cam.type = 'ORTHO'
		cam.ortho_scale = max((dimx, dimy)) #ratio = max((dimx, dimy)) / min((dimx, dimy))

		#Set camera location
		camLocZ = bbox['zmin'] + dimz + 1 #add one unit to avoid clipping
		camObj.location = (locx, locy, camLocZ)

		#Set camera clipping
		cam.clip_start = 0.5
		cam.clip_end = dimz + 2 #add 2 units to avoid clipping
		cam.show_limits = True

		if context.scene.camLst != 'NEW':
			if self.redo == 1:#in update mode, we don't want overwrite initial camera name
				self.name = camObj.name
			else:#but user can change camera name in redo parameters
				camObj.name = self.name
				camObj.data.name = self.name

		camObj.select = True
		scene.objects.active = camObj

		#setup scene
		scene.camera = camObj
		scene.render.resolution_x = dimx / self.target_res
		scene.render.resolution_y = dimy / self.target_res
		scene.render.resolution_percentage = 100

		#write wf
		res = self.target_res#dimx / scene.render.resolution_x
		rot=0
		x=bbox['xmin']+dx
		y=bbox['ymax']+dy
		wf_data = str(res)+'\n'+str(rot)+'\n'+str(rot)+'\n'+str(-res)+'\n'+str(x+res/2)+'\n'+str(y-res/2)
		wf_name = self.name+'.wld'
		if wf_name in bpy.data.texts:
			wfText = bpy.data.texts[wf_name]
			wfText.clear()
		else:
			wfText=bpy.data.texts.new(name=wf_name)
		wfText.write(wf_data)


		return {'FINISHED'}

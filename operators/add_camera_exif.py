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

import os
from math import pi

import bpy
from bpy.props import StringProperty, CollectionProperty, EnumProperty
from bpy.types import Panel, Operator, OperatorFileListElement

#bgis
from ..geoscene import GeoScene

#core
from ..core.proj import reprojPt
from ..core.georaster import getImgFormat

#deps
from ..core.lib import Tyf



def newEmpty(scene, name, location):
    """Create a new empty"""
    target = bpy.data.objects.new(name, None)
    target.empty_draw_size = 10
    target.empty_draw_type = 'PLAIN_AXES'
    target.location = location
    scene.objects.link(target)
    return target

def newCamera(scene, name, location, focalLength):
    """Create a new camera"""
    cam = bpy.data.cameras.new(name)
    cam.sensor_width = 35
    cam.lens = focalLength
    cam.draw_size = 10
    cam_obj = bpy.data.objects.new(name,cam)
    cam_obj.location = location
    cam_obj.rotation_euler[0] = pi/2
    cam_obj.rotation_euler[2] = pi
    scene.objects.link(cam_obj)
    return cam, cam_obj

def newTargetCamera(scene, name, location, focalLength):
    """Create a new camera.target"""
    cam, cam_obj = newCamera(scene, name, location, focalLength)
    x, y, z = location[:]
    target = newEmpty(scene, name+".target", (x, y - 50, z))
    constraint = cam_obj.constraints.new(type='TRACK_TO')
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'
    constraint.target = target
    return cam, cam_obj



class SetGeophotosCam(Operator):
    bl_idname = "camera.geophotos"
    bl_description  = "Create cameras from geotagged photos"
    bl_label = "Exif cam"
    bl_options = {"REGISTER"}

    files = CollectionProperty(
            name="File Path",
            type=OperatorFileListElement,
            )

    directory = StringProperty(
            subtype='DIR_PATH',
            )

    filter_glob = StringProperty(
        default="*.jpg;*.jpeg;*.tif;*.tiff",
        options={'HIDDEN'},
        )

    filename_ext = ""

    exifMode = EnumProperty(
        attr="exif_mode",
        name="Action",
        description="Choose an action",
        items=[('TARGET_CAMERA','Target Camera','Create a camera with target helper'),('CAMERA','Camera','Create a camera'),('EMPTY','Empty','Create an empty helper'),('CURSOR','Cursor','Move cursor')],
        default="TARGET_CAMERA"
        )


    def invoke(self, context, event):
        scn = context.scene
        geoscn = GeoScene(scn)
        if not geoscn.isGeoref:
            self.report({'ERROR'},"The scene must be georeferenced.")
            return {'CANCELLED'}
        #File browser
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scn = context.scene
        geoscn = GeoScene(scn)
        directory = self.directory
        for file_elem in self.files:
            filepath = os.path.join(directory, file_elem.name)

            if not os.path.isfile(filepath):
                    self.report({'ERROR'},"Invalid file")
                    return {'FINISHED'}

            imgFormat = getImgFormat(filepath)
            if imgFormat not in ['JPEG', 'TIFF']:
                    self.report({'ERROR'},"Invalid format " + str(imgFormat))
                    return {'FINISHED'}

            try:
                exif = Tyf.open(filepath)
                #tags = {t.key:exif[t.key] for t in exif.exif.tags() if t.key != 'Unknown' }
            except Exception as e:
                self.report({'ERROR'},"Unable to open file. " + str(e))
                return {'FINISHED'}

            try:
                lat = exif["GPSLatitude"] * exif["GPSLatitudeRef"]
                lon = exif["GPSLongitude"] * exif["GPSLongitudeRef"]
            except:
                self.report({'ERROR'},"Can't find gps longitude or latitude")
                return {'FINISHED'}

            try:
                alt = exif["GPSAltitude"]
            except:
                alt = 0

            try:
                x, y = reprojPt(4326, geoscn.crs, lon, lat)
            except Exception as e:
                self.report({'ERROR'},"Reprojection error. " + str(e))
                return {'FINISHED'}

            try:
                print(exif["FocalLengthIn35mmFilm"])
                focalLength = exif["FocalLengthIn35mmFilm"]
            except:
                focalLength = 35

            try:
                location = (x-geoscn.crsx, y-geoscn.crsy, alt)
                name = bpy.path.display_name_from_filepath(filepath)
                if self.exifMode == "TARGET_CAMERA":
                    cam, cam_obj = newTargetCamera(scn, name, location, focalLength)
                elif self.exifMode == "CAMERA":
                    cam, cam_obj = newCamera(scn, name, location, focalLength)
                elif self.exifMode == "EMPTY":
                    newEmpty(scn,name,location)
                else:
                    scn.cursor_location = location
            except Exception as e:
                self.report({'ERROR'},"Can't perform action. " + str(e))
                return {'FINISHED'}

            if self.exifMode in ["TARGET_CAMERA","CAMERA"]:
                cam['background']  = filepath

                '''
                try:
                    cam['imageWidth']  = exif["PixelXDimension"] #for jpg, in tif tag is named imageWidth...
                    cam['imageHeight'] = exif["PixelYDimension"]
                except:
                    pass
                '''

                img = bpy.data.images.load(filepath)
                w, h = img.size
                cam['imageWidth']  = w #exif["PixelXDimension"] #for jpg, in tif tag is named imageWidth...
                cam['imageHeight'] = h

                try:
                    cam['orientation'] = exif["Orientation"]
                except:
                    cam['orientation'] = 1 #no rotation

                #Set camera rotation (NOT TESTED)
                if cam['orientation'] == 8: #90° CCW
                    cam_obj.rotation_euler[1] -= pi/2
                if cam['orientation'] == 6: #90° CW
                    cam_obj.rotation_euler[1] += pi/2
                if cam['orientation'] == 3: #180°
                    cam_obj.rotation_euler[1] += pi

                if scn.camera is None:
                    bpy.ops.camera.geophotos_setactive('EXEC_DEFAULT', camLst=cam_obj.name)

        return {'FINISHED'}


class SetActiveGeophotoCam(Operator):
    bl_idname = "camera.geophotos_setactive"
    bl_description  = "Switch active geophoto camera"
    bl_label = "Switch geophoto camera"
    bl_options = {"REGISTER"}

    def listGeoCam(self, context):
        scn = context.scene
        #put each object in a tuple (key, label, tooltip)
        return [(obj.name, obj.name, obj.name) for obj in scn.objects if obj.type == 'CAMERA' and 'background' in obj.data]

    camLst = EnumProperty(name='Camera', description='Select camera', items=listGeoCam)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'camLst')#, text='')

    def invoke(self, context, event):
        if len(self.camLst) == 0:
            self.report({'ERROR'},"No valid camera")
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self)#, width=200)

    def execute(self, context):
        if context.space_data.type != 'VIEW_3D':
            self.report({'ERROR'},"Wrong context")
            return {'CANCELLED'}

        scn = context.scene
        view3d = context.space_data

        #Get cam
        cam_obj = scn.objects[self.camLst]
        cam_obj.select = True
        scn.objects.active = cam_obj
        cam = cam_obj.data
        scn.camera = cam_obj

        #Set render size
        scn.render.resolution_x = cam['imageWidth']
        scn.render.resolution_y = cam['imageHeight']
        scn.render.resolution_percentage = 100

        #Get or load bpy image
        filepath = cam['background']
        try:
            img = [img for img in bpy.data.images if img.filepath == filepath][0]
        except:
            img = bpy.data.images.load(filepath)

        #Activate view3d background
        view3d.show_background_images = True

        #Hide all existing camera background
        for bkg in view3d.background_images:
            if bkg.view_axis == 'CAMERA':
                bkg.show_background_image = False

        #Get or load background image
        bkgs = [bkg for bkg in view3d.background_images if bkg.image is not None]
        try:
            bkg = [bkg for bkg in bkgs if bkg.image.filepath == filepath][0]
        except:
            bkg = view3d.background_images.new()
            bkg.image = img

        #Set some props
        bkg.show_background_image = True
        bkg.view_axis = 'CAMERA'
        bkg.opacity = 1

        return {'FINISHED'}

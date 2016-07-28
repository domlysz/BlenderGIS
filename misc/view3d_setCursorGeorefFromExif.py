# requires Tyf

import os, bpy
from bpy_extras.io_utils import ImportHelper
from math import pi
from bpy.props import StringProperty, CollectionProperty, EnumProperty
from bpy.types import Panel, Operator, OperatorFileListElement, WindowManager
from ..geoscene import GeoScene
from ..utils.proj import reprojPt, SRS

#deps imports
from ..lib import Tyf

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

WindowManager.exifMode = EnumProperty(
                            attr="exif_mode", 
                            name="Action", 
                            description="Choose an action", 
                            items=[('TARGET_CAMERA','Target Camera','Create a camera with target helper'),('CAMERA','Camera','Create a camera'),('EMPTY','Empty','Create an empty helper'),('CURSOR','Cursor','Move cursor')],
                            default="TARGET_CAMERA"
                            )    
    
class ToolsPanelExif(Panel):
    bl_category = "GIS"#Tab
    bl_label = "Georef from Exif"
    bl_space_type = "VIEW_3D"
    bl_context = "objectmode"
    bl_region_type = "TOOLS"

    def draw(self, context):
        wm = context.window_manager
        self.layout.prop(wm,"exifMode")
        self.layout.operator("imagereference.fromexif")


class ImageReferenceFromExifButton(Operator, ImportHelper):
    bl_idname = "imagereference.fromexif"
    bl_description  = "Move cursor / create camera to reference from exif"
    bl_label = "Exif"
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
    
    def execute(self, context):
        wm = context.window_manager
        scn = context.scene
        geoscn = GeoScene(scn)
        if not geoscn.isGeoref:
            self.report({'ERROR'},"The scene must be georeferenced.")
            return {'FINISHED'}
        directory = self.directory
        for file_elem in self.files:
            filepath = os.path.join(directory, file_elem.name)
            if os.path.isfile(filepath):
                try:
                    exif = Tyf.open(filepath)
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
                    name = os.path.basename(filepath).split('.')
                    name.pop()
                    name = '.'.join(name)
                    if wm.exifMode == "TARGET_CAMERA":
                        cam, cam_obj = newTargetCamera(scn,name,location,focalLength)
                    elif wm.exifMode == "CAMERA":
                        cam, cam_obj = newCamera(scn,name,location,focalLength)
                    elif wm.exifMode == "EMPTY":
                        newEmpty(scn,name,location)
                    else:
                        scn.cursor_location = location
                except Exception as e:
                    self.report({'ERROR'},"Can't perform action. " + str(e))
                    return {'FINISHED'}
                #for future use    
                try:
                    if wm.exifMode in ["TARGET_CAMERA","CAMERA"]:
                        cam['background']  = filepath
                        cam['orientation'] = exif["Orientation"]
                        cam['imageWidth']  = exif["ImageWidth"]
                        cam['imageLength'] = exif["ImageLength"]
                except:
                    pass
        return {'FINISHED'}

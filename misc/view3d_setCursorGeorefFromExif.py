# https://gist.github.com/erans/983821
# license MIT, requires pillow

import os
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, CollectionProperty
from bpy.types import Panel, Operator, OperatorFileListElement
from ..geoscene import GeoScene
from ..utils.proj import reprojPt, SRS

#deps imports
from ..lib import Tyf
   
class ToolsPanelExif(Panel):
    bl_category = "GIS"#Tab
    bl_label = "Georef from Exif"
    bl_space_type = "VIEW_3D"
    bl_context = "objectmode"
    bl_region_type = "TOOLS"
    def draw(self, context):
        self.layout.operator("imagereference.fromexif")

class ImageReferenceFromExifButton(Operator, ImportHelper):
    bl_idname = "imagereference.fromexif"
    bl_description  = "Move cursor to reference from exif"
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
                    exif = Tyf.open(filepath) # load an image through Tyf Image object
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
                    scn.cursor_location = (x-geoscn.crsx, y-geoscn.crsy, alt)
                except Exception as e:
                    self.report({'ERROR'},"Can't move cursor. " + str(e))
                    return {'FINISHED'}
        return {'FINISHED'}

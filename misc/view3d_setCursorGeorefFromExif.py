# https://gist.github.com/erans/983821
# license MIT, requires pillow
import bpy
import os
import sys
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, CollectionProperty
from bpy.types import Panel, Operator, OperatorFileListElement
from ..geoscene import GeoScene
from ..utils.proj import reprojPt, SRS

#deps imports
try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
except:
    PILLOW = False
else:
    PILLOW = True


def get_exif_data(image):
    """Returns a dictionary from the exif data of an PIL Image item. Also converts the GPS Tags"""
    exif_data = {}
    info = image._getexif()
    if info:
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_data = {}
                for t in value:
                    sub_decoded = GPSTAGS.get(t, t)
                    gps_data[sub_decoded] = value[t]
                exif_data[decoded] = gps_data
            else:
                exif_data[decoded] = value
    return exif_data

def _get_if_exist(data, key):
    if key in data:
        return data[key]    
    return None
    
def _convert_to_degress(value):
    """Helper function to convert the GPS coordinates stored in the EXIF to degress in float format"""
    d0 = value[0][0]
    d1 = value[0][1]
    d = float(d0) / float(d1)
    m0 = value[1][0]
    m1 = value[1][1]
    m = float(m0) / float(m1)
    s0 = value[2][0]
    s1 = value[2][1]
    s = float(s0) / float(s1)
    return d + (m / 60.0) + (s / 3600.0)

def get_wgs84(exif_data):
    """Returns the latitude and longitude, if available, from the provided exif_data (obtained through get_exif_data above)"""
    lat = None
    lon = None
    alt = None
    if "GPSInfo" in exif_data:      
        gps_info = exif_data["GPSInfo"]
        gps_latitude = _get_if_exist(gps_info, "GPSLatitude")
        gps_latitude_ref = _get_if_exist(gps_info, 'GPSLatitudeRef')
        gps_longitude = _get_if_exist(gps_info, 'GPSLongitude')
        gps_longitude_ref = _get_if_exist(gps_info, 'GPSLongitudeRef')
        gps_altitude = _get_if_exist(gps_info, 'GPSAltitude')
        if gps_altitude:
            d0 = gps_altitude[0]
            d1 = gps_altitude[1]
            alt = float(d0) / float(d1)
        if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
            lat = _convert_to_degress(gps_latitude)
            if gps_latitude_ref != "N":                     
                lat = 0 - lat
            lon = _convert_to_degress(gps_longitude)
            if gps_longitude_ref != "E":
                lon = 0 - lon
    return lat, lon, alt

def convert_wgs84_to_CRS(lat, lon):
    """Convert WGS84 to local CRS"""
    scn = bpy.context.scene
    geoscn = GeoScene(scn)
    x = None
    y = None
    try:
        x, y = reprojPt(4326, geoscn.crs, lon, lat)
    except Exception as e:
        print('Warning, reproj error. ' + str(e))
    return x, y

def image_reference_from_exif(filepath):
    try:
        image = Image.open(filepath) # load an image through PIL's Image object
    except:
        return
    exif_data = get_exif_data(image)
    lat, lon, alt = get_wgs84(exif_data)
    x, y = convert_wgs84_to_CRS(lat, lon)
    try:
        bpy.context.scene.cursor_location = (x, y, alt)
    except Exception as e:
        print('Unable to move cursor. ' + str(e))
        
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
        default="*" + ";*".join(bpy.path.extensions_image),
        options={'HIDDEN'},
        )
    filename_ext = ""
    def invoke(self, context, event):
        if not PILLOW:
            self.report({'ERROR'}, "Please install Python Pillow module")
            return {'CANCELLED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        directory = self.directory
        for file_elem in self.files:
            filepath = os.path.join(directory, file_elem.name)
            if os.path.isfile(filepath):
                image_reference_from_exif(filepath)
        return {'FINISHED'}

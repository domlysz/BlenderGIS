import logging
logging.basicConfig(level=logging.getLevelName('INFO'))


#Try to install external libs
import importlib.metadata, subprocess, sys
#logging.info('Installing external dependencies...')
#subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
requiredDeps = ['pillow', 'pyshp', 'Tyf', 'pyproj', 'overpy'] #['pyshp==2.1.0', 'Tyf==1.2.4']
optionalDeps = ['ImageIO']
deps = requiredDeps #+ optionalDeps
installed = [pkg.metadata['Name'] for pkg in importlib.metadata.distributions()]
logging.debug(f'Installed package : {installed}')
#missing = required - installed
for dep in deps:
    if dep in installed:
        logging.info(f'> {dep} package is already installed')
    else:
        logging.info(f'> installing {dep}...')
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', dep])
##

from .checkdeps import HAS_GDAL, HAS_PYPROJ, HAS_IMGIO, HAS_PIL
from .settings import settings
from .errors import OverlapError

from .utils import XY, BBOX

from .proj import SRS, Reproj, reprojPt, reprojPts, reprojBbox, reprojImg

from .georaster import GeoRef, GeoRaster, NpImage

from .basemaps import GRIDS, SOURCES, MapService, GeoPackage, TileMatrix

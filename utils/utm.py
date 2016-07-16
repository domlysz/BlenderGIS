

#Original code from https://github.com/Turbo87/utm
#>simplified version that only handle utm zones (and not latitude bands from MGRS grid)
#>reverse coord order : latlon --> lonlat
#>add support for UTM EPSG codes

# more infos : http://geokov.com/education/utm.aspx
# formulas : https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system

import math


K0 = 0.9996

E = 0.00669438
E2 = E * E
E3 = E2 * E
E_P2 = E / (1.0 - E)

SQRT_E = math.sqrt(1 - E)
_E = (1 - SQRT_E) / (1 + SQRT_E)
_E2 = _E * _E
_E3 = _E2 * _E
_E4 = _E3 * _E
_E5 = _E4 * _E

M1 = (1 - E / 4 - 3 * E2 / 64 - 5 * E3 / 256)
M2 = (3 * E / 8 + 3 * E2 / 32 + 45 * E3 / 1024)
M3 = (15 * E2 / 256 + 45 * E3 / 1024)
M4 = (35 * E3 / 3072)

P2 = (3. / 2 * _E - 27. / 32 * _E3 + 269. / 512 * _E5)
P3 = (21. / 16 * _E2 - 55. / 32 * _E4)
P4 = (151. / 96 * _E3 - 417. / 128 * _E5)
P5 = (1097. / 512 * _E4)

R = 6378137


class OutOfRangeError(ValueError):
	pass


def longitude_to_zone_number(longitude):
	return int((longitude + 180) / 6) + 1

def latitude_to_northern(latitude):
	return latitude >= 0

def lonlat_to_zone_northern(lon, lat):
	zone = longitude_to_zone_number(lon)
	north = latitude_to_northern(lat)
	return zone, north

def zone_number_to_central_longitude(zone_number):
	return (zone_number - 1) * 6 - 180 + 3


# Each UTM zone on WGS84 datum has a dedicated EPSG code : 326xx for north hemisphere and 327xx for south
# where xx is the zone number from 1 to 60

#UTM_EPSG_CODES = ['326' + str(i).zfill(2) for i in range(1,61)] + ['327' + str(i).zfill(2) for i in range(1,61)]
UTM_EPSG_CODES = [32600 + i for i in range(1,61)] + [32700 + i for i in range(1,61)]

def _code_from_epsg(epsg):
	'''Return & validate EPSG code str from user input'''
	epsg = str(epsg)
	if epsg.isdigit():
		code = epsg
	elif ':' in epsg:
		auth, code = epsg.split(':')
	else:
		raise ValueError('Invalid UTM EPSG code')
	if code in map(str, UTM_EPSG_CODES):
		return code
	else:
		raise ValueError('Invalid UTM EPSG code')

def epsg_to_zone_northern(epsg):
	code = _code_from_epsg(epsg)
	zone = int(code[-2:])
	if code[2] == '6':
		northern = True
	else:
		northern = False
	return zone, northern

def lonlat_to_epsg(longitude, latitude):
	zone = longitude_to_zone_number(longitude)
	if latitude_to_northern(latitude):
		return 'EPSG:326' + str(zone).zfill(2)
	else:
		return 'EPSG:327' + str(zone).zfill(2)

def zone_northern_to_epsg(zone, northern):
	if northern:
		return 'EPSG:326' + str(zone).zfill(2)
	else:
		return 'EPSG:327' + str(zone).zfill(2)


######

class UTM():

	def __init__(self, zone, north):
		'''
		zone : UTM zone number 
		north : True if north hemesphere, False if south
		'''
		if not 1 <= zone <= 60:
			raise OutOfRangeError('zone number out of range (must be between 1 and 60)')
		self.zone_number = zone
		self.northern = north

	@classmethod
	def init_from_epsg(cls, epsg):
		zone, north = epsg_to_zone_northern(epsg)
		return cls(zone, north)

	@classmethod
	def init_from_lonlat(cls, lon, lat):
		zone, north = lonlat_to_zone_northern(lon, lat)
		return cls(zone, north)


	def utm_to_lonlat(self, easting, northing):

		if not 100000 <= easting < 1000000:
			raise OutOfRangeError('easting out of range (must be between 100.000 m and 999.999 m)')
		if not 0 <= northing <= 10000000:
			raise OutOfRangeError('northing out of range (must be between 0 m and 10.000.000 m)')

		x = easting - 500000
		y = northing

		if not self.northern:
			y -= 10000000

		m = y / K0
		mu = m / (R * M1)

		p_rad = (mu +
				 P2 * math.sin(2 * mu) +
				 P3 * math.sin(4 * mu) +
				 P4 * math.sin(6 * mu) +
				 P5 * math.sin(8 * mu))

		p_sin = math.sin(p_rad)
		p_sin2 = p_sin * p_sin

		p_cos = math.cos(p_rad)

		p_tan = p_sin / p_cos
		p_tan2 = p_tan * p_tan
		p_tan4 = p_tan2 * p_tan2

		ep_sin = 1 - E * p_sin2
		ep_sin_sqrt = math.sqrt(1 - E * p_sin2)

		n = R / ep_sin_sqrt
		r = (1 - E) / ep_sin

		c = _E * p_cos**2
		c2 = c * c

		d = x / (n * K0)
		d2 = d * d
		d3 = d2 * d
		d4 = d3 * d
		d5 = d4 * d
		d6 = d5 * d

		latitude = (p_rad - (p_tan / r) *
					(d2 / 2 -
					 d4 / 24 * (5 + 3 * p_tan2 + 10 * c - 4 * c2 - 9 * E_P2)) +
					 d6 / 720 * (61 + 90 * p_tan2 + 298 * c + 45 * p_tan4 - 252 * E_P2 - 3 * c2))

		longitude = (d -
					 d3 / 6 * (1 + 2 * p_tan2 + c) +
					 d5 / 120 * (5 - 2 * c + 28 * p_tan2 - 3 * c2 + 8 * E_P2 + 24 * p_tan4)) / p_cos

		return (math.degrees(longitude) + zone_number_to_central_longitude(self.zone_number),
				math.degrees(latitude))


	def lonlat_to_utm(self, longitude, latitude):
		if not -80.0 <= latitude <= 84.0:
			raise OutOfRangeError('latitude out of range (must be between 80 deg S and 84 deg N)')
		if not -180.0 <= longitude <= 180.0:
			raise OutOfRangeError('longitude out of range (must be between 180 deg W and 180 deg E)')

		lat_rad = math.radians(latitude)
		lat_sin = math.sin(lat_rad)
		lat_cos = math.cos(lat_rad)

		lat_tan = lat_sin / lat_cos
		lat_tan2 = lat_tan * lat_tan
		lat_tan4 = lat_tan2 * lat_tan2

		lon_rad = math.radians(longitude)
		central_lon = zone_number_to_central_longitude(self.zone_number)
		central_lon_rad = math.radians(central_lon)

		n = R / math.sqrt(1 - E * lat_sin**2)
		c = E_P2 * lat_cos**2

		a = lat_cos * (lon_rad - central_lon_rad)
		a2 = a * a
		a3 = a2 * a
		a4 = a3 * a
		a5 = a4 * a
		a6 = a5 * a

		m = R * (M1 * lat_rad -
				 M2 * math.sin(2 * lat_rad) +
				 M3 * math.sin(4 * lat_rad) -
				 M4 * math.sin(6 * lat_rad))

		easting = K0 * n * (a +
							a3 / 6 * (1 - lat_tan2 + c) +
							a5 / 120 * (5 - 18 * lat_tan2 + lat_tan4 + 72 * c - 58 * E_P2)) + 500000

		northing = K0 * (m + n * lat_tan * (a2 / 2 +
											a4 / 24 * (5 - lat_tan2 + 9 * c + 4 * c**2) +
											a6 / 720 * (61 - 58 * lat_tan2 + lat_tan4 + 600 * c - 330 * E_P2)))

		if not self.northern:
			northing += 10000000

		return easting, northing





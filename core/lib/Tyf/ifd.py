# -*- encoding:utf-8 -*-
# Copyright © 2015-2016, THOORENS Bruno - http://bruno.thoorens.free.fr/licences/tyf.html

from . import io, os, tags, encoders, decoders, reduce, values, TYPES, urllib, StringIO
import struct


class Tag(object):
	meaning = None

	def __init__(self, tag, value=None, **kwargs):
		db = kwargs.pop("db", False)
		self.name = kwargs.pop("name", "Orphan tag")
		if not db: tag, db = tags.get(tag)

		self.tag, (self.key, self.__types, default, self.comment) = tag, db
		self.type = self.__types[-1]

		if value != None: self.digest(value)
		elif default != None:
			self.value = default
		else:
			try: self.value = self._encoder("\x00" if self.type in [2,7] else 0)
			except: self.value = b"\x00" if self.type in [2,7] else \
			                     (0, 1) if self.type in [5,10] else \
                                 (0,)

	def __setattr__(self, attr, value):
		# define encoder and decoder according to type
		if attr == "type":
			# find encoder
			hex_enc = "_%s"%hex(self.tag)
			if hasattr(encoders, hex_enc): object.__setattr__(self, "_encoder",  getattr(encoders, hex_enc))
			else: object.__setattr__(self, "_encoder", getattr(encoders, "_%s"%value))
			# find decoder
			hex_dec = "_%s"%hex(self.tag)
			if hasattr(decoders, hex_dec): object.__setattr__(self, "_decoder",  getattr(decoders, hex_dec))
			else: object.__setattr__(self, "_decoder", getattr(decoders, "_%s"%value))
		# 
		elif attr == "value":
			restricted = getattr(values, self.key, None)
			if restricted != None:
				v = value[0] if isinstance(value, tuple) and len(value) == 1 else value
				self.meaning = restricted.get(v, "no description found ["+str(v)+"]")
			self._deal(value)
			self._determine_if_offset()
		object.__setattr__(self, attr, value)

	def __repr__(self):
		return "%s 0x%x: %s = %r" % (self.name, self.tag, self.key, self.value) + ("" if not self.meaning else ' :: %s'%self.meaning)

	def _deal(self, value):
		if len(self.__types) > 1: self.type = self.__types[-1]
		else: self.type = self.__types[0]
		self.count = len(value) // (1 if self.type not in [5,10] else 2)

	def _determine_if_offset(self):
		if self.count == 1 and self.type in [1, 2, 3, 4, 6, 7, 8, 9]: setattr(self, "value_is_offset", False)
		elif self.count <= 2 and self.type in [3, 8]: setattr(self, "value_is_offset", False)
		elif self.count <= 4 and self.type in [1, 2, 6, 7]: setattr(self, "value_is_offset", False)
		else: setattr(self, "value_is_offset", True)

	def _fill(self):
		if not self.value_is_offset:
			s = struct.calcsize("="+TYPES[self.type][0])
			voidspace = (struct.calcsize("=L") - self.count*s)//s
			if self.type in [2, 7]: return self.value + b"\x00"*voidspace
			elif self.type in [1, 3, 6, 8]: return self.value + ((0,)*voidspace)
		return self.value

	def digest(self, value):
		self.value = self._encoder(value)

	def decode(self):
		return self._decoder(self.value)

	def calcsize(self):
		return struct.calcsize("=" + TYPES[self.type][0] * (self.count*(2 if self.type in [5,10] else 1))) if self.value_is_offset else 0


class Ifd(dict):
	# possible sub IFD with according tag, sub IFD name and tags family
	sub_ifd = {
		34665: ("Exif tag", tags.exfT),
		34853: ("GPS tag", tags.gpsT),
		40965: ("Interop tag", tags.itrT),
	}

	size = property(
		lambda obj: {
			"ifd": struct.calcsize("=H" + (len(obj)*"HHLL") + "L"),
			"data": reduce(int.__add__, [t.calcsize() for t in dict.values(obj)]) if len(obj) else 0
		}, None, None, "return ifd-packed size and data-packed size")

	interop = property(lambda obj: getattr(obj, "_40965", Ifd()), None, None, "shortcut to Interoperability sub ifd")
	exif = property(lambda obj: getattr(obj, "_34665", Ifd()), None, None, "shortcut to EXIF sub ifd")
	gps = property(lambda obj: getattr(obj, "_34853", Ifd()), None, None, "shortcut to GPS sub ifd")
	has_raster = property(lambda obj: 273 in obj or 288 in obj or 324 in obj or 513 in obj, None, None, "return true if it contains raster data")
	raster_loaded = property(lambda obj: not(obj.has_raster) or bool(len(obj.stripes+obj.tiles+obj.free)+len(obj.jpegIF)), None, None, "")

	def __init__(self, **kwargs):
		self.tag_name = kwargs.pop("tag_name", "Tiff tag")
		self.tag_family = kwargs.pop("tag_family", [tags.bTT, tags.xTT, tags.pTT])

		dict.__init__(self)

		self.stripes = ()
		self.tiles = ()
		self.free = ()
		self.jpegIF = b""

	def __iter__(self):
		for tag in self.tags():
			yield tag.key, tag.decode()

	def __setitem__(self, tag, value):
		_tag, database = self._tag(tag)
		if not _tag:
			raise KeyError("%s tag not a valid tag for this ifd" % tag)
		elif _tag in Ifd.sub_ifd:
			name, family = Ifd.sub_ifd[_tag]
			setattr(self, "_%s"%_tag, value if isinstance(value, Ifd) else Ifd(tag_name=name, tag_family=[family]))
			dict.__setitem__(self, _tag, Tag(_tag, 0, name=self.tag_name, db=database))
		else:
			dict.__setitem__(self, _tag, Tag(_tag, value, name=self.tag_name, db=database))

	def __getitem__(self, tag):
		_tag, database = self._tag(tag)
		if not _tag:
			return dict.__getitem__(self, tag)
		elif _tag in Ifd.sub_ifd:
			attr = "_%s"%_tag
			if not hasattr(self, attr):
				name, family = Ifd.sub_ifd[_tag]
				setattr(self, attr, Ifd(tag_name=name, tag_family=[family]))
				dict.__setitem__(self, _tag, Tag(_tag, 0, name=self.tag_name, db=database))
			return getattr(self, attr)
		return dict.__getitem__(self, _tag).decode()

	def __delitem__(self, tag):
		_tag, database = self._tag(tag)
		if not _tag:
			return dict.__delitem__(self, tag)
		elif _tag in Ifd.sub_ifd:
			attr = "_%s"%_tag
			if hasattr(self, attr): delattr(self, attr)
			else: raise KeyError("Ifd does not contains %s sub ifd" % _tag)
		return dict.__delitem__(self, _tag)

	def _tag(self, elem):
		if elem == "GPS IFD": elem = 34853
		elif elem == "Exif IFD": elem = 34665
		elif elem == "Interoperability IFD": elem = 40965

		for tf in self.tag_family:
			if elem in tf:
				return elem, tf[elem]
			else:
				for tag, (key, typ, default, desc) in tf.items():
					if elem == key:
						return tag, (key, typ, default, desc)
		return False, ("Undefined", [7], None, "Undefined tag %r"%elem)

	def set(self, tag, typ, value):
		_tag, database = self._tag(tag)
		if not _tag: raise KeyError("%s tag not a valid tag for this ifd" % tag)
		obj = Tag(_tag, name=self.tag_name, db=database)
		obj.type = typ
		obj.value = (value,) if not hasattr(value, "__len__") else value
		return dict.__setitem__(self, _tag, obj)

	def get(self, tag):
		_tag, database = self._tag(tag)
		return dict.__getitem__(self, _tag)

	def pop(self, tag):
		_tag, database = self._tag(tag)
		attr = "_%s"%_tag
		if hasattr(self, attr):
			delattr(self, attr)
		elem = dict.pop(self, _tag)
		elem.name = "Orphan tag"
		return elem

	def append(self, tag, **kwargs):
		if not isinstance(tag, Tag):
			tag = Tag(tag, **kwargs)
		tag.name = self.tag_name
		if tag.tag in Ifd.sub_ifd:
			return dict.__setitem__(self, tag.tag, tag)
		for tf in self.tag_family:
			if tag.tag in tf:
				return dict.__setitem__(self, tag.tag, tag)
		raise KeyError("%s tag not a valid tag for this ifd" % tag.tag)

	def find(self, elem):
		found = False
		for tf in self.tag_family:
			dico = dict((v[0],k) for k,v in tf.items())
			if elem in tf and elem in self:
				return dict.__getitem__(self, elem)
			elif elem in dico and dico[elem] in self:
				return dict.__getitem__(self, dico[elem])
		for tag in Ifd.sub_ifd:
			if hasattr(self, "_%s"%tag):
				found = getattr(self, "_%s"%tag).find(elem)
				if found: break
		return found

	def place(self, tag, **kwargs):
		if not isinstance(tag, Tag):
			tag = Tag(tag, **kwargs)
		elem = tag.tag
		for t,(n,f) in Ifd.sub_ifd.items():
			if elem in f:
				tag.name = n
				return dict.__setitem__(self[t], elem, tag)
		tag.name = self.tag_name
		for tf in self.tag_family:
			if elem in tf:
				return dict.__setitem__(self, elem, tag)

	def set_location(self, longitude, latitude, altitude=0.):
		ifd = self["GPS IFD"]
		ifd[1] = ifd[2] = latitude
		ifd[3] = ifd[4] = longitude
		ifd[5] = ifd[6] = altitude

	def get_location(self):
		ifd = self["GPS IFD"]
		if set([1,2,3,4,5,6]) <= set(ifd.keys()):
			return (
				ifd[3] * ifd[4],
				ifd[1] * ifd[2],
				ifd[5] * ifd[6]
			)

	def load_location(self, zoom=15, size="256x256", mcolor="0xff00ff", format="png", scale=1):
		ifd = self["GPS IFD"]
		if set([1,2,3,4]) <= set(ifd.keys()):
			latitude = ifd[1] * ifd[2]
			longitude = ifd[3] * ifd[4]
			try:
				opener = urllib.urlopen("https://maps.googleapis.com/maps/api/staticmap?center=%s,%s&zoom=%s&size=%s&markers=color:%s%%7C%s,%s&format=%s&scale=%s" % (
					latitude, longitude,
					zoom, size, mcolor,
					latitude, longitude,
					format, scale
				))
			except:
				return StringIO()
			else:
				return StringIO(opener.read())
				print("googleapis connexion error")
		else:
			return StringIO()

	def dump_location(self, tilename, zoom=15, size="256x256", mcolor="0xff00ff", format="png", scale=1):
		ifd = self["GPS IFD"]
		if set([1,2,3,4]) <= set(ifd.keys()):
			latitude = ifd[1] * ifd[2]
			longitude = ifd[3] * ifd[4]
			try:
				urllib.urlretrieve("https://maps.googleapis.com/maps/api/staticmap?center=%s,%s&zoom=%s&size=%s&markers=color:%s%%7C%s,%s&format=%s&scale=%s" % (
						latitude, longitude,
						zoom, size, mcolor,
						latitude, longitude,
						format, scale
					),
					os.path.splitext(tilename)[0] + "."+format
				)
			except:
				print("googleapis connexion error")

	def tags(self):
		for v in sorted(dict.values(self), key=lambda e:e.tag):
			yield v
		for tag in Ifd.sub_ifd.keys():
			if hasattr(self, "_%s"%tag):
				for v in getattr(self, "_%s"%tag).tags():
					yield v

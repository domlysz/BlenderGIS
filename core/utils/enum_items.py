"""Helpers for Blender EnumProperty callback item lifetimes."""

from functools import wraps


def keep_enum_items(callback):
	"""Keep each callback's returned strings alive for Blender's UI."""

	@wraps(callback)
	def wrapped(*args, **kwargs):
		items = callback(*args, **kwargs)
		wrapped._enum_items_cache = list(items)
		return wrapped._enum_items_cache

	return wrapped
